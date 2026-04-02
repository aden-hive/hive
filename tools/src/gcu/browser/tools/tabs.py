"""
Browser tab management tools - tabs, open, close, focus.

All operations go through the Beeline extension - no Playwright required.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from ..bridge import get_bridge
from .lifecycle import _contexts

logger = logging.getLogger(__name__)


def _get_context(profile: str | None = None) -> dict[str, Any] | None:
    """Get the context for a profile."""
    profile_name = profile or "default"
    return _contexts.get(profile_name)


def register_tab_tools(mcp: FastMCP) -> None:
    """Register browser tab management tools."""

    @mcp.tool()
    async def browser_tabs(profile: str | None = None) -> dict:
        """
        List all open browser tabs in the agent's tab group.

        Each tab includes:
        - ``id``: Chrome tab ID (integer)
        - ``url``: Current URL
        - ``title``: Page title
        - ``groupId``: Chrome tab group ID

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with list of tabs and counts
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started. Call browser_start first."}

        try:
            result = await bridge.list_tabs(ctx.get("groupId"))
            tabs = result.get("tabs", [])

            return {
                "ok": True,
                "tabs": tabs,
                "total": len(tabs),
                "activeTabId": ctx.get("activeTabId"),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_open(
        url: str,
        background: bool = False,
        profile: str | None = None,
    ) -> dict:
        """
        Open a new browser tab and navigate to the given URL.

        The tab is automatically added to the agent's tab group.
        This tool waits for the page to load before returning.

        Args:
            url: URL to navigate to
            background: Open in background without stealing focus (default: False)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with new tab info (id, url, title)
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started. Call browser_start first."}

        try:
            # Create tab in the group
            result = await bridge.create_tab(url=url, group_id=ctx.get("groupId"))
            tab_id = result.get("tabId")

            # Update active tab if not background
            if not background and tab_id is not None:
                ctx["activeTabId"] = tab_id
                await bridge.activate_tab(tab_id)

            # Navigate and wait for load
            nav_result = await bridge.navigate(tab_id, url, wait_until="load")

            return {
                "ok": True,
                "tabId": tab_id,
                "url": nav_result.get("url", url),
                "title": nav_result.get("title", ""),
                "background": background,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_close(
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Close a browser tab.

        Args:
            tab_id: Chrome tab ID to close (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with close status
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started. Call browser_start first."}

        # Use active tab if not specified
        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No tab to close"}

        try:
            await bridge.close_tab(target_tab)

            # Update active tab if we closed it
            if ctx.get("activeTabId") == target_tab:
                result = await bridge.list_tabs(ctx.get("groupId"))
                tabs = result.get("tabs", [])
                ctx["activeTabId"] = tabs[0].get("id") if tabs else None

            return {"ok": True, "closed": target_tab}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_focus(tab_id: int, profile: str | None = None) -> dict:
        """
        Focus a browser tab.

        Args:
            tab_id: Chrome tab ID to focus
            profile: Browser profile name (default: "default")

        Returns:
            Dict with focus status
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started. Call browser_start first."}

        try:
            await bridge.activate_tab(tab_id)
            ctx["activeTabId"] = tab_id
            return {"ok": True, "tabId": tab_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_close_all(
        keep_active: bool = True,
        profile: str | None = None,
    ) -> dict:
        """
        Close all browser tabs in the agent's group, optionally keeping active.

        Args:
            keep_active: If True (default), keep the active tab open.
                If False, close ALL tabs (group remains but empty).
            profile: Browser profile name (default: "default")

        Returns:
            Dict with number of closed tabs and remaining count
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started. Call browser_start first."}

        try:
            result = await bridge.list_tabs(ctx.get("groupId"))
            tabs = result.get("tabs", [])
            active_tab_id = ctx.get("activeTabId")

            closed = 0
            for tab in tabs:
                tid = tab.get("id")
                if keep_active and tid == active_tab_id:
                    continue
                try:
                    await bridge.close_tab(tid)
                    closed += 1
                except Exception:
                    pass

            # Update active tab
            if not keep_active:
                ctx["activeTabId"] = None
            else:
                result = await bridge.list_tabs(ctx.get("groupId"))
                remaining = result.get("tabs", [])
                ctx["activeTabId"] = remaining[0].get("id") if remaining else None

            return {
                "ok": True,
                "closed_count": closed,
                "remaining": len(tabs) - closed,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_close_finished(
        keep_active: bool = True,
        profile: str | None = None,
    ) -> dict:
        """
        Close all tabs except the active one.

        This is a convenience wrapper around browser_close_all.

        Args:
            keep_active: If True (default), keep the active tab open.
            profile: Browser profile name (default: "default")

        Returns:
            Dict with closed_count, skipped_count, and remaining tab count
        """
        return await browser_close_all(keep_active=keep_active, profile=profile)
