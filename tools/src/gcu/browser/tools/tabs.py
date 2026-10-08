"""
Browser tab management tools - tabs, open, close, activate.

All operations go through the Beeline extension - no Playwright required.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..bridge import connection_error, get_bridge
from ..session import _active_profile
from ..telemetry import log_tool_call
from .lifecycle import _contexts, _ensure_context, _tab_overflow_hint, summarize_group_tabs

# Schemes Chrome refuses to let any extension debug. browser_open can
# still CREATE a tab at these URLs (chrome.tabs.create allows it), but
# the post-create CDP attach + navigate would fail; the helper below
# lets the tool short-circuit that path cleanly.
_PRIVILEGED_SCHEMES = (
    "chrome://",
    "chrome-extension://",
    "devtools://",
    "view-source:",
    "chrome-search://",
    "chrome-error://",
    "chrome-untrusted://",
)


def _is_privileged_scheme(url: str) -> bool:
    return isinstance(url, str) and url.startswith(_PRIVILEGED_SCHEMES)


logger = logging.getLogger(__name__)


def _get_context(profile: str | None = None) -> dict[str, Any] | None:
    """Get the context for a profile.

    If profile is None, uses the _active_profile context variable
    (set by subagent executor to the agent_id).
    """
    if profile is not None:
        profile_name = profile
    else:
        profile_name = _active_profile.get()
    return _contexts.get(profile_name)


# ── browser_tabs prompts ─────────────────────────────────────

BROWSER_TABS_DOC = """\
List all open browser tabs in the agent's tab group.

Each tab includes:
- ``id``: Chrome tab ID (integer)
- ``url``: Current URL
- ``title``: Page title
- ``groupId``: Chrome tab group ID

Returns a dict with list of tabs and counts."""

BROWSER_TABS_PARAMS = {
    "profile": 'Browser profile name (default: "default")',
}

# ── browser_open prompts ─────────────────────────────────────

BROWSER_OPEN_DOC = """\
Open a browser tab at the given URL — preferred entry point.

This is the agent's primary "go to a page" tool and the cold-start
entry point — if no browser context exists yet for the profile,
one is created transparently. The first call after a fresh
context reuses the seed ``about:blank`` tab; subsequent calls
open new tabs in the agent's tab group. Waits for the page to
load before returning.

Returns a dict with new tab info (id, url, title)."""

BROWSER_OPEN_PARAMS = {
    "url": "URL to navigate to",
    "background": "Open in background without stealing focus (default: False)",
    "profile": 'Browser profile name (default: "default")',
}

# ── browser_close prompts ─────────────────────────────────────

BROWSER_CLOSE_DOC = """\
Close a browser tab.

Returns a dict with close status."""

BROWSER_CLOSE_PARAMS = {
    "tab_id": "Chrome tab ID to close (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
}

# ── browser_activate_tab prompts ─────────────────────────────────────

BROWSER_ACTIVATE_TAB_DOC = """\
Switch the active browser tab to the given tab ID.

Use this to bring an existing tab to the foreground before interacting
with it. The ``tab_id`` argument is required and must be an integer
returned by ``browser_tabs``; passing null/None is not supported (use
``browser_tabs`` to discover a valid ID first).

