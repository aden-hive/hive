"""
Browser lifecycle management tools.

Provides tools for starting, stopping, and managing browser sessions.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..bridge import BeelineBridge

# Global bridge instance - in production, this might be managed per agent
_bridge: BeelineBridge | None = None


def get_bridge() -> BeelineBridge:
    """Get or create the global bridge instance."""
    global _bridge
    if _bridge is None:
        _bridge = BeelineBridge()
    return _bridge


async def browser_start(profile: str) -> dict[str, Any]:
    """Start a browser session for the given profile.

    Args:
        profile: Unique identifier for the agent/profile (e.g., 'agent_1')

    Returns:
        Dict with session info including ok status and tab ID
    """
    bridge = get_bridge()
    try:
        result = await bridge.create_context(profile)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def browser_stop(profile: str) -> dict[str, Any]:
    """Stop the browser session for the given profile.

    Args:
        profile: Unique identifier for the agent/profile

    Returns:
        Dict with ok status
    """
    bridge = get_bridge()
    try:
        result = await bridge.destroy_context(profile)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def register_lifecycle_tools(mcp: FastMCP) -> None:
    """Register browser lifecycle management tools with the MCP server."""
    mcp.tool()(browser_start)
    mcp.tool()(browser_stop)
