"""
Advanced browser tools.

Provides tools for waiting, resizing, file uploads, dialog handling, and CDP operations.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


async def browser_evaluate(profile: str, script: str) -> dict[str, Any]:
    """Evaluate JavaScript in the page context.

    Args:
        profile: Unique identifier for the agent/profile
        script: JavaScript code to execute

    Returns:
        Dict with evaluation result
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.evaluate(tab_id, script)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def register_advanced_tools(mcp: FastMCP) -> None:
    """Register advanced browser tools with the MCP server."""
    mcp.tool()(browser_evaluate)
