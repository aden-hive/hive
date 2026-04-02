"""Tests for GraphSpec.validate() — duplicate edge IDs, self-loops, missing condition_expr."""

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec


def _node(node_id: str) -> NodeSpec:
    """Helper to create a minimal valid node."""
    return NodeSpec(
        id=node_id,
        name=node_id,
        description=f"Test node {node_id}",
        node_type="event_loop",
        input_keys=[],
        output_keys=[],
    )


class TestDuplicateEdgeIDs:
    def test_duplicate_edge_ids_flagged(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            nodes=[_node("a"), _node("b"), _node("c")],
            edges=[
                EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ALWAYS),
                EdgeSpec(id="e1", source="b", target="c", condition=EdgeCondition.ALWAYS),
            ],
            entry_node="a",
        )
        result = graph.validate()
        assert any("Duplicate edge ID" in e and "e1" in e for e in result["errors"])

    def test_unique_edge_ids_pass(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            nodes=[_node("a"), _node("b"), _node("c")],
            edges=[
                EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ALWAYS),
                EdgeSpec(id="e2", source="b", target="c", condition=EdgeCondition.ALWAYS),
            ],
            entry_node="a",
        )
        result = graph.validate()
        assert not any("Duplicate edge ID" in e for e in result["errors"])


class TestSelfLoopDetection:
    def test_always_self_loop_flagged(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            nodes=[_node("a")],
            edges=[
                EdgeSpec(id="loop", source="a", target="a", condition=EdgeCondition.ALWAYS),
            ],
            entry_node="a",
        )
        result = graph.validate()
        assert any("self-loop" in e for e in result["errors"])

    def test_conditional_self_loop_allowed(self):
        """Conditional self-loops are a valid pattern (retry with condition)."""
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            nodes=[_node("a"), _node("b")],
            edges=[
                EdgeSpec(
                    id="retry",
                    source="a",
                    target="a",
                    condition=EdgeCondition.CONDITIONAL,
                    condition_expr="retry_count < 3",
                ),
                EdgeSpec(id="done", source="a", target="b", condition=EdgeCondition.ON_SUCCESS),
            ],
            entry_node="a",
        )
        result = graph.validate()
        assert not any("self-loop" in e for e in result["errors"])


class TestConditionalEdgeExpr:
    def test_conditional_without_expr_flagged(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            nodes=[_node("a"), _node("b")],
            edges=[
                EdgeSpec(
                    id="bad",
                    source="a",
                    target="b",
                    condition=EdgeCondition.CONDITIONAL,
                    condition_expr=None,
                ),
            ],
            entry_node="a",
        )
        result = graph.validate()
        assert any("condition_expr" in e for e in result["errors"])

    def test_conditional_with_expr_passes(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            nodes=[_node("a"), _node("b")],
            edges=[
                EdgeSpec(
                    id="ok",
                    source="a",
                    target="b",
                    condition=EdgeCondition.CONDITIONAL,
                    condition_expr="confidence > 0.8",
                ),
            ],
            entry_node="a",
        )
        result = graph.validate()
        assert not any("condition_expr" in e for e in result["errors"])
