"""Tests for agent.json config validation.

Ensures AgentRunner.load() catches invalid configs early with clear errors
instead of failing at runtime with confusing messages.

Fixes: https://github.com/adenhq/hive/issues/2039
"""

import pytest

from framework.runner.config_validator import AgentConfigError, validate_agent_config


def _minimal_valid_config() -> dict:
    """Return a minimal valid agent.json config."""
    return {
        "id": "test_agent",
        "name": "Test Agent",
        "entry_node": "node_1",
        "nodes": [
            {
                "id": "node_1",
                "name": "Start Node",
                "node_type": "llm_generate",
                "input_keys": [],
                "output_keys": ["result"],
            }
        ],
        "edges": [],
        "goal": {
            "id": "goal_1",
            "name": "Test Goal",
            "description": "A test goal",
        },
    }


class TestValidateAgentConfig:
    """Tests for validate_agent_config."""

    def test_valid_config_passes(self):
        """A minimal valid config should not raise."""
        validate_agent_config(_minimal_valid_config())

    def test_valid_config_with_edges(self):
        """A valid config with edges should not raise."""
        config = _minimal_valid_config()
        config["nodes"].append(
            {
                "id": "node_2",
                "name": "End Node",
                "node_type": "llm_generate",
                "input_keys": ["result"],
                "output_keys": ["final"],
            }
        )
        config["edges"] = [{"source": "node_1", "target": "node_2"}]
        validate_agent_config(config)

    # --- Missing top-level fields ---

    def test_missing_id_raises(self):
        config = _minimal_valid_config()
        del config["id"]
        with pytest.raises(AgentConfigError, match="Missing required field: 'id'"):
            validate_agent_config(config)

    def test_missing_name_raises(self):
        config = _minimal_valid_config()
        del config["name"]
        with pytest.raises(AgentConfigError, match="Missing required field: 'name'"):
            validate_agent_config(config)

    def test_missing_nodes_raises(self):
        config = _minimal_valid_config()
        del config["nodes"]
        with pytest.raises(AgentConfigError, match="Missing required field: 'nodes'"):
            validate_agent_config(config)

    def test_missing_edges_raises(self):
        config = _minimal_valid_config()
        del config["edges"]
        with pytest.raises(AgentConfigError, match="Missing required field: 'edges'"):
            validate_agent_config(config)

    def test_missing_entry_node_raises(self):
        config = _minimal_valid_config()
        del config["entry_node"]
        with pytest.raises(AgentConfigError, match="Missing required field: 'entry_node'"):
            validate_agent_config(config)

    def test_missing_goal_raises(self):
        config = _minimal_valid_config()
        del config["goal"]
        with pytest.raises(AgentConfigError, match="Missing required field: 'goal'"):
            validate_agent_config(config)

    def test_empty_config_raises(self):
        with pytest.raises(AgentConfigError, match="Missing required field"):
            validate_agent_config({})

    # --- Wrong types ---

    def test_nodes_wrong_type_raises(self):
        config = _minimal_valid_config()
        config["nodes"] = "not_a_list"
        with pytest.raises(AgentConfigError, match="must be list, got str"):
            validate_agent_config(config)

    def test_edges_wrong_type_raises(self):
        config = _minimal_valid_config()
        config["edges"] = "not_a_list"
        with pytest.raises(AgentConfigError, match="must be list, got str"):
            validate_agent_config(config)

    def test_goal_wrong_type_raises(self):
        config = _minimal_valid_config()
        config["goal"] = "not_a_dict"
        with pytest.raises(AgentConfigError, match="must be dict, got str"):
            validate_agent_config(config)

    # --- Node validation ---

    def test_node_missing_id_raises(self):
        config = _minimal_valid_config()
        del config["nodes"][0]["id"]
        config["entry_node"] = "node_1"  # won't match
        with pytest.raises(AgentConfigError, match="missing required field 'id'"):
            validate_agent_config(config)

    def test_node_missing_name_raises(self):
        config = _minimal_valid_config()
        del config["nodes"][0]["name"]
        with pytest.raises(AgentConfigError, match="missing required field 'name'"):
            validate_agent_config(config)

    def test_node_missing_node_type_raises(self):
        config = _minimal_valid_config()
        del config["nodes"][0]["node_type"]
        with pytest.raises(AgentConfigError, match="missing required field 'node_type'"):
            validate_agent_config(config)

    def test_node_invalid_node_type_raises(self):
        config = _minimal_valid_config()
        config["nodes"][0]["node_type"] = "invalid_type"
        with pytest.raises(AgentConfigError, match="invalid node_type 'invalid_type'"):
            validate_agent_config(config)

    def test_node_not_dict_raises(self):
        config = _minimal_valid_config()
        config["nodes"] = ["not_a_dict"]
        with pytest.raises(AgentConfigError, match="must be a dict"):
            validate_agent_config(config)

    def test_duplicate_node_ids_raises(self):
        config = _minimal_valid_config()
        config["nodes"].append(config["nodes"][0].copy())
        with pytest.raises(AgentConfigError, match="duplicate node id 'node_1'"):
            validate_agent_config(config)

    def test_llm_tool_use_without_tools_raises(self):
        config = _minimal_valid_config()
        config["nodes"][0]["node_type"] = "llm_tool_use"
        config["nodes"][0].pop("tools", None)
        with pytest.raises(AgentConfigError, match="no tools are declared"):
            validate_agent_config(config)

    # --- All valid node types accepted ---

    @pytest.mark.parametrize(
        "node_type",
        ["llm_tool_use", "llm_generate", "router", "function", "human_input", "event_loop"],
    )
    def test_all_valid_node_types_accepted(self, node_type):
        config = _minimal_valid_config()
        config["nodes"][0]["node_type"] = node_type
        if node_type == "llm_tool_use":
            config["nodes"][0]["tools"] = ["web_search"]
        validate_agent_config(config)  # Should not raise

    # --- Entry node validation ---

    def test_entry_node_not_in_nodes_raises(self):
        config = _minimal_valid_config()
        config["entry_node"] = "nonexistent_node"
        with pytest.raises(AgentConfigError, match="does not match any node id"):
            validate_agent_config(config)

    # --- Edge validation ---

    def test_edge_invalid_source_raises(self):
        config = _minimal_valid_config()
        config["edges"] = [{"source": "fake_node", "target": "node_1"}]
        with pytest.raises(AgentConfigError, match="source 'fake_node' is not a valid node id"):
            validate_agent_config(config)

    def test_edge_invalid_target_raises(self):
        config = _minimal_valid_config()
        config["edges"] = [{"source": "node_1", "target": "fake_node"}]
        with pytest.raises(AgentConfigError, match="target 'fake_node' is not a valid node id"):
            validate_agent_config(config)

    def test_edge_missing_source_raises(self):
        config = _minimal_valid_config()
        config["edges"] = [{"target": "node_1"}]
        with pytest.raises(AgentConfigError, match="missing required field 'source'"):
            validate_agent_config(config)

    def test_edge_missing_target_raises(self):
        config = _minimal_valid_config()
        config["edges"] = [{"source": "node_1"}]
        with pytest.raises(AgentConfigError, match="missing required field 'target'"):
            validate_agent_config(config)

    def test_edge_not_dict_raises(self):
        config = _minimal_valid_config()
        config["edges"] = ["not_a_dict"]
        with pytest.raises(AgentConfigError, match="must be a dict"):
            validate_agent_config(config)

    # --- Goal validation ---

    def test_goal_missing_id_raises(self):
        config = _minimal_valid_config()
        del config["goal"]["id"]
        with pytest.raises(AgentConfigError, match="goal: missing required field 'id'"):
            validate_agent_config(config)

    def test_goal_missing_name_raises(self):
        config = _minimal_valid_config()
        del config["goal"]["name"]
        with pytest.raises(AgentConfigError, match="goal: missing required field 'name'"):
            validate_agent_config(config)

    def test_goal_missing_description_raises(self):
        config = _minimal_valid_config()
        del config["goal"]["description"]
        with pytest.raises(
            AgentConfigError, match="goal: missing required field 'description'"
        ):
            validate_agent_config(config)

    def test_goal_empty_dict_raises(self):
        config = _minimal_valid_config()
        config["goal"] = {}
        with pytest.raises(AgentConfigError, match="goal: missing required field"):
            validate_agent_config(config)

    # --- Error reporting ---

    def test_multiple_errors_all_reported(self):
        """All errors should be collected and reported at once."""
        config = _minimal_valid_config()
        config["entry_node"] = "nonexistent"
        config["goal"] = {}  # missing id, name, description

        with pytest.raises(AgentConfigError) as exc_info:
            validate_agent_config(config)

        # Should contain multiple errors
        assert len(exc_info.value.errors) >= 2

    def test_error_message_includes_config_path(self):
        """Error message should include the config file path."""
        with pytest.raises(AgentConfigError, match="my/custom/path.json"):
            validate_agent_config({}, config_path="my/custom/path.json")

    def test_error_message_includes_docs_reference(self):
        """Error message should point to documentation."""
        with pytest.raises(AgentConfigError, match="getting-started.md"):
            validate_agent_config({})
