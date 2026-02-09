"""
Tests for Mermaid diagram export from GraphSpec.
"""

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.mermaid import _sanitize_id, to_mermaid
from framework.graph.node import NodeSpec


def _make_node(node_id: str, name: str = "", node_type: str = "event_loop") -> NodeSpec:
    """Helper to create a minimal NodeSpec."""
    return NodeSpec(
        id=node_id,
        name=name or node_id,
        description=f"Test node {node_id}",
        node_type=node_type,
    )


def _make_edge(
    edge_id: str,
    source: str,
    target: str,
    condition: EdgeCondition = EdgeCondition.ALWAYS,
    condition_expr: str | None = None,
    description: str = "",
) -> EdgeSpec:
    """Helper to create a minimal EdgeSpec."""
    return EdgeSpec(
        id=edge_id,
        source=source,
        target=target,
        condition=condition,
        condition_expr=condition_expr,
        description=description,
    )


# -- Linear graph --


def test_linear_graph():
    """A -> B -> C produces correct Mermaid output."""
    graph = GraphSpec(
        id="linear",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["c"],
        nodes=[_make_node("a", "A"), _make_node("b", "B"), _make_node("c", "C")],
        edges=[
            _make_edge("e1", "a", "b"),
            _make_edge("e2", "b", "c"),
        ],
    )

    result = to_mermaid(graph)

    assert "graph TD" in result
    assert "_start_((Start)) --> a" in result
    assert "a --> b" in result
    assert "b --> c" in result


def test_linear_graph_via_method():
    """GraphSpec.to_mermaid() delegates to the standalone function."""
    graph = GraphSpec(
        id="linear",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["c"],
        nodes=[_make_node("a", "A"), _make_node("b", "B"), _make_node("c", "C")],
        edges=[
            _make_edge("e1", "a", "b"),
            _make_edge("e2", "b", "c"),
        ],
    )

    assert graph.to_mermaid() == to_mermaid(graph)


# -- Edge conditions --


def test_on_success_edge():
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[_make_node("a"), _make_node("b")],
        edges=[_make_edge("e1", "a", "b", EdgeCondition.ON_SUCCESS)],
    )

    result = to_mermaid(graph)
    assert '-->|"Success"|' in result


def test_on_failure_edge():
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[_make_node("a"), _make_node("b")],
        edges=[_make_edge("e1", "a", "b", EdgeCondition.ON_FAILURE)],
    )

    result = to_mermaid(graph)
    assert '-->|"Failure"|' in result


def test_conditional_edge_with_expr():
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[_make_node("a"), _make_node("b")],
        edges=[
            _make_edge(
                "e1", "a", "b", EdgeCondition.CONDITIONAL, condition_expr="output.confidence > 0.8"
            )
        ],
    )

    result = to_mermaid(graph)
    assert "output.confidence > 0.8" in result


def test_conditional_edge_without_expr():
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[_make_node("a"), _make_node("b")],
        edges=[_make_edge("e1", "a", "b", EdgeCondition.CONDITIONAL)],
    )

    result = to_mermaid(graph)
    assert "Conditional" in result


def test_llm_decide_edge_with_description():
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[_make_node("a"), _make_node("b")],
        edges=[
            _make_edge(
                "e1",
                "a",
                "b",
                EdgeCondition.LLM_DECIDE,
                description="Only if results need refinement",
            )
        ],
    )

    result = to_mermaid(graph)
    assert "Only if results need refinement" in result


def test_llm_decide_edge_without_description():
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[_make_node("a"), _make_node("b")],
        edges=[_make_edge("e1", "a", "b", EdgeCondition.LLM_DECIDE)],
    )

    result = to_mermaid(graph)
    assert "LLM Decision" in result


# -- Fan-out and fan-in --


def test_fan_out():
    """One node branching to multiple targets."""
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b", "c"],
        nodes=[_make_node("a"), _make_node("b"), _make_node("c")],
        edges=[
            _make_edge("e1", "a", "b", EdgeCondition.ON_SUCCESS),
            _make_edge("e2", "a", "c", EdgeCondition.ON_FAILURE),
        ],
    )

    result = to_mermaid(graph)
    assert 'a -->|"Success"| b' in result
    assert 'a -->|"Failure"| c' in result


