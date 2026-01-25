"""
Tests for GraphExecutor max_retries behavior.

Tests verify that:
- GraphExecutor respects node_spec.max_retries instead of using hardcoded value
- Different nodes can have different retry limits
- Default max_retries (3) is used when not specified
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from framework.graph.node import NodeSpec, NodeContext, NodeResult, NodeProtocol
from framework.graph.executor import GraphExecutor, ExecutionResult
from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal, SuccessCriterion


class MockRuntime:
    """Mock runtime for testing."""

    def start_run(self, **kwargs):
        return "run_id"

    def decide(self, **kwargs):
        return "dec_id"

    def record_outcome(self, **kwargs):
        pass

    def report_problem(self, **kwargs):
        pass

    def end_run(self, **kwargs):
        pass

    def set_node(self, node_id):
        pass


class FailingNode(NodeProtocol):
    """A node that always fails for testing retry behavior."""

    def __init__(self):
        self.execution_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.execution_count += 1
        return NodeResult(success=False, error="Intentional failure for testing")


class TestMaxRetriesRespected:
    """Tests for Issue #363 - max_retries should be read from node_spec."""

    @pytest.mark.asyncio
    async def test_respects_custom_max_retries(self, tmp_path):
        """Test that executor respects node_spec.max_retries instead of hardcoded 3."""
        # Create a node with max_retries=5
        node = NodeSpec(
            id="fail_node",
            name="Failing Node",
            description="Always fails",
            node_type="function",
            max_retries=5,  # Custom value - should retry 5 times, not 3
        )

        graph = GraphSpec(
            id="test-graph",
            goal_id="goal",
            entry_node="fail_node",
            terminal_nodes=["fail_node"],
            nodes=[node],
            edges=[],
        )

        goal = Goal(
            id="goal",
            name="Test Goal",
            description="Test retry behavior",
            success_criteria=[
                SuccessCriterion(
                    id="1",
                    description="Should fail",
                    metric="success",
                    target="false"
                )
            ],
        )

        # Create executor with mock runtime
        executor = GraphExecutor(runtime=MockRuntime())

        # Register a node that tracks executions
        failing_node = FailingNode()
        executor.register_node("fail_node", failing_node)

        # Execute
        result = await executor.execute(graph, goal)

        # Should have failed after 5 attempts (not 3)
        assert result.success is False
        assert "after 5 attempts" in result.error
        assert failing_node.execution_count == 5

    @pytest.mark.asyncio
    async def test_respects_high_max_retries(self, tmp_path):
        """Test that executor handles high max_retries values."""
        node = NodeSpec(
            id="fail_node",
            name="Failing Node",
            description="Always fails",
            node_type="function",
            max_retries=10,  # Even higher retry limit
        )

        graph = GraphSpec(
            id="test-graph",
            goal_id="goal",
            entry_node="fail_node",
            terminal_nodes=["fail_node"],
            nodes=[node],
            edges=[],
        )

        goal = Goal(
            id="goal",
            name="Test Goal",
            description="Test high retry count",
            success_criteria=[
                SuccessCriterion(
                    id="1",
                    description="Should fail",
                    metric="success",
                    target="false"
                )
            ],
        )

        executor = GraphExecutor(runtime=MockRuntime())
        failing_node = FailingNode()
        executor.register_node("fail_node", failing_node)

        result = await executor.execute(graph, goal)

        # Should have retried 10 times
        assert result.success is False
        assert "after 10 attempts" in result.error
        assert failing_node.execution_count == 10

    @pytest.mark.asyncio
    async def test_default_max_retries(self, tmp_path):
        """Test that default max_retries (3) is respected when not set."""
        # Don't set max_retries - should use default of 3
        node = NodeSpec(
            id="fail_node",
            name="Failing Node",
            description="Always fails",
            node_type="function",
            # max_retries not set - should default to 3
        )

        assert node.max_retries == 3  # Verify default

        graph = GraphSpec(
            id="test-graph",
            goal_id="goal",
            entry_node="fail_node",
            terminal_nodes=["fail_node"],
            nodes=[node],
            edges=[],
        )

        goal = Goal(
            id="goal",
            name="Test Goal",
            description="Test default retry count",
            success_criteria=[
                SuccessCriterion(
                    id="1",
                    description="Should fail",
                    metric="success",
                    target="false"
                )
            ],
        )

        executor = GraphExecutor(runtime=MockRuntime())
        failing_node = FailingNode()
        executor.register_node("fail_node", failing_node)

        result = await executor.execute(graph, goal)

        # Should have retried 3 times (default)
        assert result.success is False
        assert "after 3 attempts" in result.error
        assert failing_node.execution_count == 3

    @pytest.mark.asyncio
    async def test_different_nodes_different_retries(self, tmp_path):
        """Test that different nodes can have different retry limits."""
        # This is a regression test to ensure per-node config works
        node1 = NodeSpec(
            id="node1",
            name="Node 1",
            description="First node",
            node_type="function",
            max_retries=2,
        )

        node2 = NodeSpec(
            id="node2",
            name="Node 2",
            description="Second node",
            node_type="function",
            max_retries=7,
        )

        # Each node should have its own retry limit
        assert node1.max_retries == 2
        assert node2.max_retries == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
