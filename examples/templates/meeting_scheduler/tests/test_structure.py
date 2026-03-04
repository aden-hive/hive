"""Structural tests for Meeting Scheduler."""

import pytest
from meeting_scheduler import (
    default_agent, goal, nodes, edges, entry_node, entry_points,
    terminal_nodes, conversation_mode, identity_prompt, loop_config
)


class TestGoalDefinition:
    def test_goal_exists(self):
        assert goal is not None
        assert goal.id == "meeting-scheduler-goal"
        assert len(goal.success_criteria) == 4
        assert len(goal.constraints) == 3

    def test_success_criteria_weights_sum_to_one(self):
        total = sum(sc.weight for sc in goal.success_criteria)
        assert abs(total - 1.0) < 0.01


class TestNodeStructure:
    def test_three_nodes(self):
        assert len(nodes) == 3
        assert nodes[0].id == "intake"
        assert nodes[1].id == "schedule"
        assert nodes[2].id == "confirm"

    def test_intake_is_client_facing(self):
        assert nodes[0].client_facing is True

    def test_schedule_has_required_tools(self):
        required = {"calendar_check_availability", "calendar_create_event", "google_sheets_append_values", "send_email"}
        actual = set(nodes[1].tools)
        assert required.issubset(actual)

    def test_confirm_is_client_facing(self):
        assert nodes[2].client_facing is True


class TestEdgeStructure:
    def test_three_edges(self):
        assert len(edges) == 3

    def test_linear_path(self):
        assert edges[0].source == "intake"
        assert edges[0].target == "schedule"
        assert edges[1].source == "schedule"
        assert edges[1].target == "confirm"

    def test_loop_back(self):
        assert edges[2].source == "confirm"
        assert edges[2].target == "intake"


class TestGraphConfiguration:
    def test_entry_node(self):
        assert entry_node == "intake"

    def test_entry_points(self):
        assert entry_points == {"start": "intake"}

    def test_forever_alive(self):
        assert terminal_nodes == []

    def test_conversation_mode(self):
        assert conversation_mode == "continuous"

    def test_loop_config_valid(self):
        assert "max_iterations" in loop_config
        assert "max_tool_calls_per_turn" in loop_config
        assert "max_history_tokens" in loop_config


class TestAgentClass:
    def test_default_agent_created(self):
        assert default_agent is not None

    def test_validate_passes(self):
        result = default_agent.validate()
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_agent_info(self):
        info = default_agent.info()
        assert info["name"] == "Meeting Scheduler"
        assert "schedule" in [n for n in info["nodes"]]


class TestRunnerLoad:
    def test_agent_runner_load_succeeds(self, runner_loaded):
        assert runner_loaded is not None
