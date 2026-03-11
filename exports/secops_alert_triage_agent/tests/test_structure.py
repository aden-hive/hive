"""Structure validation tests for SecOps Alert Triage Agent."""

import pytest


class TestAgentStructure:
    """Tests for agent structure validation."""

    def test_agent_instantiation(self, agent):
        """Test that the agent can be instantiated."""
        assert agent is not None
        assert hasattr(agent, "goal")
        assert hasattr(agent, "nodes")
        assert hasattr(agent, "edges")

    def test_goal_defined(self, agent):
        """Test that the goal is properly defined."""
        assert agent.goal.id == "secops-alert-triage"
        assert agent.goal.name == "SecOps Alert Triage Agent"
        assert len(agent.goal.success_criteria) == 5
        assert len(agent.goal.constraints) == 4

    def test_nodes_defined(self, agent):
        """Test that all required nodes are defined."""
        node_ids = {node.id for node in agent.nodes}
        expected_nodes = {
            "intake",
            "dedup",
            "fp-filter",
            "severity",
            "enrichment",
            "hitl-escalation",
            "digest",
        }
        assert expected_nodes == node_ids

    def test_edges_defined(self, agent):
        """Test that all edges are properly defined."""
        edge_ids = {edge.id for edge in agent.edges}
        expected_edges = {
            "intake-to-dedup",
            "dedup-to-fp-filter",
            "fp-filter-to-severity",
            "severity-to-enrichment",
            "enrichment-to-hitl",
            "hitl-to-digest",
        }
        assert expected_edges == edge_ids

    def test_entry_node_defined(self, agent):
        """Test that entry node is defined."""
        assert agent.entry_node == "intake"
        assert "start" in agent.entry_points
        assert agent.entry_points["start"] == "intake"

    def test_terminal_nodes_defined(self, agent):
        """Test that terminal nodes are defined."""
        assert "digest" in agent.terminal_nodes

    def test_client_facing_nodes(self, agent):
        """Test that client-facing nodes are properly marked."""
        client_facing = [n.id for n in agent.nodes if n.client_facing]
        expected_client_facing = {"intake", "hitl-escalation", "digest"}
        assert expected_client_facing == set(client_facing)

    def test_hitl_gate_present(self, agent):
        """Test that HITL gate node is present for human confirmation."""
        node_ids = {node.id for node in agent.nodes}
        assert "hitl-escalation" in node_ids

    def test_validation_passes(self, agent):
        """Test that agent validation passes."""
        result = agent.validate()
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_node_input_output_keys(self, agent):
        """Test that nodes have proper input/output keys defined."""
        for node in agent.nodes:
            assert node.input_keys is not None
            assert node.output_keys is not None


class TestSuccessCriteria:
    """Tests for success criteria definitions."""

    def test_false_positive_suppression_criterion(self, agent):
        """Test false positive suppression success criterion."""
        criterion = next(
            (
                c
                for c in agent.goal.success_criteria
                if c.id == "false-positive-suppression"
            ),
            None,
        )
        assert criterion is not None
        assert criterion.target == ">=35%"
        assert criterion.weight == 0.20

    def test_escalation_accuracy_criterion(self, agent):
        """Test escalation accuracy success criterion."""
        criterion = next(
            (c for c in agent.goal.success_criteria if c.id == "escalation-accuracy"),
            None,
        )
        assert criterion is not None
        assert criterion.target == ">=90%"
        assert criterion.weight == 0.25

    def test_human_confirmation_criterion(self, agent):
        """Test human confirmation success criterion."""
        criterion = next(
            (c for c in agent.goal.success_criteria if c.id == "human-confirmation"),
            None,
        )
        assert criterion is not None
        assert criterion.target == "100%"
        assert criterion.weight == 0.25


class TestConstraints:
    """Tests for constraint definitions."""

    def test_mandatory_hitl_constraint(self, agent):
        """Test mandatory HITL constraint."""
        constraint = next(
            (c for c in agent.goal.constraints if c.id == "mandatory-hitl"), None
        )
        assert constraint is not None
        assert constraint.constraint_type == "hard"
        assert constraint.category == "safety"

    def test_audit_trail_constraint(self, agent):
        """Test audit trail constraint."""
        constraint = next(
            (c for c in agent.goal.constraints if c.id == "audit-trail"), None
        )
        assert constraint is not None
        assert constraint.constraint_type == "hard"
        assert constraint.category == "compliance"

    def test_alert_preservation_constraint(self, agent):
        """Test alert preservation constraint."""
        constraint = next(
            (c for c in agent.goal.constraints if c.id == "alert-preservation"), None
        )
        assert constraint is not None
        assert constraint.constraint_type == "hard"
        assert constraint.category == "data_integrity"


class TestConfig:
    """Tests for agent configuration."""

    def test_metadata_defined(self):
        """Test that metadata is properly defined."""
        from exports.secops_alert_triage_agent import metadata

        assert metadata.name == "SecOps Alert Triage Agent"
        assert metadata.version == "1.0.0"

    def test_default_config(self):
        """Test that default config is available."""
        from exports.secops_alert_triage_agent import default_config

        assert default_config is not None
        assert hasattr(default_config, "model")

    def test_suppression_rules_defined(self):
        """Test that default suppression rules are defined."""
        from exports.secops_alert_triage_agent.config import DEFAULT_SUPPRESSION_RULES

        assert "known_ci_ips" in DEFAULT_SUPPRESSION_RULES
        assert "scheduled_scanners" in DEFAULT_SUPPRESSION_RULES

    def test_asset_criticality_defined(self):
        """Test that asset criticality levels are defined."""
        from exports.secops_alert_triage_agent.config import DEFAULT_ASSET_CRITICALITY

        assert "production" in DEFAULT_ASSET_CRITICALITY
        assert DEFAULT_ASSET_CRITICALITY["production"]["weight"] == 1.0
