"""
Browser session management.

Manages Playwright browser instances with support for multiple profiles,
each with independent browser context and multiple tabs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

logger = logging.getLogger(__name__)

# Browser User-Agent for stealth mode
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Default timeouts
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_NAVIGATION_TIMEOUT_MS = 60000


@dataclass
class BrowserSession:
    """
    Manages a browser session with multiple tabs.

    Each session corresponds to a profile and maintains:
    - A single browser instance
    - A browser context with shared cookies/storage
    - Multiple pages (tabs)
    - Console message capture per tab
    """

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
        """Stop the browser and clean up resources."""
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
        """Ensure browser is running, starting it if necessary."""
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
        """Capture console messages for a tab."""
        if target_id in self.console_messages:
            self.console_messages[target_id].append(
                {
                    "type": msg.type,
                    "text": msg.text,
                }
            )

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
        """Focus a tab by bringing it to front."""
        if target_id not in self.pages:
            return {"ok": False, "error": "Tab not found"}

        self.active_page_id = target_id
        await self.pages[target_id].bring_to_front()
        return {"ok": True, "targetId": target_id}

    async def list_tabs(self) -> list[dict]:
        """List all open tabs with their metadata."""
        tabs = []
        for tid, page in self.pages.items():
            try:
                tabs.append(
                    {
                        "targetId": tid,
                        "url": page.url,
                        "title": await page.title(),
                        "active": tid == self.active_page_id,
                    }
                )
            except Exception:
                pass
        return tabs

    def get_active_page(self) -> Page | None:
        """Get the currently active page."""
        if self.active_page_id and self.active_page_id in self.pages:
            return self.pages[self.active_page_id]
        return None

    def get_page(self, target_id: str | None = None) -> Page | None:
        """Get a page by target_id or return the active page."""
        if target_id:
            return self.pages.get(target_id)
        return self.get_active_page()


# ---------------------------------------------------------------------------
# Global Session Registry
# ---------------------------------------------------------------------------

_sessions: dict[str, BrowserSession] = {}


def get_session(profile: str = "default") -> BrowserSession:
    """Get or create a browser session for a profile."""
    if profile not in _sessions:
        _sessions[profile] = BrowserSession(profile=profile)
    return _sessions[profile]


def get_all_sessions() -> dict[str, BrowserSession]:
    """Get all registered sessions."""
    return _sessions
