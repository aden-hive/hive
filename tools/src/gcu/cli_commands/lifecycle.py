"""``hive-browser setup | status | stop`` — mirror of ``browser_setup`` /
``browser_status`` / ``browser_stop`` (see ``gcu/browser/tools/lifecycle.py``)."""

from __future__ import annotations

import argparse
import time

from gcu.browser.bridge import connection_error, get_bridge
from gcu.browser.telemetry import log_tool_call
from gcu.browser.tools.lifecycle import (
    _CHROME_WEB_STORE_URL,
    _connected_profiles,
    _contexts,
    _resolve_profile,
    close_profile_context,
)


async def cmd_setup(args: argparse.Namespace) -> dict:
    bridge = get_bridge()
    connected = bool(bridge and bridge.is_connected)

    if connected:
        profiles = await _connected_profiles(bridge)
        status = "Extension is connected and ready. Run `hive-browser open <url>` to begin."
        if len(profiles) > 1:
            labels = ", ".join(p.get("label") for p in profiles if p.get("label"))
            status += (
                f" {len(profiles)} Chrome profiles are connected ({labels}); pass --browser-profile <label> to `hive-browser open` to choose one."
            )
        return {"ok": True, "connected": True, "status": status, "connected_profiles": profiles}

    return {
        "ok": False,
        "connected": False,
        "status": (
            "The Hive browser extension isn't connected. Make sure the Hive app is "
            "running, then follow the steps below to install and enable the Hive "
            "Browser Bridge extension in Chrome."
        ),
        "install_url": _CHROME_WEB_STORE_URL,
        "instructions": {
            "step_1": f"Open the Hive Browser Bridge listing in the Chrome Web Store: {_CHROME_WEB_STORE_URL}",
            "step_2": "Click 'Add to Chrome' and confirm the install prompt.",
            "step_3": "Pin the extension (puzzle-piece icon → pin) and click its toolbar icon to verify it says 'Connected'.",
            "step_4": "Return here and retry — the bridge will pick up the new connection automatically.",
        },
        "note": (
            "The extension connects to the local Hive runtime via WebSocket on "
            "ws://127.0.0.1:14829/bridge (older builds use 9229). Chrome must be "
            "running and the extension must be enabled."
        ),
    }


async def cmd_status(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    params = {"profile": args.profile}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge), "connected": False}
        log_tool_call("browser_status", params, result=result)
        return result

    profile_name = _resolve_profile(args.profile)
    conn_profiles = await _connected_profiles(bridge)
    ctx = _contexts.get(profile_name)

    if ctx:
        try:
            tabs_result = await bridge.list_tabs(ctx.get("groupId"))
            tabs = tabs_result.get("tabs", [])
            result = {
                "ok": True,
                "connected": True,
                "profile": profile_name,
                "running": True,
                "groupId": ctx.get("groupId"),
                "activeTab": ctx.get("activeTabId"),
                "browser_profile": ctx.get("browser_profile"),
                "connected_profiles": conn_profiles,
                "tabs": len(tabs),
            }
            if not tabs:
                result["hint"] = "No open tabs in this session — run `hive-browser open <url>` to start."
            log_tool_call("browser_status", params, result=result, duration_ms=(time.perf_counter() - start) * 1000)
            return result
        except Exception as e:
            result = {
                "ok": True,
                "connected": True,
                "profile": profile_name,
                "running": False,
                "error": str(e),
                "connected_profiles": conn_profiles,
            }
            log_tool_call("browser_status", params, result=result, duration_ms=(time.perf_counter() - start) * 1000)
            return result

    result = {
        "ok": True,
        "connected": True,
        "profile": profile_name,
        "running": False,
        "connected_profiles": conn_profiles,
        "tabs": 0,
    }
    log_tool_call("browser_status", params, result=result, duration_ms=(time.perf_counter() - start) * 1000)
    return result


async def cmd_stop(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    params = {"profile": args.profile}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_stop", params, result=result)
        return result

    profile_name = _resolve_profile(args.profile)
    result = await close_profile_context(profile_name, reason="tool")
    log_tool_call("browser_stop", params, result=result, duration_ms=(time.perf_counter() - start) * 1000)
    return result
