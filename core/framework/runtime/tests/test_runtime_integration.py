"""
Extended integration tests for AgentRuntime, ExecutionStream, and related components.

These tests complement the existing test_agent_runtime.py with additional coverage for:
- Concurrent execution scenarios
- Error handling and recovery
- Guardrail integration
- Event bus subscription patterns
- Session state persistence
"""

import asyncio
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from framework.graph import Goal
from framework.graph.goal import SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec, EdgeSpec, EdgeCondition, AsyncEntryPointSpec
from framework.graph.node import NodeSpec
from framework.graph.executor import ExecutionResult
from framework.runtime.shared_state import SharedStateManager, IsolationLevel
from framework.runtime.event_bus import EventBus, EventType, AgentEvent
from framework.runtime.guardrails import (
    GuardrailRegistry,
    GuardrailContext,
    BudgetGuardrail,
    MaxStepsGuardrail,
    GuardrailSeverity,
)


# === Fixtures ===

@pytest.fixture
def event_bus():
    """Create fresh EventBus for each test."""
    return EventBus()


@pytest.fixture
def state_manager():
    """Create fresh SharedStateManager for each test."""
    return SharedStateManager()


@pytest.fixture
def guardrail_registry():
    """Create a guardrail registry with default guardrails."""
    registry = GuardrailRegistry()
    registry.add(BudgetGuardrail(max_cost_usd=100.0, max_tokens=1000000))
    registry.add(MaxStepsGuardrail(max_steps=100))
    return registry


@pytest.fixture
def sample_goal():
    """Create a sample goal."""
    return Goal(
        id="test-goal",
        name="Test Goal",
        description="A goal for testing",
        success_criteria=[
            SuccessCriterion(
                id="sc-complete",
                description="Complete execution successfully",
                metric="execution_success",
                target="true",
                weight=1.0,
            ),
        ],
        constraints=[
            Constraint(
                id="c-budget",
                description="Stay within budget",
                constraint_type="hard",
            ),
        ],
    )


# === Event Bus Extended Tests ===

class TestEventBusExtended:
    """Extended tests for EventBus functionality."""

    @pytest.mark.asyncio
    async def test_multiple_subscribers_same_event(self, event_bus):
        """Test multiple subscribers receive the same event."""
        received_1 = []
        received_2 = []

        async def handler_1(event: AgentEvent):
            received_1.append(event)

        async def handler_2(event: AgentEvent):
            received_2.append(event)

        event_bus.subscribe([EventType.EXECUTION_STARTED], handler_1)
        event_bus.subscribe([EventType.EXECUTION_STARTED], handler_2)

        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="test",
            execution_id="exec-1",
        ))

        await asyncio.sleep(0.1)

        assert len(received_1) == 1
        assert len(received_2) == 1

    @pytest.mark.asyncio
    async def test_subscriber_receives_only_subscribed_types(self, event_bus):
        """Test subscribers only receive subscribed event types."""
        received = []

        async def handler(event: AgentEvent):
            received.append(event)

        event_bus.subscribe([EventType.EXECUTION_COMPLETED], handler)

        # Publish different event type
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="test",
        ))

        # Publish subscribed type
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="test",
        ))

        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].type == EventType.EXECUTION_COMPLETED

    @pytest.mark.asyncio
    async def test_event_history_maintained(self, event_bus):
        """Test event history is maintained."""
        for i in range(5):
            await event_bus.publish(AgentEvent(
                type=EventType.STATE_CHANGED,
                stream_id="test",
                execution_id=f"exec-{i}",
            ))

        history = event_bus.get_history()
        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_event_history_limit(self):
        """Test event history respects max limit."""
        bus = EventBus(max_history=3)

        for i in range(5):
            await bus.publish(AgentEvent(
                type=EventType.STATE_CHANGED,
                stream_id="test",
                execution_id=f"exec-{i}",
            ))

        history = bus.get_history()
        assert len(history) == 3
        # Should have the last 3 events
        assert history[0].execution_id == "exec-2"


# === Shared State Manager Extended Tests ===

