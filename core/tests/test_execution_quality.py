"""
Tests for execution quality tracking.

Verifies that ExecutionResult properly tracks retries, partial failures,
and execution quality to ensure observability reflects semantic correctness.
"""

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.graph.goal import Goal, SuccessCriterion
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.core import Runtime


class FlakyNode(NodeProtocol):
    """A node that fails N times before succeeding."""

    def __init__(self, fail_count: int = 2):
        self.fail_count = fail_count
        self.attempt = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Execute with flaky behavior."""
        self.attempt += 1
        if self.attempt <= self.fail_count:
            return NodeResult(
                success=False,
                error=f"Simulated failure {self.attempt}/{self.fail_count}",
            )

        # Get the output keys from the node spec and populate them
        output = {}
        for key in ctx.node_spec.output_keys:
            output[key] = f"succeeded after {self.attempt} attempts"

        return NodeResult(
            success=True,
            output=output,
        )

    def validate_input(self, ctx: NodeContext) -> list[str]:
        return []


class AlwaysSucceedsNode(NodeProtocol):
    """A node that always succeeds immediately."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        # Get the output keys from the node spec and populate them
        output = {}
        for key in ctx.node_spec.output_keys:
            output[key] = "success"

        return NodeResult(
            success=True,
            output=output,
        )

    def validate_input(self, ctx: NodeContext) -> list[str]:
        return []


