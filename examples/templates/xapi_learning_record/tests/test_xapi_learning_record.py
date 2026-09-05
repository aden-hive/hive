"""Structural tests for xAPI Learning Record Agent."""

from xapi_learning_record import (
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
        assert goal.id == "xapi-learning-record"
        assert len(goal.success_criteria) == 3
        assert len(goal.constraints) == 3

    def test_success_criteria_weights_sum_to_one(self):
        total = sum(sc.weight for sc in goal.success_criteria)
        assert abs(total - 1.0) < 0.01


class TestNodeStructure:
    def test_five_nodes(self):
        assert len(nodes) == 5
        assert nodes[0].id == "event-capture"
        assert nodes[1].id == "statement-builder"
        assert nodes[2].id == "validator"
        assert nodes[3].id == "lrs-dispatch"
        assert nodes[4].id == "confirmation"

    def test_event_capture_is_client_facing(self):
        assert nodes[0].client_facing is True

    def test_statement_builder_has_tool(self):
        assert "build_xapi_statement" in nodes[1].tools

    def test_validator_has_tool(self):
        assert "validate_statement" in nodes[2].tools

    def test_lrs_dispatch_has_tool(self):
        assert "post_to_lrs" in nodes[3].tools

    def test_confirmation_is_client_facing(self):
        assert nodes[4].client_facing is True

    def test_middle_nodes_not_client_facing(self):
        for node in nodes[1:4]:
            assert node.client_facing is False, f"{node.id} should not be client-facing"


class TestEdgeStructure:
    def test_five_edges(self):
        assert len(edges) == 5

    def test_linear_pipeline(self):
        assert edges[0].source == "event-capture"
        assert edges[0].target == "statement-builder"
        assert edges[1].source == "statement-builder"
        assert edges[1].target == "validator"
        assert edges[2].source == "validator"
        assert edges[2].target == "lrs-dispatch"
        assert edges[3].source == "lrs-dispatch"
        assert edges[3].target == "confirmation"

    def test_loop_back(self):
        assert edges[4].source == "confirmation"
        assert edges[4].target == "event-capture"


class TestGraphConfiguration:
    def test_entry_node(self):
        assert entry_node == "event-capture"

    def test_entry_points(self):
        assert entry_points == {"default": "event-capture"}

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
        assert info["name"] == "xAPI Learning Record Agent"
        assert "event-capture" in [n for n in info["nodes"]]


class TestToolFunctions:
    def test_build_xapi_statement(self):
        from xapi_learning_record.tools import build_xapi_statement

        event = {
            "actor": {"name": "Test User", "mbox": "mailto:test@example.com"},
            "verb": {
                "id": "http://adlnet.gov/expapi/verbs/completed",
                "display": "completed",
            },
            "object": {
                "id": "https://example.com/activity/1",
                "name": "Test Activity",
            },
        }
        result = build_xapi_statement(event)
        assert isinstance(result, dict)
        assert "id" in result
        assert "timestamp" in result
        assert result["actor"]["name"] == "Test User"

    def test_validate_statement_valid(self):
        from xapi_learning_record.tools import build_xapi_statement, validate_statement

        event = {
            "actor": {"name": "Test User", "mbox": "mailto:test@example.com"},
            "verb": {
                "id": "http://adlnet.gov/expapi/verbs/completed",
                "display": "completed",
            },
            "object": {
                "id": "https://example.com/activity/1",
                "name": "Test Activity",
            },
        }
        stmt = build_xapi_statement(event)
        result = validate_statement(stmt)
        assert isinstance(result, dict)
        assert result["valid"] is True


class TestRunnerLoad:
    def test_agent_runner_load_succeeds(self, runner_loaded):
        assert runner_loaded is not None
