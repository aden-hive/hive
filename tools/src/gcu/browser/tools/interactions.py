"""
Browser interaction tools - click, type, fill, press, hover, select, scroll, drag.

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


def register_interaction_tools(mcp: FastMCP) -> None:
    """Register browser interaction tools."""

    @mcp.tool()
    async def browser_click(
        selector: str,
        tab_id: int | None = None,
        profile: str | None = None,
        button: Literal["left", "right", "middle"] = "left",
        double_click: bool = False,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Click an element on the page.

        Args:
            selector: CSS selector for the element
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            button: Mouse button to click (left, right, middle)
            double_click: Perform double-click (default: False)
            timeout_ms: Timeout waiting for element (default: 30000)

        Returns:
            Dict with click result and coordinates
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
            result = await bridge.click(
                target_tab,
                selector,
                button=button,
                click_count=2 if double_click else 1,
                timeout_ms=timeout_ms,
            )
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_click_coordinate(
        x: float,
        y: float,
        tab_id: int | None = None,
        profile: str | None = None,
        button: Literal["left", "right", "middle"] = "left",
    ) -> dict:
        """
        Click at specific viewport coordinates.

        Args:
            x: X coordinate in the viewport
            y: Y coordinate in the viewport
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            button: Mouse button to click (left, right, middle)

        Returns:
            Dict with click result
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
            result = await bridge.click_coordinate(target_tab, x, y, button=button)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_type(
        selector: str,
        text: str,
        tab_id: int | None = None,
        profile: str | None = None,
        delay_ms: int = 0,
        clear_first: bool = True,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Type text into an input element.

        Args:
            selector: CSS selector for the input element
            text: Text to type
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            delay_ms: Delay between keystrokes in ms (default: 0)
            clear_first: Clear existing text before typing (default: True)
            timeout_ms: Timeout waiting for element (default: 30000)

        Returns:
            Dict with type result
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
            result = await bridge.type_text(
                target_tab,
                selector,
                text,
                clear_first=clear_first,
                delay_ms=delay_ms,
                timeout_ms=timeout_ms,
            )
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_fill(
        selector: str,
        value: str,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Fill an input element with a value (clears existing content first).

        Faster than browser_type for filling form fields.

        Args:
            selector: CSS selector for the input element
            value: Value to fill
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout waiting for element (default: 30000)

        Returns:
            Dict with fill result
        """
        return await browser_type(
            selector=selector,
            text=value,
            tab_id=tab_id,
            profile=profile,
            delay_ms=0,
            clear_first=True,
            timeout_ms=timeout_ms,
        )

    @mcp.tool()
    async def browser_press(
        key: str,
        selector: str | None = None,
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Press a keyboard key.

        Args:
            key: Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown')
            selector: Focus element first (optional)
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with press result
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
            result = await bridge.press_key(target_tab, key, selector=selector)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_hover(
        selector: str,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Hover over an element.

        Args:
            selector: CSS selector for the element
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout waiting for element (default: 30000)

        Returns:
            Dict with hover result
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
            result = await bridge.hover(target_tab, selector, timeout_ms=timeout_ms)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_select(
        selector: str,
        values: list[str],
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Select option(s) in a dropdown/select element.

        Args:
            selector: CSS selector for the select element
            values: List of values to select
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with select result
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
            result = await bridge.select_option(target_tab, selector, values)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_scroll(
        direction: Literal["up", "down", "left", "right"] = "down",
        amount: int = 500,
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Scroll the page.

        Args:
            direction: Scroll direction (up, down, left, right)
            amount: Scroll amount in pixels (default: 500)
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with scroll result
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
            result = await bridge.scroll(target_tab, direction=direction, amount=amount)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def browser_drag(
        start_selector: str,
        end_selector: str,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Drag from one element to another.

        Note: This is implemented via CDP mouse events and may not work
        for all drag-and-drop scenarios (e.g., HTML5 drag-drop).

        Args:
            start_selector: CSS selector for drag start element
            end_selector: CSS selector for drag end element
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout waiting for elements (default: 30000)

        Returns:
            Dict with drag result
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
            # Get coordinates for both elements and perform drag via CDP
            await bridge.cdp_attach(target_tab)
            await bridge._cdp(target_tab, "DOM.enable")
            await bridge._cdp(target_tab, "Input.enable")

            doc = await bridge._cdp(target_tab, "DOM.getDocument")
            root_id = doc.get("root", {}).get("nodeId")

            deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
            start_node = None
            while asyncio.get_event_loop().time() < deadline:
                result = await bridge._cdp(
                    target_tab,
                    "DOM.querySelector",
                    {"nodeId": root_id, "selector": start_selector},
                )
                start_node = result.get("nodeId")
                if start_node:
                    break
                await asyncio.sleep(0.1)

            if not start_node:
                return {"ok": False, "error": f"Start element not found: {start_selector}"}

            end_node = None
            while asyncio.get_event_loop().time() < deadline:
                result = await bridge._cdp(
                    target_tab,
                    "DOM.querySelector",
                    {"nodeId": root_id, "selector": end_selector},
                )
                end_node = result.get("nodeId")
                if end_node:
                    break
                await asyncio.sleep(0.1)

            if not end_node:
                return {"ok": False, "error": f"End element not found: {end_selector}"}

            # Get box models
            start_box = await bridge._cdp(
                target_tab, "DOM.getBoxModel", {"nodeId": start_node}
            )
            end_box = await bridge._cdp(
                target_tab, "DOM.getBoxModel", {"nodeId": end_node}
            )

            sc = start_box.get("content", [])
            ec = end_box.get("content", [])

            start_x = (sc[0] + sc[2] + sc[4] + sc[6]) / 4
            start_y = (sc[1] + sc[3] + sc[5] + sc[7]) / 4
            end_x = (ec[0] + ec[2] + ec[4] + ec[6]) / 4
            end_y = (ec[1] + ec[3] + ec[5] + ec[7]) / 4

            # Perform drag: mouse down at start, move to end, mouse up
            await bridge._cdp(
                target_tab,
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    "x": start_x,
                    "y": start_y,
                    "button": "left",
                    "clickCount": 1,
                },
            )
            await bridge._cdp(
                target_tab,
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": end_x, "y": end_y},
            )
            await bridge._cdp(
                target_tab,
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    "x": end_x,
                    "y": end_y,
                    "button": "left",
                    "clickCount": 1,
                },
            )

            return {
                "ok": True,
                "action": "drag",
                "from": start_selector,
                "to": end_selector,
                "fromCoords": {"x": start_x, "y": start_y},
                "toCoords": {"x": end_x, "y": end_y},
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
