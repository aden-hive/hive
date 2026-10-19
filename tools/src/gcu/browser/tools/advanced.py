"""
Browser advanced tools - wait, evaluate, get_text, get_attribute, resize,
upload, dialog_respond.

All operations go through the Beeline extension via CDP - no Playwright required.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ..bridge import connection_error, get_bridge, unnest_json_result
from ..telemetry import log_tool_call
from .tabs import _get_context

logger = logging.getLogger(__name__)


async def _resolve_blockers(bridge, tab_id: int, error_str: str | None) -> list[dict]:
    """Look up structured blockers for ``tab_id`` with a synchronous re-audit
    when the error fingerprint indicates a foreign-extension frame.

    Some bridge methods still raise on CDP failure rather than returning a
    structured envelope; their callers used to flatten those errors to a
    plain ``{ok: False, error: str(e)}`` with no actionable culprit info.
    This helper:

    1. Reads ``bridge.get_tab_blockers`` (the cache populated by ``_cdp`` /
       ``_evaluate_failure`` / etc.)
    2. If the cache is empty AND ``error_str`` looks like a foreign-frame
       error, fires ``bridge.tab_health(force_audit=True)`` to run the
       page-DOM probe that names the offender (Calendly / Grammarly / …)
       and re-read the cache.
    3. Final fallback: classify ``error_str`` itself so the agent at least
       sees the generic blocker.
    """
    try:
        blockers: list[dict] = []
        if bridge is not None:
            try:
                blockers = list(await bridge.get_tab_blockers(tab_id) or [])
            except Exception:
                blockers = []

        looks_foreign_frame = isinstance(error_str, str) and "chrome-extension://" in error_str.lower() and "different extension" in error_str.lower()
        if not blockers and looks_foreign_frame and bridge is not None:
            try:
                # Synchronous audit → names the offender by reading the
                # page DOM via chrome.scripting; the cache it populates
                # carries the offender_name in context.
                await bridge.tab_health(tab_id, force_audit=True)
                blockers = list(await bridge.get_tab_blockers(tab_id) or [])
            except Exception:
                blockers = []

        if not blockers and error_str:
            from ..health import classify_all

            ext_id = getattr(get_bridge(), "_extension_id", None)
            ctx_kw = {"our_extension_id": ext_id} if ext_id else {}
            objs = classify_all({}, str(error_str), ctx=ctx_kw)
            blockers = [b.to_dict() for b in objs]
        return blockers
    except Exception:
        return []


# ── browser_evaluate prompts ─────────────────────────────────────

BROWSER_EVALUATE_DOC = """\
Execute JavaScript in a browser tab and return the result.

Runs in the page context; the value of the last expression is returned. Use
it to read state or drive the page when no semantic tool fits — e.g. element
attributes (`el.getAttribute('href')`), history navigation (`history.back()` /
`history.forward()`), computed styles, or scroll position.

Returns a dict with the evaluation result."""

BROWSER_EVALUATE_PARAMS = {
    "script": (
        "The JavaScript code to execute. The code will be evaluated in the "
        "page context. The result of the last expression will be returned "
        "automatically. Do NOT use 'return' statements - just write the "
        "expression you want to evaluate (e.g., 'window.myData.value' not "
        "'return window.myData.value'). You can access and modify the DOM, "
        "call page functions, and interact with page variables."
    ),
    "tab_id": "Chrome tab ID. Defaults to the active tab.",
    "profile": 'Browser profile name. Defaults to "default".',
}


# NOTE: browser_wait was merged into the unified ``browser_interact``
# tool as its ``wait`` action (duration / wait_for_selector /
# wait_for_text). See interact.py.

# ── browser_get_text prompts ─────────────────────────────────────

BROWSER_GET_TEXT_DOC = """\
Get text content of an element.

Returns a dict with the element text content."""

BROWSER_GET_TEXT_PARAMS = {
    "selector": "CSS selector",
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
    "timeout_ms": "Timeout in milliseconds (default: 30000)",
}

# ── browser_resize prompts ─────────────────────────────────────

BROWSER_RESIZE_DOC = """\
Resize the browser viewport.

Returns a dict with the resize result."""

BROWSER_RESIZE_PARAMS = {
    "width": "Viewport width in pixels",
    "height": "Viewport height in pixels",
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
}

# ── browser_upload prompts ─────────────────────────────────────

BROWSER_UPLOAD_DOC = """\
Upload files to a file input element.

