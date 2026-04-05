"""
Browser navigation tools.

Provides tools for navigating pages, going back/forward, and reloading.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


async def browser_open(profile: str, url: str, wait_until: str = "load") -> dict[str, Any]:
    """Navigate to a URL in the current tab for the profile.

    Args:
        profile: Unique identifier for the agent/profile
        url: URL to navigate to
        wait_until: When to consider navigation complete

    Returns:
        Dict with ok status and final URL
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.navigate(tab_id, url, wait_until)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def browser_go_back(profile: str) -> dict[str, Any]:
    """Go back in history in the current tab.

    Args:
        profile: Unique identifier for the agent/profile

    Returns:
        Dict with ok status
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.go_back(tab_id)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def browser_go_forward(profile: str) -> dict[str, Any]:
    """Go forward in history in the current tab.

    Args:
        profile: Unique identifier for the agent/profile

    Returns:
        Dict with ok status
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.go_forward(tab_id)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def browser_reload(profile: str) -> dict[str, Any]:
    """Reload the current page in the current tab.

    Args:
        profile: Unique identifier for the agent/profile

    Returns:
        Dict with ok status
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.reload(tab_id)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def register_navigation_tools(mcp: FastMCP) -> None:
    """Register browser navigation tools with the MCP server."""
    mcp.tool()(browser_open)
    mcp.tool()(browser_go_back)
    mcp.tool()(browser_go_forward)
    mcp.tool()(browser_reload)
