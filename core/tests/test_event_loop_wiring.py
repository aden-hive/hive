"""
Tests for event_loop node type wiring (Issue #2513).

Covers:
- NodeSpec.client_facing field
- event_loop in VALID_NODE_TYPES
- _get_node_implementation() event_loop branch
- no-retry enforcement in serial execution path
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.core import Runtime


class AlwaysFailsNode(NodeProtocol):
    """A test node that always fails."""

    def __init__(self):
        self.attempt_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1
        return NodeResult(success=False, error=f"Permanent error (attempt {self.attempt_count})")


class SucceedsOnceNode(NodeProtocol):
    """A test node that always succeeds."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(success=True, output={"result": "ok"})


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Mock asyncio.sleep to avoid real delays from exponential backoff."""
    monkeypatch.setattr("asyncio.sleep", AsyncMock())


@pytest.fixture
def runtime():
    """Create a mock Runtime for testing."""
    runtime = MagicMock(spec=Runtime)
    runtime.start_run = MagicMock(return_value="test_run_id")
    runtime.decide = MagicMock(return_value="test_decision_id")
    runtime.record_outcome = MagicMock()
    runtime.end_run = MagicMock()
    runtime.report_problem = MagicMock()
    runtime.set_node = MagicMock()
    return runtime


# --- NodeSpec.client_facing tests ---


def test_client_facing_defaults_false():
    """NodeSpec without client_facing should default to False."""
    spec = NodeSpec(
        id="n1",
        name="Node 1",
        description="test",
        node_type="event_loop",
    )
    assert spec.client_facing is False


def test_client_facing_explicit_true():
    """NodeSpec with client_facing=True should retain the value."""
    spec = NodeSpec(
        id="n1",
        name="Node 1",
        description="test",
        node_type="event_loop",
        client_facing=True,
    )
    assert spec.client_facing is True


# --- VALID_NODE_TYPES tests ---


def test_event_loop_in_valid_node_types():
    """'event_loop' must be in GraphExecutor.VALID_NODE_TYPES."""
    assert "event_loop" in GraphExecutor.VALID_NODE_TYPES


def test_event_loop_node_spec_accepted():
    """Creating a NodeSpec with node_type='event_loop' should not raise."""
    spec = NodeSpec(
        id="el1",
        name="Event Loop",
        description="test",
        node_type="event_loop",
    )
    assert spec.node_type == "event_loop"


# --- _get_node_implementation() tests ---


def test_unregistered_event_loop_auto_creates(runtime):
    """An event_loop node not in the registry should be auto-created."""
    from framework.graph.event_loop_node import EventLoopNode

    spec = NodeSpec(
        id="el1",
        name="Event Loop",
        description="test",
        node_type="event_loop",
    )
    executor = GraphExecutor(runtime=runtime)

    result = executor._get_node_implementation(spec)
    assert isinstance(result, EventLoopNode)
    # Auto-created node should be cached in registry
    assert "el1" in executor.node_registry


def test_registered_event_loop_returns_impl(runtime):
    """A registered event_loop node should be returned from the registry."""
    spec = NodeSpec(
        id="el1",
        name="Event Loop",
        description="test",
        node_type="event_loop",
    )
    impl = SucceedsOnceNode()
    executor = GraphExecutor(runtime=runtime)
    executor.register_node("el1", impl)

    result = executor._get_node_implementation(spec)
    assert result is impl


# --- No-retry enforcement (serial path) ---


@pytest.mark.asyncio
async def test_event_loop_max_retries_forced_zero(runtime):
    """Custom NodeProtocol impls with node_type=event_loop keep their max_retries."""
    node_spec = NodeSpec(
        id="el_fail",
        name="Failing Event Loop",
        description="event loop that fails",
        node_type="event_loop",
        max_retries=3,
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="el_fail",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["el_fail"],
    )

    goal = Goal(id="test_goal", name="Test", description="test")

    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    executor.register_node("el_fail", failing_node)

    result = await executor.execute(graph, goal, {})

    # Custom nodes (not EventLoopNode instances) keep their max_retries
    assert not result.success
    assert failing_node.attempt_count == 3


@pytest.mark.asyncio
async def test_event_loop_max_retries_zero_no_warning(runtime, caplog):
    """An event_loop node with max_retries=0 should not log a warning."""
    node_spec = NodeSpec(
        id="el_zero",
        name="Zero Retry Event Loop",
        description="event loop with 0 retries",
        node_type="event_loop",
        max_retries=0,
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="el_zero",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["el_zero"],
    )

    goal = Goal(id="test_goal", name="Test", description="test")

    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    executor.register_node("el_zero", failing_node)

    import logging

    with caplog.at_level(logging.WARNING):
        await executor.execute(graph, goal, {})

    # max_retries=0 should not trigger the override warning
    assert "Overriding to 0" not in caplog.text


@pytest.mark.asyncio
async def test_event_loop_max_retries_positive_logs_warning(runtime, caplog):
    """An event_loop node with max_retries=3 should log a warning about override."""
    node_spec = NodeSpec(
        id="el_warn",
        name="Warning Event Loop",
        description="event loop with retries",
        node_type="event_loop",
        max_retries=3,
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="el_warn",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["el_warn"],
    )

    goal = Goal(id="test_goal", name="Test", description="test")

    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    executor.register_node("el_warn", failing_node)

    import logging

    with caplog.at_level(logging.WARNING):
        await executor.execute(graph, goal, {})

    # Custom nodes (not EventLoopNode instances) don't get override warning
    assert "Overriding to 0" not in caplog.text


# --- Existing node types unaffected ---


def test_existing_node_types_unchanged():
    """Only event_loop is a valid node type."""
    expected = {"event_loop"}
    assert expected == GraphExecutor.VALID_NODE_TYPES

    # Default node_type is event_loop
    spec = NodeSpec(id="x", name="X", description="x")
    assert spec.node_type == "event_loop"

    # Default max_retries is still 3
    assert spec.max_retries == 3

    # Default client_facing is False
    assert spec.client_facing is False