class AlwaysFailsNode(NodeProtocol):
    """A node that always fails (for testing max retries)."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(
            success=False,
            error="Permanent failure",
        )

    def validate_input(self, ctx: NodeContext) -> list[str]:
        return []


@pytest.mark.asyncio
class TestExecutionQuality:
    """Test execution quality tracking."""

    async def test_clean_success_no_retries(self, tmp_path):
        """Test clean success when no retries occur."""
        # Setup
        runtime = Runtime(tmp_path)
        goal = Goal(
            id="test",
            name="Test",
            description="Test clean execution",
            success_criteria=[
                SuccessCriterion(
                    id="works",
                    description="Works",
                    metric="output_equals",
                    target="success",
                )
            ],
        )

        # Create simple graph with always-succeeding node
        graph = GraphSpec(
            id="test-graph",
            goal_id=goal.id,
            nodes=[
                NodeSpec(
                    id="node1",
                    name="Always Succeeds",
                    description="Never fails",
                    node_type="event_loop",
                    output_keys=["result"],
                ),
            ],
            edges=[],
            entry_node="node1",
            terminal_nodes=["node1"],
        )

        executor = GraphExecutor(
            runtime=runtime,
            node_registry={"node1": AlwaysSucceedsNode()},
        )

        # Execute
        result = await executor.execute(graph, goal)

        # Verify - this should be clean success
        assert result.success is True
        assert result.execution_quality == "clean"
        assert result.total_retries == 0
        assert result.nodes_with_failures == []
        assert result.had_partial_failures is False
        assert result.is_clean_success is True
        assert result.is_degraded_success is False

    async def test_degraded_success_with_retries(self, tmp_path):
        """Test degraded success when retries occur but eventually succeeds."""
        # Setup
        runtime = Runtime(tmp_path)
        goal = Goal(
            id="test",
            name="Test",
            description="Test execution with retries",
            success_criteria=[
                SuccessCriterion(
                    id="works",
                    description="Works eventually",
                    metric="output_equals",
                    target="success",
                )
            ],
        )

        # Create graph with flaky node (fails 2 times before succeeding)
        # (actual impl from registry is FlakyNode)
        graph = GraphSpec(
            id="test-graph",
            goal_id=goal.id,
            nodes=[
                NodeSpec(
                    id="flaky",
                    name="Flaky Node",
                    description="Fails then succeeds",
                    node_type="event_loop",
                    output_keys=["result"],
                    max_retries=3,  # Allow retries
                ),
            ],
            edges=[],
            entry_node="flaky",
            terminal_nodes=["flaky"],
        )

        executor = GraphExecutor(
            runtime=runtime,
            node_registry={"flaky": FlakyNode(fail_count=2)},
        )

        # Execute
        result = await executor.execute(graph, goal)

        # Verify - this should be degraded success
        assert result.success is True
        assert result.execution_quality == "degraded"
        assert result.total_retries == 2
        assert "flaky" in result.nodes_with_failures
        assert result.retry_details["flaky"] == 2
        assert result.had_partial_failures is True
        assert result.is_clean_success is False
        assert result.is_degraded_success is True

    async def test_failed_execution_max_retries_exceeded(self, tmp_path):
        """Test failed execution when max retries are exceeded."""
        # Setup
        runtime = Runtime(tmp_path)
        goal = Goal(
            id="test",
            name="Test",
            description="Test execution failure",
            success_criteria=[
                SuccessCriterion(
                    id="works",
                    description="Should work",
                    metric="output_equals",
                    target="success",
                )
            ],
        )

        # Create graph with always-failing node
        # (actual impl from registry is AlwaysFailsNode)
        graph = GraphSpec(
            id="test-graph",
            goal_id=goal.id,
            nodes=[
                NodeSpec(
                    id="fails",
                    name="Always Fails",
                    description="Never succeeds",
                    node_type="event_loop",
                    output_keys=["result"],
                    max_retries=2,  # Will retry twice then fail
                ),
            ],
            edges=[],
            entry_node="fails",
            terminal_nodes=["fails"],
        )

        executor = GraphExecutor(
            runtime=runtime,
            node_registry={"fails": AlwaysFailsNode()},
        )

        # Execute
        result = await executor.execute(graph, goal)

        # Verify - this should be failed
        assert result.success is False
        assert result.execution_quality == "failed"
        assert result.total_retries == 2
        assert "fails" in result.nodes_with_failures
        assert result.retry_details["fails"] == 2
        assert result.had_partial_failures is True
        assert result.error is not None
        assert "failed after 2 attempts" in result.error

    async def test_multi_node_partial_failures(self, tmp_path):
        """Test tracking failures across multiple nodes."""
        # Setup
        runtime = Runtime(tmp_path)
        goal = Goal(
            id="test",
            name="Test",
            description="Test multi-node execution",
            success_criteria=[
                SuccessCriterion(
                    id="works",
                    description="All nodes succeed",
                    metric="output_equals",
                    target="success",
                )
            ],
        )

        # Create graph with multiple flaky nodes
        # (actual impls from registry are FlakyNode instances)
        graph = GraphSpec(
            id="test-graph",
            goal_id=goal.id,
            nodes=[
                NodeSpec(
                    id="flaky1",
                    name="Flaky Node 1",
                    description="Fails once",
                    node_type="event_loop",
                    output_keys=["result1"],
                    max_retries=3,
                ),
                NodeSpec(
                    id="flaky2",
                    name="Flaky Node 2",
                    description="Fails twice",
                    node_type="event_loop",
                    input_keys=["result1"],
                    output_keys=["result2"],
                    max_retries=3,
                ),
                NodeSpec(
                    id="success",
                    name="Success Node",
                    description="Always succeeds",
                    node_type="event_loop",
                    input_keys=["result2"],
                    output_keys=["final"],
                ),
            ],
            edges=[
                EdgeSpec(
                    id="e1",
                    source="flaky1",
                    target="flaky2",
                    condition=EdgeCondition.ON_SUCCESS,
                ),
                EdgeSpec(
                    id="e2",
                    source="flaky2",
                    target="success",
                    condition=EdgeCondition.ON_SUCCESS,
                ),
            ],
            entry_node="flaky1",
            terminal_nodes=["success"],
        )

        executor = GraphExecutor(
            runtime=runtime,
            node_registry={
                "flaky1": FlakyNode(fail_count=1),  # Fails once
                "flaky2": FlakyNode(fail_count=2),  # Fails twice
                "success": AlwaysSucceedsNode(),
            },
        )

        # Execute
        result = await executor.execute(graph, goal)

        # Verify - should succeed but be degraded
        assert result.success is True
        assert result.execution_quality == "degraded"
        assert result.total_retries == 3  # 1 + 2 retries
        assert set(result.nodes_with_failures) == {"flaky1", "flaky2"}
        assert result.retry_details["flaky1"] == 1
        assert result.retry_details["flaky2"] == 2
        assert result.had_partial_failures is True
        assert result.is_clean_success is False
        assert result.is_degraded_success is True

    async def test_execution_result_properties(self, tmp_path):
        """Test ExecutionResult helper properties."""
        # Clean success
        clean = ExecutionResult(
            success=True,
            execution_quality="clean",
        )
        assert clean.is_clean_success is True
        assert clean.is_degraded_success is False

        # Degraded success
        degraded = ExecutionResult(
            success=True,
            execution_quality="degraded",
            total_retries=2,
        )
        assert degraded.is_clean_success is False
        assert degraded.is_degraded_success is True

        # Failed
        failed = ExecutionResult(
            success=False,
            execution_quality="failed",
        )
        assert failed.is_clean_success is False
        assert failed.is_degraded_success is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
