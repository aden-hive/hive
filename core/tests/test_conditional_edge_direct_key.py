"""
Regression tests for conditional edge direct key access (Issue #3599).

Verifies that node outputs are written to memory before edge evaluation,
enabling direct key access in conditional expressions (e.g., 'score > 80')
instead of requiring output['score'] > 80 syntax.
"""

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.core import Runtime


class SimpleRuntime(Runtime):
    """Minimal runtime for testing."""

    def start_run(self, **kwargs):
        return "test-run"

    def end_run(self, **kwargs):
        pass

    def report_problem(self, **kwargs):
        pass

    def decide(self, **kwargs):
        return "test-decision"

    def record_outcome(self, **kwargs):
        pass

    def set_node(self, **kwargs):
        pass


class ScoreNode(NodeProtocol):
    """Node that outputs a score value."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(success=True, output={"score": 85})


class HighScoreNode(NodeProtocol):
    """Consumer node for high scores."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(success=True, output={"result": "high_score_path"})


class MultiKeyNode(NodeProtocol):
    """Node that outputs multiple keys."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(success=True, output={"x": 100, "y": 50})


class ConsumerNode(NodeProtocol):
    """Generic consumer node."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(success=True, output={"processed": True})


@pytest.mark.asyncio
async def test_direct_key_access_in_conditional_edge():
    """
    Verify direct key access works in conditional edges (e.g., 'score > 80').

    This is the core regression test for issue #3599. Before the fix,
    node outputs were only written to memory during input mapping (after
    edge evaluation), causing NameError when edges tried to access keys directly.
    """
    goal = Goal(
        id="test-direct-key",
        name="Test Direct Key Access",
        description="Test that direct key access works in conditional edges",
    )

    nodes = [
        NodeSpec(
            id="score_node",
            name="ScoreNode",
            description="Outputs a score",
            node_type="event_loop",
            output_keys=["score"],
        ),
        NodeSpec(
            id="high_score_node",
            name="HighScoreNode",
            description="Handles high scores",
            node_type="event_loop",
            input_keys=["score"],
            output_keys=["result"],
        ),
    ]

    # Edge with DIRECT key access: 'score > 80' (not 'output["score"] > 80')
    edges = [
        EdgeSpec(
            id="score_to_high",
            source="score_node",
            target="high_score_node",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="score > 80",  # Direct key access
        )
    ]

    graph = GraphSpec(
        id="test-graph",
        goal_id="test-direct-key",
        entry_node="score_node",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["high_score_node"],
    )

    runtime = SimpleRuntime(storage_path="/tmp/test")
    executor = GraphExecutor(runtime=runtime)
    executor.register_node("score_node", ScoreNode())
    executor.register_node("high_score_node", HighScoreNode())

    result = await executor.execute(graph, goal, {})

    # Verify the edge was followed (high_score_node executed)
    assert result.success, "Execution should succeed"
    assert "high_score_node" in result.path, (
        f"Expected high_score_node in path. "
        f"Condition 'score > 80' should evaluate to True (score=85). "
        f"Path: {result.path}"
    )


@pytest.mark.asyncio
async def test_backward_compatibility_output_syntax():
    """
    Verify backward compatibility: output['key'] syntax still works.

    The fix should not break existing code that uses the explicit
    output dictionary syntax in conditional expressions.
    """
    goal = Goal(
        id="test-backward-compat",
        name="Test Backward Compatibility",
        description="Test that output['key'] syntax still works",
    )

    nodes = [
        NodeSpec(
            id="score_node",
            name="ScoreNode",
            description="Outputs a score",
            node_type="event_loop",
            output_keys=["score"],
        ),
        NodeSpec(
            id="consumer_node",
            name="ConsumerNode",
            description="Consumer",
            node_type="event_loop",
            input_keys=["score"],
            output_keys=["processed"],
        ),
    ]

    # Edge with OLD syntax: output['score'] > 80
    edges = [
        EdgeSpec(
            id="score_to_consumer",
            source="score_node",
            target="consumer_node",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output['score'] > 80",  # Old explicit syntax
        )
    ]

    graph = GraphSpec(
        id="test-graph-compat",
        goal_id="test-backward-compat",
        entry_node="score_node",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["consumer_node"],
    )

    runtime = SimpleRuntime(storage_path="/tmp/test")
    executor = GraphExecutor(runtime=runtime)
    executor.register_node("score_node", ScoreNode())
    executor.register_node("consumer_node", ConsumerNode())

    result = await executor.execute(graph, goal, {})

    # Verify backward compatibility maintained
    assert result.success, "Execution should succeed"
    assert "consumer_node" in result.path, (
        f"Expected consumer_node in path. "
        f"Old syntax output['score'] > 80 should still work. "
        f"Path: {result.path}"
    )


