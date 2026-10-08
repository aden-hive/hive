"""``hive-browser tab list | close | activate`` — mirror of ``browser_tabs`` /
``browser_close`` / ``browser_activate_tab`` (tabs.py)."""

from __future__ import annotations

import argparse
import time

from gcu.browser.bridge import connection_error, get_bridge
from gcu.browser.telemetry import log_tool_call
from gcu.browser.tools.lifecycle import _persist_contexts, _tab_overflow_hint
from gcu.browser.tools.tabs import _get_context

_NOT_STARTED = "Browser not started. Run `hive-browser open <url>` first to open a tab."


async def cmd_tab_list(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    params = {"profile": args.profile}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_tabs", params, result=result)
        return result

    ctx = _get_context(args.profile)
    if not ctx:
        result = {"ok": False, "error": _NOT_STARTED}
        log_tool_call("browser_tabs", params, result=result)
        return result

    try:
        result = await bridge.list_tabs(ctx.get("groupId"))
        tabs = result.get("tabs", [])
        # Report `active` from the tracked activeTabId, not Chrome's per-window
        # flag (which is ambiguous for a background group) — so `tab list` agrees
        # with `tab activate` (audit B2).
        active_id = ctx.get("activeTabId")
        for t in tabs:
            t["active"] = (t.get("id") or t.get("tabId")) == active_id
        result = {
            "ok": True,
            **_tab_overflow_hint(len(tabs)),
            "total": len(tabs),
            "activeTabId": active_id,
            "tabs": tabs,
        }
        log_tool_call("browser_tabs", params, result=result, duration_ms=(time.perf_counter() - start) * 1000)
        return result
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        log_tool_call("browser_tabs", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
        return result


async def cmd_tab_close(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    tab_id = args.tab_id
    params = {"tab_id": tab_id, "profile": args.profile}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_close", params, result=result)
        return result

    ctx = _get_context(args.profile)
    if not ctx:
        result = {"ok": False, "error": _NOT_STARTED}
        log_tool_call("browser_close", params, result=result)
        return result

    target_tab = tab_id or ctx.get("activeTabId")
    if target_tab is None:
        result = {"ok": False, "error": "No tab to close"}
        log_tool_call("browser_close", params, result=result)
        return result

    try:
        await bridge.close_tab(target_tab)
        tabs_set = ctx.get("tabs")
        if isinstance(tabs_set, set):
            tabs_set.discard(target_tab)
        if ctx.get("activeTabId") == target_tab:
            result = await bridge.list_tabs(ctx.get("groupId"))
            tabs = result.get("tabs", [])
            ctx["activeTabId"] = tabs[0].get("id") if tabs else None
        _persist_contexts()  # survive the tab-set / active change across invocations
        result = {"ok": True, "closed": target_tab}
        log_tool_call(
            "browser_close", params, result=result, duration_ms=(time.perf_counter() - start) * 1000, tab_id=target_tab, action=("close", "")
        )
        return result
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        log_tool_call("browser_close", params, error=e, duration_ms=(time.perf_counter() - start) * 1000, tab_id=target_tab, action=("close", ""))
        return result


async def cmd_tab_activate(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    tab_id = args.tab_id
    params = {"tab_id": tab_id, "profile": args.profile}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_activate_tab", params, result=result)
        return result

    ctx = _get_context(args.profile)
    if not ctx:
        result = {"ok": False, "error": _NOT_STARTED}
        log_tool_call("browser_activate_tab", params, result=result)
        return result

    try:
        # Verify the tab is actually in this session's group before claiming
        # success — activate_tab is fire-and-forget and can't self-verify (audit B2).
        tabs_result = await bridge.list_tabs(ctx.get("groupId"))
        group_tab_ids = {(t.get("id") or t.get("tabId")) for t in tabs_result.get("tabs", [])}
        if tab_id not in group_tab_ids:
            result = {"ok": False, "error": f"No such tab {tab_id} in this session's group"}
            log_tool_call("browser_activate_tab", params, result=result)
            return result
        await bridge.activate_tab(tab_id)
        ctx["activeTabId"] = tab_id
        # Persist so the activation survives across per-invocation CLI processes.
        _persist_contexts()
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
            "browser_activate_tab", params, error=e, duration_ms=(time.perf_counter() - start) * 1000, tab_id=tab_id, action=("focus", str(tab_id))
        )
        return result
