"""Tests for MCPRegistry core module."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from framework.runner.mcp_registry import MCPRegistry

# ── Helpers ──────────────────────────────────────────────────────────


def _write_mock_index(cache_dir: Path, servers: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "registry_index.json").write_text(
        json.dumps({"servers": servers}), encoding="utf-8"
    )


def _setup_registry_with_servers(tmp_path: Path) -> MCPRegistry:
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()

    registry.add_local(name="jira", transport="stdio", command="uvx", args=["jira-mcp"])
    registry.add_local(name="slack", transport="http", url="http://localhost:4020")
    registry.add_local(name="github", transport="http", url="http://localhost:4030")

    data = registry._read_installed()
    data["servers"]["jira"]["manifest"]["tags"] = ["productivity", "pm"]
    data["servers"]["slack"]["manifest"]["tags"] = ["productivity", "messaging"]
    data["servers"]["github"]["manifest"]["tags"] = ["dev"]
    data["servers"]["jira"]["manifest"]["hive"] = {"profiles": ["productivity"]}
    data["servers"]["slack"]["manifest"]["hive"] = {"profiles": ["productivity"]}
    data["servers"]["github"]["manifest"]["hive"] = {"profiles": ["developer"]}
    registry._write_installed(data)
    return registry


# ── Initialization ──────────────────────────────────────────────────


def test_init_creates_directory_structure(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    assert (tmp_path / "mcp_registry" / "config.json").exists()
    assert (tmp_path / "mcp_registry" / "installed.json").exists()
    assert (tmp_path / "mcp_registry" / "cache").is_dir()


def test_init_default_config(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    config = json.loads((tmp_path / "mcp_registry" / "config.json").read_text())
    assert "index_url" in config
    assert "refresh_interval_hours" in config


def test_init_preserves_existing(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    base.mkdir(parents=True)
    (base / "installed.json").write_text(json.dumps({"servers": {"jira": {"enabled": True}}}))
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    assert "jira" in json.loads((base / "installed.json").read_text())["servers"]


# ── add_local ───────────────────────────────────────────────────────


def test_add_local_http(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="my-db", transport="http", url="http://localhost:9090")
    entry = registry._read_installed()["servers"]["my-db"]
    assert entry["source"] == "local"
    assert entry["transport"] == "http"
    assert entry["enabled"] is True


def test_add_local_duplicate_raises(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="my-db", transport="http", url="http://localhost:9090")
    with pytest.raises(ValueError, match="already exists"):
        registry.add_local(name="my-db", transport="http", url="http://localhost:9090")


def test_add_local_stdio(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(
        name="tools",
        transport="stdio",
        command="uvx",
        args=["my-mcp"],
        cwd="/opt/tools",
        description="My tools",
    )
    entry = registry._read_installed()["servers"]["tools"]
    assert entry["manifest"]["stdio"]["command"] == "uvx"
    assert entry["manifest"]["stdio"]["cwd"] == "/opt/tools"
    assert entry["manifest"]["description"] == "My tools"


def test_add_local_unix(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="db", transport="unix", socket_path="/tmp/mcp.sock")
    entry = registry._read_installed()["servers"]["db"]
    assert entry["transport"] == "unix"
    assert entry["manifest"]["unix"]["socket_path"] == "/tmp/mcp.sock"


def test_add_local_sse(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="stream", transport="sse", url="http://localhost:8080/sse")
    entry = registry._read_installed()["servers"]["stream"]
    assert entry["transport"] == "sse"


def test_add_local_stdio_requires_command(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="command is required"):
        registry.add_local(name="x", transport="stdio")


def test_add_local_http_requires_url(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="url is required"):
        registry.add_local(name="x", transport="http")


def test_add_local_unix_requires_socket_path(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="socket_path is required"):
        registry.add_local(name="x", transport="unix")


def test_add_local_unsupported_transport(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="Unsupported transport"):
        registry.add_local(name="x", transport="grpc")


# ── install ─────────────────────────────────────────────────────────


def test_install_from_index(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {
                "name": "jira",
                "version": "1.2.0",
                "transport": {"supported": ["stdio"], "default": "stdio"},
                "stdio": {"command": "uvx", "args": ["jira-mcp-server"]},
            }
        },
    )
    registry.install("jira")
    entry = registry._read_installed()["servers"]["jira"]
    assert entry["source"] == "registry"
    assert entry["transport"] == "stdio"
    assert entry["manifest"]["name"] == "jira"
    assert entry["manifest"]["version"] == "1.2.0"
    assert entry["manifest"]["stdio"]["command"] == "uvx"


def test_install_not_found_raises(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(base / "cache", {})
    with pytest.raises(ValueError, match="not found"):
        registry.install("nonexistent")


def test_install_duplicate_raises(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {
                "name": "jira",
                "version": "1.0.0",
                "transport": {"default": "stdio"},
                "stdio": {"command": "uvx"},
            }
        },
    )
    registry.install("jira")
    with pytest.raises(ValueError, match="already exists"):
        registry.install("jira")


def test_install_version_pin(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {"slack": {"name": "slack", "version": "2.0.0", "transport": {"default": "http"}}},
    )
    registry.install("slack", version="2.0.0")
    entry = registry._read_installed()["servers"]["slack"]
    assert entry["pinned"] is True


def test_install_version_mismatch_raises(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {"jira": {"name": "jira", "version": "1.2.0", "transport": {"default": "stdio"}}},
    )
    with pytest.raises(ValueError, match="Version mismatch"):
        registry.install("jira", version="2.0.0")


# ── remove / enable / disable ──────────────────────────────────────


def test_remove(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="db", transport="http", url="http://localhost:9090")
    registry.remove("db")
    assert "db" not in registry._read_installed()["servers"]


def test_remove_nonexistent_raises(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="not installed"):
        registry.remove("ghost")


def test_enable_disable(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="db", transport="http", url="http://localhost:9090")
    registry.disable("db")
    assert registry._read_installed()["servers"]["db"]["enabled"] is False
    registry.enable("db")
    assert registry._read_installed()["servers"]["db"]["enabled"] is True


# ── list / get / search ─────────────────────────────────────────────


def test_list_installed(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="a", transport="http", url="http://localhost:1")
    registry.add_local(name="b", transport="http", url="http://localhost:2")
    assert len(registry.list_installed()) == 2


def test_get_server(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="jira", transport="http", url="http://localhost:4010")
    assert registry.get_server("jira") is not None
    assert registry.get_server("nonexistent") is None


def test_search_by_name(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {"name": "jira", "description": "Issues", "tags": []},
            "slack": {"name": "slack", "description": "Chat", "tags": []},
        },
    )
    assert len(registry.search("jira")) == 1


def test_search_by_tag(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {"name": "jira", "tags": ["pm"]},
            "linear": {"name": "linear", "tags": ["pm"]},
            "slack": {"name": "slack", "tags": ["chat"]},
        },
    )
    assert len(registry.search("pm")) == 2


def test_search_by_description(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {"name": "jira", "description": "Manage issues", "tags": []},
            "slack": {"name": "slack", "description": "Send messages", "tags": []},
        },
    )
    assert len(registry.search("issues")) == 1


def test_search_by_tool_name(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {"name": "jira", "tags": [], "tools": [{"name": "create_issue"}]},
            "slack": {"name": "slack", "tags": [], "tools": [{"name": "send_message"}]},
        },
    )
    assert len(registry.search("create_issue")) == 1


def test_list_available(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(base / "cache", {"a": {"name": "a"}, "b": {"name": "b"}})
    assert len(registry.list_available()) == 2


# ── set_override ────────────────────────────────────────────────────


def test_set_override_env(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="jira", transport="http", url="http://localhost:4010")
    registry.set_override("jira", "TOKEN", "secret")
    assert registry._read_installed()["servers"]["jira"]["overrides"]["env"]["TOKEN"] == "secret"


def test_set_override_headers(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="jira", transport="http", url="http://localhost:4010")
    registry.set_override("jira", "Authorization", "Bearer x", override_type="headers")
    entry = registry._read_installed()["servers"]["jira"]
    assert entry["overrides"]["headers"]["Authorization"] == "Bearer x"


def test_set_override_invalid_type(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="jira", transport="http", url="http://localhost:4010")
    with pytest.raises(ValueError, match="Invalid override type"):
        registry.set_override("jira", "k", "v", override_type="cookies")


# ── update_index ────────────────────────────────────────────────────


def test_update_index_writes_cache(tmp_path: Path, monkeypatch):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()

    class MockResponse:
        status_code = 200

        def json(self):
            return {"servers": {"jira": {"name": "jira"}}}

        def raise_for_status(self):
            pass

    monkeypatch.setattr("framework.runner.mcp_registry.httpx.get", lambda *a, **kw: MockResponse())
    registry.update_index()
    cached = json.loads((base / "cache" / "registry_index.json").read_text())
    assert "jira" in cached["servers"]
    assert (base / "cache" / "last_fetched").exists()
    assert not (base / "cache" / "last_fetched.json").exists()


def test_update_index_network_error(tmp_path: Path, monkeypatch):
    import httpx as _httpx

    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    monkeypatch.setattr(
        "framework.runner.mcp_registry.httpx.get",
        lambda *a, **kw: (_ for _ in ()).throw(_httpx.ConnectError("fail")),
    )
    with pytest.raises(_httpx.ConnectError):
        registry.update_index()


# ── is_index_stale ──────────────────────────────────────────────────


def test_is_index_stale_no_cache(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    assert registry.is_index_stale() is True


def test_is_index_stale_fresh(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    MCPRegistry._write_json(
        base / "cache" / "last_fetched",
        {"timestamp": datetime.now(UTC).isoformat()},
    )
    assert registry.is_index_stale() is False


def test_is_index_stale_expired(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    old = datetime.now(UTC) - timedelta(hours=48)
    MCPRegistry._write_json(
        base / "cache" / "last_fetched",
        {"timestamp": old.isoformat()},
    )
    assert registry.is_index_stale() is True


def test_is_index_stale_supports_legacy_filename(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    MCPRegistry._write_json(
        base / "cache" / "last_fetched.json",
        {"timestamp": datetime.now(UTC).isoformat()},
    )
    assert registry.is_index_stale() is False


def test_is_index_stale_missing_timestamp_returns_true(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    MCPRegistry._write_json(base / "cache" / "last_fetched", {"bad": "data"})
    assert registry.is_index_stale() is True


# ── resolve_for_agent ───────────────────────────────────────────────


def test_resolve_include(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    configs = registry.resolve_for_agent(include=["jira", "slack"])
    assert [c.name for c in configs] == ["jira", "slack"]


def test_resolve_exclude(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    configs = registry.resolve_for_agent(include=["jira", "slack", "github"], exclude=["github"])
    assert "github" not in [c.name for c in configs]


def test_resolve_tags(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    configs = registry.resolve_for_agent(tags=["productivity"])
    names = [c.name for c in configs]
    assert "jira" in names and "slack" in names and "github" not in names


def test_resolve_profile(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    configs = registry.resolve_for_agent(profile="productivity")
    names = [c.name for c in configs]
    assert "jira" in names and "slack" in names


def test_resolve_profile_all(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    assert len(registry.resolve_for_agent(profile="all")) == 3


def test_resolve_max_tools(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    data = registry._read_installed()
    data["servers"]["jira"]["manifest"]["tools"] = [{"name": "a"}, {"name": "b"}]
    data["servers"]["slack"]["manifest"]["tools"] = [{"name": "c"}, {"name": "d"}]
    data["servers"]["github"]["manifest"]["tools"] = [{"name": "e"}]
    registry._write_installed(data)
    configs = registry.resolve_for_agent(profile="all", max_tools=3)
    total = sum(
        len(registry._read_installed()["servers"][c.name]["manifest"].get("tools", []))
        for c in configs
    )
    assert total <= 3 and len(configs) >= 1


def test_resolve_skips_disabled(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    registry.disable("jira")
    configs = registry.resolve_for_agent(include=["jira", "slack"])
    assert "jira" not in [c.name for c in configs]


def test_resolve_missing_server_warns(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    assert len(registry.resolve_for_agent(include=["jira", "ghost"])) == 1


def test_resolve_versions_match(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {
                "name": "jira",
                "version": "1.2.0",
                "transport": {"default": "stdio"},
                "stdio": {"command": "uvx"},
            }
        },
    )
    registry.install("jira")
    assert len(registry.resolve_for_agent(include=["jira"], versions={"jira": "1.2.0"})) == 1
    assert len(registry.resolve_for_agent(include=["jira"], versions={"jira": "9.9.9"})) == 0


# ── _manifest_to_server_config ──────────────────────────────────────


def test_config_merges_env(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="t", transport="stdio", command="uvx", env={"A": "1"})
    registry.set_override("t", "B", "2")
    configs = registry.resolve_for_agent(include=["t"])
    assert configs[0].env["A"] == "1" and configs[0].env["B"] == "2"


def test_config_overrides_win(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="t", transport="stdio", command="uvx", env={"K": "old"})
    registry.set_override("t", "K", "new")
    assert registry.resolve_for_agent(include=["t"])[0].env["K"] == "new"


def test_config_includes_cwd(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="t", transport="stdio", command="uvx", cwd="/opt")
    assert registry.resolve_for_agent(include=["t"])[0].cwd == "/opt"


def test_config_includes_description(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="t", transport="stdio", command="uvx", description="desc")
    assert registry.resolve_for_agent(include=["t"])[0].description == "desc"


def test_config_unix_transport(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="u", transport="unix", socket_path="/tmp/s.sock")
    c = registry.resolve_for_agent(include=["u"])[0]
    assert c.transport == "unix" and c.socket_path == "/tmp/s.sock"


def test_config_unsupported_transport_returns_none(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    data = registry._read_installed()
    data["servers"]["x"] = {
        "source": "local",
        "transport": "grpc",
        "enabled": True,
        "manifest": {"name": "x", "transport": {"default": "grpc"}},
        "overrides": {"env": {}, "headers": {}},
    }
    registry._write_installed(data)
    assert len(registry.resolve_for_agent(include=["x"])) == 0


# ── _server_config_to_dict ──────────────────────────────────────────


def test_server_config_to_dict(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="t", transport="stdio", command="uvx", cwd="/opt", description="d")
    config = registry.resolve_for_agent(include=["t"])[0]
    d = MCPRegistry._server_config_to_dict(config)
    assert d["name"] == "t" and d["transport"] == "stdio"
    assert d["cwd"] == "/opt" and d["description"] == "d"


# ── load_agent_selection ────────────────────────────────────────────


def test_load_agent_selection(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "mcp_registry.json").write_text(json.dumps({"include": ["jira", "slack"]}))
    dicts = registry.load_agent_selection(agent_dir)
    assert len(dicts) == 2 and all("transport" in d for d in dicts)


def test_load_agent_selection_no_file(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    assert registry.load_agent_selection(agent_dir) == []


@pytest.mark.parametrize(
    "field, bad_value",
    [
        ("include", "jira"),
        ("tags", "pm"),
        ("exclude", "jira"),
        ("profile", ["all"]),
        ("max_tools", "50"),
        ("versions", ["1.0.0"]),
    ],
)
def test_load_agent_selection_rejects_wrong_types(tmp_path: Path, field, bad_value):
    """Fields with wrong JSON types are dropped with a warning, not silently misused."""
    registry = _setup_registry_with_servers(tmp_path)
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "mcp_registry.json").write_text(json.dumps({field: bad_value}))
    configs = registry.load_agent_selection(agent_dir)
    # All bad fields are dropped, so resolve_for_agent gets no criteria and returns []
    assert configs == []


# ── run_health_check ────────────────────────────────────────────────


def test_run_health_check_healthy(tmp_path: Path, monkeypatch):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="db", transport="http", url="http://localhost:9090")

    class MockClient:
        def __init__(self, config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def list_tools(self):
            return []

    monkeypatch.setattr("framework.runner.mcp_registry.MCPClient", MockClient)
    result = registry.run_health_check("db")
    assert result["status"] == "healthy"
    assert registry._read_installed()["servers"]["db"]["last_health_check_at"] is not None


def test_health_check_public_api(tmp_path: Path, monkeypatch):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="db", transport="http", url="http://localhost:9090")

    class MockClient:
        def __init__(self, config):
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def list_tools(self):
            return []

    monkeypatch.setattr("framework.runner.mcp_registry.MCPClient", MockClient)
    result = registry.health_check("db")
    assert result["status"] == "healthy"


def test_health_check_prefers_pooled_connection(tmp_path: Path, monkeypatch):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="db", transport="http", url="http://localhost:9090")

    class FakePooledClient:
        def list_tools(self):
            return [object(), object()]

    class FakeManager:
        def __init__(self):
            self.acquire_calls = 0
            self.release_calls = 0

        def has_connection(self, server_name: str) -> bool:
            return server_name == "db"

        def health_check(self, server_name: str) -> bool:
            return server_name == "db"

        def acquire(self, config):
            self.acquire_calls += 1
            return FakePooledClient()

        def release(self, server_name: str) -> None:
            self.release_calls += 1

    fake_manager = FakeManager()
    monkeypatch.setattr(
        "framework.runner.mcp_registry.MCPConnectionManager.get_instance",
        lambda: fake_manager,
    )

    class UnexpectedClient:
        def __init__(self, config):
            raise AssertionError("fresh MCPClient should not be constructed")

    monkeypatch.setattr("framework.runner.mcp_registry.MCPClient", UnexpectedClient)

    result = registry.health_check("db")
    assert result["status"] == "healthy"
    assert result["tools"] == 2
    assert fake_manager.acquire_calls == 1
    assert fake_manager.release_calls == 1


def test_health_check_uses_installed_transport_preference(tmp_path: Path, monkeypatch):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(
        name="api",
        manifest={
            "transport": {"supported": ["stdio", "http"], "default": "stdio"},
            "stdio": {"command": "uvx", "args": ["legacy-server"]},
            "http": {"url": "http://localhost:9001"},
        },
        transport="http",
    )

    seen_transport: list[str] = []

    class MockClient:
        def __init__(self, config):
            seen_transport.append(config.transport)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def list_tools(self):
            return []

    monkeypatch.setattr("framework.runner.mcp_registry.MCPClient", MockClient)
    result = registry.health_check("api")
    assert result["status"] == "healthy"
    assert seen_transport == ["http"]


def test_run_health_check_unhealthy(tmp_path: Path, monkeypatch):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="db", transport="http", url="http://localhost:9999")

    class MockClient:
        def __init__(self, config):
            pass

        def __enter__(self):
            raise ConnectionError("refused")

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("framework.runner.mcp_registry.MCPClient", MockClient)
    result = registry.run_health_check("db")
    assert result["status"] == "unhealthy"
    assert "refused" in result["error"]


def test_run_health_check_list_tools_failure(tmp_path: Path, monkeypatch):
    """Health check where connect succeeds but list_tools fails."""
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="db", transport="http", url="http://localhost:9090")

    class MockClient:
        def __init__(self, config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def list_tools(self):
            raise RuntimeError("tools discovery failed")

    monkeypatch.setattr("framework.runner.mcp_registry.MCPClient", MockClient)
    result = registry.run_health_check("db")
    assert result["status"] == "unhealthy"
    assert "tools discovery failed" in result["error"]


def test_run_health_check_unsupported_transport(tmp_path: Path):
    """Health check on server with unsupported transport returns unhealthy."""
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    data = registry._read_installed()
    data["servers"]["weird"] = {
        "source": "local",
        "transport": "grpc",
        "enabled": True,
        "manifest": {"name": "weird", "transport": {"default": "grpc"}},
        "overrides": {"env": {}, "headers": {}},
        "last_health_check_at": None,
        "last_health_status": None,
        "last_error": None,
        "last_used_at": None,
        "last_validated_with_hive_version": None,
    }
    registry._write_installed(data)
    result = registry.run_health_check("weird")
    assert result["status"] == "unhealthy"
    assert "Unsupported transport" in result["error"]


def test_run_health_check_not_installed(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="not installed"):
        registry.run_health_check("ghost")


def test_resolve_for_agent_no_criteria(tmp_path: Path):
    """resolve_for_agent with no criteria returns empty list."""
    registry = _setup_registry_with_servers(tmp_path)
    configs = registry.resolve_for_agent()
    assert configs == []


def test_install_version_pin_no_version_in_manifest(tmp_path: Path):
    """install with version should fail if manifest has no version field."""
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache", {"noversion": {"name": "noversion", "transport": {"default": "stdio"}}}
    )
    with pytest.raises(ValueError, match="no version field"):
        registry.install("noversion", version="1.0.0")


# ── Scope gap fixes ─────────────────────────────────────────────────


def test_add_local_with_inline_manifest(tmp_path: Path):
    """add_local with manifest dict should register the server directly."""
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()

    manifest = {
        "description": "Custom Jira server",
        "transport": {"supported": ["stdio"], "default": "stdio"},
        "stdio": {"command": "uvx", "args": ["jira-mcp"], "env": {"TOKEN": "abc"}},
        "tags": ["pm"],
    }
    registry.add_local(name="jira", manifest=manifest)

    entry = registry._read_installed()["servers"]["jira"]
    assert entry["source"] == "local"
    assert entry["transport"] == "stdio"
    assert entry["manifest"]["stdio"]["command"] == "uvx"
    assert entry["manifest"]["tags"] == ["pm"]
    assert entry["manifest"]["name"] == "jira"


def test_add_local_manifest_without_transport_defaults(tmp_path: Path):
    """add_local with manifest but no transport key should default to stdio."""
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()

    manifest = {"stdio": {"command": "echo"}}
    registry.add_local(name="simple", manifest=manifest)

    entry = registry._read_installed()["servers"]["simple"]
    assert entry["transport"] == "stdio"


def test_add_local_requires_transport_without_manifest(tmp_path: Path):
    """add_local without manifest or transport should raise."""
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="transport is required"):
        registry.add_local(name="broken")


def test_install_with_transport_override(tmp_path: Path):
    """install with transport should override the manifest default."""
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {
                "name": "jira",
                "version": "1.0.0",
                "transport": {"supported": ["stdio", "http"], "default": "stdio"},
                "stdio": {"command": "uvx"},
                "http": {"url": "http://localhost:4010"},
            }
        },
    )

    registry.install("jira", transport="http")
    entry = registry._read_installed()["servers"]["jira"]
    assert entry["transport"] == "http"
    config = registry.resolve_for_agent(include=["jira"])[0]
    assert config.transport == "http"
    assert config.url == "http://localhost:4010"


def test_install_with_unsupported_transport_raises(tmp_path: Path):
    """install with transport not in supported list should raise."""
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {
                "name": "jira",
                "version": "1.0.0",
                "transport": {"supported": ["stdio"], "default": "stdio"},
            }
        },
    )

    with pytest.raises(ValueError, match="not supported"):
        registry.install("jira", transport="http")


def test_install_registry_entry_uses_updated_cached_manifest(tmp_path: Path):
    """Registry installs should resolve via the current cached index."""
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {
                "name": "jira",
                "version": "1.0.0",
                "transport": {"supported": ["stdio"], "default": "stdio"},
                "stdio": {"command": "uvx", "args": ["jira-v1"]},
            }
        },
    )

    registry.install("jira")

    _write_mock_index(
        base / "cache",
        {
            "jira": {
                "name": "jira",
                "version": "1.1.0",
                "transport": {"supported": ["stdio"], "default": "stdio"},
                "stdio": {"command": "uvx", "args": ["jira-v2"]},
            }
        },
    )

    config = registry.resolve_for_agent(include=["jira"])[0]
    assert config.transport == "stdio"
    assert config.args == ["jira-v2"]


def test_install_registry_entry_resolves_without_cache(tmp_path: Path):
    """Registry installs should remain usable even when the cache is missing."""
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {
                "name": "jira",
                "version": "1.0.0",
                "transport": {"supported": ["stdio"], "default": "stdio"},
                "stdio": {"command": "uvx", "args": ["jira-mcp"]},
            }
        },
    )

    registry.install("jira")
    (base / "cache" / "registry_index.json").unlink()

    config = registry.resolve_for_agent(include=["jira"])[0]
    assert config.transport == "stdio"
    assert config.command == "uvx"
    assert config.args == ["jira-mcp"]


def test_run_health_check_all_servers(tmp_path: Path, monkeypatch):
    """run_health_check with no name should check all servers."""
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    registry.add_local(name="a", transport="http", url="http://localhost:1")
    registry.add_local(name="b", transport="http", url="http://localhost:2")

    class MockClient:
        def __init__(self, config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def list_tools(self):
            return []

    monkeypatch.setattr("framework.runner.mcp_registry.MCPClient", MockClient)

    results = registry.run_health_check()
    assert isinstance(results, dict)
    assert "a" in results
    assert "b" in results
    assert results["a"]["status"] == "healthy"
    assert results["b"]["status"] == "healthy"


# ── Edge case coverage ──────────────────────────────────────────────


def test_add_local_sse_requires_url(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="url is required"):
        registry.add_local(name="x", transport="sse")


def test_enable_nonexistent_raises(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="not installed"):
        registry.enable("ghost")


def test_disable_nonexistent_raises(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="not installed"):
        registry.disable("ghost")


def test_list_installed_empty(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    assert registry.list_installed() == []


def test_list_available_empty_index(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    assert registry.list_available() == []


def test_set_override_nonexistent_raises(tmp_path: Path):
    registry = MCPRegistry(base_path=tmp_path / "mcp_registry")
    registry.initialize()
    with pytest.raises(ValueError, match="not installed"):
        registry.set_override("ghost", "KEY", "val")


def test_search_no_results(tmp_path: Path):
    base = tmp_path / "mcp_registry"
    registry = MCPRegistry(base_path=base)
    registry.initialize()
    _write_mock_index(
        base / "cache",
        {
            "jira": {"name": "jira", "description": "Issues", "tags": []},
        },
    )
    assert registry.search("nonexistent_query_xyz") == []


def test_resolve_profile_matches_nothing(tmp_path: Path):
    registry = _setup_registry_with_servers(tmp_path)
    configs = registry.resolve_for_agent(profile="nonexistent_profile")
    assert configs == []


# ── _get_hive_version ────────────────────────────────────────────────


def test_get_hive_version_section_aware(tmp_path: Path, monkeypatch):
    """Version must come from [project], not from a [tool.*] section."""
    from importlib.metadata import PackageNotFoundError

    import framework.runner.mcp_registry as mod

    # Create directory structure so parents[2] of fake file -> tmp_path
    runner_dir = tmp_path / "framework" / "runner"
    runner_dir.mkdir(parents=True)
    fake_file = runner_dir / "mcp_registry.py"
    fake_file.touch()

    # Put version in [tool.*] before [project] to trigger the old bug
    toml_content = (
        '[tool.something]\nversion = "9.9.9"\n\n[project]\nname = "framework"\nversion = "0.7.1"\n'
    )
    (tmp_path / "pyproject.toml").write_text(toml_content, encoding="utf-8")

    monkeypatch.setattr(
        "framework.runner.mcp_registry.version",
        lambda _pkg: (_ for _ in ()).throw(PackageNotFoundError()),
    )
    monkeypatch.setattr(mod, "__file__", str(fake_file))

    assert MCPRegistry._get_hive_version() == "0.7.1"


def test_get_hive_version_missing_toml(tmp_path: Path, monkeypatch):
    """Returns 'unknown' when pyproject.toml does not exist."""
    from importlib.metadata import PackageNotFoundError

    import framework.runner.mcp_registry as mod

    runner_dir = tmp_path / "framework" / "runner"
    runner_dir.mkdir(parents=True)
    fake_file = runner_dir / "mcp_registry.py"
    fake_file.touch()

    monkeypatch.setattr(
        "framework.runner.mcp_registry.version",
        lambda _pkg: (_ for _ in ()).throw(PackageNotFoundError()),
    )
    monkeypatch.setattr(mod, "__file__", str(fake_file))

    assert MCPRegistry._get_hive_version() == "unknown"
