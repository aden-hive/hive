"""
Tests for AgentRuntime and multi-entry-point execution.

Tests:
1. AgentRuntime creation and lifecycle
2. Entry point registration
3. Concurrent executions across streams
4. SharedBufferManager isolation levels
5. OutcomeAggregator goal evaluation
6. EventBus pub/sub
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from framework.graph import Goal
from framework.orchestrator.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.orchestrator.goal import Constraint, SuccessCriterion
from framework.orchestrator.node import NodeSpec
from framework.host.agent_host import AgentHost, create_agent_runtime
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.host.execution_manager import EntryPointSpec
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.shared_state import IsolationLevel, SharedBufferManager
from framework.schemas.session_state import SessionState, SessionTimestamps

# === Test Fixtures ===


@pytest.fixture
def sample_goal():
    """Create a sample goal for testing."""
    return Goal(
        id="test-goal",
        name="Test Goal",
        description="A goal for testing multi-entry-point execution",
        success_criteria=[
            SuccessCriterion(
                id="sc-1",
                description="Process all requests",
                metric="requests_processed",
                target="100%",
                weight=1.0,
            ),
        ],
        constraints=[
            Constraint(
                id="c-1",
                description="Must not exceed rate limits",
                constraint_type="hard",
                category="operational",
            ),
        ],
    )


@pytest.fixture
def sample_graph():
    """Create a sample graph with multiple entry points."""
    nodes = [
        NodeSpec(
            id="process-webhook",
            name="Process Webhook",
            description="Process incoming webhook",
            node_type="event_loop",
            input_keys=["webhook_data"],
            output_keys=["result"],
        ),
        NodeSpec(
            id="process-api",
            name="Process API Request",
            description="Process API request",
            node_type="event_loop",
            input_keys=["request_data"],
            output_keys=["result"],
        ),
        NodeSpec(
            id="complete",
            name="Complete",
            description="Execution complete",
            node_type="terminal",
            input_keys=["result"],
            output_keys=["final_result"],
        ),
    ]

    edges = [
        EdgeSpec(
            id="webhook-to-complete",
            source="process-webhook",
            target="complete",
            condition=EdgeCondition.ON_SUCCESS,
        ),
        EdgeSpec(
            id="api-to-complete",
            source="process-api",
            target="complete",
            condition=EdgeCondition.ON_SUCCESS,
        ),
    ]

    return GraphSpec(
        id="test-graph",
        goal_id="test-goal",
        version="1.0.0",
        entry_node="process-webhook",
        entry_points={"start": "process-webhook"},
        terminal_nodes=["complete"],
        pause_nodes=[],
        nodes=nodes,
        edges=edges,
    )


@pytest.fixture
def temp_storage():
    """Create a temporary storage directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# === SharedBufferManager Tests ===


class TestSharedBufferManager:
    """Tests for SharedBufferManager."""

    def test_create_buffer(self):
        """Test creating execution-scoped buffer."""
        manager = SharedBufferManager()
        buffer = manager.create_buffer(
            execution_id="exec-1",
            stream_id="webhook",
            isolation=IsolationLevel.SHARED,
        )
        assert buffer is not None
        assert buffer._execution_id == "exec-1"
        assert buffer._stream_id == "webhook"

    @pytest.mark.asyncio
    async def test_isolated_state(self):
        """Test isolated state doesn't leak between executions."""
        manager = SharedBufferManager()

        buf1 = manager.create_buffer("exec-1", "stream-1", IsolationLevel.ISOLATED)
        buf2 = manager.create_buffer("exec-2", "stream-1", IsolationLevel.ISOLATED)

        await buf1.write("key", "value1")
        await buf2.write("key", "value2")

        assert await buf1.read("key") == "value1"
        assert await buf2.read("key") == "value2"

    @pytest.mark.asyncio
    async def test_shared_state(self):
        """Test shared state is visible across executions."""
        manager = SharedBufferManager()

        manager.create_buffer("exec-1", "stream-1", IsolationLevel.SHARED)
        manager.create_buffer("exec-2", "stream-1", IsolationLevel.SHARED)

        # Write to global scope
        await manager.write(
            key="global_key",
            value="global_value",
            execution_id="exec-1",
            stream_id="stream-1",
            isolation=IsolationLevel.SHARED,
            scope="global",
        )

        # Both should see it
        value1 = await manager.read("global_key", "exec-1", "stream-1", IsolationLevel.SHARED)
        value2 = await manager.read("global_key", "exec-2", "stream-1", IsolationLevel.SHARED)

        assert value1 == "global_value"
        assert value2 == "global_value"

    def test_cleanup_execution(self):
        """Test execution cleanup removes state."""
        manager = SharedBufferManager()
        manager.create_buffer("exec-1", "stream-1", IsolationLevel.ISOLATED)

        assert "exec-1" in manager._execution_state

        manager.cleanup_execution("exec-1")

        assert "exec-1" not in manager._execution_state


