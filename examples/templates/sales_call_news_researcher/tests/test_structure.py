"""Structural tests for Sales Call News Researcher."""

from sales_call_news_researcher import (
    conversation_mode,
    default_agent,
    edges,
    entry_node,
    entry_points,
    goal,
    loop_config,
    nodes,
    terminal_nodes,
)


class TestGoalDefinition:
    def test_goal_exists(self):
        assert goal is not None
        assert goal.id == "sales-call-news-researcher-goal"
        assert len(goal.success_criteria) == 5
        assert len(goal.constraints) == 4

    def test_success_criteria_weights_sum_to_one(self):
        total = sum(sc.weight for sc in goal.success_criteria)
        assert abs(total - 1.0) < 0.01


class TestNodeStructure:
    def test_six_nodes(self):
        assert len(nodes) == 6
        assert nodes[0].id == "calendar-scan"
        assert nodes[1].id == "company-identifier"
        assert nodes[2].id == "news-fetcher"
        assert nodes[3].id == "news-curator"
        assert nodes[4].id == "email-composer"
        assert nodes[5].id == "email-sender"

    def test_calendar_scan_has_required_tools(self):
        required = {"calendar_list_events", "save_data"}
        actual = set(nodes[0].tools)
        assert required.issubset(actual)

    def test_news_fetcher_has_required_tools(self):
        required = {"news_search", "web_search", "load_data", "save_data"}
        actual = set(nodes[2].tools)
        assert required.issubset(actual)

    def test_email_sender_is_client_facing(self):
        assert nodes[5].client_facing is True

    def test_email_sender_has_required_tools(self):
        required = {"send_email", "load_data"}
        actual = set(nodes[5].tools)
        assert required.issubset(actual)


class TestEdgeStructure:
    def test_six_edges(self):
        assert len(edges) == 6

    def test_linear_path(self):
        assert edges[0].source == "calendar-scan"
        assert edges[0].target == "company-identifier"
        assert edges[1].source == "company-identifier"
        assert edges[1].target == "news-fetcher"
        assert edges[2].source == "news-fetcher"
        assert edges[2].target == "news-curator"
        assert edges[3].source == "news-curator"
        assert edges[3].target == "email-composer"
        assert edges[4].source == "email-composer"
        assert edges[4].target == "email-sender"

    def test_loop_back(self):
        assert edges[5].source == "email-sender"
        assert edges[5].target == "calendar-scan"


class TestGraphConfiguration:
    def test_entry_node(self):
        assert entry_node == "calendar-scan"

    def test_entry_points(self):
        assert entry_points == {"start": "calendar-scan"}

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
        assert info["name"] == "Sales Call News Researcher"
        assert "news-fetcher" in list(info["nodes"])


class TestRunnerLoad:
    def test_agent_runner_load_succeeds(self, runner_loaded):
        assert runner_loaded is not None
