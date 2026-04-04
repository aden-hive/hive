"""
Browser lifecycle tools - start, stop, status.

These tools manage the browser context via the Beeline extension bridge.
No Playwright required - all operations go through the Chrome extension.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from ..bridge import get_bridge
from ..session import _active_profile
from ..telemetry import log_context_event, log_tool_call

logger = logging.getLogger(__name__)

# Track active contexts per profile
_contexts: dict[str, dict[str, Any]] = {}


def _resolve_profile(profile: str | None) -> str:
    """Resolve profile name, using context variable if not provided."""
    if profile is not None:
        return profile
    return _active_profile.get()


# Resolve extension path relative to this file: tools/browser-extension/
_EXTENSION_PATH = (
    Path(__file__).parent.parent.parent.parent.parent / "browser-extension"
).resolve()


def register_lifecycle_tools(mcp: FastMCP) -> None:
    """Register browser lifecycle management tools."""

    @mcp.tool()
    async def browser_setup() -> dict:
        """
        Check browser extension status and show installation instructions if needed.

        Call this first if browser tools are not working. It checks whether the
        Hive Chrome extension is installed and connected, and provides step-by-step
        instructions to install it if not.

        Returns:
            Dict with connection status and setup instructions if needed
        """
        bridge = get_bridge()
        connected = bool(bridge and bridge.is_connected)

        ext_path = str(_EXTENSION_PATH)
        ext_exists = _EXTENSION_PATH.exists()

        if connected:
            return {
                "ok": True,
                "connected": True,
                "status": "Extension is connected and ready. Call browser_start to begin.",
            }

        return {
            "ok": False,
            "connected": False,
            "status": "Extension not connected",
            "instructions": {
                "step_1": "Open Chrome and go to chrome://extensions",
                "step_2": "Enable 'Developer mode' (toggle in the top-right corner)",
                "step_3": "Click 'Load unpacked'",
                "step_4": f"Select this directory: {ext_path}",
                "step_5": "Click the extension icon in the Chrome toolbar to confirm it says 'Connected'",
                "step_6": "Return here and call browser_start",
            },
            "extensionPath": ext_path,
            "extensionPathExists": ext_exists,
            "note": (
                "The extension connects via WebSocket on ws://127.0.0.1:9229/beeline. "
                "Make sure Chrome is running before loading the extension."
            ),
        }

    @mcp.tool()
    async def browser_status(profile: str | None = None) -> dict:
        """
        Get the current status of the browser.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with browser status
        """
        start = time.perf_counter()
        params = {"profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {
                "ok": False,
                "error": "Browser extension not connected. Call browser_setup for installation instructions.",
                "connected": False,
            }
            log_tool_call("browser_status", params, result=result)
            return result

        profile_name = _resolve_profile(profile)
        ctx = _contexts.get(profile_name)

        if ctx:
            try:
                tabs_result = await bridge.list_tabs(ctx.get("groupId"))
                tabs = tabs_result.get("tabs", [])
                result = {
                    "ok": True,
                    "connected": True,
                    "profile": profile_name,
                    "running": True,
                    "groupId": ctx.get("groupId"),
                    "activeTab": ctx.get("activeTabId"),
                    "tabs": len(tabs),
                }
                log_tool_call(
                    "browser_status",
                    params,
                    result=result,
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
                return result
            except Exception as e:
                result = {
                    "ok": True,
                    "connected": True,
                    "profile": profile_name,
                    "running": False,
                    "error": str(e),
                }
                log_tool_call(
                    "browser_status",
                    params,
                    result=result,
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
                return result

        result = {
            "ok": True,
            "connected": True,
            "profile": profile_name,
            "running": False,
            "tabs": 0,
        }
        log_tool_call(
            "browser_status",
            params,
            result=result,
            duration_ms=(time.perf_counter() - start) * 1000,
        )
        return result

    @mcp.tool()
    async def browser_start(profile: str | None = None) -> dict:
        """
        Start a browser context for the given profile.

        Creates a tab group in the user's Chrome via the Beeline extension.
        No separate browser process is launched - uses the user's existing Chrome.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with start status including groupId and initial tabId
        """
        start = time.perf_counter()
        params = {"profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {
                "ok": False,
                "error": (
                    "Browser extension not connected. Call browser_setup for installation instructions."
                ),
            }
            log_tool_call("browser_start", params, result=result)
            return result

        profile_name = _resolve_profile(profile)

        # Check if already running
        if profile_name in _contexts:
            ctx = _contexts[profile_name]
            result = {
                "ok": True,
                "status": "already_running",
                "profile": profile_name,
                "groupId": ctx.get("groupId"),
                "activeTabId": ctx.get("activeTabId"),
            }
            log_tool_call(
                "browser_start",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

        try:
            result = await bridge.create_context(profile_name)
            group_id = result.get("groupId")
            tab_id = result.get("tabId")

            _contexts[profile_name] = {
                "groupId": group_id,
                "activeTabId": tab_id,
            }

            logger.info(
                "Started browser context '%s': groupId=%s, tabId=%s",
                profile_name,
                group_id,
                tab_id,
            )

            log_context_event("start", profile_name, group_id=group_id, tab_id=tab_id)

            result = {
                "ok": True,
                "status": "started",
                "profile": profile_name,
                "groupId": group_id,
                "activeTabId": tab_id,
            }
            log_tool_call(
                "browser_start",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result
        except Exception as e:
            logger.exception("Failed to start browser context")
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_start", params, error=e, duration_ms=(time.perf_counter() - start) * 1000
            )
            return result

    @mcp.tool()
    async def browser_stop(profile: str | None = None) -> dict:
        """
        Stop the browser context and close all tabs in the group.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with stop status
        """
        start = time.perf_counter()
        params = {"profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_stop", params, result=result)
            return result

        profile_name = _resolve_profile(profile)
        ctx = _contexts.pop(profile_name, None)

        if not ctx:
            result = {"ok": True, "status": "not_running", "profile": profile_name}
            log_tool_call(
                "browser_stop",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

        try:
            group_id = ctx.get("groupId")
            closed_tabs = 0
            if group_id is not None:
                result = await bridge.destroy_context(group_id)
                closed_tabs = result.get("closedTabs", 0)
                logger.info(
                    "Stopped browser context '%s': closed %d tabs",
                    profile_name,
                    closed_tabs,
                )

            log_context_event(
                "stop", profile_name, group_id=group_id, details={"closed_tabs": closed_tabs}
            )

            result = {
                "ok": True,
                "status": "stopped",
                "profile": profile_name,
                "closedTabs": closed_tabs,
            }
            log_tool_call(
                "browser_stop",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result
        except Exception as e:
            logger.exception("Failed to stop browser context")
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_stop", params, error=e, duration_ms=(time.perf_counter() - start) * 1000
            )
            return result
