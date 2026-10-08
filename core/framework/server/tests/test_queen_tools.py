"""Tests for the per-queen MCP tool allowlist filter + routes.

Covers:
1. QueenPhaseState filter semantics (default-allow, allowlist, empty, all-
   phase MCP filtering, memo identity for LLM prompt-cache stability).
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

    def test_allowlist_applies_to_mcp_tools_in_every_phase(self):
        ps = QueenPhaseState(phase="independent")
        ps.independent_tools = [_tool("mcp_a"), _tool("lc_c")]
        ps.colony_tools = [_tool("mcp_a"), _tool("lc_colony")]
        ps.mcp_tool_names_all = {"mcp_a"}
        ps.enabled_mcp_tools = []
        ps.rebuild_independent_filter()

        assert [t.name for t in ps.get_current_tools()] == ["lc_c"]

        ps.phase = "colony"
        assert [t.name for t in ps.get_current_tools()] == ["lc_colony"]

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

    def test_suggest_colony_gated_to_independent_phase(self):
        """``suggest_colony`` (synthetic, framework-handled) must surface
        only in the independent phase. The queen orchestrator wires it
        into ``independent_tools``; on switch to colony the
        ``dynamic_tools_provider`` (== get_current_tools) must drop it
        so the LLM no longer sees the tool.
        """
        from framework.agent_loop.internals.synthetic_tools import (
            build_suggest_colony_tool,
        )

        ps = QueenPhaseState(phase="independent")
        ps.independent_tools = [_tool("read_file"), build_suggest_colony_tool()]
        ps.colony_tools = [_tool("read_file"), _tool("run_worker")]
        ps.mcp_tool_names_all = set()
        ps.enabled_mcp_tools = None
        ps.rebuild_independent_filter()

        # Independent phase: tool must be present.
        names = [t.name for t in ps.get_current_tools()]
        assert "suggest_colony" in names, names

        # Colony phase: tool must be absent. This is what stops the LLM
        # from emitting a fork suggestion while already inside a colony.
        ps.phase = "colony"
        names = [t.name for t in ps.get_current_tools()]
        assert "suggest_colony" not in names, names
        assert "run_worker" in names, names

        # And switching back restores it.
        ps.phase = "independent"
        names = [t.name for t in ps.get_current_tools()]
        assert "suggest_colony" in names, names


class TestAlwaysEnabledSearchableSplit:
    """The always-enabled / searchable tier split + on-demand loading.

    Intent: a queen boots with a small global eager toolset; every other MCP
    tool it is allowed to use is searchable (manifest-only) until loaded via
    search_tools, and loads survive a session restart. Always-enabled tools
    are granted unconditionally — the allowlist cannot disable them.
    """

    def _ps(self, **kw):
        ps = QueenPhaseState(phase="independent")
        ps.independent_tools = [_tool("read_file"), _tool("gmail_send"), _tool("notion_search"), _tool("lc_task")]
        ps.mcp_tool_names_all = {"read_file", "gmail_send", "notion_search"}
        ps.always_enabled_names = {"read_file"}
        for k, v in kw.items():
            setattr(ps, k, v)
        ps.rebuild_independent_filter()
        return ps

    def test_only_always_enabled_and_lifecycle_are_eager(self):
        ps = self._ps(enabled_mcp_tools=None)  # allow-all
        # Eager = always-enabled MCP (read_file) + non-MCP lifecycle (lc_task).
        assert [t.name for t in ps.get_current_tools()] == ["read_file", "lc_task"]
        # The other allowed MCP tools are searchable, not callable.
        assert sorted(t.name for t in ps.get_searchable_tools()) == ["gmail_send", "notion_search"]

    def test_always_enabled_bypasses_allowlist(self):
        # Allowlist names neither read_file nor the others; read_file is still
        # granted (and eager) because it is always-enabled.
        ps = self._ps(enabled_mcp_tools=["gmail_send"])
        assert "read_file" in [t.name for t in ps.get_current_tools()]
        # gmail_send is allowed but not always-enabled → searchable.
        assert [t.name for t in ps.get_searchable_tools()] == ["gmail_send"]
        # notion_search is not allowed → absent from both tiers.
        all_names = {t.name for t in ps.get_current_tools()} | {t.name for t in ps.get_searchable_tools()}
        assert "notion_search" not in all_names

    def test_empty_always_enabled_disables_split(self):
        """Fail-open: no always-enabled set → every allowed tool is eager."""
        ps = self._ps(always_enabled_names=set(), enabled_mcp_tools=None)
        assert [t.name for t in ps.get_current_tools()] == [
            "read_file",
            "gmail_send",
            "notion_search",
            "lc_task",
        ]
        assert ps.get_searchable_tools() == []

    def test_searchable_set_excludes_eager(self):
        ps = self._ps(enabled_mcp_tools=None)
        searchable = {t.name for t in ps.get_searchable_tools()}
        assert searchable == {"gmail_send", "notion_search"}
        assert "read_file" not in searchable  # always-enabled → eager, not searchable

    def test_promote_loads_tool_into_eager(self):
        ps = self._ps(enabled_mcp_tools=None)
        loaded = ps.promote_searched_tools(["gmail_send"])
        assert loaded == ["gmail_send"]
        assert "gmail_send" in [t.name for t in ps.get_current_tools()]
        assert "gmail_send" not in [t.name for t in ps.get_searchable_tools()]
        # Re-loading is idempotent.
        assert ps.promote_searched_tools(["gmail_send"]) == []

    def test_loaded_tools_persist_and_restore(self, tmp_path):
        meta = tmp_path / "meta.json"
        ps = self._ps(enabled_mcp_tools=None, meta_path=meta)
        ps.promote_searched_tools(["gmail_send"])
        assert json.loads(meta.read_text())["loaded_tools"] == ["gmail_send"]

        # Simulate restart: a fresh phase state restores from meta.json.
        persisted = json.loads(meta.read_text()).get("loaded_tools", [])
        ps2 = self._ps(enabled_mcp_tools=None)
        ps2.restore_loaded_tools(persisted, registered_names={"read_file", "gmail_send", "notion_search", "lc_task"})
        ps2.rebuild_independent_filter()
        assert "gmail_send" in [t.name for t in ps2.get_current_tools()]

    def test_restore_drops_unregistered_or_disallowed(self):
        ps = self._ps(enabled_mcp_tools=["gmail_send"])
        # notion_search: not allowed → dropped. ghost_tool: unregistered → dropped.
        ps.restore_loaded_tools(
            ["gmail_send", "notion_search", "ghost_tool"],
            registered_names={"read_file", "gmail_send", "notion_search", "lc_task"},
        )
        assert ps.loaded_tool_names == ["gmail_send"]


def test_match_searchable_tools_select_and_keywords():
    from framework.tools.queen_lifecycle_tools import _match_searchable_tools

    pool = [
        Tool(name="gmail_send", description="Send an email via Gmail", parameters={}),
        Tool(name="gmail_list_messages", description="List Gmail messages", parameters={}),
        Tool(name="notion_search", description="Search Notion pages", parameters={}),
    ]
    # Exact-name selection, order preserved, unknown names dropped.
    assert _match_searchable_tools("select:notion_search,nope", pool) == ["notion_search"]
    # Keyword scoring: "gmail" hits both gmail tools, not notion.
    out = _match_searchable_tools("gmail", pool)
    assert set(out) == {"gmail_send", "gmail_list_messages"}
    assert "notion_search" not in out
    # No hit → empty.
    assert _match_searchable_tools("kubernetes", pool) == []


# ---------------------------------------------------------------------------
# Route round-trip tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeSession:
    queen_name: str
    phase_state: QueenPhaseState
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
    # Pin a high version so sidecars written under this fixture postdate
    # every entry in _CATEGORY_ADDITIONS — keeps PATCH/legacy tests from
    # picking up GA grants they don't care about. Production always has
    # HIVE_APP_VERSION set by the Electron spawn.
    monkeypatch.setenv("HIVE_APP_VERSION", "99.0.0")

    queen_id = "queen_technology"
    (queens_dir / queen_id).mkdir()
    (queens_dir / queen_id / "profile.yaml").write_text(yaml.safe_dump({"name": "Alexandra", "title": "Head of Technology"}))
    return queens_dir, queen_id


async def _make_app(*, manager: _FakeManager) -> web.Application:
    app = web.Application()
    app["manager"] = manager
    routes_queen_tools.register_routes(app)
    return app


@pytest.mark.asyncio
async def test_get_tools_default_excludes_oauth_for_unknown_queen(queen_dir, monkeypatch):
    """Queens NOT in the role-default table get every credential-less tool
    by default — but OAuth-bound tools stay opt-in until the user enables
    them via the Tool Library. Mirrors the contract enforced by
    ``resolve_queen_default_tools``: with a catalog, the unknown-queen
    fallback returns a concrete list rather than the legacy ``None``."""
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)

    queens_dir, _ = queen_dir
    custom_id = "queen_custom_unknown"
    (queens_dir / custom_id).mkdir()
    (queens_dir / custom_id / "profile.yaml").write_text(yaml.safe_dump({"name": "Custom", "title": "Custom Role"}))

    manager = _FakeManager()
    # Mix a credential-less tool and a credentialed (gmail_*) tool in
    # the catalog so the test exercises both branches of the filter.
    manager._mcp_tool_catalog = {
        "files-tools": [
            {"name": "read_file", "description": "read", "input_schema": {}},
            {"name": "write_file", "description": "write", "input_schema": {}},
        ],
        "hive_tools": [
            {
                "name": "gmail_list_messages",
                "description": "list",
                "input_schema": {},
                "provider": "google",
            },
        ],
    }

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(f"/api/queen/{custom_id}/tools")
        assert resp.status == 200
        body = await resp.json()

    enabled = set(body["enabled_mcp_tools"] or [])
    assert "read_file" in enabled and "write_file" in enabled
    assert "gmail_list_messages" not in enabled  # OAuth → opt-in
    assert body["is_role_default"] is True  # no sidecar → role default
    assert body["stale"] is False

    servers = {s["name"]: s for s in body["mcp_servers"]}
    files_tools = {t["name"]: t for t in servers["files-tools"]["tools"]}
    assert files_tools["read_file"]["enabled"] is True
    hive = {t["name"]: t for t in servers["hive_tools"]["tools"]}
    assert hive["gmail_list_messages"]["enabled"] is False


@pytest.mark.asyncio
async def test_get_tools_applies_role_default(queen_dir, monkeypatch):
    """Known persona queens get their role-based default allowlist."""
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)
    _, queen_id = queen_dir  # queen_technology — has a role default

    manager = _FakeManager()
    # file_ops (in the technology role) grants pdf_read + attach_file by name,
    # so staging them in the catalog surfaces them in the default.
    # unrelated-server is NOT referenced by any role category — its tools
    # must NOT leak in.
    manager._mcp_tool_catalog = {
        "hive_tools": [
            {"name": "pdf_read", "description": "", "input_schema": {}},
            {"name": "attach_file", "description": "", "input_schema": {}},
        ],
        "unrelated-server": [
            {"name": "fluffy_unknown_tool", "description": "", "input_schema": {}},
        ],
    }

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(f"/api/queen/{queen_id}/tools")
        assert resp.status == 200
        body = await resp.json()

    assert body["is_role_default"] is True
    enabled = set(body["enabled_mcp_tools"] or [])
    # file_ops grants pdf_read + attach_file by name.
    assert "pdf_read" in enabled
    assert "attach_file" in enabled
    # Tools registered under a server the role doesn't reference are NOT
    # part of the default.
    assert "fluffy_unknown_tool" not in enabled


@pytest.mark.asyncio
async def test_get_tools_exposes_categories(queen_dir, monkeypatch):
    """Response includes the category catalog with role-default flags."""
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)
    _, queen_id = queen_dir  # queen_technology

    manager = _FakeManager()
    manager._mcp_tool_catalog = {
        "hive_tools": [
            {"name": "pdf_read", "description": "", "input_schema": {}},
            {"name": "attach_file", "description": "", "input_schema": {}},
        ],
    }

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(f"/api/queen/{queen_id}/tools")
        assert resp.status == 200
        body = await resp.json()

    cats = {c["name"]: c for c in body["categories"]}
    # Categories that contribute to queen_technology's role default
    assert cats["file_ops"]["in_role_default"] is True
    assert cats["browser_basic"]["in_role_default"] is True
    # Spreadsheet category is exposed even though queen_technology doesn't
    # use it — frontend can group/show it.
    assert "spreadsheet_advanced" in cats
    assert cats["spreadsheet_advanced"]["in_role_default"] is False
    # Security was removed from queen_technology defaults.
    assert cats["security"]["in_role_default"] is False
    # file_ops grants pdf_read + attach_file by name.
    assert "pdf_read" in cats["file_ops"]["tools"]
    assert "attach_file" in cats["file_ops"]["tools"]


@pytest.mark.asyncio
async def test_get_tools_live_session_preserves_server_scoped_defaults(queen_dir, monkeypatch):
    """A live session must use registry server groups, not the flat fallback.

    If the catalog collapses to ``{"MCP Tools": [...]}``, the
    ``@server:chart-tools`` role-default shorthand cannot expand and the
    ``charts`` category degrades to empty.
    """
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)
    _, queen_id = queen_dir  # queen_technology — has charts in role default

    class _FakeRegistry:
        _mcp_server_tools = {
            "chart-tools": {"chart_render", "diagram_render"},
        }

        def get_full_mcp_catalog(self):
            return {}

        def get_tools(self):
            return {name: _tool(name) for name in {"chart_render", "diagram_render"}}

    phase_state = QueenPhaseState(phase="independent")
    phase_state.independent_tools = [
        _tool("chart_render"),
        _tool("diagram_render"),
    ]
    phase_state.mcp_tool_names_all = {
        "chart_render",
        "diagram_render",
    }
    session = _FakeSession(queen_name=queen_id, phase_state=phase_state)
    session._queen_tool_registry = _FakeRegistry()
    manager = _FakeManager(_sessions={"sess-1": session})

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(f"/api/queen/{queen_id}/tools")
        assert resp.status == 200
        body = await resp.json()

    enabled = set(body["enabled_mcp_tools"] or [])
    assert {"chart_render", "diagram_render"} <= enabled
    cats = {c["name"]: c for c in body["categories"]}
    assert sorted(cats["charts"]["tools"]) == ["chart_render", "diagram_render"]


def test_resolve_queen_default_tools_expands_server_shorthand():
    """@server:NAME shorthand expands against the provided catalog."""
    from framework.agents.queen.queen_tools_defaults import resolve_queen_default_tools

    catalog = {
        "chart-tools": [
            {"name": "chart_render"},
            {"name": "diagram_render"},
        ],
    }
    # queen_technology uses the "charts" category → expands via @server:chart-tools.
    result = resolve_queen_default_tools("queen_technology", catalog)
    assert result is not None
    assert "chart_render" in result
    assert "diagram_render" in result


def test_resolve_queen_default_tools_unknown_queen():
    """Unknown queens default to "every credential-less tool" when a
    catalog is supplied, and to legacy ``None`` (allow-all) only when
    no catalog is available — preserving the boot-path fallback used
    by stripped-down environments that can't enumerate MCP servers."""
    from framework.agents.queen.queen_tools_defaults import resolve_queen_default_tools

    # No catalog: still allow-all (legacy boot-path semantic).
    assert resolve_queen_default_tools("queen_made_up", None) is None

    # Empty catalog: empty allowlist (no tools to grant).
    assert resolve_queen_default_tools("queen_made_up", {}) == []

    # Catalog with one credential-less tool: that tool is granted.
    catalog = {"files-tools": [{"name": "read_file"}]}
    out = resolve_queen_default_tools("queen_made_up", catalog)
    assert out == ["read_file"]


