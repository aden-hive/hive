"""
Browser navigation tools - navigate, go_back, go_forward, reload.
"""

from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
)

from ..session import DEFAULT_NAVIGATION_TIMEOUT_MS, get_session


def register_navigation_tools(mcp: FastMCP) -> None:
    """Register browser navigation tools."""

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
