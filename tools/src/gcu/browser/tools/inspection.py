"""
Browser inspection tools.

Provides tools for inspecting page content, taking screenshots, and evaluating JavaScript.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


async def browser_get_text(profile: str, selector: str) -> dict[str, Any]:
    """Get text content of an element matching the CSS selector.

    Args:
        profile: Unique identifier for the agent/profile
        selector: CSS selector for the element

    Returns:
        Dict with text content
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.get_text(tab_id, selector)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def browser_screenshot(profile: str, full_page: bool = False) -> dict[str, Any]:
    """Take a screenshot of the current page.

    Args:
        profile: Unique identifier for the agent/profile
        full_page: Whether to capture the full page or just viewport

    Returns:
        Dict with base64-encoded screenshot data
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.screenshot(tab_id, full_page)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


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


def register_inspection_tools(mcp: FastMCP) -> None:
    """Register browser inspection tools with the MCP server."""
    mcp.tool()(browser_get_text)
    mcp.tool()(browser_screenshot)
    mcp.tool()(browser_evaluate)
