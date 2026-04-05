"""
Browser tab management tools.

Provides tools for creating, listing, activating, and closing browser tabs.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


async def browser_tabs(profile: str) -> dict[str, Any]:
    """List all tabs in the browser session for the given profile.

    Args:
        profile: Unique identifier for the agent/profile

    Returns:
        Dict with list of tabs, each containing id, url, and title
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    try:
        result = await bridge.list_tabs(profile)
        return result
    except Exception as e:
        return {"tabs": [], "error": str(e)}


async def browser_close_tab(tab_id: int, profile: str) -> dict[str, Any]:
    """Close the specified tab in the browser session.

    Args:
        tab_id: ID of the tab to close
        profile: Unique identifier for the agent/profile

    Returns:
        Dict with ok status
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    try:
        result = await bridge.close_tab(tab_id)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def register_tab_tools(mcp: FastMCP) -> None:
    """Register browser tab management tools with the MCP server."""
    mcp.tool()(browser_tabs)
    mcp.tool()(browser_close_tab)
