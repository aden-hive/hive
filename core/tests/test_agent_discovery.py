"""Tests for agent discovery helpers.

Verifies that ``_is_valid_agent_dir`` and ``_has_agents`` recognise both
``agent.json`` and ``agent.py``-based agents so that ``hive list`` and
``hive dispatch`` do not silently skip Python-defined agents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from framework.runner.cli import _has_agents, _is_valid_agent_dir


@pytest.fixture()
def tmp_agents(tmp_path: Path):
    """Create a temporary directory with sample agent folders."""
    # JSON-only agent
    json_agent = tmp_path / "json_agent"
    json_agent.mkdir()
    (json_agent / "agent.json").write_text("{}")

    # Python-only agent
    py_agent = tmp_path / "py_agent"
    py_agent.mkdir()
    (py_agent / "agent.py").write_text("# python agent")

    # Both JSON and Python agent
    both_agent = tmp_path / "both_agent"
    both_agent.mkdir()
    (both_agent / "agent.json").write_text("{}")
    (both_agent / "agent.py").write_text("# python agent")

    # Not an agent (no agent.json or agent.py)
    not_agent = tmp_path / "not_agent"
    not_agent.mkdir()
    (not_agent / "README.md").write_text("# not an agent")

    return tmp_path


class TestIsValidAgentDir:
    """Tests for _is_valid_agent_dir."""

    def test_json_agent(self, tmp_agents: Path) -> None:
        assert _is_valid_agent_dir(tmp_agents / "json_agent") is True

    def test_python_agent(self, tmp_agents: Path) -> None:
        assert _is_valid_agent_dir(tmp_agents / "py_agent") is True

    def test_both_agent(self, tmp_agents: Path) -> None:
        assert _is_valid_agent_dir(tmp_agents / "both_agent") is True

    def test_not_agent(self, tmp_agents: Path) -> None:
        assert _is_valid_agent_dir(tmp_agents / "not_agent") is False

    def test_nonexistent_path(self, tmp_agents: Path) -> None:
        assert _is_valid_agent_dir(tmp_agents / "nonexistent") is False

    def test_file_not_dir(self, tmp_agents: Path) -> None:
        f = tmp_agents / "some_file.txt"
        f.write_text("not a directory")
        assert _is_valid_agent_dir(f) is False


class TestHasAgents:
    """Tests for _has_agents."""

    def test_directory_with_agents(self, tmp_agents: Path) -> None:
        assert _has_agents(tmp_agents) is True

    def test_empty_directory(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _has_agents(empty) is False

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        assert _has_agents(tmp_path / "nonexistent") is False

    def test_directory_with_only_python_agents(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents"
        agent_dir.mkdir()
        py_agent = agent_dir / "my_agent"
        py_agent.mkdir()
        (py_agent / "agent.py").write_text("# python agent")
        assert _has_agents(agent_dir) is True
