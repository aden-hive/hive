"""``hive-browser interact | select | upload`` — mirror of ``browser_interact`` /
``browser_select`` / ``browser_upload``.

``interact`` reuses the module-level ``_dispatch`` in ``gcu/browser/tools/interact.py``
verbatim (the action dispatcher is the single source of truth), then collapses its
content-block return into a JSON dict — spilling any screenshot/zoom image to a file
+ ``_image`` marker the framework re-inlines into the session."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time

from gcu.browser.bridge import connection_error, get_bridge
from gcu.browser.telemetry import log_tool_call
from gcu.browser.tools.interact import _dispatch, _interact_action
from gcu.browser.tools.tabs import _get_context


def _blocks_to_cli_dict(result, *, intent: str | None = None) -> dict:
    """Collapse ``_dispatch``'s dict-or-content-block-list return into a JSON dict.

    A screenshot / zoom / coordinate-click returns an inline ``ImageContent``;
    the CLI can't carry that, so the JPEG is spilled to a file and referenced via
    ``saved_to`` + an ``_image`` marker (re-inlined by the framework)."""
    from mcp.types import ImageContent, TextContent

    if isinstance(result, dict):
        return result

    meta: dict = {"ok": True}
    image_data: str | None = None
    for block in result:
        if isinstance(block, TextContent):
            try:
                meta = json.loads(block.text)
            except Exception:
                meta = {"ok": True, "text": block.text}
        elif isinstance(block, ImageContent):
            image_data = block.data

    if image_data:
        from gcu.browser.tools.inspection import _write_browser_artifact_bytes

        tab = meta.get("tabId") or 0
        path = _write_browser_artifact_bytes("browser_interact", tab, base64.b64decode(image_data), ".jpg")
        meta = {**meta, "saved_to": str(path), "_image": {"path": str(path), "mime": "image/jpeg", "intent": intent}}
    return meta


async def cmd_interact(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    action = args.action
    log_params = {"action": action, "tab_id": args.tab, "profile": args.profile, "selector": args.selector}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        err = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_interact", log_params, result=err)
        return err

    ctx = _get_context(args.profile)
    if not ctx:
        err = {"ok": False, "error": "Browser not started. Run `hive-browser open <url>` first to open a tab."}
        log_tool_call("browser_interact", log_params, result=err)
        return err

    target_tab = args.tab or ctx.get("activeTabId")
    if target_tab is None:
        err = {"ok": False, "error": "No active tab"}
        log_tool_call("browser_interact", log_params, result=err)
        return err

    try:
        result = await _dispatch(
            action,
            bridge,
            target_tab,
            selector=args.selector,
            coordinate=args.coordinate,
            start_selector=args.start_selector,
            start_coordinate=args.start_coordinate,
            text=args.text,
            clear_first=not args.no_clear_first,
            use_insert_text=not args.no_insert_text,
            modifiers=args.modifiers,
            repeat=args.repeat,
            scroll_direction=args.scroll_direction,
            scroll_amount=args.scroll_amount,
            intent=args.intent,
            full_page=args.full_page,
            annotate=not args.no_annotate,
            region=args.region,
            duration=args.duration,
            wait_for_selector=args.wait_for_selector,
            wait_for_text=args.wait_for_text,
            timeout_ms=args.timeout_ms,
            auto_snapshot_mode=args.auto_snapshot_mode,
            wait_after_ms=args.wait_after_ms,
            log_params=log_params,
            start=start,
        )
        out = _blocks_to_cli_dict(result, intent=args.intent)
        history_action = _interact_action(
            action,
            args.selector,
            args.coordinate,
            args.start_selector,
            args.start_coordinate,
            args.text,
            args.scroll_direction,
            args.wait_for_selector,
            args.wait_for_text,
            args.duration,
        )
        log_tool_call(
            "browser_interact",
            log_params,
            result={"ok": out.get("ok", True), "action": action},
            duration_ms=(time.perf_counter() - start) * 1000,
            tab_id=target_tab,
            action=history_action,
        )
        return out
    except Exception as e:
        err = {"ok": False, "error": str(e)}
        log_tool_call("browser_interact", log_params, error=e, duration_ms=(time.perf_counter() - start) * 1000, tab_id=target_tab)
        return err


async def cmd_select(args: argparse.Namespace) -> dict:
    from gcu.browser.tools.interact import _truncate_target

    start = time.perf_counter()
    values = args.value
    params = {"selector": args.selector, "values": values, "tab_id": args.tab, "profile": args.profile}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_select", params, result=result)
        return result

    ctx = _get_context(args.profile)
    if not ctx:
        result = {"ok": False, "error": "Browser not started. Run `hive-browser open <url>` first to open a tab."}
        log_tool_call("browser_select", params, result=result)
        return result

    target_tab = args.tab or ctx.get("activeTabId")
    if target_tab is None:
        result = {"ok": False, "error": "No active tab"}
        log_tool_call("browser_select", params, result=result)
        return result

    select_target = _truncate_target(f"{args.selector} = {', '.join(values)}" if values else args.selector)
    try:
        select_result = await bridge.select_option(target_tab, args.selector, values)
        log_tool_call(
            "browser_select",
            params,
            result=select_result,
            duration_ms=(time.perf_counter() - start) * 1000,
            tab_id=target_tab,
            action=("select", select_target),
        )
        return select_result
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        log_tool_call(
            "browser_select", params, error=e, duration_ms=(time.perf_counter() - start) * 1000, tab_id=target_tab, action=("select", select_target)
        )
        return result


async def cmd_upload(args: argparse.Namespace) -> dict:
    from pathlib import Path

    selector = args.selector
    file_paths = args.file
    trigger_selector = args.trigger_selector
    timeout_ms = args.timeout_ms

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        return {"ok": False, "error": connection_error(bridge)}

    ctx = _get_context(args.profile)
    if not ctx:
        return {"ok": False, "error": "Browser not started"}

    target_tab = args.tab or ctx.get("activeTabId")
    if target_tab is None:
        return {"ok": False, "error": "No active tab"}

    import base64
    import mimetypes

    # Read the files locally and set them on the input via a page-context
    # DataTransfer. Chrome's chrome.debugger (which the extension uses) BLOCKS
    # `DOM.setFileInputFiles` with "-32000 Not allowed" as an anti-exfiltration
    # measure, so that CDP path can never work here. Injecting the bytes as File
    # objects in the page does — and the CLI has local filesystem access to read
    # them (unlike the page).
    files_payload = []
    for p in file_paths:
        fp = Path(p).expanduser()
        if not fp.is_file():
            return {"ok": False, "error": f"File not found: {p}"}
        mime = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
        files_payload.append({"name": fp.name, "type": mime, "b64": base64.b64encode(fp.read_bytes()).decode()})

    # NOTE: these MUST be ARG-LESS IIFEs ending in `})()` — bridge.evaluate only
    # recognizes that form as "already wrapped" and returns its value; an
    # arg-passing IIFE (`})(args)`) is re-wrapped WITHOUT a return, so its value
    # is lost (that silently made the exists-poll spin the full timeout). Embed
    # the values in the body instead of passing them as arguments.
    inject_js = (
        "(function(){"
        "var selector=" + json.dumps(selector) + ";"
        "var files=" + json.dumps(files_payload) + ";"
        "var input=document.querySelector(selector);"
        "if(!input)return {found:false};"
        "if(input.tagName!=='INPUT'||input.type!=='file')return {found:true,not_file_input:true,tag:input.tagName,type:input.type};"
        "var dt=new DataTransfer();"
        "for(var i=0;i<files.length;i++){var f=files[i];var bin=atob(f.b64);"
        "var arr=new Uint8Array(bin.length);for(var j=0;j<bin.length;j++)arr[j]=bin.charCodeAt(j);"
        "dt.items.add(new File([arr],f.name,{type:f.type||'application/octet-stream'}));}"
        "var fired=false;input.addEventListener('change',function(){fired=true;},{once:true});"
        "input.files=dt.files;"
        "input.dispatchEvent(new Event('input',{bubbles:true}));"
        "input.dispatchEvent(new Event('change',{bubbles:true}));"
        "return {found:true,count:dt.files.length,change_fired:fired,"
        "files:Array.prototype.slice.call(input.files).map(function(x){return {name:x.name,size:x.size,type:x.type};})};"
        "})()"
    )
    exists_js = "(function(){var e=document.querySelector(" + json.dumps(selector) + ");return !!(e&&e.tagName==='INPUT'&&e.type==='file');})()"

    intercept_enabled = False
    try:
        # Trigger mode: the input is created on demand and clicking it opens the
        # native OS picker. Intercept the picker so it doesn't block the tab,
        # then click to materialize the (lazily-created) input.
        if trigger_selector:
            await bridge.cdp_attach(target_tab)
            await bridge._cdp(target_tab, "Page.enable")
            await bridge._cdp(target_tab, "Page.setInterceptFileChooserDialog", {"enabled": True})
            intercept_enabled = True
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
                return {"ok": False, "error": f"Trigger element not found: {trigger_selector}"}

        # Wait (cheaply) for the file input, then inject once.
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while True:
            ev = await bridge.evaluate(target_tab, exists_js)
            if (ev or {}).get("result"):
                break
            if asyncio.get_event_loop().time() >= deadline:
                return {"ok": False, "error": f"File input not found: {selector}"}
            await asyncio.sleep(0.1)

        ev = await bridge.evaluate(target_tab, inject_js)
        result = (ev or {}).get("result") or {}
        if result.get("not_file_input"):
            return {"ok": False, "error": f"{selector} is a <{result.get('tag')}> (type={result.get('type')}), not a file input"}
        if not result.get("found"):
            return {"ok": False, "error": f"File input not found: {selector}"}

        return {
            "ok": True,
            "action": "upload",
            "selector": selector,
            "files": [f["name"] for f in files_payload],
            "count": result.get("count", len(files_payload)),
            # change_fired=True means the page's onchange ran (the site observed
            # the upload); files is what the input holds now.
            "accepted": {"change_fired": result.get("change_fired"), "files": result.get("files")},
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if intercept_enabled:
            try:
                await bridge._cdp(target_tab, "Page.setInterceptFileChooserDialog", {"enabled": False})
            except Exception:
                pass
