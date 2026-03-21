"""Tests for MCP registry CLI commands."""

import argparse
import json
from unittest.mock import MagicMock, patch

from framework.runner.mcp_registry_cli import (
    cmd_init,
    cmd_install,
    cmd_test,
    cmd_update,
    cmd_validate,
)

VALID_MANIFEST = {
    "name": "test-server",
    "display_name": "Test Server",
    "version": "0.1.0",
    "description": "A test MCP server",
    "author": {"name": "Test", "github": "testuser"},
    "maintainer": {"github": "testuser"},
    "repository": "https://github.com/testuser/test-server",
    "license": "MIT",
    "status": "community",
    "transport": {"supported": ["stdio"], "default": "stdio"},
    "install": {"pip": "test-server"},
    "stdio": {"command": "uvx", "args": ["test-server"]},
    "tools": [{"name": "do_thing", "description": "Does a thing"}],
}


def test_validate_valid_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(VALID_MANIFEST))
    args = argparse.Namespace(path=str(path))
    assert cmd_validate(args) == 0


def test_validate_invalid_manifest(tmp_path):
    manifest = {"name": "BAD NAME"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    args = argparse.Namespace(path=str(path))
    assert cmd_validate(args) == 1


def test_validate_directory_path(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(VALID_MANIFEST))
    args = argparse.Namespace(path=str(tmp_path))
    assert cmd_validate(args) == 0


def test_validate_missing_file():
    args = argparse.Namespace(path="/nonexistent/manifest.json")
    assert cmd_validate(args) == 1


def test_validate_invalid_json(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("not json {{{")
    args = argparse.Namespace(path=str(path))
    assert cmd_validate(args) == 1


# --- cmd_init tests ---


def test_init_creates_manifest(tmp_path):
    user_inputs = ["my-server", "My Server", "A test server", "stdio", "my-server-pkg"]
    with patch("builtins.input", side_effect=user_inputs):
        args = argparse.Namespace(server_url=None, output_dir=str(tmp_path))
        result = cmd_init(args)
    assert result == 0
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "README.md").exists()
    # Round-trip: generated manifest should pass validation
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    from framework.runner.mcp_manifest_schema import validate_manifest

    assert validate_manifest(manifest) == []


def test_init_with_server_url(tmp_path):
    mock_response_data = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [{"name": "search", "description": "Search things", "inputSchema": {}}]
        },
    }
    user_inputs = ["my-server", "My Server", "A test server", "http", "my-server-pkg"]
    with (
        patch("builtins.input", side_effect=user_inputs),
        patch("httpx.post") as mock_post,
    ):
        mock_post.return_value.json.return_value = mock_response_data
        mock_post.return_value.status_code = 200
        args = argparse.Namespace(server_url="http://localhost:4000", output_dir=str(tmp_path))
        result = cmd_init(args)
    assert result == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert len(manifest["tools"]) == 1
    assert manifest["tools"][0]["name"] == "search"


def test_init_server_url_unreachable(tmp_path):
    user_inputs = ["my-server", "My Server", "A test server", "stdio", "my-server-pkg"]
    with (
        patch("builtins.input", side_effect=user_inputs),
        patch("httpx.post", side_effect=Exception("Connection refused")),
    ):
        args = argparse.Namespace(server_url="http://localhost:9999", output_dir=str(tmp_path))
        result = cmd_init(args)
    assert result == 0  # should still succeed with empty tools
    assert (tmp_path / "manifest.json").exists()


# --- cmd_test tests ---


