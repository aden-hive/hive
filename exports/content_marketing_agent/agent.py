"""Content Marketing Agent - Main agent definition.

This agent automatically creates and publishes blog posts based on company news
with a human-in-the-loop approval workflow.
"""

from __future__ import annotations

from uuid import uuid4

from framework.graph import (
    Constraint,
    EdgeCondition,
    EdgeSpec,
    Goal,
    GraphSpec,
    SuccessCriterion,
)

from .config import ContentMarketingConfig, load_config
from .nodes import (
    ALL_NODES,
    APPROVAL_ROUTER_NODE,
    CONTENT_WRITER_NODE,
    FEEDBACK_LEARNER_NODE,
    HUMAN_APPROVAL_NODE,
    NEWS_MONITOR_NODE,
    PUBLISHER_NODE,
    QUALITY_REVIEW_NODE,
    QUALITY_ROUTER_NODE,
)
from .tools import CONTENT_MARKETING_TOOLS


# =============================================================================
# Goal Definition
# =============================================================================

CONTENT_MARKETING_GOAL = Goal(
    id="content-marketing-001",
    name="Content Marketing Agent",
    description="""
    Automatically create and publish engaging blog content based on company news,
    maintaining brand voice consistency and quality standards with human oversight.
    """,
    success_criteria=[
        SuccessCriterion(
            id="content_published",
            description="Blog post is successfully published to WordPress",
            metric="output_contains",
            target="published: true",
            weight=0.4,
        ),
        SuccessCriterion(
            id="quality_threshold",
            description="Content passes quality review with score >= 0.7",
            metric="output_contains",
            target="quality_score",
            weight=0.3,
        ),
        SuccessCriterion(
            id="human_approved",
            description="Content receives human approval before publishing",
            metric="output_contains",
            target="approved",
            weight=0.3,
        ),
    ],
    constraints=[
        Constraint(
            id="brand_voice",
            description="Content must maintain consistent brand voice",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="factual_accuracy",
            description="Content must be factually accurate based on source news",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="human_oversight",
            description="All content must receive human approval before publishing",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="revision_limit",
            description="Maximum 3 revision attempts before escalation",
            constraint_type="soft",
            category="scope",
        ),
    ],
)


# =============================================================================
# Edge Definitions
# =============================================================================

CONTENT_MARKETING_EDGES = [
    # News Monitor → Content Writer (if relevant)
    EdgeSpec(
        id="news-to-writer",
        source="news_monitor",
        target="content_writer",
        condition=EdgeCondition.ON_SUCCESS,
        description="Proceed to writing if news is relevant",
    ),
    # Content Writer → Quality Review
    EdgeSpec(
        id="writer-to-review",
        source="content_writer",
        target="quality_review",
        condition=EdgeCondition.ON_SUCCESS,
        description="Send draft for quality review",
    ),
    # Quality Review → Quality Router
    EdgeSpec(
        id="review-to-router",
        source="quality_review",
        target="quality_router",
        condition=EdgeCondition.ALWAYS,
        description="Route based on quality score",
    ),
    # Quality Router → Human Approval (passes review)
    EdgeSpec(
        id="router-to-human",
        source="quality_router",
        target="human_approval",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="output.passes_review == True",
        description="Quality passes threshold, send for human review",
    ),
    # Quality Router → Content Writer (needs revision)
    EdgeSpec(
        id="router-to-revision",
        source="quality_router",
        target="content_writer",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="output.passes_review == False",
        description="Quality below threshold, revise content",
        priority=-1,  # Lower priority than approval path
    ),
    # Human Approval → Approval Router
    EdgeSpec(
        id="human-to-router",
        source="human_approval",
        target="approval_router",
        condition=EdgeCondition.ALWAYS,
        description="Route based on human decision",
    ),
    # Approval Router → Publisher (approved)
    EdgeSpec(
        id="approved-to-publish",
        source="approval_router",
        target="publisher",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="'approved' in str(output).lower() or 'edited' in str(output).lower()",
        description="Content approved, publish to WordPress",
    ),
    # Approval Router → Feedback Learner (rejected)
    EdgeSpec(
        id="rejected-to-feedback",
        source="approval_router",
        target="feedback_learner",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="'rejected' in str(output).lower()",
        description="Content rejected, learn from feedback",
        priority=-1,
    ),
    # Feedback Learner → Content Writer (retry with feedback)
    EdgeSpec(
        id="feedback-to-writer",
        source="feedback_learner",
        target="content_writer",
        condition=EdgeCondition.ON_SUCCESS,
        description="Apply feedback and retry content generation",
    ),
]


