"""``hive-browser evaluate`` — mirror of ``browser_evaluate``."""

from __future__ import annotations

import argparse

from gcu.browser.bridge import connection_error, get_bridge, unnest_json_result
from gcu.browser.tools.advanced import _resolve_blockers
from gcu.browser.tools.tabs import _get_context
from gcu.cli_commands.script import read_arg_value
from gcu.errors import validation


async def cmd_evaluate(args: argparse.Namespace) -> dict:
    js = read_arg_value(getattr(args, "js", None))
    if not js or not js.strip():
        raise validation("evaluate requires JavaScript via --js (inline, @file, or -)")

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        return {"ok": False, "error": connection_error(bridge)}

    ctx = _get_context(args.profile)
    if not ctx:
        return {"ok": False, "error": "Browser not started"}

    target_tab = args.tab or ctx.get("activeTabId")
    if target_tab is None:
        return {"ok": False, "error": "No active tab"}

    try:
        # Brief in-page toast so the user sees JS executing (mirrors the tool).
        snippet = js.strip().replace("'", "\\'")[:80]
        toast_js = f"""
        (function(){{
          var old=document.getElementById('__hive_toast');if(old)old.remove();
          var t=document.createElement('div');t.id='__hive_toast';
          t.style.cssText='position:fixed;z-index:2147483647;top:12px;right:12px;'
            +'background:rgba(30,30,30,0.9);color:#a5d6ff;font:12px/18px monospace;'
            +'padding:8px 14px;border-radius:6px;max-width:420px;pointer-events:none;'
            +'white-space:pre-wrap;word-break:break-all;transition:opacity 0.4s;opacity:1;'
            +'border:1px solid rgba(59,130,246,0.4);box-shadow:0 4px 12px rgba(0,0,0,0.3);';
          t.textContent='\\u25b6 '+'{snippet}';
          document.documentElement.appendChild(t);
          setTimeout(function(){{t.style.opacity='0';}},2000);
          setTimeout(function(){{t.remove();}},2500);
        }})();
        """
        try:
            await bridge.evaluate(target_tab, toast_js)
        except Exception:
            pass

        result = await bridge.evaluate(target_tab, js)
        if not result.get("ok") and "blockers" not in result:
            blockers = await _resolve_blockers(bridge, target_tab, result.get("error"))
            if blockers:
                result = {**result, "blockers": blockers}
        if result.get("ok") and "result" in result:
            result["result"] = unnest_json_result(result["result"])
        return result
    except Exception as e:
        err: dict = {"ok": False, "error": str(e)}
        blockers = await _resolve_blockers(bridge, target_tab, str(e))
        if blockers:
            err["blockers"] = blockers
        return err
