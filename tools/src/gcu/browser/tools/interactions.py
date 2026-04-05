"""
Browser interaction tools.

Provides tools for clicking, typing, scrolling, and other user interactions.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


async def browser_click(profile: str, selector: str) -> dict[str, Any]:
    """Click on an element matching the CSS selector.

    Args:
        profile: Unique identifier for the agent/profile
        selector: CSS selector for the element to click

    Returns:
        Dict with ok status
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.click(tab_id, selector)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def browser_type(profile: str, selector: str, text: str) -> dict[str, Any]:
    """Type text into an input element.

    Args:
        profile: Unique identifier for the agent/profile
        selector: CSS selector for the input element
        text: Text to type

    Returns:
        Dict with ok status
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.type_text(tab_id, selector, text)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def browser_press_key(profile: str, key: str) -> dict[str, Any]:
    """Press a keyboard key.

    Args:
        profile: Unique identifier for the agent/profile
        key: Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown', etc.)

    Returns:
        Dict with ok status
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.press_key(tab_id, key)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def browser_scroll(profile: str, direction: str, amount: int) -> dict[str, Any]:
    """Scroll the page.

    Args:
        profile: Unique identifier for the agent/profile
        direction: Direction to scroll ('up', 'down', 'left', 'right')
        amount: Amount to scroll in pixels

    Returns:
        Dict with ok status
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.scroll(tab_id, direction, amount)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def browser_select_option(profile: str, selector: str, values: list[str]) -> dict[str, Any]:
    """Select options in a select element.

    Args:
        profile: Unique identifier for the agent/profile
        selector: CSS selector for the select element
        values: List of option values to select

    Returns:
        Dict with ok status and selected values
    """
    from .lifecycle import get_bridge

    bridge = get_bridge()
    tab_id = bridge.get_current_tab(profile)
    if tab_id is None:
        return {"ok": False, "error": "No active tab for profile"}

    try:
        result = await bridge.select_option(tab_id, selector, values)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def register_interaction_tools(mcp: FastMCP) -> None:
    """Register browser interaction tools with the MCP server."""
    mcp.tool()(browser_click)
    mcp.tool()(browser_type)
    mcp.tool()(browser_press_key)
    mcp.tool()(browser_scroll)
    mcp.tool()(browser_select_option)
