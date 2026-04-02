"""
Browser inspection tools - screenshot, snapshot, console.

All operations go through the Beeline extension via CDP - no Playwright required.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Literal

from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from ..bridge import get_bridge
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
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"ok": False, "error": "Extension not connected"}),
                )
            ]

        ctx = _get_context(profile)
        if not ctx:
            err_msg = json.dumps({"ok": False, "error": "Browser not started"})
            return [TextContent(type="text", text=err_msg)]

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return [
                TextContent(type="text", text=json.dumps({"ok": False, "error": "No active tab"}))
            ]

        try:
            if selector:
                logger.warning("Element screenshots not supported, capturing full page")

            result = await bridge.screenshot(target_tab, full_page=full_page)

            if not result.get("ok"):
                return [TextContent(type="text", text=json.dumps(result))]

            data = result.get("data")
            mime_type = result.get("mimeType", "image/png")

            meta = json.dumps({
                "ok": True,
                "tabId": target_tab,
                "url": result.get("url", ""),
                "imageType": mime_type.split("/")[-1],
                "size": len(base64.b64decode(data)) if data else 0,
                "fullPage": full_page,
            })

            return [
                TextContent(type="text", text=meta),
                ImageContent(type="image", data=data, mimeType=mime_type),
            ]
        except Exception as e:
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
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started. Call browser_start first."}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        try:
            result = await bridge.snapshot(target_tab)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

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
        # Console capture requires subscribing to Runtime.consoleAPICalled events
        # which needs persistent event handling.
        return {
            "ok": True,
            "message": "Console capture not yet implemented",
            "suggestion": "Use browser_evaluate to check specific values or errors",
        }

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
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started. Call browser_start first."}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

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

            result = await bridge.evaluate(target_tab, script)

            if result.get("ok"):
                return {
                    "ok": True,
                    "tabId": target_tab,
                    "html": result.get("result"),
                    "selector": selector,
                }
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}
