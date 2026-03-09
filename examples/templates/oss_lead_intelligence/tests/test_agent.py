"""Tests for OSS Lead Intelligence Agent."""

import pytest


class TestOSSLeadIntelligenceAgent:
    """Test suite for OSS Lead Intelligence Agent."""

    def test_agent_initialization(self, agent):
        """Test that the agent initializes correctly."""
        assert agent.goal is not None
        assert agent.goal.id == "oss-lead-intelligence"
        assert len(agent.nodes) == 5
        assert len(agent.edges) == 4

    def test_agent_validation(self, agent):
        """Test that the agent graph is valid."""
        result = agent.validate()
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_entry_node(self, agent):
        """Test that the entry node is correctly set."""
        assert agent.entry_node == "config-intake"

    def test_terminal_nodes(self, agent):
        """Test that terminal nodes are correctly defined."""
        assert "crm-sync-and-notify" in agent.terminal_nodes
        assert "review-leads" in agent.terminal_nodes
        assert "enrich-and-score" in agent.terminal_nodes

    def test_node_ids_are_unique(self, agent):
        """Test that all node IDs are unique."""
        node_ids = [node.id for node in agent.nodes]
        assert len(node_ids) == len(set(node_ids))

    def test_edge_sources_exist(self, agent):
        """Test that all edge source nodes exist."""
        node_ids = {node.id for node in agent.nodes}
        for edge in agent.edges:
            assert edge.source in node_ids, f"Edge source '{edge.source}' not found"

    def test_edge_targets_exist(self, agent):
        """Test that all edge target nodes exist."""
        node_ids = {node.id for node in agent.nodes}
        for edge in agent.edges:
            assert edge.target in node_ids, f"Edge target '{edge.target}' not found"

    def test_goal_success_criteria_weights(self, agent):
        """Test that success criteria weights sum to 1.0."""
        total_weight = sum(sc.weight for sc in agent.goal.success_criteria)
        assert abs(total_weight - 1.0) < 0.01, (
            f"Weights sum to {total_weight}, expected 1.0"
        )

    def test_goal_has_constraints(self, agent):
        """Test that the goal has privacy and safety constraints."""
        constraint_ids = [c.id for c in agent.goal.constraints]
        assert "public-data-only" in constraint_ids
        assert "no-auto-email" in constraint_ids
        assert "no-crm-deletion" in constraint_ids

    def test_client_facing_nodes(self, agent):
        """Test that client-facing nodes are properly marked."""
        client_facing_nodes = [n for n in agent.nodes if n.client_facing]
        assert len(client_facing_nodes) == 2
        client_facing_ids = {n.id for n in client_facing_nodes}
        assert "config-intake" in client_facing_ids
        assert "review-leads" in client_facing_ids

    def test_conditional_edges(self, agent):
        """Test that conditional edges have proper conditions."""
        from framework.graph import EdgeCondition

        conditional_edges = [
            e for e in agent.edges if e.condition == EdgeCondition.CONDITIONAL
        ]
        assert len(conditional_edges) == 2
        for edge in conditional_edges:
            assert edge.condition_expr is not None

    def test_github_scan_node_tools(self, agent):
        """Test that github-scan node has required tools."""
        github_node = next(n for n in agent.nodes if n.id == "github-scan")
        assert "github_list_stargazers" in github_node.tools
        assert "github_get_user_profile" in github_node.tools

    def test_enrich_node_tools(self, agent):
        """Test that enrich-and-score node has required tools."""
        enrich_node = next(n for n in agent.nodes if n.id == "enrich-and-score")
        assert "apollo_enrich_person" in enrich_node.tools
        assert "apollo_enrich_company" in enrich_node.tools

    def test_crm_node_tools(self, agent):
        """Test that crm-sync-and-notify node has required tools."""
        crm_node = next(n for n in agent.nodes if n.id == "crm-sync-and-notify")
        assert "hubspot_create_contact" in crm_node.tools
        assert "hubspot_create_company" in crm_node.tools
        assert "hubspot_create_deal" in crm_node.tools
        assert "slack_post_message" in crm_node.tools
