"""Tests for Content Marketing Agent."""

from __future__ import annotations

import pytest

from content_marketing_agent.agent import (
    CONTENT_MARKETING_EDGES,
    CONTENT_MARKETING_GOAL,
    CONTENT_MARKETING_GRAPH,
    ContentMarketingAgent,
)
from content_marketing_agent.tools import (
    analyze_news_relevance,
    publish_to_wordpress,
    store_feedback,
    validate_content_quality,
)


class TestContentMarketingAgent:
    """Test suite for ContentMarketingAgent."""

    def test_agent_initialization(self):
        """Agent should initialize with default config."""
        agent = ContentMarketingAgent()
        assert agent.config is not None
        assert agent.config.brand_name == "Acme Corp"

    def test_agent_info(self):
        """Agent info should return expected structure."""
        agent = ContentMarketingAgent()
        info = agent.info

        assert info["name"] == "Content Marketing Agent"
        assert info["entry_node"] == "news_monitor"
        assert "publisher" in info["terminal_nodes"]
        assert "human_approval" in info["pause_nodes"]
        assert info["node_count"] == 8
        assert info["edge_count"] == 9

    def test_agent_validation_passes(self):
        """Agent should pass validation."""
        agent = ContentMarketingAgent()
        result = agent.validate()

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_initial_memory(self):
        """Initial memory should contain required keys."""
        agent = ContentMarketingAgent()
        memory = agent.get_initial_memory(
            news_title="Test News",
            news_summary="Test summary content",
        )

        assert memory["news_title"] == "Test News"
        assert memory["news_summary"] == "Test summary content"
        assert memory["brand_name"] == "Acme Corp"
        assert memory["revision_count"] == 0


class TestGoalDefinition:
    """Test suite for Goal definition."""

    def test_goal_has_success_criteria(self):
        """Goal should have success criteria defined."""
        assert len(CONTENT_MARKETING_GOAL.success_criteria) >= 3

    def test_goal_has_constraints(self):
        """Goal should have constraints defined."""
        assert len(CONTENT_MARKETING_GOAL.constraints) >= 3

    def test_human_oversight_constraint(self):
        """Goal should require human oversight."""
        constraints = {c.id: c for c in CONTENT_MARKETING_GOAL.constraints}
        assert "human_oversight" in constraints
        assert constraints["human_oversight"].constraint_type == "hard"


class TestGraphStructure:
    """Test suite for Graph structure."""

    def test_graph_has_hitl_node(self):
        """Graph should have human-in-the-loop node."""
        assert "human_approval" in CONTENT_MARKETING_GRAPH.pause_nodes

    def test_graph_entry_node(self):
        """Graph should start with news monitor."""
        assert CONTENT_MARKETING_GRAPH.entry_node == "news_monitor"

    def test_graph_terminal_node(self):
        """Graph should end with publisher."""
        assert "publisher" in CONTENT_MARKETING_GRAPH.terminal_nodes

    def test_all_edges_have_valid_sources(self):
        """All edge sources should exist in nodes."""
        node_ids = {n.id for n in CONTENT_MARKETING_GRAPH.nodes}
        for edge in CONTENT_MARKETING_EDGES:
            assert edge.source in node_ids, f"Edge {edge.id} has unknown source: {edge.source}"

    def test_all_edges_have_valid_targets(self):
        """All edge targets should exist in nodes."""
        node_ids = {n.id for n in CONTENT_MARKETING_GRAPH.nodes}
        for edge in CONTENT_MARKETING_EDGES:
            assert edge.target in node_ids, f"Edge {edge.id} has unknown target: {edge.target}"


class TestTools:
    """Test suite for agent tools."""

    def test_analyze_news_relevance(self):
        """analyze_news_relevance should return relevance analysis."""
        result = analyze_news_relevance(
            title="New Technology Innovation",
            summary="Company announces breakthrough in AI technology.",
        )

        assert "is_relevant" in result
        assert "relevance_score" in result
        assert 0 <= result["relevance_score"] <= 1

    def test_validate_content_quality(self):
        """validate_content_quality should return quality metrics."""
        content = """
## Introduction

This is a test blog post with some content that demonstrates
the quality validation system.

## Main Content

Here is the main body of the article with additional details
and information about the topic being discussed.

## Conclusion

This wraps up our discussion of the topic.
"""
        result = validate_content_quality(
            content=content,
            title="Test Blog Post Title",
            brand_voice="professional",
        )

        assert "quality_score" in result
        assert "word_count" in result
        assert "issues" in result
        assert result["word_count"] > 0

    def test_publish_to_wordpress_mock(self):
        """publish_to_wordpress should return mock result."""
        result = publish_to_wordpress(
            title="Test Post",
            content="Test content",
            tags=["test"],
            status="draft",
        )

        assert result["success"] is True
        assert result["status"] == "draft"
        assert "post_id" in result
        assert "url" in result

    def test_store_feedback(self):
        """store_feedback should return confirmation."""
        result = store_feedback(
            content_id="test-123",
            feedback="Good content but needs more detail",
            rejection_reason="Incomplete",
            quality_issues=["Missing examples"],
        )

        assert result["stored"] is True
        assert result["content_id"] == "test-123"
        assert result["feedback"] == "Good content but needs more detail"


class TestNodeSpecifications:
    """Test suite for node specifications."""

    def test_news_monitor_node(self):
        """News monitor node should be configured correctly."""
        nodes = {n.id: n for n in CONTENT_MARKETING_GRAPH.nodes}
        node = nodes["news_monitor"]

        assert node.node_type == "llm_tool_use"
        assert "analyze_news_relevance" in node.tools
        assert "news_title" in node.input_keys

    def test_content_writer_node(self):
        """Content writer node should be configured correctly."""
        nodes = {n.id: n for n in CONTENT_MARKETING_GRAPH.nodes}
        node = nodes["content_writer"]

        assert node.node_type == "llm_generate"
        assert "brand_voice" in node.input_keys
        assert "draft_content" in node.output_keys

    def test_human_approval_node(self):
        """Human approval node should be HITL type."""
        nodes = {n.id: n for n in CONTENT_MARKETING_GRAPH.nodes}
        node = nodes["human_approval"]

        assert node.node_type == "human_input"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
