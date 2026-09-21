"""Tests for GraphSpec.validate() — duplicate edge IDs, unconditional self-loops,
and CONDITIONAL edges missing condition_expr.

Run with:
    cd core
    pytest tests/test_graph_spec_validation.py -v
"""

import pytest

from framework.orchestrator.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.orchestrator.node import NodeSpec


def _node(node_id: str) -> NodeSpec:
    return NodeSpec(id=node_id, name=node_id, description="")


def _base_graph(**kwargs) -> GraphSpec:
    """Minimal valid graph with two nodes and one edge."""
    a = _node("a")
    b = _node("b")
    edge = EdgeSpec(id="a-b", source="a", target="b", condition=EdgeCondition.ON_SUCCESS)
    return GraphSpec(
        id="test-graph",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[a, b],
        edges=[edge],
        **kwargs,
    )


def test_valid_graph_has_no_errors():
    result = _base_graph().validate()
    assert result["errors"] == []


def test_duplicate_edge_ids_raises_error():
    a = _node("a")
    b = _node("b")
    c = _node("c")
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b", "c"],
        nodes=[a, b, c],
        edges=[
            EdgeSpec(id="dup", source="a", target="b"),
            EdgeSpec(id="dup", source="a", target="c"),
        ],
    )
    errors = graph.validate()["errors"]
    assert any("Duplicate edge ID 'dup'" in e for e in errors)


def test_unique_edge_ids_no_duplicate_error():
    a = _node("a")
    b = _node("b")
    c = _node("c")
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b", "c"],
        nodes=[a, b, c],
        edges=[
            EdgeSpec(id="a-b", source="a", target="b"),
            EdgeSpec(id="a-c", source="a", target="c"),
        ],
    )
    errors = graph.validate()["errors"]
    assert not any("Duplicate edge ID" in e for e in errors)


def test_unconditional_self_loop_raises_error():
    a = _node("a")
    b = _node("b")
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[a, b],
        edges=[
            EdgeSpec(id="self-loop", source="a", target="a", condition=EdgeCondition.ALWAYS),
            EdgeSpec(id="a-b", source="a", target="b"),
        ],
    )
    errors = graph.validate()["errors"]
    assert any("unconditional self-loop" in e for e in errors)
    assert any("self-loop" in e for e in errors)


def test_conditional_self_loop_is_allowed():
    """A self-loop with CONDITIONAL is valid — it only fires when the expression is true."""
    a = _node("a")
    b = _node("b")
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[a, b],
        edges=[
            EdgeSpec(
                id="retry",
                source="a",
                target="a",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.retry == true",
            ),
            EdgeSpec(id="a-b", source="a", target="b"),
        ],
    )
    errors = graph.validate()["errors"]
    assert not any("self-loop" in e for e in errors)


def test_conditional_edge_without_expr_raises_error():
    a = _node("a")
    b = _node("b")
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[a, b],
        edges=[
            EdgeSpec(id="a-b", source="a", target="b", condition=EdgeCondition.CONDITIONAL),
        ],
    )
    errors = graph.validate()["errors"]
    assert any("condition=CONDITIONAL" in e and "condition_expr" in e for e in errors)


def test_conditional_edge_with_expr_is_valid():
    a = _node("a")
    b = _node("b")
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[a, b],
        edges=[
            EdgeSpec(
                id="a-b",
                source="a",
                target="b",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.score > 0.8",
            ),
        ],
    )
    errors = graph.validate()["errors"]
    assert not any("condition_expr" in e for e in errors)


def test_multiple_validation_errors_reported_together():
    """All three bug classes can be reported in a single validate() call."""
    a = _node("a")
    b = _node("b")
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[a, b],
        edges=[
            EdgeSpec(id="dup", source="a", target="b"),
            EdgeSpec(id="dup", source="a", target="b"),
            EdgeSpec(id="loop", source="a", target="a", condition=EdgeCondition.ALWAYS),
            EdgeSpec(id="no-expr", source="a", target="b", condition=EdgeCondition.CONDITIONAL),
        ],
    )
    errors = graph.validate()["errors"]
    assert any("Duplicate edge ID" in e for e in errors)
    assert any("unconditional self-loop" in e for e in errors)
    assert any("condition_expr" in e for e in errors)
