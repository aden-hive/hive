"""
Browser navigation tools - navigate, go_back, go_forward, reload.

All operations go through the Beeline extension via CDP.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from fastmcp import FastMCP

from ..bridge import get_bridge
from ..telemetry import log_tool_call
from .tabs import _get_context

logger = logging.getLogger(__name__)


def register_navigation_tools(mcp: FastMCP) -> None:
    """Register browser navigation tools."""

    @mcp.tool()
    async def browser_navigate(
        url: str,
        tab_id: int | None = None,
        profile: str | None = None,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "load",
    ) -> dict:
        """
        Navigate a tab to a URL.

        This tool waits for the page to reach the ``wait_until`` condition
        before returning.

        Args:
            url: URL to navigate to
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            wait_until: Wait condition - one of: commit, domcontentloaded,
                load (default), networkidle

        Returns:
            Dict with navigation result (url, title)
        """
        start = time.perf_counter()
        params = {"url": url, "tab_id": tab_id, "profile": profile, "wait_until": wait_until}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_navigate", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_navigate", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab. Open a tab first with browser_open."}
            log_tool_call("browser_navigate", params, result=result)
            return result

        try:
            nav_result = await bridge.navigate(target_tab, url, wait_until=wait_until)
            result = {
                "ok": True,
                "tabId": target_tab,
                "url": nav_result.get("url"),
                "title": nav_result.get("title"),
            }
            log_tool_call(
                "browser_navigate",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_navigate",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

    @mcp.tool()
    async def browser_go_back(
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Navigate back in browser history.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with navigation result
        """
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_go_back", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_go_back", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_go_back", params, result=result)
            return result

        try:
            nav_result = await bridge.go_back(target_tab)
            log_tool_call(
                "browser_go_back",
                params,
                result=nav_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return nav_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_go_back", params, error=e, duration_ms=(time.perf_counter() - start) * 1000
            )
            return result

    @mcp.tool()
    async def browser_go_forward(
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Navigate forward in browser history.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with navigation result
        """
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_go_forward", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_go_forward", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_go_forward", params, result=result)
            return result

        try:
            nav_result = await bridge.go_forward(target_tab)
            log_tool_call(
                "browser_go_forward",
                params,
                result=nav_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return nav_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_go_forward",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

    @mcp.tool()
    async def browser_reload(
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Reload the current page.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with reload result
        """
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_reload", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_reload", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_reload", params, result=result)
            return result

        try:
            nav_result = await bridge.reload(target_tab)
            log_tool_call(
                "browser_reload",
                params,
                result=nav_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return nav_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_reload", params, error=e, duration_ms=(time.perf_counter() - start) * 1000
            )
            return result
