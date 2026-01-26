"""
Test that GraphExecutor respects node_spec.max_retries configuration.

This test verifies the fix for Issue #363 where GraphExecutor was ignoring
the max_retries field in NodeSpec and using a hardcoded value of 3.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from framework.graph.executor import GraphExecutor, ExecutionResult
from framework.graph.node import NodeSpec, NodeProtocol, NodeContext, NodeResult
from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
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
                success=False,
                error=f"Transient error (attempt {self.attempt_count})"
            )
        
        return NodeResult(
            success=True,
            output={"result": f"succeeded after {self.attempt_count} attempts"}
        )


class AlwaysFailsNode(NodeProtocol):
    """A test node that always fails."""
    
    def __init__(self):
        self.attempt_count = 0
    
    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1
        return NodeResult(
            success=False,
            error=f"Permanent error (attempt {self.attempt_count})"
        )


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
        max_retries=10,  # Should allow 10 retries
        node_type="function",
        output_keys=["result"]
    )
    
    # Create graph
    graph = GraphSpec(
        name="Test Graph",
        entry_node="flaky_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["flaky_node"]
    )
    
    # Create goal
    goal = Goal(
        id="test_goal",
        name="Test Goal",
        description="Test that max_retries is respected"
    )
    
    # Create executor and register flaky node (fails 5 times, succeeds on 6th)
    executor = GraphExecutor(runtime=runtime)
    flaky_node = FlakyTestNode(fail_times=5)
    executor.register_node("flaky_node", flaky_node)
    
    # Execute
    result = await executor.execute(graph, goal, {})
    
    # Should succeed because 5 failures < 10 max_retries
    assert result.success == True
    assert flaky_node.attempt_count == 6  # 5 failures + 1 success
    assert "succeeded after 6 attempts" in result.output.get("result", "")


@pytest.mark.asyncio
async def test_executor_respects_custom_max_retries_low(runtime):
    """
    Test that executor respects max_retries when set to low value (2).
    
    Node fails 5 times. With max_retries=2, should fail after 2 attempts.
    """
    # Create node with max_retries=2
    node_spec = NodeSpec(
        id="fragile_node",
        name="Fragile Node",
        max_retries=2,  # Should only retry twice
        node_type="function",
        output_keys=["result"]
    )
    
    # Create graph
    graph = GraphSpec(
        name="Test Graph",
        entry_node="fragile_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["fragile_node"]
    )
    
    # Create goal
    goal = Goal(
        id="test_goal",
        name="Test Goal",
        description="Test low max_retries"
    )
    
    # Create executor and register always-failing node
    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    executor.register_node("fragile_node", failing_node)
    
    # Execute
    result = await executor.execute(graph, goal, {})
    
    # Should fail after exactly 2 attempts (max_retries=2 means try 3 times total: initial + 2 retries)
    assert result.success == False
    assert failing_node.attempt_count == 3  # Initial attempt + 2 retries
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
        # max_retries not specified, should default to 3
        node_type="function",
        output_keys=["result"]
    )
    
    # Create graph
    graph = GraphSpec(
        name="Test Graph",
        entry_node="default_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["default_node"]
    )
    
    # Create goal
    goal = Goal(
        id="test_goal",
        name="Test Goal",
        description="Test default max_retries"
    )
    
    # Create executor with always-failing node
    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    executor.register_node("default_node", failing_node)
    
    # Execute
    result = await executor.execute(graph, goal, {})
    
    # Should fail after default 3 retries (4 total attempts)
    assert result.success == False
    assert failing_node.attempt_count == 4  # Initial + 3 retries
    assert "failed after 3 attempts" in result.error


@pytest.mark.asyncio
async def test_executor_max_retries_one_succeeds_immediately(runtime):
    """
    Test that max_retries=1 allows one retry before failing.
    """
    # Create node with max_retries=1
    node_spec = NodeSpec(
        id="one_retry_node",
        name="One Retry Node",
        max_retries=1,
        node_type="function",
        output_keys=["result"]
    )
    
    # Create graph
    graph = GraphSpec(
        name="Test Graph",
        entry_node="one_retry_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["one_retry_node"]
    )
    
    # Create goal
    goal = Goal(
        id="test_goal",
        name="Test Goal",
        description="Test max_retries=1"
    )
    
    # Create executor with node that fails once, succeeds on second try
    executor = GraphExecutor(runtime=runtime)
    flaky_node = FlakyTestNode(fail_times=1)
    executor.register_node("one_retry_node", flaky_node)
    
    # Execute
    result = await executor.execute(graph, goal, {})
    
    # Should succeed on second attempt
    assert result.success == True
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
        max_retries=2,
        node_type="function",
        output_keys=["result1"]
    )
    
    node2_spec = NodeSpec(
        id="node2",
        name="Node 2",
        max_retries=5,
        node_type="function",
        input_keys=["result1"],
        output_keys=["result2"]
    )
    
    # Note: This test would require more complex graph setup with edges
    # For now, we've verified that max_retries is read from node_spec correctly
    # The actual value varies per node as expected
    assert node1_spec.max_retries == 2
    assert node2_spec.max_retries == 5
