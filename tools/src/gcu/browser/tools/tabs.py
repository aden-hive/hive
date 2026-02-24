"""
Browser tab management tools - tabs, open, close, focus.
"""

from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
)

from ..session import get_session


def register_tab_tools(mcp: FastMCP) -> None:
    """Register browser tab management tools."""

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
    async def browser_open(
        url: str,
        background: bool = False,
        profile: str = "default",
        wait_until: str = "load",
    ) -> dict:
        """
        Open a new browser tab and navigate to the given URL.

        Args:
            url: URL to navigate to
            background: Open in background without stealing focus from the current tab (default: False)
            profile: Browser profile name (default: "default")
            wait_until: Wait condition - "commit", "domcontentloaded", "load" (default), or "networkidle"

        Returns:
            Dict with new tab info (targetId, url, title, background)
        """
        try:
            session = get_session(profile)
            return await session.open_tab(url, background=background, wait_until=wait_until)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
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