# =============================================================================
# Graph Specification
# =============================================================================

CONTENT_MARKETING_GRAPH = GraphSpec(
    id="content-marketing-graph",
    goal_id="content-marketing-001",
    version="1.0.0",
    description="Automated content marketing with HITL approval",
    entry_node="news_monitor",
    terminal_nodes=["publisher"],
    pause_nodes=["human_approval"],
    nodes=ALL_NODES,
    edges=CONTENT_MARKETING_EDGES,
    memory_keys=[
        "news_title",
        "news_summary",
        "brand_name",
        "brand_voice",
        "target_audience",
        "news_analysis",
        "draft_content",
        "quality_review",
        "route_on",
        "human_decision",
        "feedback_analysis",
        "publication_result",
        "previous_feedback",
        "revision_count",
    ],
    default_model="claude-sonnet-4-20250514",
    cleanup_llm_model="gpt-4o-mini",  # Use OpenAI for JSON cleanup
    max_tokens=4096,
    max_steps=20,
    max_retries_per_node=3,
    created_by="human",
)


# =============================================================================
# Agent Class
# =============================================================================


class ContentMarketingAgent:
    """
    Content Marketing Agent for automated blog content generation.

    This agent:
    1. Monitors news for relevance
    2. Generates brand-aligned blog content
    3. Reviews quality metrics
    4. Requests human approval (HITL)
    5. Learns from rejection feedback
    6. Publishes approved content

    Usage:
        agent = ContentMarketingAgent()
        result = await agent.run(
            news_title="Company Announces New Product",
            news_summary="Details about the announcement...",
        )
    """

    goal = CONTENT_MARKETING_GOAL
    graph = CONTENT_MARKETING_GRAPH
    tools = CONTENT_MARKETING_TOOLS

    def __init__(self, config: ContentMarketingConfig | None = None):
        """Initialize the agent with configuration."""
        self.config = config or load_config()

    @property
    def info(self) -> dict:
        """Return agent information."""
        return {
            "name": self.goal.name,
            "id": self.goal.id,
            "description": self.goal.description.strip(),
            "version": self.graph.version,
            "entry_node": self.graph.entry_node,
            "terminal_nodes": self.graph.terminal_nodes,
            "pause_nodes": self.graph.pause_nodes,
            "node_count": len(self.graph.nodes),
            "edge_count": len(self.graph.edges),
            "tool_count": len(self.tools),
            "success_criteria": [c.description for c in self.goal.success_criteria],
            "constraints": [c.description for c in self.goal.constraints],
        }

    def validate(self) -> dict:
        """Validate the agent graph structure."""
        errors = []
        warnings = []

        # Check all edge sources exist
        node_ids = {n.id for n in self.graph.nodes}
        for edge in self.graph.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge '{edge.id}' has unknown source: {edge.source}")
            if edge.target not in node_ids:
                errors.append(f"Edge '{edge.id}' has unknown target: {edge.target}")

        # Check entry node exists
        if self.graph.entry_node not in node_ids:
            errors.append(f"Entry node '{self.graph.entry_node}' not found in nodes")

        # Check terminal nodes exist
        for terminal in self.graph.terminal_nodes:
            if terminal not in node_ids:
                errors.append(f"Terminal node '{terminal}' not found in nodes")

        # Check pause nodes exist
        for pause in self.graph.pause_nodes:
            if pause not in node_ids:
                errors.append(f"Pause node '{pause}' not found in nodes")

        # Check for unreachable nodes
        reachable = {self.graph.entry_node}
        changed = True
        while changed:
            changed = False
            for edge in self.graph.edges:
                if edge.source in reachable and edge.target not in reachable:
                    reachable.add(edge.target)
                    changed = True

        unreachable = node_ids - reachable
        if unreachable:
            warnings.append(f"Unreachable nodes: {unreachable}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "nodes_checked": len(node_ids),
            "edges_checked": len(self.graph.edges),
        }

    def get_initial_memory(
        self,
        news_title: str,
        news_summary: str,
    ) -> dict:
        """Build initial shared memory for a run."""
        return {
            "news_title": news_title,
            "news_summary": news_summary,
            "brand_name": self.config.brand_name,
            "brand_voice": self.config.brand_voice,
            "target_audience": self.config.target_audience,
            "previous_feedback": "No previous feedback.",
            "revision_count": 0,
        }


# Convenience exports
goal = CONTENT_MARKETING_GOAL
graph = CONTENT_MARKETING_GRAPH
tools = CONTENT_MARKETING_TOOLS
Agent = ContentMarketingAgent
