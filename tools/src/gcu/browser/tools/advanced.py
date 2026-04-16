"""
Browser advanced tools - wait, evaluate, get_text, get_attribute, resize, dialog.

All operations go through the Beeline extension via CDP - no Playwright required.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastmcp import FastMCP

from ..bridge import get_bridge
from .tabs import _get_context

logger = logging.getLogger(__name__)


def register_advanced_tools(mcp: FastMCP) -> None:
    """Register browser advanced tools."""

    @mcp.tool()
    async def browser_wait(
        wait_ms: int = 1000,
        selector: str | None = None,
        text: str | None = None,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 5000,
    ) -> dict:
        """
        Wait for a condition.

        Args:
            wait_ms: Time to wait in milliseconds (if no selector/text)
            selector: Wait for element to appear (optional)
            text: Wait for text to appear on page (optional)
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Max wait time in ms for the selector/text poll.
                Default 5000ms (fast-fail). If the condition isn't met
                within 5s the call returns {"ok": False, "error": ...}
                and the agent can try a different approach instead of
                burning 30s per miss. Pass a larger value (e.g. 15000)
                only when you genuinely expect the element to take
                longer than 5s to render.

        Returns:
            Dict with wait result
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        try:
            if selector:
                result = await bridge.wait_for_selector(target_tab, selector, timeout_ms=timeout_ms)
                if result.get("ok"):
                    return {
                        "ok": True,
                        "action": "wait",
                        "condition": "selector",
                        "selector": selector,
                    }
                return result
            elif text:
                result = await bridge.wait_for_text(target_tab, text, timeout_ms=timeout_ms)
                if result.get("ok"):
                    return {
                        "ok": True,
                        "action": "wait",
                        "condition": "text",
                        "text": text,
                    }
                return result
            else:
                await asyncio.sleep(wait_ms / 1000)
                return {"ok": True, "action": "wait", "condition": "time", "ms": wait_ms}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_evaluate(
        script: str,
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        ESCAPE HATCH — execute raw JavaScript. USE ONLY as a last
        resort. 99% of browser automation does NOT need this tool.
        Before reaching for it, try a semantic tool first:

          - browser_click / browser_click_coordinate  → for clicks
          - browser_type(use_insert_text=True)        → for text input
          - browser_screenshot + browser_get_rect     → for locating elements
          - browser_shadow_query                      → for shadow-DOM selectors
          - browser_get_text / browser_get_attribute  → for reading state

        ANTI-PATTERNS — stop and switch tools if you notice yourself:

          1. Calling browser_evaluate 2+ times in a row to guess at
             selectors. Each attempt costs ~30 tokens of JS + a full
             LLM round-trip. After 2 empty results, the selector
             strategy is wrong — pivot to browser_screenshot +
             browser_click_coordinate. The screenshot + coord path
             works on shadow DOM, iframes, and React-obfuscated
             class names indifferently.

          2. Writing a walk(root) recursive shadow-DOM traversal
             function. Use browser_shadow_query — it does the
             traversal in C++ via CDP's querySelector, not in JS.

          3. Calling document.execCommand('insertText', ...) to type
             into Lexical / contenteditable. Use
             browser_type(use_insert_text=True, text='...') instead.
             It handles the click-then-focus-then-insert sequence
             with built-in retries.

          4. Trying to read a nested iframe's contentDocument. That
             usually fails (cross-origin or late hydration). Use
             browser_screenshot to see it, then browser_click_coordinate.

        LEGITIMATE uses (when nothing semantic fits):

          - Reading a computed style, window size, or scroll position
            that no tool exposes.
          - Firing a one-shot site-specific API call (e.g. an analytics
            beacon the test needs).
          - Stripping an onbeforeunload handler that blocks navigation.
          - Probing for shadow roots whose existence is conditional.

        Args:
            script: JavaScript code to execute. Keep it small. If you
                need to traverse the DOM, prefer browser_shadow_query.
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with evaluation result. On a "find X" script that
            returns [] or null: do NOT retry with a different
            selector — take a screenshot and switch to coordinates.
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

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
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_get_text(
        selector: str,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Get text content of an element.

        Args:
            selector: CSS selector
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with element text content
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

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

    @mcp.tool()
    async def browser_get_attribute(
        selector: str,
        attribute: str,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Get an attribute value of an element.

        Args:
            selector: CSS selector
            attribute: Attribute name to get (e.g., 'href', 'src')
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with attribute value
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        try:
            result = await bridge.get_attribute(target_tab, selector, attribute, timeout_ms=timeout_ms)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_resize(
        width: int,
        height: int,
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Resize the browser viewport.

        Args:
            width: Viewport width in pixels
            height: Viewport height in pixels
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with resize result
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        try:
            result = await bridge.resize(target_tab, width, height)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_upload(
        selector: str,
        file_paths: list[str],
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Upload files to a file input element.

        Note: File upload via CDP requires extension file access.
        This may require additional extension permissions.

        Args:
            selector: CSS selector for the file input
            file_paths: List of file paths to upload
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in ms (default: 30000)

        Returns:
            Dict with upload result
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        try:
            from pathlib import Path

            for path in file_paths:
                if not Path(path).exists():
                    return {"ok": False, "error": f"File not found: {path}"}

            await bridge.cdp_attach(target_tab)
            await bridge._cdp(target_tab, "DOM.enable")

            doc = await bridge._cdp(target_tab, "DOM.getDocument")
            root_id = doc.get("root", {}).get("nodeId")

            deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
            node_id = None
            while asyncio.get_event_loop().time() < deadline:
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

            await bridge._cdp(
                target_tab,
                "DOM.setFileInputFiles",
                {"files": file_paths, "nodeId": node_id},
            )

            return {
                "ok": True,
                "action": "upload",
                "selector": selector,
                "files": file_paths,
                "count": len(file_paths),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_dialog(
        action: Literal["accept", "dismiss"] = "accept",
        prompt_text: str | None = None,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Handle browser dialogs (alert, confirm, prompt).

        Note: Dialog handling via CDP requires Page.javascriptDialogOpening
        event handling. This sets up a one-time handler.

        Call BEFORE triggering the action that opens the dialog.

        Args:
            action: How to handle - "accept" or "dismiss"
            prompt_text: Text for prompt dialogs (optional)
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in ms (default: 30000)

        Returns:
            Dict with dialog handling result
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        try:
            await bridge.cdp_attach(target_tab)
            await bridge._cdp(target_tab, "Page.enable")

            return {
                "ok": True,
                "action": "handler_set",
                "message": "Dialog handler prepared.",
                "suggestion": "Handle dialogs manually or use browser_evaluate.",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
