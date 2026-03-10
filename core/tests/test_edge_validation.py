"""
Tests for edge validation checks in GraphSpec.validate().

Validates three rules:
1. Duplicate edge IDs are flagged as errors.
2. Unconditional self-loops (source == target, condition=ALWAYS) produce a warning.
3. CONDITIONAL edges without condition_expr are flagged as errors.
"""

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec


def _make_nodes(*ids: str) -> list[NodeSpec]:
    return [NodeSpec(id=nid, name=nid, description="test") for nid in ids]


class TestDuplicateEdgeIds:
    """Duplicate edge IDs should be flagged."""

    def test_duplicate_edge_ids_error(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            entry_node="a",
            nodes=_make_nodes("a", "b"),
            edges=[
                EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ALWAYS),
                EdgeSpec(id="e1", source="b", target="a", condition=EdgeCondition.ALWAYS),
            ],
        )
        errors = graph.validate()["errors"]
        dup_errors = [e for e in errors if "Duplicate edge ID" in e]
        assert len(dup_errors) == 1
        assert "'e1'" in dup_errors[0]

    def test_unique_edge_ids_pass(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            entry_node="a",
            nodes=_make_nodes("a", "b"),
            edges=[
                EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ALWAYS),
                EdgeSpec(id="e2", source="b", target="a", condition=EdgeCondition.ALWAYS),
            ],
        )
        errors = graph.validate()["errors"]
        dup_errors = [e for e in errors if "Duplicate edge ID" in e]
        assert len(dup_errors) == 0


class TestUnconditionalSelfLoop:
    """Unconditional self-loops should produce a warning."""

    def test_always_self_loop_warning(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            entry_node="a",
            nodes=_make_nodes("a"),
            edges=[
                EdgeSpec(id="loop", source="a", target="a", condition=EdgeCondition.ALWAYS),
            ],
        )
        warnings = graph.validate()["warnings"]
        loop_warnings = [w for w in warnings if "unconditional self-loop" in w]
        assert len(loop_warnings) == 1
        assert "'a'" in loop_warnings[0]

    def test_conditional_self_loop_no_warning(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            entry_node="a",
            nodes=_make_nodes("a"),
            edges=[
                EdgeSpec(
                    id="loop",
                    source="a",
                    target="a",
                    condition=EdgeCondition.CONDITIONAL,
                    condition_expr="output.retry == true",
                ),
            ],
        )
        warnings = graph.validate()["warnings"]
        loop_warnings = [w for w in warnings if "unconditional self-loop" in w]
        assert len(loop_warnings) == 0


class TestConditionalWithoutExpr:
    """CONDITIONAL edges without condition_expr should be flagged."""

    def test_conditional_no_expr_error(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            entry_node="a",
            nodes=_make_nodes("a", "b"),
            edges=[
                EdgeSpec(id="e", source="a", target="b", condition=EdgeCondition.CONDITIONAL),
            ],
        )
        errors = graph.validate()["errors"]
        expr_errors = [e for e in errors if "no condition_expr" in e]
        assert len(expr_errors) == 1

    def test_conditional_with_expr_pass(self):
        graph = GraphSpec(
            id="g",
            goal_id="goal",
            entry_node="a",
            nodes=_make_nodes("a", "b"),
            edges=[
                EdgeSpec(
                    id="e",
                    source="a",
                    target="b",
                    condition=EdgeCondition.CONDITIONAL,
                    condition_expr="output.confidence < 0.8",
                ),
            ],
        )
        errors = graph.validate()["errors"]
        expr_errors = [e for e in errors if "no condition_expr" in e]
        assert len(expr_errors) == 0
