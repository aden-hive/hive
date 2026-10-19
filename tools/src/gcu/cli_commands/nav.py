"""``hive-browser open | navigate | reload`` — mirror of ``browser_open`` /
``browser_navigate`` / ``browser_reload`` (tabs.py + navigation.py)."""

from __future__ import annotations

import argparse
import time

from gcu.browser.bridge import connection_error, get_bridge
from gcu.browser.telemetry import log_tool_call
from gcu.browser.tools.lifecycle import (
    _connected_profiles,
    _ensure_context,
    _persist_contexts,
    summarize_group_tabs,
)
from gcu.browser.tools.tabs import _get_context, _is_privileged_scheme
from gcu.errors import validation


async def validate_browser_profile(bridge, browser_profile: str | None) -> None:
    """Reject an unknown ``--browser-profile`` (audit B4).

    The bridge's ``resolve_connection`` silently falls back to the sole connected
    Chrome profile for an unknown label — so an agent that thinks it's isolated is
    actually on the default. Validate against the connected labels; reject only
    when we HAVE a label list and the given one isn't in it (an empty list means
    we couldn't enumerate — don't guess).
    """
    if not browser_profile or browser_profile == "default":
        return
    profiles = await _connected_profiles(bridge)
    labels = [p.get("label") for p in profiles if p.get("label")]
    if labels and browser_profile not in labels:
        raise validation(f"unknown browser profile {browser_profile!r}. connected: {labels}")


async def cmd_open(args: argparse.Namespace) -> dict:
    url = args.url
    start = time.perf_counter()
    params = {"url": url, "background": args.background, "profile": args.profile, "browser_profile": args.browser_profile}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_open", params, result=result)
        return result

    await validate_browser_profile(bridge, args.browser_profile)

    tab_id: int | None = None
    try:
        _, ctx, _ = await _ensure_context(bridge, args.profile, args._display_name, args.browser_profile)
        seed_tab = ctx.pop("_seedTabId", None)
        if seed_tab is not None:
            tab_id = seed_tab
        else:
            result = await bridge.create_tab(url=url, group_id=ctx.get("groupId"))
            tab_id = result.get("tabId")

        if tab_id is not None:
            ctx.setdefault("tabs", set()).add(tab_id)

        if not args.background and tab_id is not None:
            ctx["activeTabId"] = tab_id
            await bridge.activate_tab(tab_id)
        # Persist the new tab + active cursor so the next CLI invocation sees them
        # (the earlier _ensure_context persist predates this tab, audit B2).
        _persist_contexts()

        if _is_privileged_scheme(url):
            nav_result = {"url": url, "title": ""}
        else:
            nav_result = await bridge.navigate(tab_id, url, wait_until="load")

        group_summary = await summarize_group_tabs(bridge, ctx)
        result = {
            "ok": True,
            "tabId": tab_id,
            "url": nav_result.get("url", url),
            "title": nav_result.get("title", ""),
            "background": args.background,
            "browser_profile": ctx.get("browser_profile"),
            **group_summary,
        }
        log_tool_call("browser_open", params, result=result, duration_ms=(time.perf_counter() - start) * 1000, tab_id=tab_id, action=("open", url))
        return result
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        if tab_id is not None:
            result["tabId"] = tab_id
            result["hint"] = (
                "A tab was created before this error. Run `hive-browser tab list` to verify "
                "state, or `hive-browser tab close` to discard it, before retrying."
            )
        log_tool_call("browser_open", params, error=e, duration_ms=(time.perf_counter() - start) * 1000, tab_id=tab_id, action=("open", url))
        return result


async def cmd_navigate(args: argparse.Namespace) -> dict:
    # Import navigation helpers lazily so the module import stays cheap and the
    # rate-limiter (framework dep) is only pulled when a nav actually runs.
    from framework.rate_limiter import SocialRateLimiter

    from gcu.browser.tools.navigation import (
        _LINKEDIN_PROFILE_RE,
        _is_instagram_profile_url,
        _record_profile_view,
    )

    url = args.url
    tab_id = args.tab
    wait_until = args.wait_until
    start = time.perf_counter()
    params = {"url": url, "tab_id": tab_id, "profile": args.profile, "wait_until": wait_until, "browser_profile": args.browser_profile}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_navigate", params, result=result)
        return result

    await validate_browser_profile(bridge, args.browser_profile)

    try:
        _, ctx, _ = await _ensure_context(bridge, args.profile, args._display_name, args.browser_profile)
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        log_tool_call("browser_navigate", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
        return result

    target_tab = tab_id or ctx.get("activeTabId")
    if target_tab is None:
        result = {"ok": False, "error": "No active tab. Open a tab first with `hive-browser open`."}
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
        from gcu.browser.hooks.rate_limit_hook import _detect_identity

        _nav_account_id = await _detect_identity(bridge, target_tab, _profile_platform) or "unknown"
        limiter = SocialRateLimiter()
        check = limiter.check(_profile_platform, _nav_account_id, "profile_view")
        if not check["allowed"]:
            from gcu.browser.hooks.rate_limit_hook import RATE_LIMIT_GUIDANCE

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
        nav_result = await bridge.navigate(target_tab, url, wait_until=wait_until, timeout_ms=args.timeout_ms)
        # Propagate ANY bridge-level failure (pending dialog, DNS / chrome-error
        # page) — don't hardcode ok:true over it (audit B3).
        if not nav_result.get("ok", True):
            log_tool_call(
                "browser_navigate",
                params,
                result=nav_result,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=("navigate", url),
            )
            return {**nav_result, "tabId": target_tab}
        group_summary = await summarize_group_tabs(bridge, ctx)
        result = {
            "ok": True,
            "tabId": target_tab,
            "url": nav_result.get("url"),
            "title": nav_result.get("title"),
            "browser_profile": ctx.get("browser_profile"),
            **group_summary,
        }
        if _profile_platform:
            _record_profile_view(_profile_platform, _nav_account_id)
        log_tool_call(
            "browser_navigate", params, result=result, duration_ms=(time.perf_counter() - start) * 1000, tab_id=target_tab, action=("navigate", url)
        )
        return result
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        log_tool_call(
            "browser_navigate", params, error=e, duration_ms=(time.perf_counter() - start) * 1000, tab_id=target_tab, action=("navigate", url)
        )
        return result


async def cmd_reload(args: argparse.Namespace) -> dict:
    start = time.perf_counter()
    params = {"tab_id": args.tab, "profile": args.profile}

    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        result = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_reload", params, result=result)
        return result

    ctx = _get_context(args.profile)
    if not ctx:
        result = {"ok": False, "error": "Browser not started. Run `hive-browser open <url>` first."}
        log_tool_call("browser_reload", params, result=result)
        return result

    target_tab = args.tab or ctx.get("activeTabId")
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
            "browser_reload", params, error=e, duration_ms=(time.perf_counter() - start) * 1000, tab_id=target_tab, action=("navigate", "reload")
        )
        return result
