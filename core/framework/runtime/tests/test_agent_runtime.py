"""
Tests for AgentRuntime and multi-entry-point execution.

Tests:
1. AgentRuntime creation and lifecycle
2. Entry point registration
3. Concurrent executions across streams
4. SharedStateManager isolation levels
5. OutcomeAggregator goal evaluation
6. EventBus pub/sub
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from framework.graph import Goal
from framework.graph.edge import AsyncEntryPointSpec, EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.goal import Constraint, SuccessCriterion
from framework.graph.node import NodeSpec
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.runtime.execution_stream import EntryPointSpec
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.shared_state import IsolationLevel, SharedStateManager

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
            node_type="llm_generate",
            input_keys=["webhook_data"],
            output_keys=["result"],
        ),
        NodeSpec(
            id="process-api",
            name="Process API Request",
            description="Process API request",
            node_type="llm_generate",
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

    async_entry_points = [
        AsyncEntryPointSpec(
            id="webhook",
            name="Webhook Handler",
            entry_node="process-webhook",
            trigger_type="webhook",
            isolation_level="shared",
        ),
        AsyncEntryPointSpec(
            id="api",
            name="API Handler",
            entry_node="process-api",
            trigger_type="api",
            isolation_level="shared",
        ),
    ]

    return GraphSpec(
        id="test-graph",
        goal_id="test-goal",
        version="1.0.0",
        entry_node="process-webhook",
        entry_points={"start": "process-webhook"},
        async_entry_points=async_entry_points,
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


# === SharedStateManager Tests ===


class TestSharedStateManager:
    """Tests for SharedStateManager."""

    def test_create_memory(self):
        """Test creating execution-scoped memory."""
        manager = SharedStateManager()
        memory = manager.create_memory(
            execution_id="exec-1",
            stream_id="webhook",
            isolation=IsolationLevel.SHARED,
        )
        assert memory is not None
        assert memory._execution_id == "exec-1"
        assert memory._stream_id == "webhook"

    @pytest.mark.asyncio
    async def test_isolated_state(self):
        """Test isolated state doesn't leak between executions."""
        manager = SharedStateManager()

        mem1 = manager.create_memory("exec-1", "stream-1", IsolationLevel.ISOLATED)
        mem2 = manager.create_memory("exec-2", "stream-1", IsolationLevel.ISOLATED)

        await mem1.write("key", "value1")
        await mem2.write("key", "value2")

        assert await mem1.read("key") == "value1"
        assert await mem2.read("key") == "value2"

    @pytest.mark.asyncio
    async def test_shared_state(self):
        """Test shared state is visible across executions."""
        manager = SharedStateManager()

        manager.create_memory("exec-1", "stream-1", IsolationLevel.SHARED)
        manager.create_memory("exec-2", "stream-1", IsolationLevel.SHARED)

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
        manager = SharedStateManager()
        manager.create_memory("exec-1", "stream-1", IsolationLevel.ISOLATED)

        assert "exec-1" in manager._execution_state

        manager.cleanup_execution("exec-1")

        assert "exec-1" not in manager._execution_state


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
        runtime = AgentRuntime(
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
        runtime = AgentRuntime(
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
        runtime = AgentRuntime(
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
        runtime = AgentRuntime(
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
        runtime = AgentRuntime(
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


class TestGraphSpecValidation:
    """Tests for GraphSpec with async_entry_points."""

    def test_has_async_entry_points(self, sample_graph):
        """Test checking for async entry points."""
        assert sample_graph.has_async_entry_points() is True

        # Graph without async entry points
        simple_graph = GraphSpec(
            id="simple",
            goal_id="goal",
            entry_node="start",
            nodes=[],
            edges=[],
        )
        assert simple_graph.has_async_entry_points() is False

    def test_get_async_entry_point(self, sample_graph):
        """Test getting async entry point by ID."""
        ep = sample_graph.get_async_entry_point("webhook")
        assert ep is not None
        assert ep.id == "webhook"
        assert ep.entry_node == "process-webhook"

        ep_not_found = sample_graph.get_async_entry_point("nonexistent")
        assert ep_not_found is None

    def test_validate_async_entry_points(self):
        """Test validation catches async entry point errors."""
        nodes = [
            NodeSpec(
                id="valid-node",
                name="Valid Node",
                description="A valid node",
                node_type="llm_generate",
                input_keys=[],
                output_keys=[],
            ),
        ]

        # Invalid entry node
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="valid-node",
            async_entry_points=[
                AsyncEntryPointSpec(
                    id="invalid",
                    name="Invalid",
                    entry_node="nonexistent-node",
                    trigger_type="webhook",
                ),
            ],
            nodes=nodes,
            edges=[],
        )

        errors = graph.validate()
        assert any("nonexistent-node" in e for e in errors)

        # Invalid isolation level
        graph2 = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="valid-node",
            async_entry_points=[
                AsyncEntryPointSpec(
                    id="bad-isolation",
                    name="Bad Isolation",
                    entry_node="valid-node",
                    trigger_type="webhook",
                    isolation_level="invalid",
                ),
            ],
            nodes=nodes,
            edges=[],
        )

        errors2 = graph2.validate()
        assert any("isolation_level" in e for e in errors2)

        # Invalid trigger type
        graph3 = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="valid-node",
            async_entry_points=[
                AsyncEntryPointSpec(
                    id="bad-trigger",
                    name="Bad Trigger",
                    entry_node="valid-node",
                    trigger_type="invalid_trigger",
                ),
            ],
            nodes=nodes,
            edges=[],
        )

        errors3 = graph3.validate()
        assert any("trigger_type" in e for e in errors3)


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
