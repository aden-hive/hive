"""Tests for GraphSpec.validate() gap fixes (issue #6090).

Covers:
- Duplicate edge IDs
- Unconditional self-loops (source == target with ALWAYS/ON_SUCCESS/ON_FAILURE)
- CONDITIONAL edge with empty or missing condition_expr
"""

import pytest

from framework.orchestrator.edge import EdgeCondition, EdgeSpec, GraphSpec


def _make_graph(edges, nodes=None):
    """Build a minimal GraphSpec with the given edges."""
    if nodes is None:
        # Provide minimal stubs for all source/target nodes referenced in edges
        seen = set()
        for e in edges:
            seen.add(e.source)
            seen.add(e.target)
        nodes = [type("Node", (), {"id": nid, "node_type": "stub"})() for nid in seen]
    return GraphSpec(
        id="test-graph",
        goal_id="g1",
        entry_node=edges[0].source if edges else nodes[0].id,
        terminal_nodes=[],
        nodes=nodes,
        edges=edges,
    )


class TestDuplicateEdgeIds:
    def test_duplicate_edge_ids_detected(self):
        e1 = EdgeSpec(id="e1", source="a", target="b")
        e2 = EdgeSpec(id="e1", source="b", target="c")
        graph = _make_graph([e1, e2])
        result = graph.validate()
        assert any("duplicate" in err.lower() for err in result["errors"])

    def test_unique_edge_ids_no_error(self):
        e1 = EdgeSpec(id="e1", source="a", target="b")
        e2 = EdgeSpec(id="e2", source="b", target="c")
        graph = _make_graph([e1, e2])
        result = graph.validate()
        assert not any("duplicate" in err.lower() for err in result["errors"])


class TestUnconditionalSelfLoops:
    @pytest.mark.parametrize(
        "condition",
        [EdgeCondition.ALWAYS, EdgeCondition.ON_SUCCESS, EdgeCondition.ON_FAILURE],
    )
    def test_self_loop_unconditional(self, condition):
        e = EdgeSpec(id="e1", source="a", target="a", condition=condition)
        graph = _make_graph([e])
        result = graph.validate()
        assert any("self-loop" in err.lower() for err in result["errors"])

    def test_conditional_self_loop_not_flagged(self):
        e = EdgeSpec(
            id="e1",
            source="a",
            target="a",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="true",
        )
        graph = _make_graph([e])
        result = graph.validate()
        assert not any("self-loop" in err.lower() for err in result["errors"])


class TestConditionalMissingExpr:
    def test_conditional_edge_missing_expr(self):
        e = EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.CONDITIONAL)
        graph = _make_graph([e])
        result = graph.validate()
        assert any("condition_expr" in err.lower() or "expression" in err.lower() for err in result["errors"])

    def test_conditional_edge_empty_expr(self):
        e = EdgeSpec(
            id="e1",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="",
        )
        graph = _make_graph([e])
        result = graph.validate()
        assert any("condition_expr" in err.lower() or "expression" in err.lower() for err in result["errors"])

    def test_conditional_edge_whitespace_only_expr(self):
        e = EdgeSpec(
            id="e1",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="   ",
        )
        graph = _make_graph([e])
        result = graph.validate()
        assert any("condition_expr" in err.lower() or "expression" in err.lower() for err in result["errors"])

    def test_conditional_edge_with_expr_no_error(self):
        e = EdgeSpec(
            id="e1",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output.x > 1",
        )
        graph = _make_graph([e])
        result = graph.validate()
        assert not any("condition_expr" in err.lower() or "expression" in err.lower() for err in result["errors"])