def test_fan_in():
    """Multiple sources converging to one target."""
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["c"],
        nodes=[_make_node("a"), _make_node("b"), _make_node("c")],
        edges=[
            _make_edge("e1", "a", "b"),
            _make_edge("e2", "a", "c"),
            _make_edge("e3", "b", "c"),
        ],
    )

    result = to_mermaid(graph)
    assert "a --> c" in result
    assert "b --> c" in result


# -- Feedback loops (cycles) --


def test_feedback_loop():
    """Cycles render without infinite recursion."""
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["c"],
        nodes=[_make_node("a"), _make_node("b"), _make_node("c")],
        edges=[
            _make_edge("e1", "a", "b", EdgeCondition.ON_SUCCESS),
            _make_edge("e2", "b", "a", EdgeCondition.ON_FAILURE),  # feedback loop
            _make_edge("e3", "b", "c", EdgeCondition.ON_SUCCESS),
        ],
    )

    result = to_mermaid(graph)
    assert 'b -->|"Failure"| a' in result
    assert 'b -->|"Success"| c' in result


# -- Node types and shapes --


def test_node_type_shapes():
    """Different node types get correct Mermaid shapes."""
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="llm",
        terminal_nodes=["human"],
        nodes=[
            _make_node("llm", "LLM Node", "event_loop"),
            _make_node("func", "Function Node", "function"),
            _make_node("route", "Router Node", "router"),
            _make_node("human", "Human Input", "human_input"),
        ],
        edges=[
            _make_edge("e1", "llm", "func"),
            _make_edge("e2", "func", "route"),
            _make_edge("e3", "route", "human"),
        ],
    )

    result = to_mermaid(graph)
    assert 'llm("LLM Node")' in result
    assert 'func[["Function Node"]]' in result
    assert 'route{"Router Node"}' in result
    assert 'human(["Human Input"])' in result


# -- Terminal nodes --


def test_terminal_nodes_get_style():
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="a",
        terminal_nodes=["b"],
        nodes=[_make_node("a"), _make_node("b")],
        edges=[_make_edge("e1", "a", "b")],
    )

    result = to_mermaid(graph)
    assert "classDef terminal stroke-width:4px" in result
    assert "class b terminal" in result


# -- Entry node --


def test_entry_node_has_start_arrow():
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="first",
        terminal_nodes=["first"],
        nodes=[_make_node("first")],
        edges=[],
    )

    result = to_mermaid(graph)
    assert "_start_((Start)) --> first" in result


# -- ID sanitization --


def test_sanitize_id_special_characters():
    assert _sanitize_id("my-node") == "my_node"
    assert _sanitize_id("node.name") == "node_name"
    assert _sanitize_id("node with spaces") == "node_with_spaces"
    assert _sanitize_id("123start") == "_123start"
    assert _sanitize_id("already_valid") == "already_valid"


def test_node_ids_with_special_chars():
    """Node IDs with special characters are sanitized in the output."""
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="my-node",
        terminal_nodes=["end-node"],
        nodes=[_make_node("my-node", "My Node"), _make_node("end-node", "End Node")],
        edges=[_make_edge("e1", "my-node", "end-node")],
    )

    result = to_mermaid(graph)
    assert "my_node" in result
    assert "end_node" in result
    # Original IDs with hyphens should not appear as Mermaid IDs
    assert "my-node" not in result.split('"')[0]  # not outside quoted labels


# -- Empty edges --


def test_graph_with_no_edges():
    """A graph with nodes but no edges still renders nodes."""
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        entry_node="solo",
        terminal_nodes=["solo"],
        nodes=[_make_node("solo", "Solo Node")],
        edges=[],
    )

    result = to_mermaid(graph)
    assert "graph TD" in result
    assert 'solo("Solo Node")' in result
    assert "_start_((Start)) --> solo" in result