@pytest.mark.asyncio
async def test_patch_persists_and_validates(queen_dir, monkeypatch):
    monkeypatch.setattr(routes_queen_tools, "ensure_default_queens", lambda: None)
    queens_dir, queen_id = queen_dir

    manager = _FakeManager()
    manager._mcp_tool_catalog = {
        "files-tools": [
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
        server_map={"files-tools": {"read_file", "write_file"}},
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
        "hive_tools": [
            # pdf_read + attach_file are named explicitly in the file_ops
            # category, so we stage them in the catalog to surface them.
            {"name": "pdf_read", "description": "", "input_schema": {}},
            {"name": "attach_file", "description": "", "input_schema": {}},
        ],
    }

    app = await _make_app(manager=manager)
    async with TestClient(TestServer(app)) as client:
        # Seed a custom allowlist first so we have a sidecar to delete.
        resp = await client.patch(
            f"/api/queen/{queen_id}/tools",
            json={"enabled_mcp_tools": ["pdf_read"]},
        )
        assert resp.status == 200
        assert tools_path.exists()

        resp = await client.delete(f"/api/queen/{queen_id}/tools")
        assert resp.status == 200
        body = await resp.json()
        assert body["removed"] is True
        assert body["is_role_default"] is True
        assert not tools_path.exists()

        # The new effective list is the role default for queen_technology;
        # security tools were intentionally removed, so port_scan must NOT
        # appear, while file_ops members like pdf_read/attach_file do.
        enabled = set(body["enabled_mcp_tools"] or [])
        assert "pdf_read" in enabled
        assert "attach_file" in enabled
        assert "port_scan" not in enabled
        assert "subdomain_enumerate" not in enabled

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
