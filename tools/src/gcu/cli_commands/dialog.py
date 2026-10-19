"""``hive-browser dialog respond`` — mirror of ``browser_dialog_respond``."""

from __future__ import annotations

import argparse
import time

from gcu.browser.bridge import connection_error, get_bridge
from gcu.browser.telemetry import log_tool_call
from gcu.browser.tools.tabs import _get_context


async def cmd_dialog_respond(args: argparse.Namespace) -> dict:
    action = args.action
    start = time.perf_counter()
    params = {"action": action, "tab_id": args.tab, "profile": args.profile, "prompt_text": args.prompt_text}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_dialog_respond", params, result=result)
        return result

    ctx = _get_context(args.profile)
    if not ctx:
        result = {"ok": False, "error": "Browser not started. Run `hive-browser open <url>` first to open a tab."}
        log_tool_call("browser_dialog_respond", params, result=result)
        return result

    target_tab = args.tab or ctx.get("activeTabId")
    if target_tab is None:
        result = {"ok": False, "error": "No active tab"}
        log_tool_call("browser_dialog_respond", params, result=result)
        return result

    try:
        nav_result = await bridge.handle_javascript_dialog(target_tab, accept=(action == "accept"), prompt_text=args.prompt_text)
        log_tool_call(
            "browser_dialog_respond",
            params,
            result=nav_result,
            duration_ms=(time.perf_counter() - start) * 1000,
            tab_id=target_tab,
            action=("dialog", action),
        )
        return nav_result
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        log_tool_call(
            "browser_dialog_respond", params, error=e, duration_ms=(time.perf_counter() - start) * 1000, tab_id=target_tab, action=("dialog", action)
        )
        return result
