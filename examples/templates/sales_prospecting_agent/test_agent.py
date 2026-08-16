"""Tests for the Sales Prospecting Agent."""

import pytest
from .agent import SalesProspectingAgent


def test_agent_initialization():
    """Verify that the agent initializes correctly with default config."""
    agent = SalesProspectingAgent()
    assert agent.goal.id == "sales-prospecting"
    assert len(agent.nodes) == 6
    assert len(agent.edges) == 5


def test_graph_structure():
    """Verify the graph structure and node properties."""
    agent = SalesProspectingAgent()
    graph = agent._build_graph()

    assert graph.id == "sales-prospecting-graph"
    assert graph.entry_node == "intake"
    assert "send_email" in graph.terminal_nodes

    # Verify nodes are present
    node_ids = [n.id for n in graph.nodes]
    assert "intake" in node_ids
    assert "lead_search" in node_ids
    assert "company_research" in node_ids
    assert "draft_email" in node_ids
    assert "human_approval" in node_ids
    assert "send_email" in node_ids

    # Verify client-facing nodes
    intake_node = next(n for n in graph.nodes if n.id == "intake")
    assert intake_node.client_facing is True

    human_approval_node = next(n for n in graph.nodes if n.id == "human_approval")
    assert human_approval_node.client_facing is True


def test_node_tools():
    """Verify that nodes have the correct tools assigned."""
    agent = SalesProspectingAgent()
    graph = agent._build_graph()

    lead_search = next(n for n in graph.nodes if n.id == "lead_search")
    assert "apollo_search_people" in lead_search.tools

    company_research = next(n for n in graph.nodes if n.id == "company_research")
    assert "web_scrape" in company_research.tools
    assert "apollo_enrich_company" in company_research.tools

    send_email = next(n for n in graph.nodes if n.id == "send_email")
    assert "send_email" in send_email.tools


if __name__ == "__main__":
    pytest.main([__file__])