class TestSessionState:
    """Tests for session state data-buffer compatibility."""

    def test_legacy_memory_alias_populates_data_buffer(self):
        """Legacy `memory` payloads should still hydrate the session buffer."""
        state = SessionState(
            session_id="session-1",
            goal_id="goal-1",
            timestamps=SessionTimestamps(
                started_at="2026-01-01T00:00:00",
                updated_at="2026-01-01T00:00:00",
            ),
            memory={"rules": "keep starred mail"},
        )

        assert state.data_buffer == {"rules": "keep starred mail"}
        assert state.memory == {"rules": "keep starred mail"}
        assert state.to_session_state_dict()["data_buffer"] == {"rules": "keep starred mail"}


# === EventBus Tests ===


class TestEventBus:
    """Tests for EventBus pub/sub."""

    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        """Test basic publish/subscribe."""
        bus = EventBus()
        received_events = []

        async def handler(event: AgentEvent):
            received_events.append(event)

        bus.subscribe(
            event_types=[EventType.EXECUTION_STARTED],
            handler=handler,
        )

        await bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id="webhook",
                execution_id="exec-1",
                data={"test": "data"},
            )
        )

        # Allow handler to run
        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert received_events[0].type == EventType.EXECUTION_STARTED
        assert received_events[0].stream_id == "webhook"

    @pytest.mark.asyncio
    async def test_stream_filter(self):
        """Test filtering by stream ID."""
        bus = EventBus()
        received_events = []

        async def handler(event: AgentEvent):
            received_events.append(event)

        bus.subscribe(
            event_types=[EventType.EXECUTION_STARTED],
            handler=handler,
            filter_stream="webhook",
        )

        # Publish to webhook stream (should be received)
        await bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id="webhook",
            )
        )

        # Publish to api stream (should NOT be received)
        await bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id="api",
            )
        )

        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert received_events[0].stream_id == "webhook"

    def test_unsubscribe(self):
        """Test unsubscribing from events."""
        bus = EventBus()

        async def handler(event: AgentEvent):
            pass

        sub_id = bus.subscribe(
            event_types=[EventType.EXECUTION_STARTED],
            handler=handler,
        )

        assert sub_id in bus._subscriptions

        result = bus.unsubscribe(sub_id)

        assert result is True
        assert sub_id not in bus._subscriptions

    @pytest.mark.asyncio
    async def test_wait_for(self):
        """Test waiting for a specific event."""
        bus = EventBus()

        # Start waiting in background
        async def wait_and_check():
            event = await bus.wait_for(
                event_type=EventType.EXECUTION_COMPLETED,
                timeout=1.0,
            )
            return event

        wait_task = asyncio.create_task(wait_and_check())

        # Publish the event
        await asyncio.sleep(0.1)
        await bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_COMPLETED,
                stream_id="webhook",
                execution_id="exec-1",
            )
        )

        event = await wait_task

        assert event is not None
        assert event.type == EventType.EXECUTION_COMPLETED


# === OutcomeAggregator Tests ===