def _make_mock_tool(name, description=""):
    """Create a mock MCPTool with the given name."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    return tool


def test_cmd_test_pass(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(VALID_MANIFEST))
    mock_client = MagicMock()
    mock_client.list_tools.return_value = [_make_mock_tool("do_thing")]
    with patch("framework.runner.mcp_registry_cli.MCPClient", return_value=mock_client):
        args = argparse.Namespace(path=str(tmp_path))
        assert cmd_test(args) == 0
    mock_client.disconnect.assert_called_once()


def test_cmd_test_missing_tool(tmp_path):
    manifest = {
        **VALID_MANIFEST,
        "tools": [
            {"name": "search", "description": "Search"},
            {"name": "create", "description": "Create"},
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    mock_client = MagicMock()
    mock_client.list_tools.return_value = [_make_mock_tool("search")]
    with patch("framework.runner.mcp_registry_cli.MCPClient", return_value=mock_client):
        args = argparse.Namespace(path=str(tmp_path))
        assert cmd_test(args) == 1


def test_cmd_test_invalid_manifest(tmp_path):
    (tmp_path / "manifest.json").write_text('{"name": "BAD"}')
    args = argparse.Namespace(path=str(tmp_path))
    assert cmd_test(args) == 1


def test_cmd_test_connection_failure(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(VALID_MANIFEST))
    with patch("framework.runner.mcp_registry_cli.MCPClient") as mock_cls:
        mock_cls.return_value.connect.side_effect = Exception("Connection refused")
        args = argparse.Namespace(path=str(tmp_path))
        assert cmd_test(args) == 1


def test_cmd_test_cleanup_on_failure(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(VALID_MANIFEST))
    mock_client = MagicMock()
    mock_client.list_tools.side_effect = Exception("boom")
    with patch("framework.runner.mcp_registry_cli.MCPClient", return_value=mock_client):
        args = argparse.Namespace(path=str(tmp_path))
        cmd_test(args)
    mock_client.disconnect.assert_called_once()


# --- cmd_install tests ---


def test_cmd_install_success(tmp_path):
    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    (srv_dir / "manifest.json").write_text(json.dumps(VALID_MANIFEST))

    with (
        patch("framework.runner.mcp_registry.subprocess") as mock_sub,
        patch("framework.runner.mcp_registry.REGISTRY_DIR", tmp_path),
        patch("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "installed.json"),
    ):
        mock_sub.run.return_value = MagicMock(returncode=0, stderr="")
        args = argparse.Namespace(source=str(srv_dir), version=None)
        assert cmd_install(args) == 0


def test_cmd_install_invalid_manifest(tmp_path):
    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    (srv_dir / "manifest.json").write_text('{"name": "BAD"}')
    args = argparse.Namespace(source=str(srv_dir), version=None)
    assert cmd_install(args) == 1


def test_cmd_install_with_version(tmp_path):
    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    (srv_dir / "manifest.json").write_text(json.dumps(VALID_MANIFEST))

    with (
        patch("framework.runner.mcp_registry.subprocess") as mock_sub,
        patch("framework.runner.mcp_registry.REGISTRY_DIR", tmp_path),
        patch("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "installed.json"),
    ):
        mock_sub.run.return_value = MagicMock(returncode=0, stderr="")
        args = argparse.Namespace(source=str(srv_dir), version="2.0.0")
        assert cmd_install(args) == 0


# --- cmd_update tests ---


def test_cmd_update_not_installed(tmp_path):
    with patch("framework.runner.mcp_registry.INSTALLED_JSON", tmp_path / "installed.json"):
        args = argparse.Namespace(name="nope", dry_run=False)
        assert cmd_update(args) == 1


def test_cmd_update_dry_run(tmp_path):
    entry_data = {
        "test-server": {
            "pinned": False,
            "manifest": {
                "version": "1.0.0",
                "tools": [{"name": "do_thing", "inputSchema": {}}],
            },
        }
    }
    installed_path = tmp_path / "installed.json"
    installed_path.write_text(json.dumps(entry_data))
    with (
        patch("framework.runner.mcp_registry.INSTALLED_JSON", installed_path),
        patch("framework.runner.mcp_registry.REGISTRY_DIR", tmp_path),
    ):
        args = argparse.Namespace(name="test-server", dry_run=True)
        assert cmd_update(args) == 0
