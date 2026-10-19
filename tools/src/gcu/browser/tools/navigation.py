"""
Browser navigation tools - navigate, go_back, go_forward, reload.

All operations go through the Beeline extension via CDP.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Annotated, Literal

from fastmcp import FastMCP
from framework.rate_limiter import SocialRateLimiter
from pydantic import Field

from ..bridge import connection_error, get_bridge
from ..telemetry import log_tool_call
from .lifecycle import _ensure_context, summarize_group_tabs
from .tabs import _get_context

logger = logging.getLogger(__name__)

# ── Profile-view rate limiting (LinkedIn + Instagram) ────────────

_LINKEDIN_PROFILE_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/[^/?#]+",
    re.IGNORECASE,
)

_INSTAGRAM_PROFILE_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/([a-zA-Z0-9._]{1,30})/?(?:\?.*)?$",
    re.IGNORECASE,
)

_IG_NON_PROFILE_PATHS = frozenset(
    {
        "explore",
        "direct",
        "reels",
        "stories",
        "accounts",
        "p",
        "reel",
        "tv",
        "about",
        "legal",
        "developer",
        "static",
    }
)


def _is_instagram_profile_url(url: str) -> bool:
    m = _INSTAGRAM_PROFILE_RE.match(url)
    if not m:
        return False
    return m.group(1).lower() not in _IG_NON_PROFILE_PATHS


def _record_profile_view(platform: str, account_id: str | None) -> None:
    try:
        SocialRateLimiter().record(platform, account_id or "unknown", "profile_view")
    except Exception:
        logger.debug("failed to record profile_view", exc_info=True)


# ── browser_navigate prompts ─────────────────────────────────────

BROWSER_NAVIGATE_DOC = """\
Navigate a tab to a URL.

Lazy-creates a browser context if none exists; when no ``tab_id``
is given and the context was just created, navigation lands on
the seed tab. Prefer ``browser_open`` when you specifically want
a new tab — ``browser_navigate`` is for redirecting an existing tab.

Waits for the page to reach the ``wait_until`` condition before
returning.

Returns a dict with navigation result (url, title)."""

BROWSER_NAVIGATE_PARAMS = {
    "url": "URL to navigate to",
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
    "wait_until": ("Wait condition - one of: commit, domcontentloaded, load (default), networkidle"),
}

# ── browser_reload prompts ─────────────────────────────────────

BROWSER_RELOAD_DOC = """\
Reload the current page.

Returns a dict with reload result."""

BROWSER_RELOAD_PARAMS = {
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
}


def register_navigation_tools(mcp: FastMCP) -> None:
    """Register browser navigation tools."""

    @mcp.tool(description=BROWSER_NAVIGATE_DOC)
    async def browser_navigate(
        url: Annotated[str, Field(description=BROWSER_NAVIGATE_PARAMS["url"])],
        tab_id: Annotated[int | None, Field(description=BROWSER_NAVIGATE_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_NAVIGATE_PARAMS["profile"])] = None,
        wait_until: Annotated[
            Literal["commit", "domcontentloaded", "load", "networkidle"],
            Field(description=BROWSER_NAVIGATE_PARAMS["wait_until"]),
        ] = "load",
        # Framework-injected (CONTEXT_PARAM) — human-readable queen/colony
        # label for the tab group; stripped from the LLM-facing schema.
        profile_display_name: str | None = None,
        browser_profile: Annotated[
            str | None,
            Field(
                description=(
                    "Which Chrome profile to act in — a connected profile label from "
                    "list_browser_profiles. Set it to target a specific logged-in account; "
                    "omit to use the starred/sole connected profile."
                ),
            ),
        ] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"url": url, "tab_id": tab_id, "profile": profile, "wait_until": wait_until, "browser_profile": browser_profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_navigate", params, result=result)
            return result

        try:
            _, ctx, _ = await _ensure_context(bridge, profile, profile_display_name, browser_profile)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_navigate",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab. Open a tab first with browser_open."}
            log_tool_call("browser_navigate", params, result=result)
            return result

        # ── Profile-view rate limit (LinkedIn + Instagram) ─────
        _profile_platform: str | None = None
        if _LINKEDIN_PROFILE_RE.match(url):
            _profile_platform = "linkedin"
        elif _is_instagram_profile_url(url):
            _profile_platform = "instagram"

        _nav_account_id: str | None = None
        if _profile_platform:
            from ..hooks.rate_limit_hook import _detect_identity

            _nav_account_id = await _detect_identity(bridge, target_tab, _profile_platform) or "unknown"
            limiter = SocialRateLimiter()
            check = limiter.check(_profile_platform, _nav_account_id, "profile_view")
            if not check["allowed"]:
                logger.info(
                    "browser_navigate blocked: %s profile_view limit for account=%s reason=%s",
                    _profile_platform,
                    _nav_account_id,
                    check.get("reason"),
                )
                from ..hooks.rate_limit_hook import RATE_LIMIT_GUIDANCE

                result = {
                    "ok": False,
                    "error": "rate_limited",
                    "action_type": "profile_view",
                    "platform": _profile_platform,
                    "halt_campaign": check.get("halt_campaign", True),
                    **{k: v for k, v in check.items() if k != "allowed"},
                    "guidance": RATE_LIMIT_GUIDANCE,
                }
                log_tool_call("browser_navigate", params, result=result, duration_ms=(time.perf_counter() - start) * 1000)
                return result

        try:
            nav_result = await bridge.navigate(target_tab, url, wait_until=wait_until)
            # Bridge short-circuits with ok=False + pending_dialog when a
            # native beforeunload / confirm dialog blocks the navigation.
            # Pass that envelope through unchanged so the agent can route
            # to browser_dialog_respond instead of seeing a misleading
            # "navigated successfully" with the previous page's URL.
            if not nav_result.get("ok", True) and "pending_dialog" in nav_result:
                log_tool_call(
                    "browser_navigate",
                    params,
                    result=nav_result,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    tab_id=target_tab,
                    action=("navigate", url),
                )
                return {**nav_result, "tabId": target_tab}
            # Mirror browser_open: surface the group's full tab list so the
            # agent can spot click-spawned popups or leftover duplicates
            # before deciding what to do next.
            group_summary = await summarize_group_tabs(bridge, ctx)
            result = {
                "ok": True,
                "tabId": target_tab,
                "url": nav_result.get("url"),
                "title": nav_result.get("title"),
                # Chrome profile this navigation ran in — so the agent can
                # confirm it's acting on the intended account.
                "browser_profile": ctx.get("browser_profile"),
                **group_summary,
            }
            if _profile_platform:
                _record_profile_view(_profile_platform, _nav_account_id)
            log_tool_call(
                "browser_navigate",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=("navigate", url),
            )
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_navigate",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=("navigate", url),
            )
            return result

    @mcp.tool(description=BROWSER_RELOAD_DOC)
    async def browser_reload(
        tab_id: Annotated[int | None, Field(description=BROWSER_RELOAD_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_RELOAD_PARAMS["profile"])] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_reload", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_open(url) first to open a tab."}
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
                tab_id=target_tab,
                action=("navigate", "reload"),
            )
            return nav_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_reload",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=("navigate", "reload"),
            )
            return result