class TestOutcomeAggregator:
    """Tests for OutcomeAggregator."""

    def test_record_decision(self, sample_goal):
        """Test recording decisions."""
        aggregator = OutcomeAggregator(sample_goal)

        from framework.schemas.decision import Decision, DecisionType

        decision = Decision(
            id="dec-1",
            node_id="process-webhook",
            intent="Process incoming webhook",
            decision_type=DecisionType.PATH_CHOICE,
            options=[],
            chosen_option_id="opt-1",
            reasoning="Standard processing path",
        )

        aggregator.record_decision("webhook", "exec-1", decision)

        assert aggregator._total_decisions == 1
        assert len(aggregator._decisions) == 1

    @pytest.mark.asyncio
    async def test_evaluate_goal_progress(self, sample_goal):
        """Test goal progress evaluation."""
        aggregator = OutcomeAggregator(sample_goal)

        progress = await aggregator.evaluate_goal_progress()

        assert "overall_progress" in progress
        assert "criteria_status" in progress
        assert "constraint_violations" in progress
        assert "recommendation" in progress

    def test_record_constraint_violation(self, sample_goal):
        """Test recording constraint violations."""
        aggregator = OutcomeAggregator(sample_goal)

        aggregator.record_constraint_violation(
            constraint_id="c-1",
            description="Rate limit exceeded",
            violation_details="More than 100 requests/minute",
            stream_id="webhook",
            execution_id="exec-1",
        )

        assert len(aggregator._constraint_violations) == 1
        assert aggregator._constraint_violations[0].constraint_id == "c-1"


# === AgentRuntime Tests ===