class TestSharedStateExtended:
    """Extended tests for SharedStateManager."""

    @pytest.mark.asyncio
    async def test_concurrent_writes_same_key(self, state_manager):
        """Test concurrent writes to the same key are handled correctly."""
        mem = state_manager.create_memory("exec-1", "stream-1", IsolationLevel.SHARED)

        async def write_value(val):
            await mem.write("counter", val)

        # Concurrent writes
        await asyncio.gather(
            write_value(1),
            write_value(2),
            write_value(3),
        )

        # Should have some value (last writer wins)
        result = await mem.read("counter")
        assert result in [1, 2, 3]

    @pytest.mark.asyncio
    async def test_read_nonexistent_key_returns_none(self, state_manager):
        """Test reading non-existent key returns None."""
        mem = state_manager.create_memory("exec-1", "stream-1", IsolationLevel.SHARED)
        result = await mem.read("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_synchronized_isolation(self, state_manager):
        """Test synchronized isolation level uses locking."""
        mem = state_manager.create_memory("exec-1", "stream-1", IsolationLevel.SYNCHRONIZED)

        write_order = []

        async def delayed_write(key, val, delay):
            await asyncio.sleep(delay)
            await mem.write(key, val)
            write_order.append(val)

        # Should maintain order due to synchronization
        await asyncio.gather(
            delayed_write("key", "first", 0.01),
            delayed_write("key", "second", 0.02),
        )

        # Both writes should complete
        assert len(write_order) == 2


# === Guardrail Integration Tests ===

class TestGuardrailIntegration:
    """Tests for guardrail integration scenarios."""

    def test_guardrail_context_creation(self, sample_goal):
        """Test creating guardrail context from execution state."""
        ctx = GuardrailContext(
            node_id="test-node",
            node_type="llm_generate",
            input_data={"query": "test"},
            goal_id=sample_goal.id,
            run_id="run-123",
            total_tokens=5000,
            total_cost_usd=0.05,
            step_count=10,
        )

        assert ctx.node_id == "test-node"
        assert ctx.total_tokens == 5000

    def test_multiple_guardrails_evaluated(self, guardrail_registry):
        """Test all guardrails are evaluated."""
        ctx = GuardrailContext(
            node_id="test",
            node_type="llm_generate",
            input_data={},
            goal_id="goal-1",
            run_id="run-1",
            total_tokens=500,
            total_cost_usd=0.01,
            step_count=5,
        )

        results = guardrail_registry.check_pre_execution(ctx)

        # Should have results from both guardrails
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_budget_guardrail_blocks_when_exceeded(self, guardrail_registry):
        """Test budget guardrail blocks when limit exceeded."""
        ctx = GuardrailContext(
            node_id="test",
            node_type="llm_generate",
            input_data={},
            goal_id="goal-1",
            run_id="run-1",
            total_tokens=2000000,  # Exceeds limit
            total_cost_usd=0.01,
            step_count=5,
        )

        results = guardrail_registry.check_pre_execution(ctx)
        violations = guardrail_registry.get_violations(results)

        assert len(violations) == 1
        assert "Token limit exceeded" in violations[0].message


# === Execution Recovery Tests ===

class TestExecutionRecovery:
    """Tests for execution error handling and recovery."""

    @pytest.mark.asyncio
    async def test_event_published_on_failure(self, event_bus):
        """Test failure events are published."""
        received = []

        async def handler(event: AgentEvent):
            received.append(event)

        event_bus.subscribe([EventType.EXECUTION_FAILED], handler)

        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_FAILED,
            stream_id="test",
            execution_id="exec-1",
            data={"error": "Test error", "node_id": "failing-node"},
        ))

        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].data["error"] == "Test error"

    @pytest.mark.asyncio
    async def test_pause_resume_events(self, event_bus):
        """Test pause and resume events."""
        events = []

        async def handler(event: AgentEvent):
            events.append(event)

        event_bus.subscribe(
            [EventType.EXECUTION_PAUSED, EventType.EXECUTION_RESUMED],
            handler,
        )

        # Simulate pause
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_PAUSED,
            stream_id="test",
            execution_id="exec-1",
            data={"paused_at_node": "hitl-node", "reason": "Human approval required"},
        ))

        # Simulate resume
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_RESUMED,
            stream_id="test",
            execution_id="exec-1",
            data={"resumed_from_node": "hitl-node"},
        ))

        await asyncio.sleep(0.1)

        assert len(events) == 2
        assert events[0].type == EventType.EXECUTION_PAUSED
        assert events[1].type == EventType.EXECUTION_RESUMED


# === Goal Progress Tests ===

class TestGoalProgress:
    """Tests for goal progress tracking."""

    @pytest.mark.asyncio
    async def test_goal_progress_event(self, event_bus):
        """Test goal progress events."""
        received = []

        async def handler(event: AgentEvent):
            received.append(event)

        event_bus.subscribe([EventType.GOAL_PROGRESS], handler)

        await event_bus.publish(AgentEvent(
            type=EventType.GOAL_PROGRESS,
            stream_id="test",
            data={
                "goal_id": "goal-1",
                "overall_progress": 0.75,
                "criteria_progress": {"sc-1": 1.0, "sc-2": 0.5},
            },
        ))

        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].data["overall_progress"] == 0.75

    @pytest.mark.asyncio
    async def test_constraint_violation_event(self, event_bus):
        """Test constraint violation events."""
        received = []

        async def handler(event: AgentEvent):
            received.append(event)

        event_bus.subscribe([EventType.CONSTRAINT_VIOLATION], handler)

        await event_bus.publish(AgentEvent(
            type=EventType.CONSTRAINT_VIOLATION,
            stream_id="test",
            execution_id="exec-1",
            data={
                "constraint_id": "c-budget",
                "violation_details": "Budget exceeded",
            },
        ))

        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].data["constraint_id"] == "c-budget"


# === Stream Coordination Tests ===

class TestStreamCoordination:
    """Tests for multi-stream coordination."""

    @pytest.mark.asyncio
    async def test_cross_stream_event_routing(self, event_bus):
        """Test events can be routed between streams."""
        webhook_events = []
        api_events = []

        async def webhook_handler(event: AgentEvent):
            webhook_events.append(event)

        async def api_handler(event: AgentEvent):
            api_events.append(event)

        event_bus.subscribe(
            [EventType.EXECUTION_COMPLETED],
            webhook_handler,
            filter_stream="webhook",
        )

        event_bus.subscribe(
            [EventType.EXECUTION_COMPLETED],
            api_handler,
            filter_stream="api",
        )

        # Publish to both streams
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="webhook",
            execution_id="exec-1",
        ))

        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="api",
            execution_id="exec-2",
        ))

        await asyncio.sleep(0.1)

        assert len(webhook_events) == 1
        assert len(api_events) == 1
        assert webhook_events[0].stream_id == "webhook"
        assert api_events[0].stream_id == "api"


# === Event Type Helpers ===

class TestEventTypeHelpers:
    """Tests for event type handling."""

    def test_agent_event_to_dict(self):
        """Test AgentEvent serialization."""
        event = AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="webhook",
            execution_id="exec-1",
            data={"key": "value"},
            correlation_id="corr-123",
        )

        data = event.to_dict()

        assert data["type"] == "execution_started"
        assert data["stream_id"] == "webhook"
        assert data["execution_id"] == "exec-1"
        assert data["data"] == {"key": "value"}
        assert data["correlation_id"] == "corr-123"
        assert "timestamp" in data
