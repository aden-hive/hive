"""Regression tests for search_tools' handling of allowlisted-but-unregistered
tools.

When a tool's MCP server fails to register at boot, the tool is still in the
queen's allowlist but absent from the live catalog. search_tools must report it
as "configured but temporarily unavailable" rather than "no such tool", so the
agent doesn't conclude an allowlisted tool (e.g. chart_render) doesn't exist.
"""

import json
import types

import pytest

from framework.llm.provider import Tool
from framework.tools.queen_lifecycle_tools import (
    QueenPhaseState,
    _match_names,
    register_queen_lifecycle_tools,
)


def _state(*, allowlist, registered):
    ps = QueenPhaseState(phase="independent")
    ps.enabled_mcp_tools = allowlist
    ps.mcp_tool_names_all = set(registered)
    return ps


def _tool(name: str) -> Tool:
    return Tool(name=name, description=f"desc of {name}", parameters={"type": "object"})


class _CapturingRegistry:
    """Minimal ToolRegistry stand-in that captures registered handlers so a
    test can invoke the real search_tools closure end-to-end."""

    def __init__(self):
        self.handlers = {}
        self._mcp_server_tools = {}

    def register(self, name, tool, handler):  # noqa: D401 - matches ToolRegistry
        self.handlers[name] = handler


async def _search_tools_handler(*, allowlist, registered, loaded):
    """Build a live search_tools closure over a phase_state with `loaded`
    tools already promoted into the eager tier, and return the handler."""
    ps = QueenPhaseState(phase="independent")
    ps.independent_tools = [_tool(n) for n in registered]
    ps.mcp_tool_names_all = set(registered)
    ps.always_enabled_names = {"read_file"}
    ps.enabled_mcp_tools = allowlist
    ps.rebuild_independent_filter()
    ps.promote_searched_tools(list(loaded))

    registry = _CapturingRegistry()
    register_queen_lifecycle_tools(
        registry,
        session=types.SimpleNamespace(colony_runtime=None),
        phase_state=ps,
    )
    return registry.handlers["search_tools"]


def test_unregistered_allowlisted_names_flags_missing_server_tool():
    # chart_render is allowed but its server didn't register this session.
    ps = _state(allowlist=["chart_render", "web_scrape"], registered={"web_scrape"})
    assert ps.unregistered_allowlisted_names() == {"chart_render"}


def test_unregistered_allowlisted_names_empty_when_all_registered():
    ps = _state(allowlist=["chart_render", "web_scrape"], registered={"chart_render", "web_scrape"})
    assert ps.unregistered_allowlisted_names() == set()


def test_unregistered_allowlisted_names_allow_all_returns_empty():
    # allow-all (None): an unregistered name can't be told apart from a typo.
    ps = _state(allowlist=None, registered={"web_scrape"})
    assert ps.unregistered_allowlisted_names() == set()


def test_match_names_select_exact():
    names = {"chart_render", "diagram_render"}
    assert _match_names("select:chart_render", names) == ["chart_render"]
    assert _match_names("select:chart_render,nope", names) == ["chart_render"]


def test_match_names_free_text_tokens():
    names = {"chart_render"}
    # The exact query the failing agent used; must resolve to chart_render.
    assert _match_names("chart render", names) == ["chart_render"]
    assert _match_names("draw a chart", names) == ["chart_render"]


def test_match_names_no_match_returns_empty():
    names = {"chart_render"}
    assert _match_names("hubspot contacts", names) == []
    assert _match_names("", names) == []
    assert _match_names("select:something_else", names) == []


# ---------------------------------------------------------------------------
# search_tools reports already-loaded tools as callable, not "not found".
#
# A loaded tool is promoted out of the searchable set, so re-searching it used
# to fall through to "No searchable tool matched ... Searchable tools: <others>".
# A queen read that as "chart_render doesn't exist" and looped on terminal_exec
# workarounds instead of calling the tool. These lock in the corrected message.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_already_loaded_tool_reports_callable():
    # chart_render is loaded; the only remaining searchable tool is gmail_send.
    handler = await _search_tools_handler(
        allowlist=None,
        registered=["read_file", "chart_render", "gmail_send"],
        loaded=["chart_render"],
    )
    out = json.loads(await handler({"query": "select:chart_render"}))
    assert out["already_loaded"] == ["chart_render"]
    assert out["loaded"] == []
    assert "callable" in out["note"]
    # Must NOT claim the tool wasn't found.
    assert "No searchable tool matched" not in out["note"]


@pytest.mark.asyncio
async def test_search_already_loaded_when_nothing_searchable_remains():
    # Everything allowed is already loaded → searchable set is empty. The
    # already-loaded match must still win over the generic "nothing to load".
    handler = await _search_tools_handler(
        allowlist=None,
        registered=["read_file", "chart_render"],
        loaded=["chart_render"],
    )
    out = json.loads(await handler({"query": "select:chart_render"}))
    assert out["already_loaded"] == ["chart_render"]
    assert "callable" in out["note"]


@pytest.mark.asyncio
async def test_search_unloaded_tool_still_loads_normally():
    # A genuinely searchable (not yet loaded) tool loads as before.
    handler = await _search_tools_handler(
        allowlist=None,
        registered=["read_file", "chart_render", "gmail_send"],
        loaded=[],
    )
    out = json.loads(await handler({"query": "select:chart_render"}))
    assert out["loaded"] == ["chart_render"]
    assert "already_loaded" in out and out["already_loaded"] == []


@pytest.mark.asyncio
async def test_search_unknown_tool_still_reports_no_match():
    # An actual unknown name keeps the "no searchable tool matched" message.
    handler = await _search_tools_handler(
        allowlist=None,
        registered=["read_file", "chart_render", "gmail_send"],
        loaded=["chart_render"],
    )
    out = json.loads(await handler({"query": "select:ghost_tool"}))
    assert out["loaded"] == []
    assert "already_loaded" not in out
    assert "No searchable tool matched" in out["note"]
