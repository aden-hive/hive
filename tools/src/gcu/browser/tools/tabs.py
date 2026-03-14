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
        List all open browser tabs with origin and age metadata.

        Each tab includes:
        - ``targetId``: Unique tab identifier
        - ``url``: Current URL
        - ``title``: Page title
        - ``active``: Whether this is the active tab
        - ``origin``: Who opened the tab — ``"agent"`` (you opened it),
          ``"popup"`` (opened by a link/script), ``"startup"`` (initial
          browser tab), or ``"user"`` (opened externally)
        - ``age_seconds``: How long the tab has been open

        The response also includes summary counts: ``total``,
        ``agent_count``, and ``popup_count``.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with list of tabs and summary counts
        """
        session = get_session(profile)
        tabs = await session.list_tabs()
        agent_count = sum(1 for t in tabs if t.get("origin") == "agent")
        popup_count = sum(1 for t in tabs if t.get("origin") == "popup")
        return {
            "ok": True,
            "tabs": tabs,
            "total": len(tabs),
            "agent_count": agent_count,
            "popup_count": popup_count,
        }

    @mcp.tool()
    async def browser_open(
        url: str,
        background: bool = False,
        profile: str = "default",
        wait_until: str = "load",
    ) -> dict:
        """
        Open a new browser tab and navigate to the given URL.

        This tool already waits for the page to reach the ``wait_until``
        condition (default: ``load``) before returning.
        You do NOT need to call ``browser_wait`` afterward.

        Args:
            url: URL to navigate to
            background: Open in background without stealing focus
                from the current tab (default: False)
            profile: Browser profile name (default: "default")
            wait_until: Wait condition - "commit",
                "domcontentloaded", "load" (default),
                or "networkidle"

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

    @mcp.tool()
    async def browser_close_all(keep_active: bool = True, profile: str = "default") -> dict:
        """
        Close all browser tabs, optionally keeping the active tab.

        Args:
            keep_active: If True (default), keep the active tab open.
                If False, close ALL tabs (browser remains running).
            profile: Browser profile name (default: "default")

        Returns:
            Dict with number of closed tabs and remaining count
        """
        session = get_session(profile)
        to_close = [
            tid
            for tid in list(session.pages.keys())
            if not (keep_active and tid == session.active_page_id)
        ]
        closed = 0
        for tid in to_close:
            result = await session.close_tab(tid)
            if result.get("ok"):
                closed += 1
        return {"ok": True, "closed_count": closed, "remaining": len(session.pages)}

    @mcp.tool()
    async def browser_close_finished(keep_active: bool = True, profile: str = "default") -> dict:
        """
        Close all agent-opened and popup tabs that you are done with.

        This is the preferred cleanup tool during and after multi-tab tasks.
        It only closes tabs with ``origin="agent"`` or ``origin="popup"``,
        leaving ``"startup"`` and ``"user"`` tabs untouched.

        Use this instead of ``browser_close_all`` when you want to clean up
        your own tabs without disturbing tabs the user may have open.

        Args:
            keep_active: If True (default), skip closing the active tab even
                if it is agent- or popup-owned. Set to False to close it too.
            profile: Browser profile name (default: "default")

        Returns:
            Dict with closed_count, skipped_count, and remaining tab count
        """
        session = get_session(profile)
        closeable_origins = {"agent", "popup"}
        to_close = [
            tid
            for tid, meta in session.page_meta.items()
            if meta.origin in closeable_origins
            and not (keep_active and tid == session.active_page_id)
        ]
        closed = 0
        skipped = 0
        for tid in to_close:
            result = await session.close_tab(tid)
            if result.get("ok"):
                closed += 1
            else:
                skipped += 1
        return {
            "ok": True,
            "closed_count": closed,
            "skipped_count": skipped,
            "remaining": len(session.pages),
        }
