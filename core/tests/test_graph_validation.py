import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec


def test_validate_rejects_multiple_client_facing_in_fanout():
    source = NodeSpec(id="source", name="Source", description="source", node_type="function")
    branch_a = NodeSpec(
        id="branch_a",
        name="Branch A",
        description="branch a",
        node_type="function",
        client_facing=True,
    )
    branch_b = NodeSpec(
        id="branch_b",
        name="Branch B",
        description="branch b",
        node_type="function",
        client_facing=True,
    )

    graph = GraphSpec(
        id="g1",
        goal_id="goal",
        entry_node="source",
        nodes=[source, branch_a, branch_b],
        edges=[
            EdgeSpec(
                id="edge_a",
                source="source",
                target="branch_a",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            EdgeSpec(
                id="edge_b",
                source="source",
                target="branch_b",
                condition=EdgeCondition.ON_SUCCESS,
            ),
        ],
        terminal_nodes=["branch_a", "branch_b"],
    )

    errors = graph.validate()
    assert any("client-facing" in error for error in errors)


def test_validate_rejects_overlapping_event_loop_outputs():
    source = NodeSpec(id="source", name="Source", description="source", node_type="function")
    branch_a = NodeSpec(
        id="branch_a",
        name="Branch A",
        description="branch a",
        node_type="event_loop",
        output_keys=["shared"],
    )
    branch_b = NodeSpec(
        id="branch_b",
        name="Branch B",
        description="branch b",
        node_type="event_loop",
        output_keys=["shared"],
    )

    graph = GraphSpec(
        id="g1",
        goal_id="goal",
        entry_node="source",
        nodes=[source, branch_a, branch_b],
        edges=[
            EdgeSpec(
                id="edge_a",
                source="source",
                target="branch_a",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            EdgeSpec(
                id="edge_b",
                source="source",
                target="branch_b",
                condition=EdgeCondition.ON_SUCCESS,
            ),
        ],
        terminal_nodes=["branch_a", "branch_b"],
    )

    errors = graph.validate()
    assert any("event_loop" in error for error in errors)
