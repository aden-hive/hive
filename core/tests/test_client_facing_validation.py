"""
Tests for deprecated client_facing warnings and output-key overlap validation.

Validates two current rules in GraphSpec.validate():
1. Non-queen client_facing=True emits a deprecation warning, not an error.
2. Parallel event_loop nodes must have disjoint output_keys.
"""

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec

# ---------------------------------------------------------------------------
# Rule 1: deprecated client_facing warnings
# ---------------------------------------------------------------------------


class TestDeprecatedClientFacingWarnings:
    """Non-queen client_facing=True should warn without blocking validation."""

    def test_non_queen_client_facing_warns(self):
        """Legacy worker-side client_facing should produce a warning."""
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

        validation = graph.validate()
        warnings = [w for w in validation["warnings"] if "deprecated client_facing=True" in w]

        assert validation["errors"] == []
        assert len(warnings) == 2
        assert "Node 'a'" in warnings[0]
        assert "Node 'b'" in warnings[1]

    def test_queen_client_facing_does_not_warn(self):
        """The compatibility field should remain silent on the queen itself."""
        graph = GraphSpec(
            id="g1",
            goal_id="goal1",
            entry_node="queen",
            nodes=[
                NodeSpec(id="queen", name="Queen", description="Queen node", client_facing=True),
                NodeSpec(
                    id="worker", name="Worker", description="Worker node", client_facing=False
                ),
            ],
            edges=[
                EdgeSpec(
                    id="queen->worker",
                    source="queen",
                    target="worker",
                    condition=EdgeCondition.ON_SUCCESS,
                ),
            ],
        )

        validation = graph.validate()
        warnings = [w for w in validation["warnings"] if "deprecated client_facing=True" in w]
        assert validation["errors"] == []
        assert warnings == []


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

        errors = graph.validate()["errors"]
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

        errors = graph.validate()["errors"]
        key_errors = [e for e in errors if "output_key" in e]
        assert len(key_errors) == 0


# ---------------------------------------------------------------------------
# Baseline: no fan-out -> no errors from these rules
# ---------------------------------------------------------------------------


class TestNoFanOutUnaffected:
    """Linear graphs should not trigger either validation rule."""

    def test_no_fan_out_unaffected(self):
        """Linear chain with queen + event_loop nodes -> no overlap errors."""
        graph = GraphSpec(
            id="g1",
            goal_id="goal1",
            entry_node="queen",
            terminal_nodes=["c"],
            nodes=[
                NodeSpec(id="queen", name="queen", description="Queen", client_facing=True),
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
                    node_type="event_loop",
                    output_keys=["x"],
                ),
            ],
            edges=[
                EdgeSpec(id="a->b", source="queen", target="b", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="b->c", source="b", target="c", condition=EdgeCondition.ON_SUCCESS),
            ],
        )

        validation = graph.validate()
        key_errors = [e for e in validation["errors"] if "output_key" in e]
        deprecated_warnings = [
            w for w in validation["warnings"] if "deprecated client_facing=True" in w
        ]
        assert len(key_errors) == 0
        assert deprecated_warnings == []