@pytest.mark.asyncio
async def test_multiple_keys_in_expression():
    """
    Verify multiple direct keys work in complex expressions.

    Tests that expressions like 'x > y and y < 100' work correctly
    when both x and y are written to memory before edge evaluation.
    """
    goal = Goal(
        id="test-multi-key",
        name="Test Multiple Keys",
        description="Test multiple keys in conditional expression",
    )

    nodes = [
        NodeSpec(
            id="multi_key_node",
            name="MultiKeyNode",
            description="Outputs multiple keys",
            node_type="event_loop",
            output_keys=["x", "y"],
        ),
        NodeSpec(
            id="consumer_node",
            name="ConsumerNode",
            description="Consumer",
            node_type="event_loop",
            input_keys=["x", "y"],
            output_keys=["processed"],
        ),
    ]

    # Complex expression with multiple direct keys
    edges = [
        EdgeSpec(
            id="multi_to_consumer",
            source="multi_key_node",
            target="consumer_node",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="x > y and y < 100",  # Multiple keys
        )
    ]

    graph = GraphSpec(
        id="test-graph-multi",
        goal_id="test-multi-key",
        entry_node="multi_key_node",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["consumer_node"],
    )

    runtime = SimpleRuntime(storage_path="/tmp/test")
    executor = GraphExecutor(runtime=runtime)
    executor.register_node("multi_key_node", MultiKeyNode())
    executor.register_node("consumer_node", ConsumerNode())

    result = await executor.execute(graph, goal, {})

    # Verify multiple keys work correctly
    assert result.success, "Execution should succeed"
    assert "consumer_node" in result.path, (
        f"Expected consumer_node in path. "
        f"Condition 'x > y and y < 100' should be True (x=100, y=50). "
        f"Path: {result.path}"
    )


@pytest.mark.asyncio
async def test_negative_case_condition_false():
    """
    Verify conditions correctly evaluate to False when not met.

    Tests that when a condition fails, the edge is NOT followed
    and execution doesn't proceed to the target node.
    """
    goal = Goal(
        id="test-negative",
        name="Test Negative Case",
        description="Test condition evaluates to False correctly",
    )

    class LowScoreNode(NodeProtocol):
        """Node that outputs a LOW score."""

        async def execute(self, ctx: NodeContext) -> NodeResult:
            return NodeResult(success=True, output={"score": 30})

    nodes = [
        NodeSpec(
            id="low_score_node",
            name="LowScoreNode",
            description="Outputs low score",
            node_type="event_loop",
            output_keys=["score"],
        ),
        NodeSpec(
            id="high_score_handler",
            name="HighScoreHandler",
            description="Should NOT execute",
            node_type="event_loop",
            input_keys=["score"],
            output_keys=["result"],
        ),
    ]

    # Condition should be FALSE (30 is not > 80)
    edges = [
        EdgeSpec(
            id="low_to_high",
            source="low_score_node",
            target="high_score_handler",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="score > 80",  # Should be False
        )
    ]

    graph = GraphSpec(
        id="test-graph-negative",
        goal_id="test-negative",
        entry_node="low_score_node",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["high_score_handler"],
    )

    runtime = SimpleRuntime(storage_path="/tmp/test")
    executor = GraphExecutor(runtime=runtime)
    executor.register_node("low_score_node", LowScoreNode())
    executor.register_node("high_score_handler", HighScoreNode())

    result = await executor.execute(graph, goal, {})

    # Verify condition correctly evaluated to False
    assert result.success, "Execution should succeed"
    assert "high_score_handler" not in result.path, (
        f"high_score_handler should NOT be in path. "
        f"Condition 'score > 80' should be False (score=30). "
        f"Path: {result.path}"
    )
