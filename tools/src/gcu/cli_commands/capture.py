"""``hive-browser screenshot`` — mirror of ``browser_screenshot``.

Returns a JSON dict (never inline image bytes — a terminal can't carry those):
the same metadata the MCP tool produced plus ``saved_to`` (the JPEG on disk) and
an ``_image`` marker the framework re-inlines into the agent's session."""

from __future__ import annotations

import argparse
import time

from gcu.browser.bridge import connection_error, get_bridge
from gcu.browser.telemetry import log_tool_call
from gcu.browser.tools.inspection import render_screenshot
from gcu.browser.tools.tabs import _get_context


async def cmd_screenshot(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    params = {"tab_id": args.tab, "profile": args.profile, "full_page": args.full_page, "selector": args.selector}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_screenshot", params, result=result)
        return result

    ctx = _get_context(args.profile)
    if not ctx:
        result = {"ok": False, "error": "Browser not started"}
        log_tool_call("browser_screenshot", params, result=result)
        return result

    target_tab = args.tab or ctx.get("activeTabId")
    if target_tab is None:
        result = {"ok": False, "error": "No active tab"}
        log_tool_call("browser_screenshot", params, result=result)
        return result

    return await render_screenshot(
        bridge,
        target_tab,
        full_page=args.full_page,
        selector=args.selector,
        annotate=not args.no_annotate,
        log_name="browser_screenshot",
        log_params=params,
        start=start,
        spill=True,
        intent=args.intent,
        selector_timeout_ms=args.timeout_ms,
    )
