import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec
from validation.errors import GraphValidationError
from validation.graph_validator import WorkflowGraphValidator


def _graph(nodes, edges, entry_node):
    return GraphSpec(
        id="test-graph",
        goal_id="goal-1",
        entry_node=entry_node,
        terminal_nodes=[],
        nodes=nodes,
        edges=edges,
        memory_keys=[],
    )


def test_unreachable_node():
    nodes = [
        NodeSpec(id="start", name="Start", description="", node_type="function"),
        NodeSpec(id="mid", name="Mid", description="", node_type="function"),
        NodeSpec(id="orphan", name="Orphan", description="", node_type="function"),
    ]
    edges = [EdgeSpec(id="start-mid", source="start", target="mid")]
    graph = _graph(nodes, edges, entry_node="start")

    with pytest.raises(GraphValidationError) as exc:
        WorkflowGraphValidator().validate(graph)

    error_types = {err.error_type for err in exc.value.errors}
    assert "unreachable_node" in error_types


def test_broken_conditional_edge():
    nodes = [
        NodeSpec(id="start", name="Start", description="", node_type="function"),
        NodeSpec(id="next", name="Next", description="", node_type="function"),
    ]
    edges = [
        EdgeSpec(
            id="start-next",
            source="start",
            target="next",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr=None,
        )
    ]
    graph = _graph(nodes, edges, entry_node="start")

    with pytest.raises(GraphValidationError) as exc:
        WorkflowGraphValidator().validate(graph)

    error_types = {err.error_type for err in exc.value.errors}
    assert "broken_conditional" in error_types


def test_infinite_cycle_without_allowance():
    nodes = [
        NodeSpec(id="a", name="A", description="", node_type="function"),
        NodeSpec(id="b", name="B", description="", node_type="function"),
    ]
    edges = [
        EdgeSpec(id="a-b", source="a", target="b"),
        EdgeSpec(id="b-a", source="b", target="a"),
    ]
    graph = _graph(nodes, edges, entry_node="a")

    with pytest.raises(GraphValidationError) as exc:
        WorkflowGraphValidator().validate(graph)

    error_types = {err.error_type for err in exc.value.errors}
    assert "infinite_cycle" in error_types


def test_missing_required_input():
    nodes = [
        NodeSpec(
            id="start",
            name="Start",
            description="",
            node_type="function",
            input_keys=["ticket"],
            output_keys=["normalized"],
        ),
        NodeSpec(
            id="analyze",
            name="Analyze",
            description="",
            node_type="function",
            input_keys=["missing"],
            output_keys=["result"],
        ),
    ]
    edges = [EdgeSpec(id="start-analyze", source="start", target="analyze")]
    graph = _graph(nodes, edges, entry_node="start")

    with pytest.raises(GraphValidationError) as exc:
        WorkflowGraphValidator().validate(graph)

    error_types = {err.error_type for err in exc.value.errors}
    assert "unsatisfied_input" in error_types