class TestAgentRuntime:
    """Tests for AgentRuntime orchestration."""

    def test_register_entry_point(self, sample_graph, sample_goal, temp_storage):
        """Test registering entry points."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="manual",
            name="Manual Trigger",
            entry_node="process-webhook",
            trigger_type="manual",
        )

        runtime.register_entry_point(entry_spec)

        assert "manual" in runtime._entry_points
        assert len(runtime.get_entry_points()) == 1

    def test_register_duplicate_entry_point_fails(self, sample_graph, sample_goal, temp_storage):
        """Test that duplicate entry point IDs fail."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="webhook",
            name="Webhook Handler",
            entry_node="process-webhook",
            trigger_type="webhook",
        )

        runtime.register_entry_point(entry_spec)

        with pytest.raises(ValueError, match="already registered"):
            runtime.register_entry_point(entry_spec)

    def test_register_invalid_entry_node_fails(self, sample_graph, sample_goal, temp_storage):
        """Test that invalid entry nodes fail."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="invalid",
            name="Invalid Entry",
            entry_node="nonexistent-node",
            trigger_type="manual",
        )

        with pytest.raises(ValueError, match="not found in graph"):
            runtime.register_entry_point(entry_spec)

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, sample_graph, sample_goal, temp_storage):
        """Test runtime start/stop lifecycle."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="webhook",
            name="Webhook Handler",
            entry_node="process-webhook",
            trigger_type="webhook",
        )

        runtime.register_entry_point(entry_spec)

        assert not runtime.is_running

        await runtime.start()

        assert runtime.is_running
        assert "webhook" in runtime._streams

        await runtime.stop()

        assert not runtime.is_running
        assert len(runtime._streams) == 0

    @pytest.mark.asyncio
    async def test_trigger_requires_running(self, sample_graph, sample_goal, temp_storage):
        """Test that trigger fails if runtime not running."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="webhook",
            name="Webhook Handler",
            entry_node="process-webhook",
            trigger_type="webhook",
        )

        runtime.register_entry_point(entry_spec)

        with pytest.raises(RuntimeError, match="not running"):
            await runtime.trigger("webhook", {"test": "data"})


# === GraphSpec Validation Tests ===


# === Integration Tests ===


class TestCreateAgentRuntime:
    """Tests for the create_agent_runtime factory."""

    def test_create_with_entry_points(self, sample_graph, sample_goal, temp_storage):
        """Test factory creates runtime with entry points."""
        entry_points = [
            EntryPointSpec(
                id="webhook",
                name="Webhook",
                entry_node="process-webhook",
                trigger_type="webhook",
            ),
            EntryPointSpec(
                id="api",
                name="API",
                entry_node="process-api",
                trigger_type="api",
            ),
        ]

        runtime = create_agent_runtime(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
            entry_points=entry_points,
        )

        assert len(runtime.get_entry_points()) == 2
        assert "webhook" in runtime._entry_points
        assert "api" in runtime._entry_points


# === Timer Entry Point Tests ===


class TestTimerEntryPoints:
    """Tests for timer-driven entry points (interval and cron)."""

    @pytest.mark.asyncio
    async def test_interval_timer_starts_task(self, sample_graph, sample_goal, temp_storage):
        """Test that interval_minutes timer creates an async task."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="timer-interval",
            name="Interval Timer",
            entry_node="process-webhook",
            trigger_type="timer",
            trigger_config={"interval_minutes": 60},
        )
        runtime.register_entry_point(entry_spec)

        await runtime.start()
        try:
            assert len(runtime._timer_tasks) == 1
            assert not runtime._timer_tasks[0].done()
            # Give the async task a moment to set next_fire
            await asyncio.sleep(0.05)
            assert "timer-interval" in runtime._timer_next_fire
        finally:
            await runtime.stop()

        assert len(runtime._timer_tasks) == 0

    @pytest.mark.asyncio
    async def test_cron_timer_starts_task(self, sample_graph, sample_goal, temp_storage):
        """Test that cron expression timer creates an async task."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="timer-cron",
            name="Cron Timer",
            entry_node="process-webhook",
            trigger_type="timer",
            trigger_config={"cron": "*/5 * * * *"},  # Every 5 minutes
        )
        runtime.register_entry_point(entry_spec)

        await runtime.start()
        try:
            assert len(runtime._timer_tasks) == 1
            assert not runtime._timer_tasks[0].done()
            # Give the async task a moment to set next_fire
            await asyncio.sleep(0.05)
            assert "timer-cron" in runtime._timer_next_fire
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_invalid_cron_expression_skipped(
        self, sample_graph, sample_goal, temp_storage, caplog
    ):
        """Test that an invalid cron expression logs a warning and skips."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="timer-bad-cron",
            name="Bad Cron Timer",
            entry_node="process-webhook",
            trigger_type="timer",
            trigger_config={"cron": "not a cron expression"},
        )
        runtime.register_entry_point(entry_spec)

        await runtime.start()
        try:
            assert len(runtime._timer_tasks) == 0
            assert "invalid cron" in caplog.text.lower() or "Invalid cron" in caplog.text
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_cron_takes_priority_over_interval(
        self, sample_graph, sample_goal, temp_storage, caplog
    ):
        """Test that when both cron and interval_minutes are set, cron wins."""
        import logging

        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="timer-both",
            name="Both Timer",
            entry_node="process-webhook",
            trigger_type="timer",
            trigger_config={"cron": "0 9 * * *", "interval_minutes": 30},
        )
        runtime.register_entry_point(entry_spec)

        with caplog.at_level(logging.INFO):
            await runtime.start()
        try:
            assert len(runtime._timer_tasks) == 1
            # Should log cron, not interval
            assert any("cron" in r.message.lower() for r in caplog.records)
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_no_interval_or_cron_warns(self, sample_graph, sample_goal, temp_storage, caplog):
        """Test that timer with neither cron nor interval_minutes logs a warning."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="timer-empty",
            name="Empty Timer",
            entry_node="process-webhook",
            trigger_type="timer",
            trigger_config={},
        )
        runtime.register_entry_point(entry_spec)

        await runtime.start()
        try:
            assert len(runtime._timer_tasks) == 0
            assert "no 'cron' or valid 'interval_minutes'" in caplog.text
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_cron_immediate_fires_first(self, sample_graph, sample_goal, temp_storage):
        """Test that run_immediately=True with cron doesn't set next_fire before first run."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="timer-cron-immediate",
            name="Cron Immediate",
            entry_node="process-webhook",
            trigger_type="timer",
            trigger_config={"cron": "0 0 * * *", "run_immediately": True},
        )
        runtime.register_entry_point(entry_spec)

        await runtime.start()
        try:
            assert len(runtime._timer_tasks) == 1
            # With run_immediately, the task enters the while loop directly,
            # so _timer_next_fire is NOT set before the first trigger attempt
            # (it pops it at the top of the loop)
            # Give it a moment to start executing
            await asyncio.sleep(0.05)
            # Task should still be running (it will try to trigger and likely fail
            # since there's no LLM, but the task itself continues)
            assert not runtime._timer_tasks[0].done()
        finally:
            await runtime.stop()


