"""
Browser lifecycle tools - start, stop, status.

These tools manage the browser context via the Beeline extension bridge.
No Playwright required - all operations go through the Chrome extension.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from ..bridge import get_bridge

logger = logging.getLogger(__name__)

# Track active contexts per profile
_contexts: dict[str, dict[str, Any]] = {}


def register_lifecycle_tools(mcp: FastMCP) -> None:
    """Register browser lifecycle management tools."""

    @mcp.tool()
    async def browser_status(profile: str | None = None) -> dict:
        """
        Get the current status of the browser.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with browser status
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {
                "ok": False,
                "error": "Browser extension not connected",
                "connected": False,
            }

        profile_name = profile or "default"
        ctx = _contexts.get(profile_name)

        if ctx:
            try:
                tabs_result = await bridge.list_tabs(ctx.get("groupId"))
                tabs = tabs_result.get("tabs", [])
                return {
                    "ok": True,
                    "connected": True,
                    "profile": profile_name,
                    "running": True,
                    "groupId": ctx.get("groupId"),
                    "activeTab": ctx.get("activeTabId"),
                    "tabs": len(tabs),
                }
            except Exception as e:
                return {
                    "ok": True,
                    "connected": True,
                    "profile": profile_name,
                    "running": False,
                    "error": str(e),
                }

        return {
            "ok": True,
            "connected": True,
            "profile": profile_name,
            "running": False,
            "tabs": 0,
        }

    @mcp.tool()
    async def browser_start(profile: str | None = None) -> dict:
        """
        Start a browser context for the given profile.

        Creates a tab group in the user's Chrome via the Beeline extension.
        No separate browser process is launched - uses the user's existing Chrome.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with start status including groupId and initial tabId
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {
                "ok": False,
                "error": (
                    "Browser extension not connected. "
                    "Install the Beeline extension and connect it."
                ),
            }

        profile_name = profile or "default"

        # Check if already running
        if profile_name in _contexts:
            ctx = _contexts[profile_name]
            return {
                "ok": True,
                "status": "already_running",
                "profile": profile_name,
                "groupId": ctx.get("groupId"),
                "activeTabId": ctx.get("activeTabId"),
            }

        try:
            result = await bridge.create_context(profile_name)
            group_id = result.get("groupId")
            tab_id = result.get("tabId")

            _contexts[profile_name] = {
                "groupId": group_id,
                "activeTabId": tab_id,
            }

            logger.info(
                "Started browser context '%s': groupId=%s, tabId=%s",
                profile_name,
                group_id,
                tab_id,
            )

            return {
                "ok": True,
                "status": "started",
                "profile": profile_name,
                "groupId": group_id,
                "activeTabId": tab_id,
            }
        except Exception as e:
            logger.exception("Failed to start browser context")
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_stop(profile: str | None = None) -> dict:
        """
        Stop the browser context and close all tabs in the group.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with stop status
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}

        profile_name = profile or "default"
        ctx = _contexts.pop(profile_name, None)

        if not ctx:
            return {"ok": True, "status": "not_running", "profile": profile_name}

        try:
            group_id = ctx.get("groupId")
            closed_tabs = 0
            if group_id is not None:
                result = await bridge.destroy_context(group_id)
                closed_tabs = result.get("closedTabs", 0)
                logger.info(
                    "Stopped browser context '%s': closed %d tabs",
                    profile_name,
                    closed_tabs,
                )

            return {
                "ok": True,
                "status": "stopped",
                "profile": profile_name,
                "closedTabs": closed_tabs,
            }
        except Exception as e:
            logger.exception("Failed to stop browser context")
            return {"ok": False, "error": str(e)}
