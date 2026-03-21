"""Tests for MCP server registry logic."""

import json
from unittest.mock import MagicMock, patch

import pytest

from framework.runner.mcp_registry import (
    ToolDiff,
    check_hive_compatibility,
    compare_tool_signatures,
    install_server,
    load_manifest,
    read_installed,
    resolve_agent_versions,
    update_server,
    write_installed,
)

VALID_MANIFEST = {
    "name": "test-srv",
    "display_name": "Test Server",
    "version": "0.1.0",
    "description": "A test server",
    "author": {"name": "Test", "github": "testuser"},
    "maintainer": {"github": "testuser"},
    "repository": "https://github.com/testuser/test",
    "license": "MIT",
    "status": "community",
    "transport": {"supported": ["stdio"], "default": "stdio"},
    "install": {"pip": "test-srv"},
    "stdio": {"command": "uvx", "args": ["test-srv"]},
    "tools": [{"name": "do_thing", "description": "Does a thing"}],
}


# --- ToolDiff tests ---


def test_tool_diff_no_changes():
    diff = ToolDiff(added=[], removed=[], changed=[], unchanged=["search"])
    assert not diff.has_breaking_changes


def test_tool_diff_removed_is_breaking():
    diff = ToolDiff(added=[], removed=["old_tool"], changed=[], unchanged=[])
    assert diff.has_breaking_changes


def test_tool_diff_changed_is_breaking():
    diff = ToolDiff(added=[], removed=[], changed=["search"], unchanged=[])
    assert diff.has_breaking_changes


def test_tool_diff_added_not_breaking():
    diff = ToolDiff(added=["new_tool"], removed=[], changed=[], unchanged=[])
    assert not diff.has_breaking_changes


def test_tool_diff_format_report():
    diff = ToolDiff(added=["new"], removed=["old"], changed=[], unchanged=["keep"])
    report = diff.format_report()
    assert "PASS" in report and "keep" in report
    assert "INFO" in report and "new" in report
    assert "FAIL" in report and "old" in report


# --- installed.json I/O tests ---


def test_read_installed_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "nope.json")
    assert read_installed() == {}


def test_write_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("framework.runner.mcp_registry.REGISTRY_DIR", tmp_path)
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "installed.json")
    data = {"my-server": {"manifest_version": "1.0.0", "enabled": True}}
    write_installed(data)
    assert read_installed() == data


def test_read_installed_handles_corrupt_json(tmp_path, monkeypatch):
    bad = tmp_path / "installed.json"
    bad.write_text("not json {{{")
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", bad)
    assert read_installed() == {}


# --- load_manifest tests ---


def test_load_manifest_from_directory(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(VALID_MANIFEST))
    result = load_manifest(tmp_path)
    assert result["name"] == "test-srv"


def test_load_manifest_validates(tmp_path):
    (tmp_path / "manifest.json").write_text('{"name": "BAD"}')
    with pytest.raises(ValueError, match="Invalid manifest"):
        load_manifest(tmp_path)


def test_load_manifest_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "nope")


# --- check_hive_compatibility tests ---


def test_compatible_no_constraints():
    assert check_hive_compatibility({"hive": {}}) == []
    assert check_hive_compatibility({}) == []


def test_incompatible_below_min(monkeypatch):
    monkeypatch.setattr("importlib.metadata.version", lambda _: "0.5.0")
    warnings = check_hive_compatibility({"hive": {"min_version": "1.0.0"}})
    assert any("Requires Hive >= 1.0.0" in w for w in warnings)


def test_incompatible_above_max(monkeypatch):
    monkeypatch.setattr("importlib.metadata.version", lambda _: "2.0.0")
    warnings = check_hive_compatibility({"hive": {"max_version": "1.5.0"}})
    assert any("Requires Hive <= 1.5.0" in w for w in warnings)


# --- compare_tool_signatures tests ---


def test_compare_no_changes():
    tools = [{"name": "search", "inputSchema": {"type": "object"}}]
    diff = compare_tool_signatures(tools, tools)
    assert diff.unchanged == ["search"]
    assert not diff.has_breaking_changes


def test_compare_tool_added():
    old = [{"name": "search", "inputSchema": {}}]
    new = [{"name": "search", "inputSchema": {}}, {"name": "create", "inputSchema": {}}]
    diff = compare_tool_signatures(old, new)
    assert diff.added == ["create"]
    assert not diff.has_breaking_changes


def test_compare_tool_removed():
    old = [
        {"name": "search", "inputSchema": {}},
        {"name": "delete", "inputSchema": {}},
    ]
    new = [{"name": "search", "inputSchema": {}}]
    diff = compare_tool_signatures(old, new)
    assert diff.removed == ["delete"]
    assert diff.has_breaking_changes


