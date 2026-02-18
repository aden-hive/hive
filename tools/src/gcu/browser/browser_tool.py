"""
GCU Browser Tool - Browser automation and interaction for GCU nodes.

Provides comprehensive browser automation capabilities including:
- Browser lifecycle management (start/stop)
- Tab management (open/close/focus/list)
- Navigation and content extraction
- Element interaction (click, type, fill, etc.)
- Screenshots and PDF generation
- Console message retrieval
- Dialog handling

Uses Playwright for browser automation.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

logger = logging.getLogger(__name__)

# Browser User-Agent
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Default timeouts
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_NAVIGATION_TIMEOUT_MS = 60000


# ---------------------------------------------------------------------------
# Browser Session State (singleton per profile)
# ---------------------------------------------------------------------------


@dataclass
class BrowserSession:
    """Manages a browser session with multiple tabs."""

    profile: str
    browser: Browser | None = None
    context: BrowserContext | None = None
    pages: dict[str, Page] = field(default_factory=dict)
    active_page_id: str | None = None
    console_messages: dict[str, list[dict]] = field(default_factory=dict)
    _playwright: Any = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self, headless: bool = True) -> dict:
        """Start the browser."""
        async with self._lock:
            if self.browser and self.browser.is_connected():
                return {"ok": True, "status": "already_running", "profile": self.profile}

            self._playwright = await async_playwright().start()
            self.browser = await self._playwright.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=BROWSER_USER_AGENT,
                locale="en-US",
            )
            return {"ok": True, "status": "started", "profile": self.profile}

    async def stop(self) -> dict:
        """Stop the browser."""
        async with self._lock:
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            self.context = None
            self.pages.clear()
            self.active_page_id = None
            self.console_messages.clear()
            return {"ok": True, "status": "stopped", "profile": self.profile}

    async def status(self) -> dict:
        """Get browser status."""
        return {
            "ok": True,
            "profile": self.profile,
            "running": self.browser is not None and self.browser.is_connected(),
            "tabs": len(self.pages),
            "active_tab": self.active_page_id,
        }

    async def ensure_running(self) -> None:
        """Ensure browser is running."""
        if not self.browser or not self.browser.is_connected():
            await self.start()

    async def open_tab(self, url: str) -> dict:
        """Open a new tab with the given URL."""
        await self.ensure_running()
        if not self.context:
            raise RuntimeError("Browser context not initialized")

        page = await self.context.new_page()
        target_id = f"tab_{id(page)}"
        self.pages[target_id] = page
        self.active_page_id = target_id
        self.console_messages[target_id] = []

        # Set up console message capture
        page.on("console", lambda msg: self._capture_console(target_id, msg))

        await page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_NAVIGATION_TIMEOUT_MS)

        return {
            "ok": True,
            "targetId": target_id,
            "url": page.url,
            "title": await page.title(),
        }

    def _capture_console(self, target_id: str, msg: Any) -> None:
        """Capture console messages."""
        if target_id in self.console_messages:
            self.console_messages[target_id].append({
                "type": msg.type,
                "text": msg.text,
            })

    async def close_tab(self, target_id: str | None = None) -> dict:
        """Close a tab."""
        tid = target_id or self.active_page_id
        if not tid or tid not in self.pages:
            return {"ok": False, "error": "Tab not found"}

        page = self.pages.pop(tid)
        await page.close()
        self.console_messages.pop(tid, None)

        if self.active_page_id == tid:
            self.active_page_id = next(iter(self.pages), None)

        return {"ok": True, "closed": tid}

    async def focus_tab(self, target_id: str) -> dict:
        """Focus a tab."""
        if target_id not in self.pages:
            return {"ok": False, "error": "Tab not found"}

        self.active_page_id = target_id
        await self.pages[target_id].bring_to_front()
        return {"ok": True, "targetId": target_id}

    async def list_tabs(self) -> list[dict]:
        """List all open tabs."""
        tabs = []
        for tid, page in self.pages.items():
            try:
                tabs.append({
                    "targetId": tid,
                    "url": page.url,
                    "title": await page.title(),
                    "active": tid == self.active_page_id,
                })
            except Exception:
                pass
        return tabs

    def get_active_page(self) -> Page | None:
        """Get the active page."""
        if self.active_page_id and self.active_page_id in self.pages:
            return self.pages[self.active_page_id]
        return None

    def get_page(self, target_id: str | None = None) -> Page | None:
        """Get a page by target_id or the active page."""
        if target_id:
            return self.pages.get(target_id)
        return self.get_active_page()


# Global session registry
_sessions: dict[str, BrowserSession] = {}


def get_session(profile: str = "default") -> BrowserSession:
    """Get or create a browser session for a profile."""
    if profile not in _sessions:
        _sessions[profile] = BrowserSession(profile=profile)
    return _sessions[profile]


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------


def register_tools(mcp: FastMCP) -> None:
    """Register GCU browser tools with the MCP server."""

    # -------------------------------------------------------------------------
    # Lifecycle Tools
    # -------------------------------------------------------------------------

    @mcp.tool()
    async def browser_status(profile: str = "default") -> dict:
        """
        Get the current status of the browser.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with browser status (running, tabs count, active tab)
        """
        session = get_session(profile)
        return await session.status()

    @mcp.tool()
    async def browser_start(profile: str = "default", headless: bool = True) -> dict:
        """
        Start the browser.

        Args:
            profile: Browser profile name (default: "default")
            headless: Run browser in headless mode (default: True)

        Returns:
            Dict with start status
        """
        session = get_session(profile)
        return await session.start(headless=headless)

    @mcp.tool()
    async def browser_stop(profile: str = "default") -> dict:
        """
        Stop the browser and close all tabs.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with stop status
        """
        session = get_session(profile)
        return await session.stop()

    # -------------------------------------------------------------------------
    # Tab Management Tools
    # -------------------------------------------------------------------------

    @mcp.tool()
    async def browser_tabs(profile: str = "default") -> dict:
        """
        List all open browser tabs.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with list of tabs (targetId, url, title, active)
        """
        session = get_session(profile)
        tabs = await session.list_tabs()
        return {"ok": True, "tabs": tabs}

    @mcp.tool()
    async def browser_open(url: str, profile: str = "default") -> dict:
        """
        Open a new browser tab and navigate to the given URL.

        Args:
            url: URL to navigate to
            profile: Browser profile name (default: "default")

        Returns:
            Dict with new tab info (targetId, url, title)
        """
        try:
            session = get_session(profile)
            return await session.open_tab(url)
        except PlaywrightTimeout:
            return {"ok": False, "error": "Navigation timed out"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Browser error: {e!s}"}

    @mcp.tool()
    async def browser_close(target_id: str | None = None, profile: str = "default") -> dict:
        """
        Close a browser tab.

        Args:
            target_id: Tab ID to close (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with close status
        """
        session = get_session(profile)
        return await session.close_tab(target_id)

    @mcp.tool()
    async def browser_focus(target_id: str, profile: str = "default") -> dict:
        """
        Focus a browser tab.

        Args:
            target_id: Tab ID to focus
            profile: Browser profile name (default: "default")

        Returns:
            Dict with focus status
        """
        session = get_session(profile)
        return await session.focus_tab(target_id)

    # -------------------------------------------------------------------------
    # Navigation Tools
    # -------------------------------------------------------------------------

    @mcp.tool()
    async def browser_navigate(
        url: str,
        target_id: str | None = None,
        profile: str = "default",
        wait_until: str = "domcontentloaded",
    ) -> dict:
        """
        Navigate the current tab to a URL.

        Args:
            url: URL to navigate to
            target_id: Tab ID to navigate (default: active tab)
            profile: Browser profile name (default: "default")
            wait_until: Wait condition (domcontentloaded, load, networkidle)

        Returns:
            Dict with navigation result (url, title)
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await page.goto(url, wait_until=wait_until, timeout=DEFAULT_NAVIGATION_TIMEOUT_MS)
            return {
                "ok": True,
                "url": page.url,
                "title": await page.title(),
            }
        except PlaywrightTimeout:
            return {"ok": False, "error": "Navigation timed out"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Browser error: {e!s}"}

    # -------------------------------------------------------------------------
    # Content Extraction Tools
    # -------------------------------------------------------------------------

    @mcp.tool()
    async def browser_snapshot(
        target_id: str | None = None,
        profile: str = "default",
        selector: str | None = None,
        max_chars: int = 50000,
    ) -> dict:
        """
        Get an accessibility tree snapshot of the current page.

        Use this to understand the page structure and find elements to interact with.
        Returns element refs (like 'e12') that can be used with browser_click, etc.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            selector: CSS selector to scope snapshot (optional)
            max_chars: Maximum characters to return (default: 50000)

        Returns:
            Dict with snapshot (text representation) and metadata
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            # Get accessibility tree
            snapshot = await page.accessibility.snapshot()
            if not snapshot:
                return {"ok": False, "error": "Could not get accessibility snapshot"}

            # Format snapshot as text with refs
            refs: dict[str, dict] = {}
            lines: list[str] = []

            def format_node(node: dict, depth: int = 0) -> None:
                indent = "  " * depth
                role = node.get("role", "")
                name = node.get("name", "")
                ref = f"e{len(refs)}"
                refs[ref] = {"role": role, "name": name}

                line = f"{indent}[{ref}] {role}"
                if name:
                    line += f': "{name[:100]}"'
                lines.append(line)

                for child in node.get("children", []):
                    format_node(child, depth + 1)

            format_node(snapshot)
            text = "\n".join(lines)

            # Truncate if needed
            if len(text) > max_chars:
                text = text[:max_chars] + "\n... (truncated)"

            return {
                "ok": True,
                "targetId": target_id or session.active_page_id,
                "url": page.url,
                "snapshot": text,
                "refs": refs,
                "refCount": len(refs),
            }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Browser error: {e!s}"}

    @mcp.tool()
    async def browser_screenshot(
        target_id: str | None = None,
        profile: str = "default",
        full_page: bool = False,
        selector: str | None = None,
        image_type: Literal["png", "jpeg"] = "png",
    ) -> dict:
        """
        Take a screenshot of the current page.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            full_page: Capture full scrollable page (default: False)
            selector: CSS selector to screenshot specific element (optional)
            image_type: Image format - png or jpeg (default: png)

        Returns:
            Dict with screenshot data (base64 encoded) and metadata
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            if selector:
                element = await page.query_selector(selector)
                if not element:
                    return {"ok": False, "error": f"Element not found: {selector}"}
                screenshot_bytes = await element.screenshot(type=image_type)
            else:
                screenshot_bytes = await page.screenshot(
                    full_page=full_page,
                    type=image_type,
                )

            return {
                "ok": True,
                "targetId": target_id or session.active_page_id,
                "url": page.url,
                "imageType": image_type,
                "imageBase64": base64.b64encode(screenshot_bytes).decode(),
                "size": len(screenshot_bytes),
            }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Browser error: {e!s}"}

    @mcp.tool()
    async def browser_console(
        target_id: str | None = None,
        profile: str = "default",
        level: str | None = None,
    ) -> dict:
        """
        Get console messages from the browser.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            level: Filter by level (log, info, warn, error) (optional)

        Returns:
            Dict with console messages
        """
        session = get_session(profile)
        tid = target_id or session.active_page_id
        if not tid:
            return {"ok": False, "error": "No active tab"}

        messages = session.console_messages.get(tid, [])
        if level:
            messages = [m for m in messages if m.get("type") == level]

        return {
            "ok": True,
            "targetId": tid,
            "messages": messages,
            "count": len(messages),
        }

    @mcp.tool()
    async def browser_pdf(
        target_id: str | None = None,
        profile: str = "default",
        path: str | None = None,
    ) -> dict:
        """
        Save the current page as PDF.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            path: File path to save PDF (optional, returns base64 if not provided)

        Returns:
            Dict with PDF data or file path
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            pdf_bytes = await page.pdf()

            if path:
                Path(path).write_bytes(pdf_bytes)
                return {
                    "ok": True,
                    "targetId": target_id or session.active_page_id,
                    "path": path,
                    "size": len(pdf_bytes),
                }
            else:
                return {
                    "ok": True,
                    "targetId": target_id or session.active_page_id,
                    "pdfBase64": base64.b64encode(pdf_bytes).decode(),
                    "size": len(pdf_bytes),
                }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Browser error: {e!s}"}

    # -------------------------------------------------------------------------
    # Interaction Tools
    # -------------------------------------------------------------------------

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
    async def browser_wait(
        wait_ms: int = 1000,
        selector: str | None = None,
        text: str | None = None,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Wait for a condition.

        Args:
            wait_ms: Time to wait in milliseconds (if no selector/text provided)
            selector: Wait for element to appear (optional)
            text: Wait for text to appear on page (optional)
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Maximum wait time in milliseconds (default: 30000)

        Returns:
            Dict with wait result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            if selector:
                await page.wait_for_selector(selector, timeout=timeout_ms)
                return {"ok": True, "action": "wait", "condition": "selector", "selector": selector}
            elif text:
                await page.wait_for_function(
                    f"document.body.innerText.includes('{text}')",
                    timeout=timeout_ms,
                )
                return {"ok": True, "action": "wait", "condition": "text", "text": text}
            else:
                await page.wait_for_timeout(wait_ms)
                return {"ok": True, "action": "wait", "condition": "time", "ms": wait_ms}
        except PlaywrightTimeout:
            return {"ok": False, "error": "Wait condition not met within timeout"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Wait failed: {e!s}"}

    @mcp.tool()
    async def browser_evaluate(
        script: str,
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Execute JavaScript in the browser context.

        Args:
            script: JavaScript code to execute
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with evaluation result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            result = await page.evaluate(script)
            return {"ok": True, "action": "evaluate", "result": result}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Evaluate failed: {e!s}"}

    @mcp.tool()
    async def browser_get_text(
        selector: str,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Get text content of an element.

        Args:
            selector: CSS selector or element ref
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with element text content
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            element = await page.wait_for_selector(selector, timeout=timeout_ms)
            if not element:
                return {"ok": False, "error": f"Element not found: {selector}"}

            text = await element.text_content()
            return {"ok": True, "selector": selector, "text": text}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Get text failed: {e!s}"}

    @mcp.tool()
    async def browser_get_attribute(
        selector: str,
        attribute: str,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Get an attribute value of an element.

        Args:
            selector: CSS selector or element ref
            attribute: Attribute name to get (e.g., 'href', 'src', 'value')
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with attribute value
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            element = await page.wait_for_selector(selector, timeout=timeout_ms)
            if not element:
                return {"ok": False, "error": f"Element not found: {selector}"}

            value = await element.get_attribute(attribute)
            return {"ok": True, "selector": selector, "attribute": attribute, "value": value}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Get attribute failed: {e!s}"}

    # -------------------------------------------------------------------------
    # Additional Tools (drag, resize, upload, dialog, profiles)
    # -------------------------------------------------------------------------

    @mcp.tool()
    async def browser_profiles() -> dict:
        """
        List all available browser profiles.

        Returns:
            Dict with list of profile names and their status
        """
        profiles = []
        for name, session in _sessions.items():
            status = await session.status()
            profiles.append({
                "name": name,
                "running": status.get("running", False),
                "tabs": status.get("tabs", 0),
            })
        # Always include default if not present
        if "default" not in _sessions:
            profiles.append({"name": "default", "running": False, "tabs": 0})
        return {"ok": True, "profiles": profiles}

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

    @mcp.tool()
    async def browser_resize(
        width: int,
        height: int,
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Resize the browser viewport.

        Args:
            width: Viewport width in pixels
            height: Viewport height in pixels
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with resize result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await page.set_viewport_size({"width": width, "height": height})
            return {
                "ok": True,
                "action": "resize",
                "width": width,
                "height": height,
            }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Resize failed: {e!s}"}

    @mcp.tool()
    async def browser_upload(
        selector: str,
        file_paths: list[str],
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Upload files to a file input element.

        Args:
            selector: CSS selector for the file input element
            file_paths: List of file paths to upload
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with upload result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            # Verify files exist
            for path in file_paths:
                if not Path(path).exists():
                    return {"ok": False, "error": f"File not found: {path}"}

            element = await page.wait_for_selector(selector, timeout=timeout_ms)
            if not element:
                return {"ok": False, "error": f"Element not found: {selector}"}

            await element.set_input_files(file_paths)
            return {
                "ok": True,
                "action": "upload",
                "selector": selector,
                "files": file_paths,
                "count": len(file_paths),
            }
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Upload failed: {e!s}"}

    @mcp.tool()
    async def browser_dialog(
        action: Literal["accept", "dismiss"] = "accept",
        prompt_text: str | None = None,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Handle browser dialogs (alert, confirm, prompt).

        This sets up a handler for the next dialog that appears.
        Call this BEFORE triggering the action that opens the dialog.

        Args:
            action: How to handle the dialog - "accept" or "dismiss"
            prompt_text: Text to enter for prompt dialogs (optional)
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout waiting for dialog (default: 30000)

        Returns:
            Dict with dialog handling result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            dialog_info: dict = {"handled": False}

            async def handle_dialog(dialog):
                dialog_info["type"] = dialog.type
                dialog_info["message"] = dialog.message
                dialog_info["handled"] = True
                if action == "accept":
                    if prompt_text is not None:
                        await dialog.accept(prompt_text)
                    else:
                        await dialog.accept()
                else:
                    await dialog.dismiss()

            page.once("dialog", handle_dialog)

            # Wait briefly for dialog to appear
            await page.wait_for_timeout(min(timeout_ms, 1000))

            if dialog_info["handled"]:
                return {
                    "ok": True,
                    "action": action,
                    "dialogType": dialog_info.get("type"),
                    "dialogMessage": dialog_info.get("message"),
                }
            else:
                return {
                    "ok": True,
                    "action": "handler_set",
                    "message": "Dialog handler set, will handle next dialog",
                }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Dialog handling failed: {e!s}"}

    @mcp.tool()
    async def browser_go_back(
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Navigate back in browser history.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with navigation result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await page.go_back()
            return {"ok": True, "action": "back", "url": page.url}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Go back failed: {e!s}"}

    @mcp.tool()
    async def browser_go_forward(
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Navigate forward in browser history.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with navigation result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await page.go_forward()
            return {"ok": True, "action": "forward", "url": page.url}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Go forward failed: {e!s}"}

    @mcp.tool()
    async def browser_reload(
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Reload the current page.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with reload result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await page.reload()
            return {"ok": True, "action": "reload", "url": page.url}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Reload failed: {e!s}"}
