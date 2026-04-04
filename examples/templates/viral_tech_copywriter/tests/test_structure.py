"""Structural tests for Viral Tech Copywriter."""

from __future__ import annotations

from pathlib import Path

import pytest
from viral_tech_copywriter import (
    ViralTechCopywriterAgent,
    default_agent,
    edges,
    entry_node,
    entry_points,
    goal,
    nodes,
    pause_nodes,
    terminal_nodes,
)

_EXPECTED_DELIVER_TOOLS = {
    "save_data",
    "append_data",
    "serve_file_to_user",
    "load_data",
    "list_data_files",
    "edit_data",
}


class TestGoalDefinition:
    def test_goal_exists(self) -> None:
        assert goal is not None
        assert goal.id == "viral-tech-copywriter-goal"
        assert len(goal.success_criteria) == 6
        assert len(goal.constraints) == 3

    def test_success_criteria_weights_sum_to_one(self) -> None:
        total = sum(sc.weight for sc in goal.success_criteria)
        assert abs(total - 1.0) < 0.01


class TestNodeStructure:
    def test_four_nodes(self) -> None:
        assert len(nodes) == 4
        assert nodes[0].id == "intake"
        assert nodes[1].id == "normalize-brief"
        assert nodes[2].id == "write-package"
        assert nodes[3].id == "deliver-exports"

    def test_client_facing_intake_and_deliver(self) -> None:
        assert nodes[0].client_facing is True
        assert nodes[3].client_facing is True

    def test_normalize_and_write_not_client_facing(self) -> None:
        assert nodes[1].client_facing is False
        assert nodes[2].client_facing is False

    def test_tools_only_on_deliver(self) -> None:
        assert nodes[0].tools == []
        assert nodes[1].tools == []
        assert nodes[2].tools == []
        assert set(nodes[3].tools) == _EXPECTED_DELIVER_TOOLS


class TestEdgeStructure:
    def test_three_edges(self) -> None:
        assert len(edges) == 3

    def test_linear_path(self) -> None:
        assert edges[0].source == "intake"
        assert edges[0].target == "normalize-brief"
        assert edges[1].source == "normalize-brief"
        assert edges[1].target == "write-package"
        assert edges[2].source == "write-package"
        assert edges[2].target == "deliver-exports"


class TestGraphConfiguration:
    def test_entry_node(self) -> None:
        assert entry_node == "intake"

    def test_entry_points(self) -> None:
        assert entry_points == {"start": "intake"}

    def test_pause_nodes(self) -> None:
        assert pause_nodes == []

    def test_terminal_nodes(self) -> None:
        assert terminal_nodes == ["deliver-exports"]


class TestAgentClass:
    def test_default_agent_created(self) -> None:
        assert default_agent is not None

    def test_validate_passes(self) -> None:
        result = default_agent.validate()
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_agent_info(self) -> None:
        info = default_agent.info()
        assert info["name"] == "Viral Tech Copywriter"
        assert info["entry_node"] == "intake"
        assert set(info["client_facing_nodes"]) == {"intake", "deliver-exports"}


class TestRunnerLoad:
    def test_agent_runner_load_succeeds(self, runner_loaded) -> None:
        assert runner_loaded is not None


class TestMcpConfig:
    def test_mcp_config_path_is_package_file(self) -> None:
        path = ViralTechCopywriterAgent.mcp_config_path()
        assert path.name == "mcp_servers.json"
        assert path.parent == Path(__file__).resolve().parents[1]
        assert path.is_file()

    def test_load_hive_tools_registry_missing_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        missing = tmp_path / "missing_mcp_servers.json"

        @classmethod
        def _fake_mcp_path(cls: type[ViralTechCopywriterAgent]) -> Path:
            return missing

        monkeypatch.setattr(ViralTechCopywriterAgent, "mcp_config_path", _fake_mcp_path)
        with pytest.raises(FileNotFoundError, match="Required MCP config"):
            ViralTechCopywriterAgent.load_hive_tools_registry()
