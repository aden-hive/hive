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
import pytest
import tempfile
from pathlib import Path

from framework.graph import Goal
from framework.graph.goal import SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec, EdgeSpec, EdgeCondition, AsyncEntryPointSpec
from framework.graph.node import NodeSpec
from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec
from framework.runtime.shared_state import SharedStateManager, IsolationLevel, StateScope
from framework.runtime.event_bus import EventBus, EventType, AgentEvent
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.stream_runtime import StreamRuntime
from framework.storage.concurrent import ConcurrentStorage


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

        mem1 = manager.create_memory("exec-1", "stream-1", IsolationLevel.SHARED)
        mem2 = manager.create_memory("exec-2", "stream-1", IsolationLevel.SHARED)

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

    @pytest.mark.asyncio
    async def test_persistent_state_save_and_load(self, temp_storage):
        """Test that state is persisted to disk and can be loaded."""
        storage = ConcurrentStorage(base_path=temp_storage)
        await storage.start()

        try:
            manager = SharedStateManager(storage=storage)

            # Write state
            mem = manager.create_memory("exec-1", "stream-1", IsolationLevel.SHARED)
            await mem.write("test_key", "test_value", scope=StateScope.GLOBAL)

            # Wait for async write to complete
            await asyncio.sleep(0.2)

            # Create a new manager and verify it loads from disk
            manager2 = SharedStateManager(storage=storage)
            mem2 = manager2.create_memory("exec-2", "stream-2", IsolationLevel.SHARED)

            # Should load from disk on first read
            value = await mem2.read("test_key")
            assert value == "test_value"
        finally:
            await storage.stop()

    @pytest.mark.asyncio
    async def test_persistent_state_lazy_loading(self, temp_storage):
        """Test that state is lazily loaded from disk on cache miss."""
        storage = ConcurrentStorage(base_path=temp_storage)
        await storage.start()

        try:
            # Pre-populate disk with state
            await storage.save_state("global", "default", {"pre_existing": "value"}, immediate=True)
            await storage.save_state("stream", "stream-1", {"stream_key": "stream_value"}, immediate=True)
            await storage.save_state("execution", "exec-1", {"exec_key": "exec_value"}, immediate=True)

            manager = SharedStateManager(storage=storage)

            # Create memory and read - should lazy load
            mem = manager.create_memory("exec-1", "stream-1", IsolationLevel.SHARED)

            # Read should trigger lazy loading
            global_val = await mem.read("pre_existing")
            stream_val = await mem.read("stream_key")
            exec_val = await mem.read("exec_key")

            assert global_val == "value"
            assert stream_val == "stream_value"
            assert exec_val == "exec_value"
        finally:
            await storage.stop()

    @pytest.mark.asyncio
    async def test_persistent_state_write_through(self, temp_storage):
        """Test that writes are persisted asynchronously."""
        storage = ConcurrentStorage(base_path=temp_storage)
        await storage.start()

        try:
            manager = SharedStateManager(storage=storage)
            mem = manager.create_memory("exec-1", "stream-1", IsolationLevel.SHARED)

            # Write to different scopes
            await mem.write("global_key", "global_val", scope=StateScope.GLOBAL)
            await mem.write("stream_key", "stream_val", scope=StateScope.STREAM)
            await mem.write("exec_key", "exec_val", scope=StateScope.EXECUTION)

            # Wait for async writes
            await asyncio.sleep(0.2)

            # Verify persisted to disk
            global_state = await storage.load_state("global", "default")
            stream_state = await storage.load_state("stream", "stream-1")
            exec_state = await storage.load_state("execution", "exec-1")

            assert global_state is not None
            assert global_state.get("global_key") == "global_val"
            assert stream_state is not None
            assert stream_state.get("stream_key") == "stream_val"
            assert exec_state is not None
            assert exec_state.get("exec_key") == "exec_val"
        finally:
            await storage.stop()

    @pytest.mark.asyncio
    async def test_backward_compatibility_no_storage(self):
        """Test that SharedStateManager works without storage (backward compatible)."""
        manager = SharedStateManager(storage=None)

        mem = manager.create_memory("exec-1", "stream-1", IsolationLevel.SHARED)
        await mem.write("key", "value")

        value = await mem.read("key")
        assert value == "value"

    @pytest.mark.asyncio
    async def test_state_survives_restart(self, temp_storage):
        """Test that state persists across manager restarts."""
        storage = ConcurrentStorage(base_path=temp_storage)
        await storage.start()

        try:
            # First session: write state
            manager1 = SharedStateManager(storage=storage)
            mem1 = manager1.create_memory("exec-1", "stream-1", IsolationLevel.SHARED)
            await mem1.write("persistent_key", "persistent_value", scope=StateScope.GLOBAL)

            # Wait for write
            await asyncio.sleep(0.2)

            # Simulate restart: create new manager
            manager2 = SharedStateManager(storage=storage)
            mem2 = manager2.create_memory("exec-2", "stream-2", IsolationLevel.SHARED)

            # Should load from disk
            value = await mem2.read("persistent_key")
            assert value == "persistent_value"
        finally:
            await storage.stop()


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

        await bus.publish(AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="webhook",
            execution_id="exec-1",
            data={"test": "data"},
        ))

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
        await bus.publish(AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="webhook",
        ))

        # Publish to api stream (should NOT be received)
        await bus.publish(AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="api",
        ))

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
        await bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="webhook",
            execution_id="exec-1",
        ))

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
