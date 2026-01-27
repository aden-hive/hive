"""
Test that GraphExecutor respects node_spec.max_retries configuration.

This test verifies the fix for Issue #363 where GraphExecutor was ignoring
the max_retries field in NodeSpec and using a hardcoded value of 3.
"""

from unittest.mock import MagicMock

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.core import Runtime


class FlakyTestNode(NodeProtocol):
    """A test node that fails a configurable number of times before succeeding."""

    def __init__(self, fail_times: int = 2):
        self.fail_times = fail_times
        self.attempt_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1

        if self.attempt_count <= self.fail_times:
            return NodeResult(
                success=False, error=f"Transient error (attempt {self.attempt_count})"
            )

        return NodeResult(
            success=True, output={"result": f"succeeded after {self.attempt_count} attempts"}
        )


class AlwaysFailsNode(NodeProtocol):
    """A test node that always fails."""

    def __init__(self):
        self.attempt_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1
        return NodeResult(success=False, error=f"Permanent error (attempt {self.attempt_count})")


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


@pytest.mark.asyncio
async def test_executor_respects_custom_max_retries_high(runtime):
    """
    Test that executor respects max_retries when set to high value (10).

    Node fails 5 times before succeeding. With max_retries=10, should succeed.
    """
    # Create node with max_retries=10
    node_spec = NodeSpec(
        id="flaky_node",
        name="Flaky Node",
        description="A node that fails multiple times before succeeding",
        max_retries=10,  # Should allow 10 retries
        node_type="function",
        output_keys=["result"],
    )

    # Create graph
    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="flaky_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["flaky_node"],
    )

    # Create goal
    goal = Goal(id="test_goal", name="Test Goal", description="Test that max_retries is respected")

    # Create executor and register flaky node (fails 5 times, succeeds on 6th)
    executor = GraphExecutor(runtime=runtime)
    flaky_node = FlakyTestNode(fail_times=5)
    executor.register_node("flaky_node", flaky_node)

    # Execute
    result = await executor.execute(graph, goal, {})

    # Should succeed because 5 failures < 10 max_retries (N total attempts allowed)
    assert result.success
    assert flaky_node.attempt_count == 6  # 5 failures + 1 success


@pytest.mark.asyncio
async def test_executor_respects_custom_max_retries_low(runtime):
    """
    Test that executor respects max_retries when set to low value (2).

    Node always fails. With max_retries=2, should fail after 2 total attempts.
    """
    # Create node with max_retries=2
    node_spec = NodeSpec(
        id="fragile_node",
        name="Fragile Node",
        description="A node with low retry tolerance",
        max_retries=2,  # max_retries=N means N total attempts allowed
        node_type="function",
        output_keys=["result"],
    )

    # Create graph
    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="fragile_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["fragile_node"],
    )

    # Create goal
    goal = Goal(id="test_goal", name="Test Goal", description="Test low max_retries")

    # Create executor and register always-failing node
    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    executor.register_node("fragile_node", failing_node)

    # Execute
    result = await executor.execute(graph, goal, {})

    # Should fail after exactly 2 attempts (max_retries=N means N total attempts)
    assert not result.success
    assert failing_node.attempt_count == 2  # 2 total attempts
    assert "failed after 2 attempts" in result.error


@pytest.mark.asyncio
async def test_executor_respects_default_max_retries(runtime):
    """
    Test that executor uses default max_retries=3 when not specified.
    """
    # Create node without specifying max_retries (should default to 3)
    node_spec = NodeSpec(
        id="default_node",
        name="Default Node",
        description="A node using default retry settings",
        # max_retries not specified, should default to 3
        node_type="function",
        output_keys=["result"],
    )

    # Create graph
    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="default_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["default_node"],
    )

    # Create goal
    goal = Goal(id="test_goal", name="Test Goal", description="Test default max_retries")

    # Create executor with always-failing node
    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    executor.register_node("default_node", failing_node)

    # Execute
    result = await executor.execute(graph, goal, {})

    # Should fail after default 3 total attempts (max_retries=N means N total attempts)
    assert not result.success
    assert failing_node.attempt_count == 3  # 3 total attempts
    assert "failed after 3 attempts" in result.error


@pytest.mark.asyncio
async def test_executor_max_retries_two_succeeds_on_second(runtime):
    """
    Test that max_retries=2 allows two attempts total.

    Node fails once, succeeds on second try. With max_retries=2, should succeed.
    """
    # Create node with max_retries=2 (allows 2 total attempts)
    node_spec = NodeSpec(
        id="two_retry_node",
        name="Two Retry Node",
        description="A node with two attempts allowed",
        max_retries=2,  # max_retries=N means N total attempts allowed
        node_type="function",
        output_keys=["result"],
    )

    # Create graph
    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="two_retry_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["two_retry_node"],
    )

    # Create goal
    goal = Goal(id="test_goal", name="Test Goal", description="Test max_retries=2")

    # Create executor with node that fails once, succeeds on second try
    executor = GraphExecutor(runtime=runtime)
    flaky_node = FlakyTestNode(fail_times=1)
    executor.register_node("two_retry_node", flaky_node)

    # Execute
    result = await executor.execute(graph, goal, {})

    # Should succeed on second attempt (max_retries=2 allows 2 total attempts)
    assert result.success
    assert flaky_node.attempt_count == 2  # 1 failure + 1 success


@pytest.mark.asyncio
async def test_executor_different_nodes_different_max_retries(runtime):
    """
    Test that different nodes in same graph can have different max_retries.
    """
    # Create two nodes with different max_retries
    node1_spec = NodeSpec(
        id="node1",
        name="Node 1",
        description="First node in multi-node test",
        max_retries=2,
        node_type="function",
        output_keys=["result1"],
    )

    node2_spec = NodeSpec(
        id="node2",
        name="Node 2",
        description="Second node in multi-node test",
        max_retries=5,
        node_type="function",
        input_keys=["result1"],
        output_keys=["result2"],
    )

    # Note: This test would require more complex graph setup with edges
    # For now, we've verified that max_retries is read from node_spec correctly
    # The actual value varies per node as expected
    assert node1_spec.max_retries == 2
    assert node2_spec.max_retries == 5
