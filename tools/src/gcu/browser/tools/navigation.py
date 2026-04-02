"""
Browser navigation tools - navigate, go_back, go_forward, reload.

All operations go through the Beeline extension via CDP.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastmcp import FastMCP

from ..bridge import get_bridge
from .tabs import _get_context

logger = logging.getLogger(__name__)


def register_navigation_tools(mcp: FastMCP) -> None:
    """Register browser navigation tools."""

    @mcp.tool()
    async def browser_navigate(
        url: str,
        tab_id: int | None = None,
        profile: str | None = None,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "load",
    ) -> dict:
        """
        Navigate a tab to a URL.

        This tool waits for the page to reach the ``wait_until`` condition
        before returning.

        Args:
            url: URL to navigate to
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            wait_until: Wait condition - one of: commit, domcontentloaded,
                load (default), networkidle

        Returns:
            Dict with navigation result (url, title)
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started. Call browser_start first."}

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab. Open a tab first with browser_open."}

        try:
            result = await bridge.navigate(target_tab, url, wait_until=wait_until)
            return {
                "ok": True,
                "tabId": target_tab,
                "url": result.get("url"),
                "title": result.get("title"),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_go_back(
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Navigate back in browser history.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with navigation result
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
            result = await bridge.go_back(target_tab)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_go_forward(
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Navigate forward in browser history.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with navigation result
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
            result = await bridge.go_forward(target_tab)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_reload(
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Reload the current page.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with reload result
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
            result = await bridge.reload(target_tab)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}
