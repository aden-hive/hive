"""
Browser session management - minimal stub for legacy compatibility.

This module provides session tracking for the bridge extension.
No Playwright is used for actual browser automation.
All operations go through the Chrome extension via CDP.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Constants
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_NAVIGATION_TIMEOUT_MS = 60000

# ContextVar for profile routing (inherited from legacy code). This is the
# AGENT/session id (which tab group), NOT the Chrome browser profile.
_active_profile: contextvars.ContextVar[str] = contextvars.ContextVar("hive_gcu_profile", default="default")

# ContextVar for the Chrome BROWSER profile (which extension connection / Chrome
# user a command targets). Distinct from _active_profile. Normally supplied per
# tool call as the injected ``browser_profile`` CONTEXT_PARAM; this var is the
# fallback default for gcu-internal helpers that run without that arg.
_active_browser_profile: contextvars.ContextVar[str] = contextvars.ContextVar("hive_gcu_browser_profile", default="default")


def set_active_profile(profile: str) -> contextvars.Token:
    """Set the active agent profile for the current async context."""
    return _active_profile.set(profile)


def set_active_browser_profile(browser_profile: str) -> contextvars.Token:
    """Set the active Chrome browser profile for the current async context."""
    return _active_browser_profile.set(browser_profile)


def get_session(profile: str | None = None) -> dict[str, Any]:
    """Get or create a session record for a profile.

    Deprecated: Sessions are now managed via the bridge extension.
    This function returns a minimal stub for compatibility.
    """
    profile_name = profile or _active_profile.get()
    return {"profile": profile_name, "status": "managed_via_bridge"}


def get_all_sessions() -> dict[str, Any]:
    """Get all registered sessions."""
    return {}


async def shutdown_all_browsers() -> None:
    """Stop all browser sessions. Called at server shutdown to clean up."""
    from gcu.browser.tools.lifecycle import shutdown_all_contexts

    await shutdown_all_contexts()


class BrowserSession:
    """Stub class for backward compatibility.

    The actual browser session is managed by the Chrome extension.
    This class provides minimal compatibility for code that
    expects a BrowserSession object.
    """

    def __init__(self, profile: str = "default") -> None:
        self.profile = profile
        self.pages: dict[str, Any] = {}
        self.active_page_id: str | None = None
        self.ref_maps: dict[str, Any] = {}