# === Cancel All Tasks Tests ===


class TestCancelAllTasks:
    """Tests for cancel_all_tasks and cancel_all_tasks_async."""

    @pytest.mark.asyncio
    async def test_cancel_all_tasks_async_returns_false_when_no_tasks(
        self, sample_graph, sample_goal, temp_storage
    ):
        """Test that cancel_all_tasks_async returns False with no running tasks."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="webhook",
            name="Webhook",
            entry_node="process-webhook",
            trigger_type="webhook",
        )
        runtime.register_entry_point(entry_spec)
        await runtime.start()

        try:
            result = await runtime.cancel_all_tasks_async()
            assert result is False
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_cancel_all_tasks_async_cancels_running_task(
        self, sample_graph, sample_goal, temp_storage
    ):
        """Test that cancel_all_tasks_async cancels a running task and returns True."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        entry_spec = EntryPointSpec(
            id="webhook",
            name="Webhook",
            entry_node="process-webhook",
            trigger_type="webhook",
        )
        runtime.register_entry_point(entry_spec)
        await runtime.start()

        try:
            # Inject a fake running task into the stream
            stream = runtime._streams["webhook"]

            async def hang_forever():
                await asyncio.get_event_loop().create_future()

            fake_task = asyncio.ensure_future(hang_forever())
            stream._execution_tasks["fake-exec"] = fake_task

            result = await runtime.cancel_all_tasks_async()
            assert result is True

            # Let the CancelledError propagate
            try:
                await fake_task
            except asyncio.CancelledError:
                pass
            assert fake_task.cancelled()

            # Clean up
            del stream._execution_tasks["fake-exec"]
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_cancel_all_tasks_async_cancels_multiple_tasks_across_streams(
        self, sample_graph, sample_goal, temp_storage
    ):
        """Test that cancel_all_tasks_async cancels tasks across multiple streams."""
        runtime = AgentHost(
            graph=sample_graph,
            goal=sample_goal,
            storage_path=temp_storage,
        )

        # Register two entry points so we get two streams
        runtime.register_entry_point(
            EntryPointSpec(
                id="stream-a",
                name="Stream A",
                entry_node="process-webhook",
                trigger_type="webhook",
            )
        )
        runtime.register_entry_point(
            EntryPointSpec(
                id="stream-b",
                name="Stream B",
                entry_node="process-webhook",
                trigger_type="webhook",
            )
        )
        await runtime.start()

        try:

            async def hang_forever():
                await asyncio.get_event_loop().create_future()

            stream_a = runtime._streams["stream-a"]
            stream_b = runtime._streams["stream-b"]

            # Two tasks in stream A, one task in stream B
            task_a1 = asyncio.ensure_future(hang_forever())
            task_a2 = asyncio.ensure_future(hang_forever())
            task_b1 = asyncio.ensure_future(hang_forever())

            stream_a._execution_tasks["exec-a1"] = task_a1
            stream_a._execution_tasks["exec-a2"] = task_a2
            stream_b._execution_tasks["exec-b1"] = task_b1

            result = await runtime.cancel_all_tasks_async()
            assert result is True

            # Let CancelledErrors propagate
            for task in [task_a1, task_a2, task_b1]:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                assert task.cancelled()

            # Clean up
            del stream_a._execution_tasks["exec-a1"]
            del stream_a._execution_tasks["exec-a2"]
            del stream_b._execution_tasks["exec-b1"]
        finally:
            await runtime.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