Returns a dict with activation status."""

BROWSER_ACTIVATE_TAB_PARAMS = {
    "tab_id": (
        "REQUIRED. Integer Chrome tab ID of the tab to switch to. "
        "Must be a concrete integer (not null). "
        "Call browser_tabs first to list available tabs and their IDs."
    ),
    "profile": 'Browser profile name (default: "default")',
}


def register_tab_tools(mcp: FastMCP) -> None:
    """Register browser tab management tools."""

    @mcp.tool(description=BROWSER_TABS_DOC)
    async def browser_tabs(
        profile: Annotated[str | None, Field(description=BROWSER_TABS_PARAMS["profile"])] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_tabs", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_open(url) first to open a tab."}
            log_tool_call("browser_tabs", params, result=result)
            return result

        try:
            result = await bridge.list_tabs(ctx.get("groupId"))
            tabs = result.get("tabs", [])

            # Hint and counts before the verbose ``tabs`` list so the nudge
            # isn't the first thing truncated when the response is large.
            result = {
                "ok": True,
                **_tab_overflow_hint(len(tabs)),
                "total": len(tabs),
                "activeTabId": ctx.get("activeTabId"),
                "tabs": tabs,
            }
            log_tool_call(
                "browser_tabs",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call("browser_tabs", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
            return result

    @mcp.tool(description=BROWSER_OPEN_DOC)
    async def browser_open(
        url: Annotated[str, Field(description=BROWSER_OPEN_PARAMS["url"])],
        background: Annotated[bool, Field(description=BROWSER_OPEN_PARAMS["background"])] = False,
        profile: Annotated[str | None, Field(description=BROWSER_OPEN_PARAMS["profile"])] = None,
        # Framework-injected (CONTEXT_PARAM) — human-readable queen/colony
        # label for the tab group; stripped from the LLM-facing schema.
        profile_display_name: str | None = None,
        browser_profile: Annotated[
            str | None,
            Field(
                description=(
                    "Which Chrome profile to open in — a connected profile label from "
                    "list_browser_profiles (the name shown in that profile's Hive extension "
                    "side panel, or its auto 3-word id). Set this to act in a specific "
                    "logged-in account; omit to use the starred/sole connected profile. The "
                    "result echoes the profile actually used so you can verify it."
                ),
            ),
        ] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"url": url, "background": background, "profile": profile, "browser_profile": browser_profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_open", params, result=result)
            return result

        tab_id: int | None = None
        try:
            _, ctx, _ = await _ensure_context(bridge, profile, profile_display_name, browser_profile)
            # Reuse the seed about:blank tab from context.create on first open
            seed_tab = ctx.pop("_seedTabId", None)
            if seed_tab is not None:
                tab_id = seed_tab
            else:
                result = await bridge.create_tab(url=url, group_id=ctx.get("groupId"))
                tab_id = result.get("tabId")

            # Track tab_ids so browser_stop can clear per-tab caches
            # for every tab in this profile at once.
            if tab_id is not None:
                ctx.setdefault("tabs", set()).add(tab_id)

            # Update active tab if not background
            if not background and tab_id is not None:
                ctx["activeTabId"] = tab_id
                await bridge.activate_tab(tab_id)

            # Navigate and wait for load. chrome.tabs.create already
            # navigated the tab to ``url`` at the create_tab step above —
            # bridge.navigate's only added value is the lifecycle wait,
            # which goes through cdp_attach and would fail on privileged
            # schemes (chrome://, chrome-extension://, devtools://, …).
            # For those, return the URL we asked for and skip the
            # CDP-bound verification — there's no scriptable content for
            # later tool calls anyway. This is the path that lets the
            # agent open chrome://extensions/?id=<offender> in response
            # to a foreign_extension_frame blocker.
            if _is_privileged_scheme(url):
                nav_result = {"url": url, "title": ""}
            else:
                nav_result = await bridge.navigate(tab_id, url, wait_until="load")

            # Include the full group tab list so the agent can see at a
            # glance whether prior calls (or click-spawned popups) left
            # extra tabs in the group — the original infinite-reopen
            # symptom came from agents not knowing duplicates existed.
            group_summary = await summarize_group_tabs(bridge, ctx)

            result = {
                "ok": True,
                "tabId": tab_id,
                "url": nav_result.get("url", url),
                "title": nav_result.get("title", ""),
                "background": background,
                # The Chrome profile this tab actually opened in (the bridge's
                # resolved connection label). Surfaced so the agent can verify it
                # landed on the intended account instead of silently using the
                # wrong/default one.
                "browser_profile": ctx.get("browser_profile"),
                **group_summary,
            }
            log_tool_call(
                "browser_open",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=tab_id,
                action=("open", url),
            )
            return result
        except Exception as e:
            # Surface tab_id when a tab was created before navigate failed —
            # otherwise the LLM has no handle to the orphan tab and just calls
            # browser_open again, creating a new tab on every retry.
            result = {"ok": False, "error": str(e)}
            if tab_id is not None:
                result["tabId"] = tab_id
                result["hint"] = (
                    "A tab was created before this error. Call browser_tabs to "
                    "verify state, or browser_close to discard it, before "
                    "retrying browser_open."
                )
            log_tool_call(
                "browser_open",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=tab_id,
                action=("open", url),
            )
            return result

    @mcp.tool(description=BROWSER_CLOSE_DOC)
    async def browser_close(
        tab_id: Annotated[int | None, Field(description=BROWSER_CLOSE_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_CLOSE_PARAMS["profile"])] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_close", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_open(url) first to open a tab."}
            log_tool_call("browser_close", params, result=result)
            return result

        # Use active tab if not specified
        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No tab to close"}
            log_tool_call("browser_close", params, result=result)
            return result

        try:
            await bridge.close_tab(target_tab)

            # Forget the closed tab so ctx["tabs"] only reflects tabs
            # that could still get per-tab cache activity.
            tabs_set = ctx.get("tabs")
            if isinstance(tabs_set, set):
                tabs_set.discard(target_tab)

            # Update active tab if we closed it
            if ctx.get("activeTabId") == target_tab:
                result = await bridge.list_tabs(ctx.get("groupId"))
                tabs = result.get("tabs", [])
                ctx["activeTabId"] = tabs[0].get("id") if tabs else None

            result = {"ok": True, "closed": target_tab}
            log_tool_call(
                "browser_close",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=("close", ""),
            )
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_close",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=("close", ""),
            )
            return result

    @mcp.tool(description=BROWSER_ACTIVATE_TAB_DOC)
    async def browser_activate_tab(
        tab_id: Annotated[int, Field(description=BROWSER_ACTIVATE_TAB_PARAMS["tab_id"])],
        profile: Annotated[str | None, Field(description=BROWSER_ACTIVATE_TAB_PARAMS["profile"])] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_activate_tab", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_open(url) first to open a tab."}
            log_tool_call("browser_activate_tab", params, result=result)
            return result

        try:
            await bridge.activate_tab(tab_id)
            ctx["activeTabId"] = tab_id
            result = {"ok": True, "tabId": tab_id}
            log_tool_call(
                "browser_activate_tab",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=tab_id,
                action=("focus", str(tab_id)),
            )
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_activate_tab",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=tab_id,
                action=("focus", str(tab_id)),
            )
            return result
