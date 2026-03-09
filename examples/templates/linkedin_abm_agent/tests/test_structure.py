import sys
import os

sys.path.insert(0, os.path.dirname(__file__) + "/..")

from agent import LinkedInABMAgent
from nodes import (
    intake_node,
    prospect_node,
    enrich_node,
    message_node,
    review_node,
    outreach_node,
    tracking_node,
)


class TestLinkedInABMAgentNodes:
    """Test LinkedIn ABM agent node definitions."""

    def test_intake_node(self):
        assert intake_node.id == "intake"
        assert intake_node.name == "Campaign Intake"
        assert intake_node.node_type == "event_loop"
        assert intake_node.client_facing is True
        assert intake_node.max_node_visits == 0
        assert intake_node.input_keys == []
        assert intake_node.output_keys == [
            "linkedin_urls",
            "target_criteria",
            "campaign_name",
        ]

        assert intake_node.success_criteria == (
            "The user has provided LinkedIn profile URLs or a Sales Navigator export, "
            "specified target criteria (role, seniority, industry), and named the campaign."
        )

    def test_prospect_node(self):
        assert prospect_node.id == "prospect"
        assert prospect_node.name == "LinkedIn Prospecting"
        assert prospect_node.node_type == "event_loop"
        assert prospect_node.client_facing is False
        assert prospect_node.max_node_visits == 0
        assert prospect_node.input_keys == ["linkedin_urls", "target_criteria"]
        assert prospect_node.output_keys == ["prospects", "validation_summary"]

    def test_enrich_node(self):
        assert enrich_node.id == "enrich"
        assert enrich_node.name == "Data Enrichment"
        assert enrich_node.node_type == "event_loop"
        assert enrich_node.client_facing is False
        assert enrich_node.max_node_visits == 0
        assert enrich_node.input_keys == ["prospects", "campaign_name"]
        assert enrich_node.output_keys == ["enriched_prospects", "enrichment_summary"]

    def test_message_node(self):
        assert message_node.id == "message"
        assert message_node.name == "Message Generation"
        assert message_node.node_type == "event_loop"
        assert message_node.client_facing is False
        assert message_node.max_node_visits == 0
        assert message_node.input_keys == ["enriched_prospects", "campaign_name"]
        assert message_node.output_keys == [
            "message_templates",
            "personalized_messages",
        ]

    def test_review_node(self):
        assert review_node.id == "review"
        assert review_node.name == "Human Review"
        assert review_node.node_type == "event_loop"
        assert review_node.client_facing is True
        assert review_node.max_node_visits == 0
        assert review_node.input_keys == [
            "enriched_prospects",
            "personalized_messages",
            "enrichment_summary",
            "campaign_name",
        ]
        assert review_node.output_keys == [
            "approved",
            "modifications",
            "selected_prospects",
        ]

    def test_outreach_node(self):
        assert outreach_node.id == "outreach"
        assert outreach_node.name == "Execute Outreach"
        assert outreach_node.node_type == "event_loop"
        assert outreach_node.client_facing is False
        assert outreach_node.max_node_visits == 0
        assert outreach_node.input_keys == [
            "enriched_prospects",
            "personalized_messages",
            "selected_prospects",
            "approved",
        ]
        assert outreach_node.output_keys == ["outreach_results", "campaign_report"]

    def test_tracking_node(self):
        assert tracking_node.id == "tracking"
        assert tracking_node.name == "Campaign Tracking"
        assert tracking_node.node_type == "event_loop"
        assert tracking_node.client_facing is True
        assert tracking_node.max_node_visits == 0
        assert tracking_node.input_keys == ["campaign_report", "campaign_name"]
        assert tracking_node.output_keys == ["final_report_path", "campaign_complete"]


class TestLinkedInABMAgentStructure:
    """Test LinkedIn ABM Agent structure validation."""

    def test_agent_structure(self):
        agent = LinkedInABMAgent()
        result = agent.validate()
        assert result["valid"]
        assert result["errors"] == []
        assert result["warnings"] == []

    def test_agent_nodes(self):
        agent = LinkedInABMAgent()
        node_ids = [node.id for node in agent.nodes]
        expected_ids = {
            "intake",
            "prospect",
            "enrich",
            "message",
            "review",
            "outreach",
            "tracking",
        }
        assert set(node_ids) == expected_ids

    def test_agent_edges(self):
        agent = LinkedInABMAgent()
        edge_ids = [edge.id for edge in agent.edges]
        expected_edges = {
            "intake-to-prospect",
            "prospect-to-enrich",
            "enrich-to-message",
            "message-to-review",
            "review-to-message",
            "review-to-outreach",
            "outreach-to-tracking",
            "tracking-to-intake",
        }
        assert set(edge_ids) == expected_edges

    def test_agent_goal(self):
        agent = LinkedInABMAgent()
        assert agent.goal.id == "linkedin-abm-agent"
        assert agent.goal.name == "LinkedIn ABM Agent"
