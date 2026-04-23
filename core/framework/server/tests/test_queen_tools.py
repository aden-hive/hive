"""Tests for the per-queen MCP tool allowlist filter + routes.

Covers:
1. QueenPhaseState filter semantics (default-allow, allowlist, empty, phase-
   isolation, memo identity for LLM prompt-cache stability).
2. routes_queen_tools round trip (GET, PATCH, validation, live-session
   hot-reload).

Route tests monkey-patch a tiny queen profile + manager catalog; they never
spawn an MCP subprocess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from framework.llm.provider import Tool
from framework.server import routes_queen_tools
from framework.tools.queen_lifecycle_tools import QueenPhaseState

# ---------------------------------------------------------------------------
# QueenPhaseState filter — pure unit tests
# ---------------------------------------------------------------------------


def _tool(name: str) -> Tool:
    return Tool(name=name, description=f"desc of {name}", parameters={"type": "object"})


class TestPhaseStateFilter:
    def test_default_allow_returns_every_tool(self):
        ps = QueenPhaseState(phase="independent")
        ps.independent_tools = [_tool("mcp_a"), _tool("mcp_b"), _tool("lc_c")]
        ps.mcp_tool_names_all = {"mcp_a", "mcp_b"}
        ps.enabled_mcp_tools = None
        ps.rebuild_independent_filter()

        names = [t.name for t in ps.get_current_tools()]
        assert names == ["mcp_a", "mcp_b", "lc_c"]

    def test_allowlist_keeps_listed_mcp_plus_all_lifecycle(self):
        ps = QueenPhaseState(phase="independent")
        ps.independent_tools = [_tool("mcp_a"), _tool("mcp_b"), _tool("lc_c")]
        ps.mcp_tool_names_all = {"mcp_a", "mcp_b"}
        ps.enabled_mcp_tools = ["mcp_a"]
        ps.rebuild_independent_filter()

        names = [t.name for t in ps.get_current_tools()]
        assert names == ["mcp_a", "lc_c"]

    def test_empty_allowlist_keeps_only_lifecycle(self):
        ps = QueenPhaseState(phase="independent")
        ps.independent_tools = [_tool("mcp_a"), _tool("mcp_b"), _tool("lc_c")]
        ps.mcp_tool_names_all = {"mcp_a", "mcp_b"}
        ps.enabled_mcp_tools = []
        ps.rebuild_independent_filter()

        names = [t.name for t in ps.get_current_tools()]
        assert names == ["lc_c"]

    def test_filter_isolated_to_independent_phase(self):
        ps = QueenPhaseState(phase="independent")
        ps.independent_tools = [_tool("mcp_a"), _tool("lc_c")]
        ps.working_tools = [_tool("mcp_a"), _tool("lc_c")]
        ps.mcp_tool_names_all = {"mcp_a"}
        ps.enabled_mcp_tools = []
        ps.rebuild_independent_filter()

        # Independent → filtered
        assert [t.name for t in ps.get_current_tools()] == ["lc_c"]

        # Other phases → unaffected
        ps.phase = "working"
        assert [t.name for t in ps.get_current_tools()] == ["mcp_a", "lc_c"]

    def test_memo_returns_stable_identity_for_prompt_cache(self):
        """Same Python list object across turns → LLM prompt cache stays warm."""
        ps = QueenPhaseState(phase="independent")
        ps.independent_tools = [_tool("mcp_a"), _tool("lc_c")]
        ps.mcp_tool_names_all = {"mcp_a"}
        ps.enabled_mcp_tools = None
        ps.rebuild_independent_filter()

        first = ps.get_current_tools()
        second = ps.get_current_tools()
        assert first is second, "memoized list must be the same object across turns"

        # A rebuild should produce a different object so downstream caches
        # correctly invalidate.
        ps.enabled_mcp_tools = ["mcp_a"]
        ps.rebuild_independent_filter()
        third = ps.get_current_tools()
        assert third is not first
        assert [t.name for t in third] == ["mcp_a", "lc_c"]


# ---------------------------------------------------------------------------
# Route round-trip tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeSession:
    queen_name: str
    phase_state: QueenPhaseState
    colony_runtime: Any = None
    id: str = "sess-1"
    _queen_tool_registry: Any = None


@dataclass
class _FakeManager:
    _sessions: dict = field(default_factory=dict)
    _mcp_tool_catalog: dict = field(default_factory=dict)


@pytest.fixture
def queen_dir(tmp_path, monkeypatch):
    """Redirect queen profile + tools storage into a tmp dir."""
    queens_dir = tmp_path / "queens"
    queens_dir.mkdir()
    monkeypatch.setattr("framework.agents.queen.queen_profiles.QUEENS_DIR", queens_dir)
    monkeypatch.setattr("framework.agents.queen.queen_tools_config.QUEENS_DIR", queens_dir)

    queen_id = "queen_technology"
    (queens_dir / queen_id).mkdir()
    (queens_dir / queen_id / "profile.yaml").write_text(
        yaml.safe_dump({"name": "Alexandra", "title": "Head of Technology"})
    )
    return queens_dir, queen_id


async def _make_app(*, manager: _FakeManager) -> web.Application:
    app = web.Application()
    app["manager"] = manager
    routes_queen_tools.register_routes(app)
    return app


@pytest.mark.asyncio
async def test_get_tools_default_allows_everything_for_unknown_queen(queen_dir, monkeypatch):
    """Queens NOT in the role-default table fall back to allow-all."""
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)

    queens_dir, _ = queen_dir
    # Use a queen id that isn't in QUEEN_DEFAULT_CATEGORIES so we exercise
    # the fallback-to-allow-all path.
    custom_id = "queen_custom_unknown"
    (queens_dir / custom_id).mkdir()
    (queens_dir / custom_id / "profile.yaml").write_text(yaml.safe_dump({"name": "Custom", "title": "Custom Role"}))

    manager = _FakeManager()
    manager._mcp_tool_catalog = {
        "coder-tools": [
            {"name": "read_file", "description": "read", "input_schema": {}},
            {"name": "write_file", "description": "write", "input_schema": {}},
        ],
    }

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(f"/api/queen/{custom_id}/tools")
        assert resp.status == 200
        body = await resp.json()

    assert body["enabled_mcp_tools"] is None
    assert body["is_role_default"] is True  # no sidecar → default-allow
    assert body["stale"] is False
    servers = {s["name"]: s for s in body["mcp_servers"]}
    assert set(servers) == {"coder-tools"}
    for tool in servers["coder-tools"]["tools"]:
        assert tool["enabled"] is True


@pytest.mark.asyncio
async def test_get_tools_applies_role_default(queen_dir, monkeypatch):
    """Known persona queens get their role-based default allowlist."""
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)
    _, queen_id = queen_dir  # queen_technology — has a role default

    manager = _FakeManager()
    # Seed a catalog covering tools the role default references so the
    # response reflects what the queen would actually see on boot.
    manager._mcp_tool_catalog = {
        "coder-tools": [
            {"name": "read_file", "description": "", "input_schema": {}},
            {"name": "port_scan", "description": "", "input_schema": {}},  # security
            {"name": "excel_read", "description": "", "input_schema": {}},  # data
            {"name": "fluffy_unknown_tool", "description": "", "input_schema": {}},
        ],
    }

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(f"/api/queen/{queen_id}/tools")
        assert resp.status == 200
        body = await resp.json()

    # queen_technology's role default includes file_read, data, security, etc.
    assert body["is_role_default"] is True
    enabled = set(body["enabled_mcp_tools"] or [])
    assert "read_file" in enabled
    assert "port_scan" in enabled  # technology role includes security
    assert "excel_read" in enabled
    # Tools not in any category (and not in a @server: expansion target
    # the role references) are NOT part of the default.
    assert "fluffy_unknown_tool" not in enabled


def test_resolve_queen_default_tools_expands_server_shorthand():
    """@server:NAME shorthand expands against the provided catalog."""
    from framework.agents.queen.queen_tools_defaults import resolve_queen_default_tools

    catalog = {
        "gcu-tools": [
            {"name": "browser_navigate"},
            {"name": "browser_click"},
        ],
    }
    # queen_brand_design uses "browser" category → expands via @server:gcu-tools.
    result = resolve_queen_default_tools("queen_brand_design", catalog)
    assert result is not None
    assert "browser_navigate" in result
    assert "browser_click" in result


def test_resolve_queen_default_tools_unknown_queen_returns_none():
    from framework.agents.queen.queen_tools_defaults import resolve_queen_default_tools

    assert resolve_queen_default_tools("queen_made_up", {}) is None


@pytest.mark.asyncio
async def test_patch_persists_and_validates(queen_dir, monkeypatch):
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)
    queens_dir, queen_id = queen_dir

    manager = _FakeManager()
    manager._mcp_tool_catalog = {
        "coder-tools": [
            {"name": "read_file", "description": "", "input_schema": {}},
            {"name": "write_file", "description": "", "input_schema": {}},
        ]
    }

    app = await _make_app(manager=manager)
    tools_path = queens_dir / queen_id / "tools.json"
    profile_path = queens_dir / queen_id / "profile.yaml"

    async with TestClient(TestServer(app)) as client:
        # Happy path
        resp = await client.patch(
            f"/api/queen/{queen_id}/tools",
            json={"enabled_mcp_tools": ["read_file"]},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["enabled_mcp_tools"] == ["read_file"]

        # Sidecar persisted; profile YAML untouched by tools PATCH
        sidecar = json.loads(tools_path.read_text())
        assert sidecar["enabled_mcp_tools"] == ["read_file"]
        assert "updated_at" in sidecar
        profile = yaml.safe_load(profile_path.read_text())
        assert "enabled_mcp_tools" not in profile

        # GET reflects the new state
        resp = await client.get(f"/api/queen/{queen_id}/tools")
        body = await resp.json()
        assert body["is_role_default"] is False  # user has explicitly saved
        servers = {t["name"]: t for t in body["mcp_servers"][0]["tools"]}
        assert servers["read_file"]["enabled"] is True
        assert servers["write_file"]["enabled"] is False

        # Null resets
        resp = await client.patch(f"/api/queen/{queen_id}/tools", json={"enabled_mcp_tools": None})
        assert resp.status == 200
        body = await resp.json()
        assert body["enabled_mcp_tools"] is None
        sidecar = json.loads(tools_path.read_text())
        assert sidecar["enabled_mcp_tools"] is None

        # Unknown tool name → 400; sidecar unchanged
        resp = await client.patch(
            f"/api/queen/{queen_id}/tools",
            json={"enabled_mcp_tools": ["nope_not_a_tool"]},
        )
        assert resp.status == 400
        detail = await resp.json()
        assert "nope_not_a_tool" in detail.get("unknown", [])
        sidecar = json.loads(tools_path.read_text())
        assert sidecar["enabled_mcp_tools"] is None


@pytest.mark.asyncio
async def test_patch_hot_reloads_live_session(queen_dir, monkeypatch):
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)
    _, queen_id = queen_dir

    # Build a fake live session whose phase state carries a tool list the
    # filter can gate. We also need a fake registry so
    # _catalog_from_live_session can enumerate tools.
    class _FakeRegistry:
        def __init__(self, server_map, tools_by_name):
            self._mcp_server_tools = server_map
            self._tools_by_name = tools_by_name

        def get_tools(self):
            return {n: MagicMock(name=n) for n in self._tools_by_name}

    tools_by_name = {"read_file": _tool("read_file"), "write_file": _tool("write_file")}
    registry = _FakeRegistry(
        server_map={"coder-tools": {"read_file", "write_file"}},
        tools_by_name=tools_by_name,
    )
    # Patch get_tools to return real Tool objects for name/description plumbing.
    registry.get_tools = lambda: tools_by_name  # type: ignore[method-assign]

    phase_state = QueenPhaseState(phase="independent")
    phase_state.independent_tools = [tools_by_name["read_file"], tools_by_name["write_file"]]
    phase_state.mcp_tool_names_all = {"read_file", "write_file"}
    phase_state.enabled_mcp_tools = None
    phase_state.rebuild_independent_filter()

    session = _FakeSession(queen_name=queen_id, phase_state=phase_state)
    session._queen_tool_registry = registry
    manager = _FakeManager(_sessions={"sess-1": session})

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        resp = await client.patch(
            f"/api/queen/{queen_id}/tools",
            json={"enabled_mcp_tools": ["read_file"]},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["refreshed_sessions"] == 1

    # Session's phase state reflects the new allowlist without a restart
    current = phase_state.get_current_tools()
    assert [t.name for t in current] == ["read_file"]


@pytest.mark.asyncio
async def test_missing_queen_returns_404(queen_dir, monkeypatch):
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)
    manager = _FakeManager()

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/queen/queen_nonexistent/tools")
        assert resp.status == 404

        resp = await client.patch(
            "/api/queen/queen_nonexistent/tools",
            json={"enabled_mcp_tools": None},
        )
        assert resp.status == 404


@pytest.mark.asyncio
async def test_delete_restores_role_default(queen_dir, monkeypatch):
    """DELETE removes tools.json so the queen falls back to the role default."""
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)
    queens_dir, queen_id = queen_dir
    tools_path = queens_dir / queen_id / "tools.json"

    manager = _FakeManager()
    manager._mcp_tool_catalog = {
        "coder-tools": [
            {"name": "read_file", "description": "", "input_schema": {}},
            {"name": "port_scan", "description": "", "input_schema": {}},
        ],
    }

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        # Seed a custom allowlist first so we have a sidecar to delete.
        resp = await client.patch(
            f"/api/queen/{queen_id}/tools",
            json={"enabled_mcp_tools": ["read_file"]},
        )
        assert resp.status == 200
        assert tools_path.exists()

        resp = await client.delete(f"/api/queen/{queen_id}/tools")
        assert resp.status == 200
        body = await resp.json()
        assert body["removed"] is True
        assert body["is_role_default"] is True
        assert not tools_path.exists()

        # The new effective list is the role default for queen_technology,
        # which includes both read_file (file_read) and port_scan (security).
        enabled = set(body["enabled_mcp_tools"] or [])
        assert "read_file" in enabled
        assert "port_scan" in enabled

        # GET confirms.
        resp = await client.get(f"/api/queen/{queen_id}/tools")
        body = await resp.json()
        assert body["is_role_default"] is True

        # Deleting again is a no-op.
        resp = await client.delete(f"/api/queen/{queen_id}/tools")
        assert resp.status == 200
        assert (await resp.json())["removed"] is False


def test_legacy_profile_field_migrates_to_sidecar(queen_dir):
    """A legacy enabled_mcp_tools field in profile.yaml is hoisted to tools.json."""
    queens_dir, queen_id = queen_dir
    profile_path = queens_dir / queen_id / "profile.yaml"
    tools_path = queens_dir / queen_id / "tools.json"

    # Seed legacy field in profile.yaml.
    profile = yaml.safe_load(profile_path.read_text()) or {}
    profile["enabled_mcp_tools"] = ["read_file", "write_file"]
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False))

    from framework.agents.queen.queen_tools_config import load_queen_tools_config

    # First load migrates.
    assert load_queen_tools_config(queen_id) == ["read_file", "write_file"]
    assert tools_path.exists()
    sidecar = json.loads(tools_path.read_text())
    assert sidecar["enabled_mcp_tools"] == ["read_file", "write_file"]

    # profile.yaml no longer contains the field; other fields preserved.
    migrated_profile = yaml.safe_load(profile_path.read_text())
    assert "enabled_mcp_tools" not in migrated_profile
    assert migrated_profile["name"] == "Alexandra"

    # Second load is a direct read — no migration work to do.
    assert load_queen_tools_config(queen_id) == ["read_file", "write_file"]
