"""
Browser inspection tools - screenshot, snapshot, console.

All operations go through the Beeline extension via CDP - no Playwright required.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Literal

from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from ..bridge import get_bridge
from ..telemetry import log_tool_call
from .tabs import _get_context

logger = logging.getLogger(__name__)


def register_inspection_tools(mcp: FastMCP) -> None:
    """Register browser inspection tools."""

    @mcp.tool()
    async def browser_screenshot(
        tab_id: int | None = None,
        profile: str | None = None,
        full_page: bool = False,
        selector: str | None = None,
        image_type: Literal["png", "jpeg"] = "png",
    ) -> list:
        """
        Take a screenshot of the current page.

        Returns the screenshot as an image the LLM can see, alongside
        text metadata (URL, size, etc.).

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            full_page: Capture full scrollable page (default: False)
            selector: CSS selector to screenshot element (optional - not supported)
            image_type: Image format - png or jpeg (default: png)

        Returns:
            List of content blocks: text metadata + image
        """
        start = time.perf_counter()
        params = {
            "tab_id": tab_id,
            "profile": profile,
            "full_page": full_page,
            "selector": selector,
        }

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = [
                TextContent(
                    type="text",
                    text=json.dumps({"ok": False, "error": "Extension not connected"}),
                )
            ]
            log_tool_call(
                "browser_screenshot",
                params,
                result={"ok": False, "error": "Extension not connected"},
            )
            return result

        ctx = _get_context(profile)
        if not ctx:
            err_msg = json.dumps({"ok": False, "error": "Browser not started"})
            log_tool_call(
                "browser_screenshot", params, result={"ok": False, "error": "Browser not started"}
            )
            return [TextContent(type="text", text=err_msg)]

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = [
                TextContent(type="text", text=json.dumps({"ok": False, "error": "No active tab"}))
            ]
            log_tool_call(
                "browser_screenshot", params, result={"ok": False, "error": "No active tab"}
            )
            return result

        try:
            if selector:
                logger.warning("Element screenshots not supported, capturing full page")

            screenshot_result = await bridge.screenshot(target_tab, full_page=full_page)

            if not screenshot_result.get("ok"):
                log_tool_call(
                    "browser_screenshot",
                    params,
                    result=screenshot_result,
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
                return [TextContent(type="text", text=json.dumps(screenshot_result))]

            data = screenshot_result.get("data")
            mime_type = screenshot_result.get("mimeType", "image/png")

            meta = json.dumps(
                {
                    "ok": True,
                    "tabId": target_tab,
                    "url": screenshot_result.get("url", ""),
                    "imageType": mime_type.split("/")[-1],
                    "size": len(base64.b64decode(data)) if data else 0,
                    "fullPage": full_page,
                }
            )

            log_tool_call(
                "browser_screenshot",
                params,
                result={
                    "ok": True,
                    "size": len(base64.b64decode(data)) if data else 0,
                    "url": screenshot_result.get("url", ""),
                },
                duration_ms=(time.perf_counter() - start) * 1000,
            )

            return [
                TextContent(type="text", text=meta),
                ImageContent(type="image", data=data, mimeType=mime_type),
            ]
        except Exception as e:
            log_tool_call(
                "browser_screenshot",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return [TextContent(type="text", text=json.dumps({"ok": False, "error": str(e)}))]

    @mcp.tool()
    async def browser_snapshot(
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Get an accessibility snapshot of the page.

        Uses CDP Accessibility.getFullAXTree to build a compact, readable
        tree of the page's interactive elements. Ideal for LLM consumption.

        Output format example:
            - navigation "Main":
              - link "Home" [ref=e1]
              - link "About" [ref=e2]
            - main:
              - heading "Welcome"
              - textbox "Search" [ref=e3]

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with the snapshot text tree, URL, and tab ID
        """
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_snapshot", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_snapshot", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_snapshot", params, result=result)
            return result

        try:
            snapshot_result = await bridge.snapshot(target_tab)
            log_tool_call(
                "browser_snapshot",
                params,
                result=snapshot_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return snapshot_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_snapshot",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

    @mcp.tool()
    async def browser_console(
        tab_id: int | None = None,
        profile: str | None = None,
        level: str | None = None,
    ) -> dict:
        """
        Get console messages from the browser.

        Note: Console capture requires Runtime.enable and event handling.
        Currently returns a message indicating this feature needs implementation.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            level: Filter by level (log, info, warn, error) (optional)

        Returns:
            Dict with console messages
        """
        result = {
            "ok": True,
            "message": "Console capture not yet implemented",
            "suggestion": "Use browser_evaluate to check specific values or errors",
        }
        log_tool_call(
            "browser_console", {"tab_id": tab_id, "profile": profile, "level": level}, result=result
        )
        return result

    @mcp.tool()
    async def browser_html(
        tab_id: int | None = None,
        profile: str | None = None,
        selector: str | None = None,
    ) -> dict:
        """
        Get the HTML content of the page or a specific element.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            selector: CSS selector to get specific element HTML (optional)

        Returns:
            Dict with HTML content
        """
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile, "selector": selector}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_html", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_html", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_html", params, result=result)
            return result

        try:
            import json as json_mod

            if selector:
                sel_json = json_mod.dumps(selector)
                script = (
                    f"(function() {{ const el = document.querySelector({sel_json}); "
                    f"return el ? el.outerHTML : null; }})()"
                )
            else:
                script = "document.documentElement.outerHTML"

            eval_result = await bridge.evaluate(target_tab, script)

            if eval_result.get("ok"):
                result = {
                    "ok": True,
                    "tabId": target_tab,
                    "html": eval_result.get("result"),
                    "selector": selector,
                }
                log_tool_call(
                    "browser_html",
                    params,
                    result={
                        "ok": True,
                        "selector": selector,
                        "html_length": len(eval_result.get("result") or ""),
                    },
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
                return result
            log_tool_call(
                "browser_html",
                params,
                result=eval_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return eval_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_html", params, error=e, duration_ms=(time.perf_counter() - start) * 1000
            )
            return result
