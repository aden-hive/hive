"""
Test that ON_FAILURE edges are followed when a node fails after max retries.

Verifies the fix for Issue #3449 where the executor would immediately terminate
when max retries were exceeded, without checking for ON_FAILURE edges that could
route to error handler nodes.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.core import Runtime


class AlwaysFailsNode(NodeProtocol):
    """A node that always fails."""

    def __init__(self):
        self.attempt_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1
        return NodeResult(success=False, error=f"Permanent error (attempt {self.attempt_count})")


class FailureHandlerNode(NodeProtocol):
    """A node that handles failures from upstream nodes."""

    def __init__(self):
        self.executed = False
        self.execute_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.executed = True
        self.execute_count += 1
        return NodeResult(
            success=True,
            output={"handled": True, "recovery": "graceful"},
        )


class SuccessNode(NodeProtocol):
    """A node that always succeeds with configurable output."""

    def __init__(self, output: dict | None = None):
        self.execute_count = 0
        self._output = output or {"result": "ok"}

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.execute_count += 1
        return NodeResult(success=True, output=self._output)


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


@pytest.fixture
def goal():
    return Goal(
        id="test_goal",
        name="Test Goal",
        description="Test ON_FAILURE edge routing",
    )


@pytest.mark.asyncio
async def test_on_failure_edge_followed_after_max_retries(runtime, goal):
    """
    When a node fails after exhausting max retries, ON_FAILURE edges should
    be followed to route execution to a failure handler node.
    """
    nodes = [
        NodeSpec(
            id="failing",
            name="Failing Node",
            description="Always fails",
            node_type="event_loop",
            output_keys=[],
            max_retries=1,
        ),
        NodeSpec(
            id="handler",
            name="Failure Handler",
            description="Handles failures",
            node_type="event_loop",
            output_keys=["handled", "recovery"],
        ),
    ]

    edges = [
        EdgeSpec(
            id="fail_to_handler",
            source="failing",
            target="handler",
            condition=EdgeCondition.ON_FAILURE,
        ),
    ]

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="failing",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["handler"],
    )

    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    handler_node = FailureHandlerNode()
    executor.register_node("failing", failing_node)
    executor.register_node("handler", handler_node)

    result = await executor.execute(graph, goal, {})

    # The handler should have executed
    assert handler_node.executed, "Failure handler was not executed"
    assert handler_node.execute_count == 1

    # Overall execution should succeed (handler recovered)
    assert result.success
    # Handler node should appear in the execution path
    assert "handler" in result.path


@pytest.mark.asyncio
async def test_no_on_failure_edge_still_terminates(runtime, goal):
    """
    When a node fails after max retries and there is no ON_FAILURE edge,
    the executor should terminate with a failure result (original behavior).
    """
    nodes = [
        NodeSpec(
            id="failing",
            name="Failing Node",
            description="Always fails",
            node_type="event_loop",
            output_keys=[],
            max_retries=1,
        ),
    ]

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="failing",
        nodes=[nodes[0]],
        edges=[],
        terminal_nodes=["failing"],
    )

    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    executor.register_node("failing", failing_node)

    result = await executor.execute(graph, goal, {})

    assert not result.success
    assert "failed after 1 attempts" in result.error


@pytest.mark.asyncio
async def test_on_failure_edge_not_followed_on_success(runtime, goal):
    """
    ON_FAILURE edges should NOT be followed when a node succeeds.
    Only ON_SUCCESS edges should fire.
    """
    nodes = [
        NodeSpec(
            id="working",
            name="Working Node",
            description="Always succeeds",
            node_type="event_loop",
            output_keys=["result"],
        ),
        NodeSpec(
            id="handler",
            name="Failure Handler",
            description="Should not be reached",
            node_type="event_loop",
            output_keys=["handled"],
        ),
        NodeSpec(
            id="next",
            name="Next Node",
            description="Normal successor",
            node_type="event_loop",
            output_keys=["done"],
        ),
    ]

    edges = [
        EdgeSpec(
            id="on_fail",
            source="working",
            target="handler",
            condition=EdgeCondition.ON_FAILURE,
        ),
        EdgeSpec(
            id="on_success",
            source="working",
            target="next",
            condition=EdgeCondition.ON_SUCCESS,
        ),
    ]

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="working",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["handler", "next"],
    )

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("working", SuccessNode(output={"result": "ok"}))
    handler_node = FailureHandlerNode()
    executor.register_node("handler", handler_node)
    executor.register_node("next", SuccessNode(output={"done": True}))

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert not handler_node.executed, "Failure handler should not run on success"
    assert "next" in result.path, "Should follow ON_SUCCESS edge to 'next'"


@pytest.mark.asyncio
async def test_on_failure_edge_with_zero_retries(runtime, goal):
    """
    ON_FAILURE edges should work even when max_retries=0 (no retries allowed).
    The node fails once and immediately routes to the failure handler.
    """
    nodes = [
        NodeSpec(
            id="fragile",
            name="Fragile Node",
            description="Fails with no retries",
            node_type="event_loop",
            output_keys=[],
            max_retries=0,
        ),
        NodeSpec(
            id="handler",
            name="Failure Handler",
            description="Handles failures",
            node_type="event_loop",
            output_keys=["handled", "recovery"],
        ),
    ]

    edges = [
        EdgeSpec(
            id="fail_to_handler",
            source="fragile",
            target="handler",
            condition=EdgeCondition.ON_FAILURE,
        ),
    ]

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="fragile",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["handler"],
    )

    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    handler_node = FailureHandlerNode()
    executor.register_node("fragile", failing_node)
    executor.register_node("handler", handler_node)

    result = await executor.execute(graph, goal, {})

    # Should route to handler after single failure (no retries)
    assert failing_node.attempt_count == 1
    assert handler_node.executed
    assert result.success


@pytest.mark.asyncio
async def test_on_failure_handler_appears_in_path(runtime, goal):
    """
    The failure handler node should appear in the execution path.
    """
    nodes = [
        NodeSpec(
            id="failing",
            name="Failing Node",
            description="Always fails",
            node_type="event_loop",
            output_keys=[],
            max_retries=1,
        ),
        NodeSpec(
            id="handler",
            name="Failure Handler",
            description="Handles failures",
            node_type="event_loop",
            output_keys=["handled", "recovery"],
        ),
    ]

    edges = [
        EdgeSpec(
            id="fail_to_handler",
            source="failing",
            target="handler",
            condition=EdgeCondition.ON_FAILURE,
        ),
    ]

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="failing",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["handler"],
    )

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("failing", AlwaysFailsNode())
    executor.register_node("handler", FailureHandlerNode())

    result = await executor.execute(graph, goal, {})

    assert "failing" in result.path
    assert "handler" in result.path
    assert result.node_visit_counts.get("handler") == 1
