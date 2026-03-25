"""Integration tests for hive mcp CLI commands."""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from framework.runner.mcp_registry_cli import (
    _parse_key_value_pairs,
    _print_security_notice_if_first_use,
    cmd_mcp_add,
    cmd_mcp_config,
    cmd_mcp_disable,
    cmd_mcp_enable,
    cmd_mcp_health,
    cmd_mcp_info,
    cmd_mcp_install,
    cmd_mcp_list,
    cmd_mcp_remove,
    cmd_mcp_search,
    cmd_mcp_update,
    register_mcp_commands,
)

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def registry_home(tmp_path, monkeypatch):
    """Set up an isolated registry base directory."""
    base = tmp_path / "mcp_registry"
    base.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    return base


@pytest.fixture()
def registry(registry_home):
    """Return an initialized MCPRegistry backed by tmp_path."""
    from framework.runner.mcp_registry import MCPRegistry

    reg = MCPRegistry(base_path=registry_home)
    reg.initialize()
    return reg


@pytest.fixture()
def _patch_get_registry(registry, monkeypatch):
    """Patch _get_registry so all CLI commands use the test registry."""
    monkeypatch.setattr(
        "framework.runner.mcp_registry_cli._get_registry",
        lambda base_path=None: registry,
    )


@pytest.fixture()
def sample_index(registry_home):
    """Write a sample registry index with two servers."""
    index = {
        "servers": {
            "jira": {
                "version": "1.2.0",
                "description": "Jira issue tracker integration",
                "status": "verified",
                "transport": {"supported": ["stdio", "http"], "default": "stdio"},
                "stdio": {"command": "uvx", "args": ["jira-mcp"]},
                "http": {"url": "http://localhost:4010"},
                "tools": [
                    {"name": "jira_create_issue", "description": "Create a Jira issue"},
                    {"name": "jira_search", "description": "Search issues with JQL"},
                ],
                "credentials": [
                    {
                        "id": "api_token",
                        "env_var": "JIRA_API_TOKEN",
                        "description": "Jira API token",
                        "help_url": "https://id.atlassian.com/manage-profile/security/api-tokens",
                        "required": True,
                    },
                ],
                "tags": ["project-management", "atlassian"],
                "hive": {"profiles": ["productivity"], "min_version": "0.5.0"},
            },
            "slack": {
                "version": "2.0.0",
                "description": "Slack messaging integration",
                "status": "community",
                "transport": {"supported": ["http"], "default": "http"},
                "http": {"url": "http://localhost:4011"},
                "tools": [{"name": "send_message", "description": "Send a Slack message"}],
                "tags": ["messaging"],
            },
        }
    }
    cache_dir = registry_home / "cache"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / "registry_index.json").write_text(json.dumps(index), encoding="utf-8")
    # Mark as fresh so auto-refresh doesn't trigger
    (cache_dir / "last_fetched").write_text(
        json.dumps({"timestamp": "2099-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    return index


def _capture(func, args_ns) -> tuple[int, str, str]:
    """Call a command handler, capturing stdout and stderr."""
    out, err = StringIO(), StringIO()
    with patch("sys.stdout", out), patch("sys.stderr", err):
        rc = func(args_ns)
    return rc, out.getvalue(), err.getvalue()


# ── argparse registration ──────────────────────────────────────────


def test_register_mcp_commands_creates_all_subcommands(capsys):
    """register_mcp_commands wires all 11 subcommands into argparse."""
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_mcp_commands(subparsers)

    expected = [
        "install",
        "add",
        "remove",
        "enable",
        "disable",
        "list",
        "info",
        "config",
        "search",
        "health",
        "update",
    ]

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["mcp", "--help"])
    assert exc_info.value.code == 0

    help_text = capsys.readouterr().out
    for cmd in expected:
        assert cmd in help_text, f"subcommand '{cmd}' missing from mcp --help"


def test_argparse_round_trip_install():
    """Verify argparse parses 'mcp install jira --version 1.0' correctly."""
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_mcp_commands(subparsers)

    args = parser.parse_args(["mcp", "install", "jira", "--version", "1.0"])
    assert args.name == "jira"
    assert args.version == "1.0"
    assert hasattr(args, "func")


# ── install ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_install_writes_to_installed_json(registry, sample_index, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    args = SimpleNamespace(name="jira", version=None, transport=None)
    rc, out, err = _capture(cmd_mcp_install, args)

    assert rc == 0
    assert "Installed jira" in out
    server = registry.get_server("jira")
    assert server is not None
    assert server["transport"] == "stdio"


@pytest.mark.usefixtures("_patch_get_registry")
def test_install_with_version_pin(registry, sample_index, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    args = SimpleNamespace(name="jira", version="1.2.0", transport=None)
    rc, out, _ = _capture(cmd_mcp_install, args)

    assert rc == 0
    server = registry.get_server("jira")
    assert server["pinned"] is True


@pytest.mark.usefixtures("_patch_get_registry")
def test_install_not_found_fails(registry, sample_index):
    args = SimpleNamespace(name="nonexistent", version=None, transport=None)
    rc, _, err = _capture(cmd_mcp_install, args)

    assert rc == 1
    assert "not found in registry" in err


@pytest.mark.usefixtures("_patch_get_registry")
def test_install_duplicate_fails(registry, sample_index):
    registry.install("jira")
    args = SimpleNamespace(name="jira", version=None, transport=None)
    rc, _, err = _capture(cmd_mcp_install, args)

    assert rc == 1
    assert "already exists" in err


# ── security notice ────────────────────────────────────────────────


def test_security_notice_shown_only_once(registry_home):
    from framework.runner.mcp_registry_cli import _mark_security_notice_shown

    err1, err2 = StringIO(), StringIO()
    with patch("sys.stderr", err1):
        _print_security_notice_if_first_use(registry_home)
    # Simulate successful install persisting the sentinel
    _mark_security_notice_shown(registry_home)
    with patch("sys.stderr", err2):
        _print_security_notice_if_first_use(registry_home)

    assert "Registry servers run code" in err1.getvalue()
    assert err2.getvalue() == ""


# ── credential prompting ──────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_credential_prompt_stores_override(registry, sample_index, monkeypatch):
    """Installing a server with required credentials prompts and stores them."""
    registry.install("jira")

    # Simulate user typing a credential value
    monkeypatch.setattr("builtins.input", lambda prompt: "my-secret-token")
    # Ensure the env var isn't already set
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

    from framework.runner.mcp_registry_cli import _prompt_for_missing_credentials

    manifest = sample_index["servers"]["jira"]
    _prompt_for_missing_credentials(registry, "jira", manifest)

    server = registry.get_server("jira")
    assert server["overrides"]["env"]["JIRA_API_TOKEN"] == "my-secret-token"


@pytest.mark.usefixtures("_patch_get_registry")
def test_credential_prompt_skips_when_env_set(registry, sample_index, monkeypatch):
    """Don't prompt when the env var is already set."""
    registry.install("jira")
    monkeypatch.setenv("JIRA_API_TOKEN", "already-set")

    calls = []
    monkeypatch.setattr("builtins.input", lambda prompt: calls.append(prompt) or "")

    from framework.runner.mcp_registry_cli import _prompt_for_missing_credentials

    manifest = sample_index["servers"]["jira"]
    _prompt_for_missing_credentials(registry, "jira", manifest)

    assert len(calls) == 0


# ── add ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_add_registers_local_http_server(registry):
    args = SimpleNamespace(
        name="my-db",
        transport="http",
        url="http://localhost:9090",
        command=None,
        args=None,
        socket_path=None,
        description="Custom DB",
        from_manifest=None,
    )
    rc, out, _ = _capture(cmd_mcp_add, args)

    assert rc == 0
    assert "Registered my-db" in out
    server = registry.get_server("my-db")
    assert server is not None
    assert server["transport"] == "http"


@pytest.mark.usefixtures("_patch_get_registry")
def test_add_missing_name_fails(registry):
    args = SimpleNamespace(
        name=None,
        transport="http",
        url="http://localhost:9090",
        command=None,
        args=None,
        socket_path=None,
        description="",
        from_manifest=None,
    )
    rc, _, err = _capture(cmd_mcp_add, args)

    assert rc == 1
    assert "--name is required" in err


@pytest.mark.usefixtures("_patch_get_registry")
def test_add_missing_transport_fails(registry):
    args = SimpleNamespace(
        name="my-db",
        transport=None,
        url=None,
        command=None,
        args=None,
        socket_path=None,
        description="",
        from_manifest=None,
    )
    rc, _, err = _capture(cmd_mcp_add, args)

    assert rc == 1
    assert "--transport is required" in err


@pytest.mark.usefixtures("_patch_get_registry")
def test_add_from_manifest_file(registry, tmp_path):
    manifest = {
        "name": "from-file",
        "description": "Loaded from manifest",
        "transport": {"supported": ["http"], "default": "http"},
        "http": {"url": "http://localhost:5000"},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    args = SimpleNamespace(
        name=None,
        transport=None,
        url=None,
        command=None,
        args=None,
        socket_path=None,
        description="",
        from_manifest=str(manifest_path),
    )
    rc, out, _ = _capture(cmd_mcp_add, args)

    assert rc == 0
    assert "Registered from-file" in out
    server = registry.get_server("from-file")
    assert server is not None


# ── remove ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_remove_deletes_server(registry, sample_index):
    registry.install("jira")
    args = SimpleNamespace(name="jira")
    rc, out, _ = _capture(cmd_mcp_remove, args)

    assert rc == 0
    assert "Removed jira" in out
    assert registry.get_server("jira") is None


@pytest.mark.usefixtures("_patch_get_registry")
def test_remove_nonexistent_fails(registry):
    args = SimpleNamespace(name="nonexistent")
    rc, _, err = _capture(cmd_mcp_remove, args)

    assert rc == 1
    assert "not installed" in err


# ── enable / disable ──────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_enable_disable_toggles_state(registry, sample_index):
    registry.install("jira")

    rc, out, _ = _capture(cmd_mcp_disable, SimpleNamespace(name="jira"))
    assert rc == 0
    assert "Disabled" in out
    assert registry.get_server("jira")["enabled"] is False

    rc, out, _ = _capture(cmd_mcp_enable, SimpleNamespace(name="jira"))
    assert rc == 0
    assert "Enabled" in out
    assert registry.get_server("jira")["enabled"] is True


# ── list ───────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_list_renders_installed_entries(registry, sample_index):
    registry.install("jira")
    registry.install("slack")

    args = SimpleNamespace(available=False, output_json=False)
    rc, out, _ = _capture(cmd_mcp_list, args)

    assert rc == 0
    assert "jira" in out
    assert "slack" in out
    assert "NAME" in out  # header


@pytest.mark.usefixtures("_patch_get_registry")
def test_list_empty_shows_help(registry):
    args = SimpleNamespace(available=False, output_json=False)
    rc, out, _ = _capture(cmd_mcp_list, args)

    assert rc == 0
    assert "No servers installed" in out


@pytest.mark.usefixtures("_patch_get_registry")
def test_list_json_output(registry, sample_index):
    registry.install("jira")

    args = SimpleNamespace(available=False, output_json=True)
    rc, out, _ = _capture(cmd_mcp_list, args)

    assert rc == 0
    data = json.loads(out)
    assert isinstance(data, list)
    assert data[0]["name"] == "jira"


@pytest.mark.usefixtures("_patch_get_registry")
def test_list_available_reads_index(registry, sample_index):
    args = SimpleNamespace(available=True, output_json=False)
    rc, out, _ = _capture(cmd_mcp_list, args)

    assert rc == 0
    assert "jira" in out
    assert "slack" in out


# ── info ───────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_info_shows_details(registry, sample_index):
    registry.install("jira")

    args = SimpleNamespace(name="jira", output_json=False)
    rc, out, _ = _capture(cmd_mcp_info, args)

    assert rc == 0
    assert "jira" in out
    assert "stdio" in out
    assert "1.2.0" in out
    assert "verified" in out


@pytest.mark.usefixtures("_patch_get_registry")
def test_info_json_output(registry, sample_index):
    registry.install("jira")

    args = SimpleNamespace(name="jira", output_json=True)
    rc, out, _ = _capture(cmd_mcp_info, args)

    assert rc == 0
    data = json.loads(out)
    assert data["name"] == "jira"
    assert data["transport"] == "stdio"


@pytest.mark.usefixtures("_patch_get_registry")
def test_info_not_found_fails(registry):
    args = SimpleNamespace(name="nonexistent", output_json=False)
    rc, _, err = _capture(cmd_mcp_info, args)

    assert rc == 1
    assert "not installed" in err
    assert "hive mcp install" in err


# ── config ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_config_sets_env_override(registry, sample_index):
    registry.install("jira")

    args = SimpleNamespace(name="jira", set_env=["JIRA_API_TOKEN=abc123"], set_header=None)
    rc, out, _ = _capture(cmd_mcp_config, args)

    assert rc == 0
    server = registry.get_server("jira")
    assert server["overrides"]["env"]["JIRA_API_TOKEN"] == "abc123"


@pytest.mark.usefixtures("_patch_get_registry")
def test_config_sets_header_override(registry, sample_index):
    registry.install("jira")

    args = SimpleNamespace(name="jira", set_env=None, set_header=["Authorization=Bearer xyz"])
    rc, out, _ = _capture(cmd_mcp_config, args)

    assert rc == 0
    server = registry.get_server("jira")
    assert server["overrides"]["headers"]["Authorization"] == "Bearer xyz"


@pytest.mark.usefixtures("_patch_get_registry")
def test_config_shows_current_when_no_args(registry, sample_index):
    registry.install("jira")
    registry.set_override("jira", "JIRA_API_TOKEN", "secret", override_type="env")

    args = SimpleNamespace(name="jira", set_env=None, set_header=None)
    rc, out, _ = _capture(cmd_mcp_config, args)

    assert rc == 0
    assert "JIRA_API_TOKEN" in out


# ── search ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_search_finds_by_name(registry, sample_index):
    args = SimpleNamespace(query="jira", output_json=False)
    rc, out, _ = _capture(cmd_mcp_search, args)

    assert rc == 0
    assert "jira" in out
    assert "slack" not in out


@pytest.mark.usefixtures("_patch_get_registry")
def test_search_finds_by_tag(registry, sample_index):
    args = SimpleNamespace(query="messaging", output_json=False)
    rc, out, _ = _capture(cmd_mcp_search, args)

    assert rc == 0
    assert "slack" in out


@pytest.mark.usefixtures("_patch_get_registry")
def test_search_no_results(registry, sample_index):
    args = SimpleNamespace(query="zzz_nonexistent_zzz", output_json=False)
    rc, out, _ = _capture(cmd_mcp_search, args)

    assert rc == 0
    assert "No servers matching" in out


@pytest.mark.usefixtures("_patch_get_registry")
def test_search_json_output(registry, sample_index):
    args = SimpleNamespace(query="jira", output_json=True)
    rc, out, _ = _capture(cmd_mcp_search, args)

    assert rc == 0
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["name"] == "jira"


# ── health ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_health_returns_status(registry, sample_index, monkeypatch):
    registry.install("jira")

    # Mock health_check to avoid real connections
    monkeypatch.setattr(
        registry,
        "health_check",
        lambda name=None: {"name": "jira", "status": "healthy", "tools": 2, "error": None},
    )

    args = SimpleNamespace(name="jira", output_json=False)
    rc, out, _ = _capture(cmd_mcp_health, args)

    assert rc == 0
    assert "healthy" in out


@pytest.mark.usefixtures("_patch_get_registry")
def test_health_json_output(registry, sample_index, monkeypatch):
    registry.install("jira")

    monkeypatch.setattr(
        registry,
        "health_check",
        lambda name=None: {"name": "jira", "status": "healthy", "tools": 2, "error": None},
    )

    args = SimpleNamespace(name="jira", output_json=True)
    rc, out, _ = _capture(cmd_mcp_health, args)

    assert rc == 0
    data = json.loads(out)
    assert "jira" in data


# ── update ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_update_named_server_reinstalls(registry, sample_index):
    """update <name> removes and reinstalls, preserving overrides."""
    registry.install("jira")
    registry.set_override("jira", "JIRA_API_TOKEN", "my-token", override_type="env")

    args = SimpleNamespace(name="jira")
    rc, out, _ = _capture(cmd_mcp_update, args)

    assert rc == 0
    assert "jira" in out
    server = registry.get_server("jira")
    assert server is not None
    # Overrides preserved
    assert server["overrides"]["env"]["JIRA_API_TOKEN"] == "my-token"


@pytest.mark.usefixtures("_patch_get_registry")
def test_update_local_server_fails(registry):
    """update <name> rejects local servers."""
    registry.add_local(name="my-db", transport="http", url="http://localhost:9090")

    args = SimpleNamespace(name="my-db")
    rc, _, err = _capture(cmd_mcp_update, args)

    assert rc == 1
    assert "local server" in err


@pytest.mark.usefixtures("_patch_get_registry")
def test_update_pinned_server_fails_with_correct_remediation(registry, sample_index):
    """update <name> rejects pinned servers with remove+install remediation, not config."""
    registry.install("jira", version="1.2.0")

    args = SimpleNamespace(name="jira")
    rc, _, err = _capture(cmd_mcp_update, args)

    assert rc == 1
    assert "pinned" in err
    assert "hive mcp remove" in err
    assert "hive mcp install" in err
    # Must NOT suggest config --set pinned=false (config only writes env/header overrides)
    assert "config" not in err


@pytest.mark.usefixtures("_patch_get_registry")
def test_update_restores_server_on_reinstall_failure(registry, sample_index):
    """update <name> restores the original entry if reinstall fails."""
    registry.install("jira")
    registry.set_override("jira", "JIRA_API_TOKEN", "my-token", override_type="env")

    # Remove jira from the cached index so install() will fail after remove()
    cache_dir = registry._cache_dir
    index = json.loads((cache_dir / "registry_index.json").read_text(encoding="utf-8"))
    del index["servers"]["jira"]
    (cache_dir / "registry_index.json").write_text(json.dumps(index), encoding="utf-8")

    args = SimpleNamespace(name="jira")
    rc, _, err = _capture(cmd_mcp_update, args)

    assert rc == 1
    assert "restored" in err

    # Server must still be installed with original data
    server = registry.get_server("jira")
    assert server is not None
    assert server["transport"] == "stdio"
    assert server["overrides"]["env"]["JIRA_API_TOKEN"] == "my-token"


@pytest.mark.usefixtures("_patch_get_registry")
def test_update_index_succeeds(registry, monkeypatch):
    monkeypatch.setattr(registry, "update_index", lambda: 5)

    args = SimpleNamespace(name=None)
    rc, out, _ = _capture(cmd_mcp_update, args)

    assert rc == 0
    assert "5 servers available" in out


@pytest.mark.usefixtures("_patch_get_registry")
def test_update_all_updates_registry_servers(registry, sample_index, monkeypatch):
    """update (no name) refreshes index and updates all installed registry servers."""
    registry.install("jira")
    registry.install("slack")
    registry.set_override("jira", "JIRA_API_TOKEN", "keep-me", override_type="env")

    # Mock update_index so it doesn't hit the network
    monkeypatch.setattr(registry, "update_index", lambda: 2)

    args = SimpleNamespace(name=None)
    rc, out, _ = _capture(cmd_mcp_update, args)

    assert rc == 0
    assert "2 installed server(s)" in out
    assert "jira" in out
    assert "slack" in out
    # Overrides preserved
    server = registry.get_server("jira")
    assert server["overrides"]["env"]["JIRA_API_TOKEN"] == "keep-me"


@pytest.mark.usefixtures("_patch_get_registry")
def test_update_all_skips_local_and_pinned(registry, sample_index, monkeypatch):
    """update (no name) skips local servers and pinned servers."""
    registry.install("jira", version="1.2.0")  # pinned
    registry.add_local(name="my-db", transport="http", url="http://localhost:9090")

    monkeypatch.setattr(registry, "update_index", lambda: 2)

    args = SimpleNamespace(name=None)
    rc, out, _ = _capture(cmd_mcp_update, args)

    assert rc == 0
    # Neither should appear in update output (both skipped)
    assert "installed server(s)" not in out


# ── parse helpers ──────────────────────────────────────────────────


def test_parse_key_value_pairs_valid():
    result = _parse_key_value_pairs(["KEY=value", "FOO=bar=baz"])
    assert result == {"KEY": "value", "FOO": "bar=baz"}


def test_parse_key_value_pairs_invalid():
    with pytest.raises(ValueError, match="Invalid format"):
        _parse_key_value_pairs(["NOEQUALS"])


def test_parse_key_value_pairs_empty_key():
    with pytest.raises(ValueError, match="Key cannot be empty"):
        _parse_key_value_pairs(["=value"])


# ── index refresh failure semantics ───────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_install_fails_when_no_cache_and_refresh_fails(registry, monkeypatch):
    """install hard-fails when there's no cached index and refresh fails."""
    import httpx

    monkeypatch.setattr(registry, "is_index_stale", lambda: True)
    monkeypatch.setattr(registry, "update_index", _raise(httpx.ConnectError("offline")))
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    args = SimpleNamespace(name="jira", version=None, transport=None)
    rc, _, err = _capture(cmd_mcp_install, args)

    assert rc == 1
    assert "no registry index available" in err


@pytest.mark.usefixtures("_patch_get_registry")
def test_install_uses_stale_cache_when_refresh_fails(registry, sample_index, monkeypatch):
    """install warns but continues with stale cache when refresh fails."""
    import httpx

    monkeypatch.setattr(registry, "is_index_stale", lambda: True)
    monkeypatch.setattr(registry, "update_index", _raise(httpx.ConnectError("offline")))
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    args = SimpleNamespace(name="jira", version=None, transport=None)
    rc, out, err = _capture(cmd_mcp_install, args)

    assert rc == 0
    assert "Using cached index" in err
    assert "Installed jira" in out


# ── list columns ──────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_list_includes_tools_count_and_trust_tier(registry, sample_index):
    """list table includes TOOLS and TRUST columns."""
    registry.install("jira")

    args = SimpleNamespace(available=False, output_json=False)
    rc, out, _ = _capture(cmd_mcp_list, args)

    assert rc == 0
    assert "TOOLS" in out
    assert "TRUST" in out
    # jira has 2 tools and "verified" status
    assert "2" in out
    assert "verified" in out


# ── config masking ────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_config_display_masks_values(registry, sample_index):
    """config display shows <set> not actual values."""
    registry.install("jira")
    registry.set_override("jira", "JIRA_API_TOKEN", "super-secret-value", override_type="env")

    args = SimpleNamespace(name="jira", set_env=None, set_header=None)
    rc, out, _ = _capture(cmd_mcp_config, args)

    assert rc == 0
    assert "<set>" in out
    assert "super-secret-value" not in out
    assert "supe..." not in out


# ── info masking ──────────────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_info_masks_override_values(registry, sample_index):
    """info display shows <set> not actual secret values."""
    registry.install("jira")
    registry.set_override("jira", "JIRA_API_TOKEN", "my-secret", override_type="env")

    args = SimpleNamespace(name="jira", output_json=False)
    rc, out, _ = _capture(cmd_mcp_info, args)

    assert rc == 0
    assert "<set>" in out
    assert "my-secret" not in out


# ── credential prompting cancel ───────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_credential_prompt_cancel_does_not_abort_install(registry, sample_index, monkeypatch):
    """Ctrl+C during credential prompting doesn't abort the install itself."""
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.setattr("builtins.input", _raise(KeyboardInterrupt()))

    # Install first, then test prompting separately
    registry.install("jira")

    from framework.runner.mcp_registry_cli import _prompt_for_missing_credentials

    manifest = sample_index["servers"]["jira"]
    # Should not raise
    _prompt_for_missing_credentials(registry, "jira", manifest)

    # Server still installed, no override set
    server = registry.get_server("jira")
    assert server is not None
    assert server["overrides"]["env"] == {}


# ── update DX-2 message ──────────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_update_nonexistent_server_fails(registry):
    """update <name> returns DX-2 error when server not installed."""
    args = SimpleNamespace(name="nonexistent")
    rc, _, err = _capture(cmd_mcp_update, args)

    assert rc == 1
    assert "not installed" in err
    assert "hive mcp install" in err


# ── helper ────────────────────────────────────────────────────────


def _raise(exc):
    """Return a callable that raises the given exception."""

    def _raiser(*args, **kwargs):
        raise exc

    return _raiser


# ── end-to-end CLI integration via real entrypoint ────────────────


def test_main_dispatches_mcp_list_through_real_argparse(registry_home, monkeypatch):
    """hive mcp list goes through main() -> register_mcp_commands -> cmd_mcp_list."""
    from framework.runner.mcp_registry import MCPRegistry

    reg = MCPRegistry(base_path=registry_home)
    reg.initialize()
    monkeypatch.setattr(
        "framework.runner.mcp_registry_cli._get_registry",
        lambda base_path=None: reg,
    )

    monkeypatch.setattr("sys.argv", ["hive", "mcp", "list"])

    from framework.cli import main

    out = StringIO()
    with patch("sys.stdout", out), pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert "No servers installed" in out.getvalue()


def test_main_dispatches_mcp_install_through_real_argparse(
    registry_home, sample_index, monkeypatch
):
    """hive mcp install jira goes through main() -> real argparse -> cmd_mcp_install."""
    from framework.runner.mcp_registry import MCPRegistry

    reg = MCPRegistry(base_path=registry_home)
    reg.initialize()
    monkeypatch.setattr(
        "framework.runner.mcp_registry_cli._get_registry",
        lambda base_path=None: reg,
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    monkeypatch.setattr("sys.argv", ["hive", "mcp", "install", "jira"])

    from framework.cli import main

    out = StringIO()
    with patch("sys.stdout", out), pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert "Installed jira" in out.getvalue()


def test_main_dispatches_mcp_update_named_through_real_argparse(registry_home, monkeypatch):
    """hive mcp update nonexistent goes through main() and returns error code 1."""
    from framework.runner.mcp_registry import MCPRegistry

    reg = MCPRegistry(base_path=registry_home)
    reg.initialize()
    monkeypatch.setattr(
        "framework.runner.mcp_registry_cli._get_registry",
        lambda base_path=None: reg,
    )
    monkeypatch.setattr("sys.argv", ["hive", "mcp", "update", "nonexistent"])

    from framework.cli import main

    err = StringIO()
    with patch("sys.stderr", err), pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    assert "not installed" in err.getvalue()


# ── info --json includes agent usage ─────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_info_json_includes_agent_usage(registry, sample_index, tmp_path, monkeypatch):
    """info --json output includes used_by_agents when agents reference the server."""
    registry.install("jira")

    # Create a fake agent dir with mcp_registry.json that includes jira
    agent_dir = tmp_path / "fake_agent"
    agent_dir.mkdir()
    (agent_dir / "mcp_registry.json").write_text(
        json.dumps({"include": ["jira"]}), encoding="utf-8"
    )

    # Patch _find_agents_using_server to use our fake directory
    monkeypatch.setattr(
        "framework.runner.mcp_registry_cli._find_agents_using_server",
        lambda reg, name: [str(agent_dir)],
    )

    args = SimpleNamespace(name="jira", output_json=True)
    rc, out, _ = _capture(cmd_mcp_info, args)

    assert rc == 0
    data = json.loads(out)
    assert "used_by_agents" in data
    assert str(agent_dir) in data["used_by_agents"]


# ── info --json masks secret values ──────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_info_json_masks_override_secrets(registry, sample_index):
    """info --json must not leak actual override values."""
    registry.install("jira")
    registry.set_override("jira", "JIRA_API_TOKEN", "super-secret-token-123", override_type="env")
    registry.set_override("jira", "Authorization", "Bearer top-secret", override_type="headers")

    args = SimpleNamespace(name="jira", output_json=True)
    rc, out, _ = _capture(cmd_mcp_info, args)

    assert rc == 0
    raw_output = out
    assert "super-secret-token-123" not in raw_output
    assert "top-secret" not in raw_output

    data = json.loads(out)
    assert data["overrides"]["env"]["JIRA_API_TOKEN"] == "<set>"
    assert data["overrides"]["headers"]["Authorization"] == "<set>"


# ── health all-servers path ──────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_health_all_servers(registry, sample_index, monkeypatch):
    """health with no name checks all installed servers."""
    registry.install("jira")
    registry.install("slack")

    monkeypatch.setattr(
        registry,
        "health_check",
        lambda name=None: {
            "jira": {"status": "healthy", "tools": 2, "error": None},
            "slack": {"status": "unhealthy", "tools": 0, "error": "Connection refused"},
        },
    )

    args = SimpleNamespace(name=None, output_json=False)
    rc, out, _ = _capture(cmd_mcp_health, args)

    assert rc == 0
    assert "jira" in out
    assert "healthy" in out
    assert "slack" in out
    assert "Connection refused" in out


@pytest.mark.usefixtures("_patch_get_registry")
def test_health_all_servers_json(registry, sample_index, monkeypatch):
    """health --json with no name returns dict keyed by server name."""
    registry.install("jira")

    monkeypatch.setattr(
        registry,
        "health_check",
        lambda name=None: {
            "jira": {"status": "healthy", "tools": 2, "error": None},
        },
    )

    args = SimpleNamespace(name=None, output_json=True)
    rc, out, _ = _capture(cmd_mcp_health, args)

    assert rc == 0
    data = json.loads(out)
    assert "jira" in data
    assert data["jira"]["status"] == "healthy"


# ── _find_agents_using_server with real files ────────────────────


def test_find_agents_using_server_resolves_via_load_agent_selection(
    registry_home, tmp_path, monkeypatch
):
    """_find_agents_using_server exercises the real helper with patched candidate dirs."""
    from framework.runner.mcp_registry import MCPRegistry

    reg = MCPRegistry(base_path=registry_home)
    reg.initialize()

    # Install a server so resolve_for_agent can find it
    cache_dir = registry_home / "cache"
    cache_dir.mkdir(exist_ok=True)
    index = {
        "servers": {
            "jira": {
                "version": "1.0.0",
                "transport": {"supported": ["http"], "default": "http"},
                "http": {"url": "http://localhost:4010"},
                "tools": [],
                "tags": ["pm"],
            }
        }
    }
    (cache_dir / "registry_index.json").write_text(json.dumps(index), encoding="utf-8")
    (cache_dir / "last_fetched").write_text(
        json.dumps({"timestamp": "2099-01-01T00:00:00+00:00"}), encoding="utf-8"
    )
    reg.install("jira")

    # Create fake agent directories: one that includes jira, one that doesn't
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    agent_yes = exports_dir / "agent_with_jira"
    agent_yes.mkdir()
    (agent_yes / "mcp_registry.json").write_text(
        json.dumps({"include": ["jira"]}), encoding="utf-8"
    )
    agent_no = exports_dir / "agent_without_jira"
    agent_no.mkdir()
    (agent_no / "mcp_registry.json").write_text(
        json.dumps({"include": ["slack"]}), encoding="utf-8"
    )

    # Patch the path resolution so the helper scans our tmp_path dirs
    import framework.runner.mcp_registry_cli as cli_mod

    def _find_with_tmp_paths(registry, name):
        """Run the real helper logic but over tmp_path agent dirs."""
        agent_dirs = []
        for child in exports_dir.iterdir():
            if child.is_dir():
                agent_dirs.append(child)

        matches = []
        for agent_dir in agent_dirs:
            registry_json = agent_dir / "mcp_registry.json"
            if not registry_json.exists():
                continue
            try:
                configs = registry.load_agent_selection(agent_dir)
                resolved_names = {c["name"] for c in configs}
                if name in resolved_names:
                    matches.append(str(agent_dir))
            except Exception:
                continue
        return matches

    monkeypatch.setattr(cli_mod, "_find_agents_using_server", _find_with_tmp_paths)

    results = cli_mod._find_agents_using_server(reg, "jira")
    assert str(agent_yes) in results
    assert str(agent_no) not in results


# ── real integration: real registry on disk → CLI commands ────────


def test_integration_real_registry_install_list_info_remove(tmp_path, monkeypatch):
    """Integration: real MCPRegistry on disk → install → list → info → config → remove.

    No _get_registry patches. Real JSON files on disk. Same pattern as
    Richard's AgentRunner integration test.
    """
    # Set credential env var so install doesn't prompt for stdin
    monkeypatch.setenv("JIRA_TOKEN", "from-env")
    from framework.runner.mcp_registry import MCPRegistry
    from framework.runner.mcp_registry_cli import (
        cmd_mcp_config,
        cmd_mcp_info,
        cmd_mcp_install,
        cmd_mcp_list,
        cmd_mcp_remove,
    )

    # Set up a real registry with a real cached index
    registry_base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=registry_base)
    registry.initialize()

    cache_dir = registry_base / "cache"
    cache_dir.mkdir(exist_ok=True)
    index = {
        "servers": {
            "jira": {
                "version": "1.2.0",
                "description": "Jira integration",
                "status": "verified",
                "transport": {"supported": ["stdio", "http"], "default": "http"},
                "http": {"url": "http://localhost:4010"},
                "tools": [
                    {"name": "create_issue", "description": "Create a Jira issue"},
                    {"name": "search", "description": "Search issues"},
                ],
                "credentials": [
                    {"env_var": "JIRA_TOKEN", "description": "API token", "required": True},
                ],
                "tags": ["pm"],
            }
        }
    }
    (cache_dir / "registry_index.json").write_text(json.dumps(index), encoding="utf-8")
    (cache_dir / "last_fetched").write_text(
        json.dumps({"timestamp": "2099-01-01T00:00:00+00:00"}), encoding="utf-8"
    )
    # Security notice sentinel so install doesn't prompt
    (registry_base / ".security_notice_shown").touch()

    # Patch _get_registry to use our real registry (only to set base_path)
    import framework.runner.mcp_registry_cli as cli_mod

    cli_mod_get_registry = cli_mod._get_registry
    cli_mod._get_registry = lambda base_path=None: registry

    try:
        # 1. Install
        rc, out, _ = _capture(
            cmd_mcp_install,
            SimpleNamespace(name="jira", version=None, transport=None),
        )
        assert rc == 0
        assert "Installed jira" in out

        # Verify real file on disk
        installed = json.loads((registry_base / "installed.json").read_text(encoding="utf-8"))
        assert "jira" in installed["servers"]
        assert installed["servers"]["jira"]["transport"] == "http"
        assert installed["servers"]["jira"]["source"] == "registry"

        # 2. List — should show jira with tools count and trust tier
        rc, out, _ = _capture(
            cmd_mcp_list,
            SimpleNamespace(available=False, output_json=False),
        )
        assert rc == 0
        assert "jira" in out
        assert "2" in out  # tools count
        assert "verified" in out  # trust tier

        # 3. Config — set a credential
        rc, out, _ = _capture(
            cmd_mcp_config,
            SimpleNamespace(name="jira", set_env=["JIRA_TOKEN=real-token"], set_header=None),
        )
        assert rc == 0

        # Verify override persisted to disk
        installed = json.loads((registry_base / "installed.json").read_text(encoding="utf-8"))
        assert installed["servers"]["jira"]["overrides"]["env"]["JIRA_TOKEN"] == "real-token"

        # 4. Info --json — verify enriched output with masked overrides
        rc, out, _ = _capture(
            cmd_mcp_info,
            SimpleNamespace(name="jira", output_json=True),
        )
        assert rc == 0
        data = json.loads(out)
        assert data["name"] == "jira"
        assert data["transport"] == "http"
        assert data["manifest_version"] == "1.2.0"
        assert data["overrides"]["env"]["JIRA_TOKEN"] == "<set>"
        assert "real-token" not in out

        # 5. Remove
        rc, out, _ = _capture(
            cmd_mcp_remove,
            SimpleNamespace(name="jira"),
        )
        assert rc == 0
        assert "Removed jira" in out

        # Verify removed from disk
        installed = json.loads((registry_base / "installed.json").read_text(encoding="utf-8"))
        assert "jira" not in installed["servers"]

    finally:
        cli_mod._get_registry = cli_mod_get_registry


# ── list --json masks secrets ────────────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_list_json_masks_override_secrets(registry, sample_index):
    """list --json must not leak actual override values."""
    registry.install("jira")
    registry.set_override("jira", "JIRA_API_TOKEN", "super-secret", override_type="env")

    args = SimpleNamespace(available=False, output_json=True)
    rc, out, _ = _capture(cmd_mcp_list, args)

    assert rc == 0
    assert "super-secret" not in out
    data = json.loads(out)
    assert data[0]["overrides"]["env"]["JIRA_API_TOKEN"] == "<set>"


# ── update preserves enabled state ──────────────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_update_preserves_disabled_state(registry, sample_index):
    """update <name> must not re-enable a disabled server."""
    registry.install("jira")
    registry.disable("jira")
    assert registry.get_server("jira")["enabled"] is False

    args = SimpleNamespace(name="jira")
    rc, out, _ = _capture(cmd_mcp_update, args)

    assert rc == 0
    server = registry.get_server("jira")
    assert server["enabled"] is False


# ── security notice sentinel after success ───────────────────────


@pytest.mark.usefixtures("_patch_get_registry")
def test_security_notice_not_persisted_on_failed_install(registry, registry_home, sample_index):
    """Sentinel must not be written if install fails."""
    sentinel = registry_home / ".security_notice_shown"
    assert not sentinel.exists()

    # Install a server that doesn't exist in the index
    args = SimpleNamespace(name="nonexistent", version=None, transport=None)
    rc, _, _ = _capture(cmd_mcp_install, args)

    assert rc == 1
    assert not sentinel.exists()


@pytest.mark.usefixtures("_patch_get_registry")
def test_security_notice_persisted_on_successful_install(
    registry, registry_home, sample_index, monkeypatch
):
    """Sentinel must be written after a successful install."""
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    sentinel = registry_home / ".security_notice_shown"
    assert not sentinel.exists()

    args = SimpleNamespace(name="jira", version=None, transport=None)
    rc, _, _ = _capture(cmd_mcp_install, args)

    assert rc == 0
    assert sentinel.exists()