Two modes:
- Direct (default): the `<input type=file>` already exists in the DOM. Pass its
  CSS `selector` and the files are set on it.
- Triggered (`trigger_selector`): for sites that create the file input on demand
  and open the native OS file picker (e.g. Google Drive's "New > File upload").
  The native picker is intercepted via CDP so it never blocks; the tool clicks
  `trigger_selector`, waits for the resulting input (matched by `selector`,
  default `input[type=file]`), and sets the files on it.

Returns a dict with the upload result. The `accepted` field is the acceptance
signal: `accepted.change_fired` is True when the page's `change` handler ran
(i.e. the site observed the upload), and `accepted.files` is what the input
holds afterwards (often empty for sites that clear it after consuming the
files). `accepted` is None if it couldn't be read back."""

BROWSER_UPLOAD_PARAMS = {
    "selector": ("CSS selector for the file input. In triggered mode this matches the input created after the click (commonly input[type=file])."),
    "file_paths": "List of file paths to upload",
    "trigger_selector": (
        "Optional CSS selector for the element to click to open the file picker "
        "(button / label / menu item). When set, the native OS picker is "
        "intercepted so it never blocks."
    ),
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
    "timeout_ms": "Timeout in ms (default: 30000)",
}


def register_advanced_tools(mcp: FastMCP) -> None:
    """Register browser advanced tools."""

    @mcp.tool(description=BROWSER_EVALUATE_DOC)
    async def browser_evaluate(
        script: Annotated[str, Field(description=BROWSER_EVALUATE_PARAMS["script"])],
        tab_id: Annotated[int | None, Field(description=BROWSER_EVALUATE_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_EVALUATE_PARAMS["profile"])] = None,
    ) -> dict:
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": connection_error(bridge)}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        try:
            # Show a brief toast in the browser so the user sees JS executing
            snippet = script.strip().replace("'", "\\'")[:80]
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

            result = await bridge.evaluate(target_tab, script)
            # bridge.evaluate may have folded a CDP transport failure (foreign
            # frame, devtools-attached, …) into ok=False with structured
            # blockers. If not, double-check the per-tab blocker cache and
            # attach — covers the case where the failure mode surfaced on
            # an earlier call but bridge.evaluate's own path didn't repopulate.
            if not result.get("ok") and "blockers" not in result:
                blockers = await _resolve_blockers(bridge, target_tab, result.get("error"))
                if blockers:
                    result = {**result, "blockers": blockers}
            # Un-nest `JSON.stringify(...)` payloads so the agent gets clean
            # nested JSON instead of an escaped string. This runs in the gcu
            # server (which recycles on restart), so the fix lands even though
            # `bridge.evaluate` itself executes in the long-lived bridge_host
            # process in client mode. Idempotent if the bridge already parsed it.
            if result.get("ok") and "result" in result:
                result["result"] = unnest_json_result(result["result"])
            return result
        except Exception as e:
            err: dict = {"ok": False, "error": str(e)}
            blockers = await _resolve_blockers(bridge, target_tab, str(e))
            if blockers:
                err["blockers"] = blockers
            return err

    @mcp.tool(description=BROWSER_GET_TEXT_DOC)
    async def browser_get_text(
        selector: Annotated[str, Field(description=BROWSER_GET_TEXT_PARAMS["selector"])],
        tab_id: Annotated[int | None, Field(description=BROWSER_GET_TEXT_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_GET_TEXT_PARAMS["profile"])] = None,
        timeout_ms: Annotated[int, Field(description=BROWSER_GET_TEXT_PARAMS["timeout_ms"])] = 30000,
    ) -> dict:
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": connection_error(bridge)}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        try:
            result = await bridge.get_text(target_tab, selector, timeout_ms=timeout_ms)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool(description=BROWSER_RESIZE_DOC)
    async def browser_resize(
        width: Annotated[int, Field(description=BROWSER_RESIZE_PARAMS["width"])],
        height: Annotated[int, Field(description=BROWSER_RESIZE_PARAMS["height"])],
        tab_id: Annotated[int | None, Field(description=BROWSER_RESIZE_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_RESIZE_PARAMS["profile"])] = None,
    ) -> dict:
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": connection_error(bridge)}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        try:
            result = await bridge.resize(target_tab, width, height)
            # Invalidate per-tab scale caches — CSS width changed, so the
            # cached viewport dimensions are stale. Click / rect tools
            # will re-query innerWidth / innerHeight on next use via
            # _ensure_viewport_size.
            try:
                from .inspection import _screenshot_scales, _viewport_sizes

                _viewport_sizes.pop(target_tab, None)
                _screenshot_scales.pop(target_tab, None)
            except Exception:
                pass
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool(description=BROWSER_UPLOAD_DOC)
    async def browser_upload(
        selector: Annotated[str, Field(description=BROWSER_UPLOAD_PARAMS["selector"])],
        file_paths: Annotated[list[str], Field(description=BROWSER_UPLOAD_PARAMS["file_paths"])],
        trigger_selector: Annotated[str | None, Field(description=BROWSER_UPLOAD_PARAMS["trigger_selector"])] = None,
        tab_id: Annotated[int | None, Field(description=BROWSER_UPLOAD_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_UPLOAD_PARAMS["profile"])] = None,
        timeout_ms: Annotated[int, Field(description=BROWSER_UPLOAD_PARAMS["timeout_ms"])] = 30000,
    ) -> dict:
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": connection_error(bridge)}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        intercept_enabled = False
        try:
            import json
            from pathlib import Path

            for path in file_paths:
                if not Path(path).exists():
                    return {"ok": False, "error": f"File not found: {path}"}

            await bridge.cdp_attach(target_tab)
            await bridge._cdp(target_tab, "DOM.enable")

            # Triggered mode: the file input does not exist until something is
            # clicked, and that click opens the native OS picker. Intercepting
            # the picker keeps the lazily-created input alive in the DOM (so we
            # can set files on it) and stops the modal dialog from blocking.
            if trigger_selector:
                await bridge._cdp(target_tab, "Page.enable")
                await bridge._cdp(
                    target_tab,
                    "Page.setInterceptFileChooserDialog",
                    {"enabled": True},
                )
                intercept_enabled = True
                # Dispatch a full pointer/mouse sequence — Drive (and many SPA
                # menus) wire their handlers to pointer/mousedown, not a bare
                # click(), so element.click() alone won't open the picker.
                click_js = (
                    "(function(){var el=document.querySelector("
                    + json.dumps(trigger_selector)
                    + ");if(!el)return 'no-trigger';var r=el.getBoundingClientRect();"
                    "var cx=r.left+r.width/2,cy=r.top+r.height/2;"
                    "['pointerdown','mousedown','pointerup','mouseup','click']"
                    ".forEach(function(t){var E=t.indexOf('pointer')===0?PointerEvent:MouseEvent;"
                    "el.dispatchEvent(new E(t,{bubbles:true,cancelable:true,composed:true,"
                    "clientX:cx,clientY:cy,button:0,view:window}));});return 'clicked';})()"
                )
                click_res = await bridge.evaluate(target_tab, click_js)
                if (click_res or {}).get("result") == "no-trigger":
                    return {
                        "ok": False,
                        "error": f"Trigger element not found: {trigger_selector}",
                    }

            doc = await bridge._cdp(target_tab, "DOM.getDocument")
            root_id = doc.get("root", {}).get("nodeId")

            deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
            node_id = None
            while asyncio.get_event_loop().time() < deadline:
                # Re-fetch the document each poll: triggered inputs are appended
                # after the initial getDocument, and a stale root nodeId can miss
                # them.
                doc = await bridge._cdp(target_tab, "DOM.getDocument")
                root_id = doc.get("root", {}).get("nodeId")
                result = await bridge._cdp(
                    target_tab,
                    "DOM.querySelector",
                    {"nodeId": root_id, "selector": selector},
                )
                node_id = result.get("nodeId")
                if node_id:
                    break
                await asyncio.sleep(0.1)

            if not node_id:
                return {"ok": False, "error": f"Element not found: {selector}"}

            # Resolve the node to a JS handle so we can confirm the page actually
            # accepted the files. Many sites read the files in their `change`
            # handler and immediately clear the input (to allow re-selecting the
            # same file), so reading `input.files` afterwards is unreliable —
            # the real signal is whether `change` fired. Install a one-shot
            # listener *before* setting the files to capture that.
            object_id = None
            try:
                resolved = await bridge._cdp(target_tab, "DOM.resolveNode", {"nodeId": node_id})
                object_id = resolved.get("object", {}).get("objectId")
                if object_id:
                    await bridge._cdp(
                        target_tab,
                        "Runtime.callFunctionOn",
                        {
                            "objectId": object_id,
                            "functionDeclaration": (
                                "function(){this.__hiveChangeFired=false;"
                                "this.addEventListener('change',function(){"
                                "this.__hiveChangeFired=true;},{once:true});}"
                            ),
                        },
                    )
            except Exception:
                object_id = None

            await bridge._cdp(
                target_tab,
                "DOM.setFileInputFiles",
                {"files": file_paths, "nodeId": node_id},
            )

            # Read back the acceptance signal: did `change` fire, and what files
            # does the input hold now (may be empty if the page consumed them).
            accepted = None
            if object_id:
                try:
                    rb = await bridge._cdp(
                        target_tab,
                        "Runtime.callFunctionOn",
                        {
                            "objectId": object_id,
                            "returnByValue": True,
                            "functionDeclaration": (
                                "function(){return {change_fired:!!this.__hiveChangeFired,"
                                "files:Array.prototype.slice.call(this.files).map("
                                "function(f){return {name:f.name,size:f.size,type:f.type};})};}"
                            ),
                        },
                    )
                    accepted = rb.get("result", {}).get("value")
                except Exception:
                    accepted = None

            return {
                "ok": True,
                "action": "upload",
                "selector": selector,
                "files": file_paths,
                "count": len(file_paths),
                # Acceptance signal: change_fired=True means the page's onchange
                # ran (the upload was observed by the site). `accepted.files` is
                # what the input holds now — empty is normal for sites that clear
                # the input after consuming it. None = couldn't read it back.
                "accepted": accepted,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            if intercept_enabled:
                try:
                    await bridge._cdp(
                        target_tab,
                        "Page.setInterceptFileChooserDialog",
                        {"enabled": False},
                    )
                except Exception:
                    pass

    @mcp.tool()
    async def browser_dialog_respond(
        action: Annotated[
            Literal["accept", "dismiss"],
            Field(
                description=(
                    "How to resolve the dialog. "
                    "'accept' clicks the affirmative button: for `beforeunload` this "
                    "DISCARDS work and leaves the page; for `confirm` returns true; "
                    "for `prompt` returns `prompt_text`. "
                    "'dismiss' cancels the dialog: for `beforeunload` the page stays."
                )
            ),
        ],
        tab_id: int | None = None,
        profile: str | None = None,
        prompt_text: Annotated[
            str | None,
            Field(description="Response text for `window.prompt` dialogs only. Ignored otherwise."),
        ] = None,
    ) -> dict:
        """
        Respond to the pending native browser dialog on a tab.

        Use this when a navigation/reload/back tool returns
        ``{"ok": false, "pending_dialog": {...}}``. The agent picks
        ``action="accept"`` to proceed (e.g. leave the page and lose
        unsaved work) or ``action="dismiss"`` to cancel (stay on the
        page). The pending dialog's ``type`` and ``message`` are
        included in that return envelope so the agent has context to
        decide.

        Args:
            action: "accept" or "dismiss".
            tab_id: Chrome tab ID (default: active tab).
            profile: Browser profile name (default: "default").
            prompt_text: Only used when the pending dialog is a
                ``window.prompt`` and ``action="accept"``.

        Returns:
            ``{"ok": true, "tab_id": ..., "dialog": {...resolved dialog...}}``
            on success. ``{"ok": false, "error": "..."}`` if no dialog
            is pending or the tab can't be resolved.
        """
        start = time.perf_counter()
        params = {
            "action": action,
            "tab_id": tab_id,
            "profile": profile,
            "prompt_text": prompt_text,
        }

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_dialog_respond", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {
                "ok": False,
                "error": "Browser not started. Call browser_open(url) first to open a tab.",
            }
            log_tool_call("browser_dialog_respond", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_dialog_respond", params, result=result)
            return result

        # NOTE: deliberately no "is a dialog pending?" pre-check. A dialog
        # can be open on the tab without the bridge having a record of it —
        # the Page.javascriptDialogOpening event was missed, or the dialog
        # opened against a previous bridge instance before an MCP-server
        # restart. This tool is the agent's escape hatch for a wedged
        # browser, so it must always attempt the recovery. handle_javascript_
        # dialog translates Chrome's "no dialog showing" into a clean result.
        try:
            nav_result = await bridge.handle_javascript_dialog(
                target_tab,
                accept=(action == "accept"),
                prompt_text=prompt_text,
            )
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
                "browser_dialog_respond",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=("dialog", action),
            )
            return result
