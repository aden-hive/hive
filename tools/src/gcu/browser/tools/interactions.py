"""
Browser interaction tools - click, type, fill, press, hover, select, scroll, drag.

Tools for interacting with page elements.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeout,
)

from ..highlight import highlight_coordinate, highlight_element
from ..refs import annotate_snapshot, resolve_selector
from ..session import DEFAULT_TIMEOUT_MS, BrowserSession, get_session

logger = logging.getLogger(__name__)

_AUTO_SNAPSHOT_MAX_CHARS = 4000


async def _auto_snapshot(
    page: Page,
    *,
    session: BrowserSession | None = None,
    target_id: str | None = None,
    wait_for_nav: bool = False,
    max_chars: int = _AUTO_SNAPSHOT_MAX_CHARS,
) -> str | None:
    """Capture a compact aria snapshot for auto-attach to action results.

    Args:
        page: Playwright Page instance.
        session: BrowserSession to store ref maps in.
        target_id: Target page id for ref map storage.
        wait_for_nav: If True, briefly wait for any in-flight navigation to
            settle before snapshotting.  Used after click actions that may
            trigger page navigation.
        max_chars: Truncate snapshot to this many characters.  Keeps the
            result small enough to survive conversation pruning (~10K char
            protection budget).  Set 0 to disable truncation.
    """
    try:
        if wait_for_nav:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=1000)
            except Exception:
                pass  # No navigation happened — that's fine
        snapshot = await page.locator(":root").aria_snapshot()

        # Annotate with refs before truncation so the full RefMap is captured
        if snapshot and session:
            snapshot, ref_map = annotate_snapshot(snapshot)
            tid = target_id or session.active_page_id
            if tid:
                session.ref_maps[tid] = ref_map

        if snapshot and max_chars > 0 and len(snapshot) > max_chars:
            snapshot = (
                snapshot[:max_chars]
                + "\n... [truncated — call browser_snapshot for full page tree]"
            )
        return snapshot
    except Exception:
        logger.debug("_auto_snapshot failed", exc_info=True)
        return None


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
        auto_snapshot: bool = True,
    ) -> dict:
        """
        Click an element on the page.

        Returns an accessibility snapshot of the page after the click
        so you can decide your next action immediately.

        Args:
            selector: CSS selector or element ref (e.g., 'e12' from snapshot)
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            button: Mouse button to click (left, right, middle)
            double_click: Perform double-click (default: False)
            timeout_ms: Timeout in milliseconds (default: 30000)
            auto_snapshot: Include page snapshot in result (default: True)

        Returns:
            Dict with click result and optional snapshot
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            try:
                selector = resolve_selector(selector, session, target_id)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

            await highlight_element(page, selector)

            if double_click:
                await page.dblclick(selector, button=button, timeout=timeout_ms)
            else:
                await page.click(selector, button=button, timeout=timeout_ms)

            result: dict = {"ok": True, "action": "click", "selector": selector}
            if auto_snapshot:
                snapshot = await _auto_snapshot(
                    page,
                    session=session,
                    target_id=target_id,
                    wait_for_nav=True,
                )
                if snapshot:
                    result["snapshot"] = snapshot
                    result["url"] = page.url
            return result
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Click failed: {e!s}"}

    @mcp.tool()
    async def browser_click_coordinate(
        x: float,
        y: float,
        target_id: str | None = None,
        profile: str = "default",
        button: Literal["left", "right", "middle"] = "left",
        auto_snapshot: bool = True,
    ) -> dict:
        """
        Click at specific viewport coordinates.

        Returns an accessibility snapshot of the page after the click.

        Args:
            x: X coordinate in the viewport
            y: Y coordinate in the viewport
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            button: Mouse button to click (left, right, middle)
            auto_snapshot: Include page snapshot in result (default: True)

        Returns:
            Dict with click result and optional snapshot
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await highlight_coordinate(page, x, y)

            await page.mouse.click(x, y, button=button)
            result: dict = {"ok": True, "action": "click_coordinate", "x": x, "y": y}
            if auto_snapshot:
                snapshot = await _auto_snapshot(
                    page,
                    session=session,
                    target_id=target_id,
                    wait_for_nav=True,
                )
                if snapshot:
                    result["snapshot"] = snapshot
                    result["url"] = page.url
            return result
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
        auto_snapshot: bool = True,
    ) -> dict:
        """
        Type text into an input element.

        Returns an accessibility snapshot of the page after typing.

        Args:
            selector: CSS selector or element ref (e.g., 'e12' from snapshot)
            text: Text to type
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            delay_ms: Delay between keystrokes in ms (default: 0)
            clear_first: Clear existing text before typing (default: True)
            timeout_ms: Timeout in milliseconds (default: 30000)
            auto_snapshot: Include page snapshot in result (default: True)

        Returns:
            Dict with type result and optional snapshot
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            try:
                selector = resolve_selector(selector, session, target_id)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

            await highlight_element(page, selector)

            if clear_first:
                await page.fill(selector, "", timeout=timeout_ms)

            await page.type(selector, text, delay=delay_ms, timeout=timeout_ms)
            result: dict = {"ok": True, "action": "type", "selector": selector, "length": len(text)}
            if auto_snapshot:
                snapshot = await _auto_snapshot(page, session=session, target_id=target_id)
                if snapshot:
                    result["snapshot"] = snapshot
                    result["url"] = page.url
            return result
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
        auto_snapshot: bool = True,
    ) -> dict:
        """
        Fill an input element with a value (clears existing content first).

        Faster than browser_type for filling form fields.
        Returns an accessibility snapshot of the page after filling.

        Args:
            selector: CSS selector or element ref
            value: Value to fill
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)
            auto_snapshot: Include page snapshot in result (default: True)

        Returns:
            Dict with fill result and optional snapshot
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            try:
                selector = resolve_selector(selector, session, target_id)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

            await highlight_element(page, selector)

            await page.fill(selector, value, timeout=timeout_ms)
            result: dict = {"ok": True, "action": "fill", "selector": selector}
            if auto_snapshot:
                snapshot = await _auto_snapshot(page, session=session, target_id=target_id)
                if snapshot:
                    result["snapshot"] = snapshot
                    result["url"] = page.url
            return result
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
                try:
                    selector = resolve_selector(selector, session, target_id)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
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

            try:
                selector = resolve_selector(selector, session, target_id)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

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
        auto_snapshot: bool = True,
    ) -> dict:
        """
        Select option(s) in a dropdown/select element.

        Returns an accessibility snapshot of the page after selection.

        Args:
            selector: CSS selector for the select element
            values: List of values to select
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)
            auto_snapshot: Include page snapshot in result (default: True)

        Returns:
            Dict with select result and optional snapshot
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            try:
                selector = resolve_selector(selector, session, target_id)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

            selected = await page.select_option(selector, values, timeout=timeout_ms)
            result: dict = {
                "ok": True,
                "action": "select",
                "selector": selector,
                "selected": selected,
            }
            if auto_snapshot:
                snapshot = await _auto_snapshot(page, session=session, target_id=target_id)
                if snapshot:
                    result["snapshot"] = snapshot
                    result["url"] = page.url
            return result
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
        auto_snapshot: bool = True,
    ) -> dict:
        """
        Scroll the page or an element.

        Returns an accessibility snapshot of the page after scrolling
        so you can see newly loaded content immediately.

        Args:
            direction: Scroll direction (up, down, left, right)
            amount: Scroll amount in pixels (default: 500)
            selector: Element to scroll (optional, scrolls page if not provided)
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            auto_snapshot: Include page snapshot in result (default: True)

        Returns:
            Dict with scroll result and optional snapshot
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
                try:
                    selector = resolve_selector(selector, session, target_id)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                element = await page.query_selector(selector)
                if element:
                    await element.evaluate(f"e => e.scrollBy({delta_x}, {delta_y})")
            else:
                await page.mouse.wheel(delta_x, delta_y)

            result: dict = {
                "ok": True,
                "action": "scroll",
                "direction": direction,
                "amount": amount,
            }
            if auto_snapshot:
                snapshot = await _auto_snapshot(page, session=session, target_id=target_id)
                if snapshot:
                    result["snapshot"] = snapshot
                    result["url"] = page.url
            return result
        except PlaywrightError as e:
            return {"ok": False, "error": f"Scroll failed: {e!s}"}

    @mcp.tool()
    async def browser_drag(
        start_selector: str,
        end_selector: str,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        auto_snapshot: bool = True,
    ) -> dict:
        """
        Drag from one element to another.

        Returns an accessibility snapshot of the page after the drag.

        Args:
            start_selector: CSS selector for drag start element
            end_selector: CSS selector for drag end element
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)
            auto_snapshot: Include page snapshot in result (default: True)

        Returns:
            Dict with drag result and optional snapshot
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            try:
                start_selector = resolve_selector(start_selector, session, target_id)
                end_selector = resolve_selector(end_selector, session, target_id)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

            await page.drag_and_drop(
                start_selector,
                end_selector,
                timeout=timeout_ms,
            )
            result: dict = {
                "ok": True,
                "action": "drag",
                "from": start_selector,
                "to": end_selector,
            }
            if auto_snapshot:
                snapshot = await _auto_snapshot(page, session=session, target_id=target_id)
                if snapshot:
                    result["snapshot"] = snapshot
                    result["url"] = page.url
            return result
        except PlaywrightTimeout:
            return {"ok": False, "error": "Element not found for drag operation"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Drag failed: {e!s}"}
