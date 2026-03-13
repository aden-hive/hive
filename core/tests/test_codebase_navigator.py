"""Tests for Codebase Navigator Agent template."""

from __future__ import annotations

import sys
from pathlib import Path

# Add core and examples/templates to sys.path for imports
_repo_root = Path(__file__).resolve().parents[1]
_project_root = _repo_root.parent
_core_path = _project_root / "core"
_templates_path = _project_root / "examples" / "templates"
for _p in (_core_path, _templates_path):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_validate_passes() -> None:
    """Agent structure validation should pass."""
    from codebase_navigator import default_agent

    validation = default_agent.validate()
    assert validation["valid"] is True
    assert len(validation["errors"]) == 0


def test_info_structure() -> None:
    """info() should return expected keys and structure."""
    from codebase_navigator import default_agent

    info = default_agent.info()
    assert "name" in info
    assert info["name"] == "Codebase Navigator"
    assert "version" in info
    assert "description" in info
    assert "nodes" in info
    assert "edges" in info
    assert "entry_node" in info
    assert info["entry_node"] == "intake"
    assert info["nodes"] == ["intake", "explore", "search", "synthesize", "deliver"]
    assert "client_facing_nodes" in info
    assert "intake" in info["client_facing_nodes"]
    assert "deliver" in info["client_facing_nodes"]


def test_nodes_have_file_tools() -> None:
    """explore: list_dir; search: grep_search; synthesize: view_file; deliver: report tools."""
    from codebase_navigator.nodes import (
        deliver_node,
        explore_node,
        search_node,
        synthesize_node,
    )

    assert "list_dir" in explore_node.tools
    assert "grep_search" in search_node.tools
    assert "view_file" in synthesize_node.tools
    assert "save_data" in deliver_node.tools
    assert "append_data" in deliver_node.tools
    assert "serve_file_to_user" in deliver_node.tools


def test_sync_repo_copies_files(tmp_path: Path) -> None:
    """sync_repo copies source into workspace (mock path)."""
    from codebase_navigator.sync_repo import sync

    # Create a minimal source tree
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("print('hello')")
    (src / "bar.txt").write_text("bar")
    sub = src / "sub"
    sub.mkdir()
    (sub / "baz.py").write_text("baz")

    workspace_base = tmp_path / "workspaces"
    count = sync(src, workspace_base=workspace_base)

    dest = workspace_base / "default" / "codebase_navigator-graph" / "current"
    assert (dest / "foo.py").exists()
    assert (dest / "bar.txt").exists()
    assert (dest / "sub" / "baz.py").exists()
    assert count >= 3


def test_runner_loads_agent(tmp_path: Path) -> None:
    """AgentRunner loads codebase_navigator and passes validation."""
    from framework.runner import AgentRunner

    agent_path = _templates_path / "codebase_navigator"
    runner = AgentRunner.load(agent_path, mock_mode=True, storage_path=tmp_path)
    validation = runner.validate()
    assert validation.valid
    assert runner.graph.entry_node == "intake"
    assert "deliver" in runner.graph.terminal_nodes
    runner.cleanup()
