"""
Browser interaction tools - click, type, fill, press, hover, select, scroll, drag.

Tools for interacting with page elements.
"""

from __future__ import annotations

from typing import Literal

from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
)

from ..session import DEFAULT_TIMEOUT_MS, get_session


def register_interaction_tools(mcp: FastMCP) -> None:
    """Register browser interaction tools."""

    @mcp.tool()
    async def browser_click(
        selector: str,
        target_id: str | None = None,
        profile: str = "default",
        button: Literal["left", "right", "middle"] = "left",
        double_click: bool = False,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Click an element on the page.

        Args:
            selector: CSS selector or element ref (e.g., 'e12' from snapshot)
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            button: Mouse button to click (left, right, middle)
            double_click: Perform double-click (default: False)
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with click result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            if double_click:
                await page.dblclick(selector, button=button, timeout=timeout_ms)
            else:
                await page.click(selector, button=button, timeout=timeout_ms)

            return {"ok": True, "action": "click", "selector": selector}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Click failed: {e!s}"}

    @mcp.tool()
    async def browser_type(
        selector: str,
        text: str,
        target_id: str | None = None,
        profile: str = "default",
        delay_ms: int = 0,
        clear_first: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Type text into an input element.

        Args:
            selector: CSS selector or element ref (e.g., 'e12' from snapshot)
            text: Text to type
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            delay_ms: Delay between keystrokes in ms (default: 0)
            clear_first: Clear existing text before typing (default: True)
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with type result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            if clear_first:
                await page.fill(selector, "", timeout=timeout_ms)

            await page.type(selector, text, delay=delay_ms, timeout=timeout_ms)
            return {"ok": True, "action": "type", "selector": selector, "length": len(text)}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Type failed: {e!s}"}

    @mcp.tool()
    async def browser_fill(
        selector: str,
        value: str,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Fill an input element with a value (clears existing content first).

        Faster than browser_type for filling form fields.

        Args:
            selector: CSS selector or element ref
            value: Value to fill
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with fill result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await page.fill(selector, value, timeout=timeout_ms)
            return {"ok": True, "action": "fill", "selector": selector}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Fill failed: {e!s}"}

    @mcp.tool()
    async def browser_press(
        key: str,
        selector: str | None = None,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Press a keyboard key.

        Args:
            key: Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown')
            selector: Focus element first (optional)
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with press result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            if selector:
                await page.press(selector, key, timeout=timeout_ms)
            else:
                await page.keyboard.press(key)

            return {"ok": True, "action": "press", "key": key}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Press failed: {e!s}"}

    @mcp.tool()
    async def browser_hover(
        selector: str,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Hover over an element.

        Args:
            selector: CSS selector or element ref
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with hover result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await page.hover(selector, timeout=timeout_ms)
            return {"ok": True, "action": "hover", "selector": selector}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Hover failed: {e!s}"}

    @mcp.tool()
    async def browser_select(
        selector: str,
        values: list[str],
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Select option(s) in a dropdown/select element.

        Args:
            selector: CSS selector for the select element
            values: List of values to select
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with select result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            selected = await page.select_option(selector, values, timeout=timeout_ms)
            return {"ok": True, "action": "select", "selector": selector, "selected": selected}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Select failed: {e!s}"}

    @mcp.tool()
    async def browser_scroll(
        direction: Literal["up", "down", "left", "right"] = "down",
        amount: int = 500,
        selector: str | None = None,
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Scroll the page or an element.

        Args:
            direction: Scroll direction (up, down, left, right)
            amount: Scroll amount in pixels (default: 500)
            selector: Element to scroll (optional, scrolls page if not provided)
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with scroll result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            delta_x = 0
            delta_y = 0
            if direction == "down":
                delta_y = amount
            elif direction == "up":
                delta_y = -amount
            elif direction == "right":
                delta_x = amount
            elif direction == "left":
                delta_x = -amount

            if selector:
                element = await page.query_selector(selector)
                if element:
                    await element.evaluate(f"e => e.scrollBy({delta_x}, {delta_y})")
            else:
                await page.mouse.wheel(delta_x, delta_y)

            return {"ok": True, "action": "scroll", "direction": direction, "amount": amount}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Scroll failed: {e!s}"}

    @mcp.tool()
    async def browser_drag(
        start_selector: str,
        end_selector: str,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Drag from one element to another.

        Args:
            start_selector: CSS selector for drag start element
            end_selector: CSS selector for drag end element
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with drag result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await page.drag_and_drop(
                start_selector,
                end_selector,
                timeout=timeout_ms,
            )
            return {
                "ok": True,
                "action": "drag",
                "from": start_selector,
                "to": end_selector,
            }
        except PlaywrightTimeout:
            return {"ok": False, "error": "Element not found for drag operation"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Drag failed: {e!s}"}
