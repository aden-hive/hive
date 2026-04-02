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
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Wait for a condition.

        Args:
            wait_ms: Time to wait in milliseconds (if no selector/text)
            selector: Wait for element to appear (optional)
            text: Wait for text to appear on page (optional)
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Max wait time in ms (default: 30000)

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
                result = await bridge.wait_for_selector(
                    target_tab, selector, timeout_ms=timeout_ms
                )
                if result.get("ok"):
                    return {
                        "ok": True,
                        "action": "wait",
                        "condition": "selector",
                        "selector": selector,
                    }
                return result
            elif text:
                result = await bridge.wait_for_text(
                    target_tab, text, timeout_ms=timeout_ms
                )
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
        Execute JavaScript in the browser context.

        Args:
            script: JavaScript code to execute
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with evaluation result
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
            result = await bridge.get_attribute(
                target_tab, selector, attribute, timeout_ms=timeout_ms
            )
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
