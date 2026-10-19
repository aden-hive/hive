"""Tests for GET /api/sessions/{id}/live_tools — the debug panel's tool view.

The endpoint must report TWO faithful sets:
  * ``actual_tools``   — what the agent loop can literally call now (the eager
    set + the ``ask_user`` synthetic the loop appends), with NO fall back to the
    registry-level ``independent_tools``.
  * ``expected_tools`` — the configured/allowed surface, status-tagged
    (callable / searchable / unregistered).
"""

import json
import types

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from framework.llm.provider import Tool
from framework.server.routes_sessions import handle_session_live_tools
from framework.tools.queen_lifecycle_tools import QueenPhaseState


def _tool(name: str) -> Tool:
    return Tool(name=name, description=f"desc of {name}", parameters={"type": "object"})


def _phase_state() -> QueenPhaseState:
    """A queen phase-state with a clear eager / searchable / unregistered split.

    registered MCP tools: chart_render, gmail_send, web_scrape
      - web_scrape   → always-enabled  → eager (callable)
      - chart_render → allowlisted + loaded-via-search → eager (callable)
      - gmail_send   → allowlisted, not loaded → searchable
    get_current_time → non-MCP lifecycle tool → eager (callable)
    ghost_tool       → allowlisted but no server registered → unregistered
    """
    ps = QueenPhaseState(phase="independent")
    ps.independent_tools = [
        _tool("chart_render"),
        _tool("gmail_send"),
        _tool("web_scrape"),
        _tool("get_current_time"),
    ]
    ps.mcp_tool_names_all = {"chart_render", "gmail_send", "web_scrape"}
    ps.always_enabled_names = {"web_scrape"}
    ps.enabled_mcp_tools = ["chart_render", "gmail_send", "web_scrape", "ghost_tool"]
    ps.rebuild_independent_filter()
    ps.promote_searched_tools(["chart_render"])
    return ps


async def _call(phase_state) -> dict:
    session = types.SimpleNamespace(phase_state=phase_state)
    manager = types.SimpleNamespace(get_session=lambda sid: session)
    app = web.Application()
    app["manager"] = manager
    req = make_mocked_request("GET", "/api/sessions/s1/live_tools", match_info={"session_id": "s1"}, app=app)
    resp = await handle_session_live_tools(req)
    return json.loads(resp.body)


@pytest.mark.asyncio
async def test_actual_is_eager_plus_ask_user_not_the_registry():
    data = await _call(_phase_state())

    assert data["phase_state_ready"] is True
    actual = {t["name"] for t in data["actual_tools"]}
    # Eager set + the ask_user synthetic the loop appends.
    assert actual == {"chart_render", "web_scrape", "get_current_time", "ask_user"}
    # Crucially NOT the registry: gmail_send (searchable) and ghost_tool
    # (unregistered) must be absent from the callable set.
    assert "gmail_send" not in actual
    assert "ghost_tool" not in actual
    # `tools` stays a back-compat alias of actual_tools.
    assert data["tools"] == data["actual_tools"]


@pytest.mark.asyncio
async def test_expected_surface_is_status_tagged():
    data = await _call(_phase_state())

    by_name = {t["name"]: t["status"] for t in data["expected_tools"]}
    assert by_name["chart_render"] == "callable"
    assert by_name["web_scrape"] == "callable"
    assert by_name["get_current_time"] == "callable"
    assert by_name["gmail_send"] == "searchable"
    assert by_name["ghost_tool"] == "unregistered"


@pytest.mark.asyncio
async def test_no_phase_state_reports_not_ready_without_registry_fallback():
    data = await _call(None)
    assert data["phase_state_ready"] is False
    assert data["actual_tools"] == []
    assert data["expected_tools"] == []


@pytest.mark.asyncio
async def test_missing_session_returns_404():
    manager = types.SimpleNamespace(get_session=lambda sid: None)
    app = web.Application()
    app["manager"] = manager
    req = make_mocked_request("GET", "/api/sessions/nope/live_tools", match_info={"session_id": "nope"}, app=app)
    resp = await handle_session_live_tools(req)
    assert resp.status == 404
