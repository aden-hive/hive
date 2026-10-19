"""``hive-browser page html | snapshot | text | shadow-query | console | resize``
— mirrors of ``browser_html`` / ``browser_snapshot`` / ``browser_get_text`` /
``browser_shadow_query`` / ``browser_console`` / ``browser_resize``."""

from __future__ import annotations

import argparse
import inspect
import json
import time

from gcu.browser.bridge import connection_error, get_bridge
from gcu.browser.telemetry import log_tool_call
from gcu.browser.tools.inspection import (
    _ensure_viewport_size,
    _write_browser_artifact,
)
from gcu.browser.tools.tabs import _get_context

_NOT_STARTED = "Browser not started. Run `hive-browser open <url>` first to open a tab."


def _require(profile, tool_name, params, tab):
    """Shared guard: return (bridge, target_tab) or an error dict."""
    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        return None, {"ok": False, "error": connection_error(bridge)}
    ctx = _get_context(profile)
    if not ctx:
        return None, {"ok": False, "error": _NOT_STARTED}
    target_tab = tab or ctx.get("activeTabId")
    if target_tab is None:
        return None, {"ok": False, "error": "No active tab"}
    return (bridge, target_tab), None


async def cmd_page_html(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    params = {"tab_id": args.tab, "profile": args.profile, "selector": args.selector}
    resolved, err = _require(args.profile, "browser_html", params, args.tab)
    if err:
        log_tool_call("browser_html", params, result=err)
        return err
    bridge, target_tab = resolved

    try:
        if args.selector:
            sel_json = json.dumps(args.selector)
            script = f"(function() {{ const el = document.querySelector({sel_json}); return el ? el.outerHTML : null; }})()"
        else:
            script = "document.documentElement.outerHTML"

        eval_result = await bridge.evaluate(target_tab, script)
        if eval_result.get("ok"):
            html_value = eval_result.get("result")
            if isinstance(html_value, str):
                try:
                    artifact_path = _write_browser_artifact("browser_html", target_tab, html_value, ".html")
                    result = {"ok": True, "tabId": target_tab, "selector": args.selector, "length": len(html_value), "saved_to": str(artifact_path)}
                    if getattr(args, "head", None):
                        result["head"] = html_value[: args.head]
                except OSError as write_err:
                    result = {"ok": False, "error": f"Failed to write html artifact: {write_err}"}
            else:
                result = {"ok": True, "tabId": target_tab, "html": html_value, "selector": args.selector}
            log_tool_call("browser_html", params, result=result, duration_ms=(time.perf_counter() - start) * 1000)
            return result
        log_tool_call("browser_html", params, result=eval_result, duration_ms=(time.perf_counter() - start) * 1000)
        return eval_result
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        log_tool_call("browser_html", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
        return result


async def cmd_page_snapshot(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    params = {"tab_id": args.tab, "profile": args.profile, "mode": args.mode}
    resolved, err = _require(args.profile, "browser_snapshot", params, args.tab)
    if err:
        log_tool_call("browser_snapshot", params, result=err)
        return err
    bridge, target_tab = resolved

    pending = bridge.get_pending_dialog(target_tab)
    if inspect.isawaitable(pending):
        pending = await pending
    if pending:
        result = {
            "ok": False,
            "error": "Page is blocked by a native browser dialog",
            "pending_dialog": {
                "tab_id": target_tab,
                "type": pending.get("type"),
                "message": pending.get("message"),
                "default_prompt": pending.get("default_prompt"),
                "url": pending.get("url"),
            },
        }
        log_tool_call("browser_snapshot", params, result=result)
        return result

    try:
        snapshot_result = await bridge.snapshot(target_tab, mode=args.mode)
        if isinstance(snapshot_result, dict) and snapshot_result.get("ok") and isinstance(snapshot_result.get("tree"), str):
            tree_text = snapshot_result["tree"]
            try:
                artifact_path = _write_browser_artifact("browser_snapshot", target_tab, tree_text, ".txt")
                result = {
                    "ok": True,
                    "tabId": snapshot_result.get("tabId", target_tab),
                    "url": snapshot_result.get("url"),
                    "length": len(tree_text),
                    "saved_to": str(artifact_path),
                }
                if getattr(args, "head", None):
                    result["head"] = tree_text[: args.head]
            except OSError as write_err:
                result = {"ok": False, "error": f"Failed to write snapshot artifact: {write_err}"}
        else:
            result = snapshot_result
        log_tool_call("browser_snapshot", params, result=result, duration_ms=(time.perf_counter() - start) * 1000)
        return result
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        log_tool_call("browser_snapshot", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
        return result


async def cmd_page_shadow_query(args: argparse.Namespace) -> dict:
    resolved, err = _require(args.profile, "browser_shadow_query", {}, args.tab)
    if err:
        return err
    bridge, target_tab = resolved

    result = await bridge.shadow_query(target_tab, args.selector)
    if not result.get("ok"):
        return result
    rect = result["rect"]
    cw, ch = await _ensure_viewport_size(target_tab, _caller="page shadow-query")
    cw_f = float(cw) if cw > 0 else 1.0
    ch_f = float(ch) if ch > 0 else 1.0
    return {
        "ok": True,
        "selector": args.selector,
        "tag": rect.get("tag"),
        "rect": {
            "x": round(rect["x"] / cw_f, 4),
            "y": round(rect["y"] / ch_f, 4),
            "w": round(rect["w"] / cw_f, 4),
            "h": round(rect["h"] / ch_f, 4),
            "cx": round(rect["cx"] / cw_f, 4),
            "cy": round(rect["cy"] / ch_f, 4),
        },
        "cssWidth": cw,
        "cssHeight": ch,
        "note": (
            "rect fields are fractions of the viewport (0..1). Pass rect.cx / rect.cy "
            "as the --coordinate of a `hive-browser interact` left_click / hover / key action."
        ),
    }


async def cmd_page_console(args: argparse.Namespace) -> dict:
    result = {
        "ok": True,
        "message": "Console capture not yet implemented",
        "suggestion": "Use `hive-browser evaluate` to check specific values or errors",
    }
    log_tool_call("browser_console", {"tab_id": args.tab, "profile": args.profile, "level": args.level}, result=result)
    return result


async def cmd_page_text(args: argparse.Namespace) -> dict:
    resolved, err = _require(args.profile, "browser_get_text", {}, args.tab)
    if err:
        return err
    bridge, target_tab = resolved
    try:
        return await bridge.get_text(target_tab, args.selector, timeout_ms=args.timeout_ms)
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def cmd_page_resize(args: argparse.Namespace) -> dict:
    resolved, err = _require(args.profile, "browser_resize", {}, args.tab)
    if err:
        return err
    bridge, target_tab = resolved
    try:
        result = await bridge.resize(target_tab, args.width, args.height)
        try:
            from gcu.browser.tools.inspection import _screenshot_scales, _viewport_sizes

            _viewport_sizes.pop(target_tab, None)
            _screenshot_scales.pop(target_tab, None)
        except Exception:
            pass
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}
