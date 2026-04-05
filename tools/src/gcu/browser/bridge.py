"""
Beeline Browser Bridge - Playwright-based browser automation.

Provides isolated browser contexts per agent profile with tab management,
navigation, interactions, inspection, and advanced operations using Playwright.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Playwright,
    async_playwright,
)
from playwright_stealth import Stealth
from pydantic import BaseModel


class BrowserConfig(BaseModel):
    """Configuration for browser instances."""

    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    timeout_ms: int = 30000


class BeelineBridge:
    """Browser automation bridge using Playwright.

    Manages isolated browser contexts per profile/agent, with tab lifecycle
    and comprehensive automation capabilities.
    """

    def __init__(self, config: BrowserConfig | None = None):
        self.config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: dict[str, BrowserContext] = {}  # profile -> context
        self._tabs: dict[int, Page] = {}  # tab_id -> page
        self._current_tabs: dict[str, int] = {}  # profile -> current tab_id
        self._next_tab_id = 1000
        self._cdp_attached: set[int] = set()
        self.is_connected = False

    async def connect(self) -> None:
        """Initialize Playwright and browser."""
        if self.is_connected:
            return

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
            ],
        )
        self.is_connected = True

    async def disconnect(self) -> None:
        """Clean up browser and Playwright."""
        for context in self._contexts.values():
            await context.close()
        self._contexts.clear()
        self._tabs.clear()
        self._cdp_attached.clear()

        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

        self.is_connected = False

    async def create_context(self, profile: str) -> dict[str, Any]:
        """Create an isolated browser context for the given profile."""
        if not self.is_connected:
            await self.connect()

        if profile in self._contexts:
            # Return existing context info
            context = self._contexts[profile]
            pages = context.pages
            tab_id = self._next_tab_id
            self._next_tab_id += 1
            if pages:
                self._tabs[tab_id] = pages[0]
            else:
                page = await context.new_page()
                self._tabs[tab_id] = page
            return {"groupId": id(context), "tabId": tab_id}

        context = await self._browser.new_context(
            viewport={"width": self.config.viewport_width, "height": self.config.viewport_height},
            user_agent=self.config.user_agent,
        )

        # Apply stealth
        await Stealth(context).apply()

        self._contexts[profile] = context

        # Create initial tab
        tab_id = self._next_tab_id
        self._next_tab_id += 1
        page = await context.new_page()
        self._tabs[tab_id] = page
        self._current_tabs[profile] = tab_id

        return {"groupId": id(context), "tabId": tab_id}

    async def destroy_context(self, profile: str) -> dict[str, Any]:
        """Destroy the browser context for the given profile."""
        if profile not in self._contexts:
            return {"ok": False, "error": "Context not found"}

        context = self._contexts[profile]
        await context.close()
        del self._contexts[profile]

        # Remove associated tabs
        to_remove = [tab_id for tab_id, page in self._tabs.items() if page.context == context]
        for tab_id in to_remove:
            del self._tabs[tab_id]
            self._cdp_attached.discard(tab_id)

        return {"ok": True}

    async def create_tab(self, profile: str, url: str = "about:blank") -> dict[str, Any]:
        """Create a new tab in the profile's context."""
        if profile not in self._contexts:
            result = await self.create_context(profile)
            return result

        context = self._contexts[profile]
        tab_id = self._next_tab_id
        self._next_tab_id += 1
        page = await context.new_page()
        if url != "about:blank":
            await page.goto(url, wait_until="load", timeout=self.config.timeout_ms)
        self._tabs[tab_id] = page
        self._current_tabs[profile] = tab_id

        return {"tabId": tab_id}

    async def close_tab(self, tab_id: int) -> dict[str, Any]:
        """Close the specified tab."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        await page.close()
        del self._tabs[tab_id]
        self._cdp_attached.discard(tab_id)

        return {"ok": True}

    async def list_tabs(self, profile: str) -> dict[str, Any]:
        """List all tabs in the profile's context."""
        if profile not in self._contexts:
            return {"tabs": []}

        context = self._contexts[profile]
        tabs = []
        for tab_id, page in self._tabs.items():
            if page.context == context:
                tabs.append(
                    {
                        "id": tab_id,
                        "url": page.url,
                        "title": await page.title() if not page.is_closed() else "",
                    }
                )

        return {"tabs": tabs}

    async def activate_tab(self, tab_id: int) -> dict[str, Any]:
        """Bring the specified tab to the front."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        await page.bring_to_front()

        # Find profile for this tab and set as current
        for profile, context in self._contexts.items():
            if page.context == context:
                self._current_tabs[profile] = tab_id
                break

        return {"ok": True}

    def get_current_tab(self, profile: str) -> int | None:
        """Get the current tab ID for the profile."""
        return self._current_tabs.get(profile)

    async def navigate(self, tab_id: int, url: str, wait_until: str = "load") -> dict[str, Any]:
        """Navigate the tab to the specified URL."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.goto(url, wait_until=wait_until, timeout=self.config.timeout_ms)
            return {"ok": True, "url": page.url}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def go_back(self, tab_id: int) -> dict[str, Any]:
        """Go back in history."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.go_back(timeout=self.config.timeout_ms)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def go_forward(self, tab_id: int) -> dict[str, Any]:
        """Go forward in history."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.go_forward(timeout=self.config.timeout_ms)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def reload(self, tab_id: int) -> dict[str, Any]:
        """Reload the current page."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.reload(timeout=self.config.timeout_ms)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def click(self, tab_id: int, selector: str) -> dict[str, Any]:
        """Click on the element matching the selector."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.click(selector, timeout=self.config.timeout_ms)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def click_coordinate(self, tab_id: int, x: float, y: float) -> dict[str, Any]:
        """Click at the specified coordinates."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.mouse.click(x, y)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def type_text(self, tab_id: int, selector: str, text: str) -> dict[str, Any]:
        """Type text into the element matching the selector."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.fill(selector, text, timeout=self.config.timeout_ms)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def press_key(self, tab_id: int, key: str) -> dict[str, Any]:
        """Press a keyboard key."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.keyboard.press(key)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def hover(self, tab_id: int, selector: str) -> dict[str, Any]:
        """Hover over the element matching the selector."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.hover(selector, timeout=self.config.timeout_ms)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def scroll(self, tab_id: int, direction: str, amount: int) -> dict[str, Any]:
        """Scroll in the specified direction by the given amount."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            if direction == "down":
                await page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                await page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "left":
                await page.evaluate(f"window.scrollBy(-{amount}, 0)")
            elif direction == "right":
                await page.evaluate(f"window.scrollBy({amount}, 0)")
            else:
                return {"ok": False, "error": f"Invalid direction: {direction}"}
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def select_option(self, tab_id: int, selector: str, values: list[str]) -> dict[str, Any]:
        """Select options in a select element."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.select_option(selector, values, timeout=self.config.timeout_ms)
            return {"ok": True, "selected": values}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def drag(
        self, tab_id: int, selector: str, target_x: float, target_y: float
    ) -> dict[str, Any]:
        """Drag the element to the target coordinates."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.drag_and_drop(
                selector,
                f"css=[style*='position: absolute; left: {target_x}px; top: {target_y}px;']",
                timeout=self.config.timeout_ms,
            )
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def evaluate(self, tab_id: int, script: str) -> dict[str, Any]:
        """Evaluate JavaScript in the page context."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            result = await page.evaluate(script)
            return {"result": result}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def snapshot(self, tab_id: int) -> dict[str, Any]:
        """Get accessibility snapshot of the page."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            snapshot = await page.accessibility.snapshot()
            return {"tree": snapshot}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def screenshot(self, tab_id: int, full_page: bool = False) -> dict[str, Any]:
        """Take a screenshot of the page."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            screenshot_bytes = await page.screenshot(full_page=full_page)
            data = base64.b64encode(screenshot_bytes).decode("utf-8")
            return {"data": data}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def get_text(self, tab_id: int, selector: str) -> dict[str, Any]:
        """Get text content of the element matching the selector."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            text = await page.inner_text(selector, timeout=self.config.timeout_ms)
            return {"text": text}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def get_attribute(self, tab_id: int, selector: str, attribute: str) -> dict[str, Any]:
        """Get attribute value of the element matching the selector."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            value = await page.get_attribute(selector, attribute, timeout=self.config.timeout_ms)
            return {"value": value}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def wait_for_selector(
        self, tab_id: int, selector: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """Wait for the selector to appear."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.wait_for_selector(selector, timeout=timeout or self.config.timeout_ms)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def wait_for_text(
        self, tab_id: int, text: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """Wait for the specified text to appear."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.wait_for_function(
                f"document.body.innerText.includes('{text}')",
                timeout=timeout or self.config.timeout_ms,
            )
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def resize(self, tab_id: int, width: int, height: int) -> dict[str, Any]:
        """Resize the viewport."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.set_viewport_size({"width": width, "height": height})
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def upload_file(self, tab_id: int, selector: str, file_path: str) -> dict[str, Any]:
        """Upload a file to the input element."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:
            await page.set_input_files(selector, file_path, timeout=self.config.timeout_ms)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def handle_dialog(
        self, tab_id: int, action: str, text: str | None = None
    ) -> dict[str, Any]:
        """Handle dialog (alert, confirm, prompt)."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        page = self._tabs[tab_id]
        try:

            def dialog_handler(dialog):
                if action == "accept":
                    dialog.accept(text) if text else dialog.accept()
                elif action == "dismiss":
                    dialog.dismiss()

            if action not in ("accept", "dismiss"):
                return {"ok": False, "error": f"Invalid action: {action}"}

            page.on("dialog", dialog_handler)
            # Wait for dialog to be handled
            await asyncio.sleep(0.1)
            page.remove_listener("dialog", dialog_handler)
            return {"ok": True}
        except PlaywrightError as e:
            return {"ok": False, "error": str(e)}

    async def cdp_attach(self, tab_id: int) -> dict[str, Any]:
        """Attach to Chrome DevTools Protocol."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        if tab_id in self._cdp_attached:
            return {"ok": True}

        # In Playwright, CDP is always available
        self._cdp_attached.add(tab_id)
        return {"ok": True}

    async def cdp_detach(self, tab_id: int) -> dict[str, Any]:
        """Detach from Chrome DevTools Protocol."""
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Tab not found"}

        if tab_id not in self._cdp_attached:
            return {"ok": True}

        self._cdp_attached.discard(tab_id)
        return {"ok": True}