def test_compare_tool_schema_changed():
    old = [{"name": "search", "inputSchema": {"properties": {"q": {"type": "string"}}}}]
    new = [{"name": "search", "inputSchema": {"properties": {"query": {"type": "string"}}}}]
    diff = compare_tool_signatures(old, new)
    assert diff.changed == ["search"]
    assert diff.has_breaking_changes


def test_compare_description_only_not_breaking():
    old = [{"name": "search", "description": "Old", "inputSchema": {}}]
    new = [{"name": "search", "description": "New", "inputSchema": {}}]
    diff = compare_tool_signatures(old, new)
    assert diff.unchanged == ["search"]
    assert not diff.has_breaking_changes


# --- resolve_agent_versions tests ---


def test_resolve_versions_match():
    installed = {"jira": {"manifest_version": "1.2.0"}}
    errors = resolve_agent_versions({"versions": {"jira": "1.2.0"}}, installed)
    assert errors == []


def test_resolve_versions_mismatch():
    installed = {"jira": {"manifest_version": "1.0.0"}}
    errors = resolve_agent_versions({"versions": {"jira": "1.2.0"}}, installed)
    assert len(errors) == 1
    assert "pinned to v1.2.0" in errors[0]
    assert "Fix:" in errors[0]


def test_resolve_versions_not_installed():
    errors = resolve_agent_versions({"versions": {"jira": "1.2.0"}}, {})
    assert len(errors) == 1
    assert "not installed" in errors[0]


def test_resolve_versions_no_pins():
    errors = resolve_agent_versions({}, {"jira": {"manifest_version": "1.0.0"}})
    assert errors == []


# --- install_server tests ---


def test_install_server_success(tmp_path, monkeypatch):
    monkeypatch.setattr("framework.runner.mcp_registry.REGISTRY_DIR", tmp_path)
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "installed.json")

    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    (srv_dir / "manifest.json").write_text(json.dumps(VALID_MANIFEST))

    with patch("framework.runner.mcp_registry.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0, stderr="")
        entry = install_server(srv_dir)

    assert entry["manifest_version"] == "0.1.0"
    assert entry["pinned"] is False
    assert entry["enabled"] is True
    installed = json.loads((tmp_path / "installed.json").read_text())
    assert "test-srv" in installed


def test_install_server_with_version_pin(tmp_path, monkeypatch):
    monkeypatch.setattr("framework.runner.mcp_registry.REGISTRY_DIR", tmp_path)
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "installed.json")

    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    (srv_dir / "manifest.json").write_text(json.dumps(VALID_MANIFEST))

    with patch("framework.runner.mcp_registry.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0, stderr="")
        entry = install_server(srv_dir, version="2.0.0")

    assert entry["pinned"] is True
    assert entry["resolved_package_version"] == "2.0.0"


def test_install_server_validation_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("framework.runner.mcp_registry.REGISTRY_DIR", tmp_path)
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "installed.json")

    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    (srv_dir / "manifest.json").write_text('{"name": "BAD"}')

    with pytest.raises(ValueError, match="Invalid manifest"):
        install_server(srv_dir)


def test_install_server_subprocess_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("framework.runner.mcp_registry.REGISTRY_DIR", tmp_path)
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "installed.json")

    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    (srv_dir / "manifest.json").write_text(json.dumps(VALID_MANIFEST))

    with patch("framework.runner.mcp_registry.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=1, stderr="Package not found")
        with pytest.raises(RuntimeError, match="Package install failed"):
            install_server(srv_dir)


# --- update_server tests ---


def test_update_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "installed.json")
    with pytest.raises(ValueError, match="not installed"):
        update_server("nope")


def test_update_pinned_server_errors(tmp_path, monkeypatch):
    installed_path = tmp_path / "installed.json"
    installed_path.write_text(
        json.dumps({"my-srv": {"pinned": True, "manifest": {"version": "1.0.0", "tools": []}}})
    )
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", installed_path)
    with pytest.raises(ValueError, match="pinned"):
        update_server("my-srv")


def test_update_dry_run_no_side_effects(tmp_path, monkeypatch):
    entry_data = {
        "my-srv": {
            "pinned": False,
            "manifest": {
                "version": "1.0.0",
                "tools": [{"name": "search", "inputSchema": {}}],
            },
        }
    }
    installed_path = tmp_path / "installed.json"
    installed_path.write_text(json.dumps(entry_data))
    monkeypatch.setattr("framework.runner.mcp_registry.INSTALLED_JSON", installed_path)
    monkeypatch.setattr("framework.runner.mcp_registry.REGISTRY_DIR", tmp_path)

    diff = update_server("my-srv", dry_run=True)
    assert not diff.has_breaking_changes

    # Verify installed.json was NOT modified
    after = json.loads(installed_path.read_text())
    assert after == entry_data
