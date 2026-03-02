"""
Tests for client-facing fan-out and event_loop output_key overlap validation.

Validates two rules added to GraphSpec.validate():
1. Fan-out must not have multiple client_facing=True targets.
2. Parallel event_loop nodes must have disjoint output_keys.
"""

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec

# ---------------------------------------------------------------------------
# Rule 1: client_facing fan-out
# ---------------------------------------------------------------------------


class TestClientFacingFanOut:
    """Fan-out to multiple client_facing=True targets must be rejected."""

    def test_fan_out_two_client_facing_fails(self):
        """Two client-facing targets on the same fan-out -> error."""
        graph = GraphSpec(
            id="g1",
            goal_id="goal1",
            entry_node="src",
            nodes=[
                NodeSpec(id="src", name="src", description="Source node"),
                NodeSpec(id="a", name="a", description="Node a", client_facing=True),
                NodeSpec(id="b", name="b", description="Node b", client_facing=True),
            ],
            edges=[
                EdgeSpec(id="src->a", source="src", target="a", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="src->b", source="src", target="b", condition=EdgeCondition.ON_SUCCESS),
            ],
        )

        errors = graph.validate()
        cf_errors = [e for e in errors if "multiple client-facing" in e]
        assert len(cf_errors) == 1
        assert "'src'" in cf_errors[0]

    def test_fan_out_one_client_facing_passes(self):
        """Only one client-facing target -> no error."""
        graph = GraphSpec(
            id="g1",
            goal_id="goal1",
            entry_node="src",
            nodes=[
                NodeSpec(id="src", name="src", description="Source node"),
                NodeSpec(id="a", name="a", description="Node a", client_facing=True),
                NodeSpec(id="b", name="b", description="Node b", client_facing=False),
            ],
            edges=[
                EdgeSpec(id="src->a", source="src", target="a", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="src->b", source="src", target="b", condition=EdgeCondition.ON_SUCCESS),
            ],
        )

        errors = graph.validate()
        cf_errors = [e for e in errors if "multiple client-facing" in e]
        assert len(cf_errors) == 0

    def test_fan_out_zero_client_facing_passes(self):
        """No client-facing targets at all -> no error."""
        graph = GraphSpec(
            id="g1",
            goal_id="goal1",
            entry_node="src",
            nodes=[
                NodeSpec(id="src", name="src", description="Source node"),
                NodeSpec(id="a", name="a", description="Node a"),
                NodeSpec(id="b", name="b", description="Node b"),
            ],
            edges=[
                EdgeSpec(id="src->a", source="src", target="a", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="src->b", source="src", target="b", condition=EdgeCondition.ON_SUCCESS),
            ],
        )

        errors = graph.validate()
        cf_errors = [e for e in errors if "multiple client-facing" in e]
        assert len(cf_errors) == 0


# ---------------------------------------------------------------------------
# Rule 2: event_loop output_key overlap
# ---------------------------------------------------------------------------


class TestEventLoopOutputKeyOverlap:
    """Parallel event_loop nodes with overlapping output_keys must be rejected."""

    def test_overlapping_output_keys_event_loop_fails(self):
        """Two event_loop nodes sharing an output_key -> error."""
        graph = GraphSpec(
            id="g1",
            goal_id="goal1",
            entry_node="src",
            nodes=[
                NodeSpec(id="src", name="src", description="Source node"),
                NodeSpec(
                    id="a",
                    name="a",
                    description="Node a",
                    node_type="event_loop",
                    output_keys=["status", "shared"],
                ),
                NodeSpec(
                    id="b",
                    name="b",
                    description="Node b",
                    node_type="event_loop",
                    output_keys=["result", "shared"],
                ),
            ],
            edges=[
                EdgeSpec(id="src->a", source="src", target="a", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="src->b", source="src", target="b", condition=EdgeCondition.ON_SUCCESS),
            ],
        )

        errors = graph.validate()
        key_errors = [e for e in errors if "output_key" in e]
        assert len(key_errors) == 1
        assert "'shared'" in key_errors[0]

    def test_disjoint_output_keys_event_loop_passes(self):
        """Two event_loop nodes with disjoint output_keys -> no error."""
        graph = GraphSpec(
            id="g1",
            goal_id="goal1",
            entry_node="src",
            nodes=[
                NodeSpec(id="src", name="src", description="Source node"),
                NodeSpec(
                    id="a",
                    name="a",
                    description="Node a",
                    node_type="event_loop",
                    output_keys=["status"],
                ),
                NodeSpec(
                    id="b",
                    name="b",
                    description="Node b",
                    node_type="event_loop",
                    output_keys=["result"],
                ),
            ],
            edges=[
                EdgeSpec(id="src->a", source="src", target="a", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="src->b", source="src", target="b", condition=EdgeCondition.ON_SUCCESS),
            ],
        )

        errors = graph.validate()
        key_errors = [e for e in errors if "output_key" in e]
        assert len(key_errors) == 0


# ---------------------------------------------------------------------------
# Baseline: no fan-out -> no errors from these rules
# ---------------------------------------------------------------------------


class TestNoFanOutUnaffected:
    """Linear graphs should not trigger either validation rule."""

    def test_no_fan_out_unaffected(self):
        """Linear chain with client_facing and event_loop nodes -> no errors."""
        graph = GraphSpec(
            id="g1",
            goal_id="goal1",
            entry_node="a",
            terminal_nodes=["c"],
            nodes=[
                NodeSpec(id="a", name="a", description="Node a", client_facing=True),
                NodeSpec(
                    id="b",
                    name="b",
                    description="Node b",
                    node_type="event_loop",
                    output_keys=["x"],
                ),
                NodeSpec(
                    id="c",
                    name="c",
                    description="Node c",
                    client_facing=True,
                    node_type="event_loop",
                    output_keys=["x"],
                ),
            ],
            edges=[
                EdgeSpec(id="a->b", source="a", target="b", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="b->c", source="b", target="c", condition=EdgeCondition.ON_SUCCESS),
            ],
        )

        errors = graph.validate()
        cf_errors = [e for e in errors if "multiple client-facing" in e]
        key_errors = [e for e in errors if "output_key" in e]
        assert len(cf_errors) == 0
        assert len(key_errors) == 0
