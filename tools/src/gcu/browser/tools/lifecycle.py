"""
Browser lifecycle tools - start, stop, status.

These tools manage the browser context via the Beeline extension bridge.
No Playwright required - all operations go through the Chrome extension.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..bridge import DEFAULT_BROWSER_PROFILE, BridgeError, connection_error, get_bridge
from ..session import _active_browser_profile, _active_profile
from ..telemetry import log_context_event, log_tool_call

logger = logging.getLogger(__name__)

# Track active contexts per profile
_contexts: dict[str, dict[str, Any]] = {}

# Lazy per-profile lock so two concurrent queens hitting _ensure_context
# for the same profile don't both call bridge.create_context (which would
# produce duplicate tab groups for one logical profile).
_context_locks: dict[str, asyncio.Lock] = {}

# Deferred closes. When close_profile_context can't reach the bridge during a
# reap (a sub-second extension reload racing worker shutdown), the (profile,
# groupId) lands here instead of being silently dropped, and drain_dead_letter()
# retries it. In-memory and per-process — the runtime reaping workers is
# long-lived, so a deferral from one reap is retried on the next. The
# bridge-side orphan reaper is the durable backstop for the rest.
_DEAD_LETTER: list[dict[str, Any]] = []

# How long close_profile_context waits for a momentarily-disconnected bridge to
# come back before deferring. The disconnect that races shutdown is usually a
# sub-second extension reload, so a short wait converts most would-be leaks into
# synchronous closes; the dead-letter queue covers the rest.
_REAP_RECONNECT_WAIT_S = 3.0
_REAP_RECONNECT_POLL_S = 0.1


async def _await_bridge_reconnect() -> Any | None:
    """Poll for the bridge to (re)connect, up to ``_REAP_RECONNECT_WAIT_S``.

    Returns the connected bridge, or ``None`` if it never came back in the
    window.
    """
    deadline = time.monotonic() + _REAP_RECONNECT_WAIT_S
    while time.monotonic() < deadline:
        bridge = get_bridge()
        if bridge and bridge.is_connected:
            return bridge
        await asyncio.sleep(_REAP_RECONNECT_POLL_S)
    bridge = get_bridge()
    return bridge if (bridge and bridge.is_connected) else None


def _enqueue_dead_letter(profile_name: str, group_id: int, name: str | None, reason: str, browser_profile: str | None = None) -> None:
    """Queue a deferred close for later retry. Deduped by (profile, groupId)."""
    for entry in _DEAD_LETTER:
        if entry.get("profile") == profile_name and entry.get("groupId") == group_id:
            return
    _DEAD_LETTER.append(
        {
            "profile": profile_name,
            "groupId": group_id,
            "name": name,
            "reason": reason,
            "browser_profile": browser_profile,
        }
    )


async def drain_dead_letter() -> int:
    """Retry deferred context closes. Idempotent; safe to call repeatedly.

    Returns the number of groups successfully closed this pass. Entries whose
    close still fails are left queued for the next attempt.
    """
    if not _DEAD_LETTER:
        return 0
    bridge = get_bridge()
    if not (bridge and bridge.is_connected):
        return 0
    closed = 0
    for entry in list(_DEAD_LETTER):
        try:
            await bridge.destroy_context(entry["groupId"], browser_profile=entry.get("browser_profile"))
        except Exception as exc:
            logger.debug("drain_dead_letter: retry failed for group=%s: %s", entry.get("groupId"), exc)
            continue
        _DEAD_LETTER.remove(entry)
        closed += 1
        logger.info(
            "drain_dead_letter: closed deferred context profile=%s group=%s",
            entry.get("profile"),
            entry.get("groupId"),
        )
    return closed


def list_active_contexts() -> list[dict[str, Any]]:
    """Read-only snapshot of the in-memory profile→tab-group registry.

    Used by the worker reap-timeline test endpoint to assert that a
    worker's profile entry disappears after termination. Does NOT touch
    the bridge — purely a view onto local state.
    """
    snapshot: list[dict[str, Any]] = []
    for profile, ctx in _contexts.items():
        tabs = ctx.get("tabs")
        if isinstance(tabs, set):
            tab_count = len(tabs)
        elif isinstance(tabs, (list, tuple)):
            tab_count = len(tabs)
        else:
            tab_count = 0
        snapshot.append(
            {
                "profile": profile,
                "group_id": ctx.get("groupId"),
                "name": ctx.get("name"),
                "tab_count": tab_count,
                "active_tab_id": ctx.get("activeTabId"),
            }
        )
    return snapshot


def _profile_lock(profile_name: str) -> asyncio.Lock:
    lock = _context_locks.get(profile_name)
    if lock is None:
        lock = asyncio.Lock()
        _context_locks[profile_name] = lock
    return lock


# ── Context persistence ────────────────────────────────────────────────────
# In client mode the bridge — and the Chrome tab groups it owns — outlive this
# gcu process. Persisting the profile→group index lets a freshly-restarted gcu
# re-attach to tabs that are still open instead of orphaning them and creating
# a duplicate group.
_CONTEXTS_FILE = Path.home() / ".hive" / "browser_contexts.json"


def _persist_contexts() -> None:
    """Best-effort snapshot of the profile→group index to disk (client mode).

    Only the stable identity (groupId + label) is stored; live tab ids are
    re-derived from the bridge on rehydrate, so they can never go stale here.
    """
    from ..bridge import is_client_mode

    if not is_client_mode():
        return
    try:
        snapshot = {
            profile: {
                "groupId": ctx.get("groupId"),
                "name": ctx.get("name"),
                "browser_profile": ctx.get("browser_profile"),
                # Persist the tracked active tab so it survives across per-invocation
                # CLI processes (audit B2). Chrome's per-window `active` flag is
                # ambiguous for a background tab group, so it can't be re-derived
                # reliably on rehydrate — the agent's explicit `tab activate` (and
                # open/navigate) is the source of truth.
                "activeTabId": ctx.get("activeTabId"),
            }
            for profile, ctx in _contexts.items()
            if ctx.get("groupId") is not None
        }
        _CONTEXTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONTEXTS_FILE.write_text(json.dumps(snapshot))
    except Exception as e:
        logger.debug("could not persist browser contexts: %s", e)


async def rehydrate_contexts(bridge: Any) -> None:
    """Rebuild ``_contexts`` from tab groups that survived a gcu restart.

    For each persisted profile→group entry whose group still has live tabs,
    repopulate ``_contexts`` with fresh tab info from the bridge. Groups whose
    tabs are all gone are dropped. A no-op when nothing is persisted.
    """
    try:
        snapshot = json.loads(_CONTEXTS_FILE.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(snapshot, dict):
        return

    recovered = 0
    for profile, meta in snapshot.items():
        group_id = (meta or {}).get("groupId")
        if group_id is None or profile in _contexts:
            continue
        try:
            tabs_result = await bridge.list_tabs(group_id)
        except Exception:
            continue  # group gone or bridge busy — drop it
        tabs = tabs_result.get("tabs", []) or []
        tab_ids = {t.get("id") or t.get("tabId") for t in tabs}
        tab_ids.discard(None)
        if not tab_ids:
            continue  # every tab closed while gcu was down — drop it
        # Prefer the persisted active tab (the agent's explicit cursor); fall back
        # to Chrome's `active` flag / first tab only if that tab is gone (audit B2).
        persisted_active = (meta or {}).get("activeTabId")
        if persisted_active in tab_ids:
            active_tab_id = persisted_active
        else:
            active = next((t for t in tabs if t.get("active")), tabs[0])
            active_tab_id = active.get("id") or active.get("tabId")
        bp = (meta or {}).get("browser_profile") or "default"
        _contexts[profile] = {
            "groupId": group_id,
            "activeTabId": active_tab_id,
            "_seedTabId": None,  # the seed tab was consumed in the prior session
            "name": (meta or {}).get("name"),
            "browser_profile": bp,
            "tabs": tab_ids,
        }
        # Re-publish to the bridge's registry — it may have restarted too and
        # come back with an empty registry, which would blank out /contexts.
        try:
            await bridge.register_context(profile, group_id, (meta or {}).get("name"), browser_profile=bp)
        except Exception:
            pass
        recovered += 1

    if recovered:
        logger.info("rehydrated %d browser context(s) from a previous gcu session", recovered)
    # Retry any closes that were deferred while the bridge was unreachable.
    try:
        await drain_dead_letter()
    except Exception:
        pass
    # Re-persist so dropped (stale) entries don't linger on disk.
    _persist_contexts()


def _resolve_profile(profile: str | None) -> str:
    """Resolve profile name, using context variable if not provided."""
    if profile is not None:
        return profile
    return _active_profile.get()


def _resolve_browser_profile(browser_profile: str | None) -> str:
    """Resolve the Chrome browser-profile label, falling back to the contextvar
    default ("default") when a tool call didn't carry one."""
    if browser_profile:
        return browser_profile
    return _active_browser_profile.get()


async def _connected_profiles(bridge: Any) -> list[dict[str, Any]]:
    """All Chrome profiles currently connected to the bridge — for discovery.

    Surfaced in browser_status / browser_setup so an agent sees EVERY connected
    profile (not just its own context's one) and can pick a label to pass as
    ``browser_profile``. ``bridge.connected_profiles`` is sync in host mode but a
    coroutine via the client-mode RemoteBridge RPC, so await it conditionally.
    Best-effort: returns [] on any error or against an older bridge.
    """
    try:
        fn = getattr(bridge, "connected_profiles", None)
        if fn is None:
            return []
        res = fn()
        if inspect.isawaitable(res):
            res = await res
        return res or []
    except Exception:
        return []


# Resolve extension path relative to this file: tools/browser-extension/
# Kept for legacy callers; install flow now points at the Chrome Web Store.
_EXTENSION_PATH = (Path(__file__).parent.parent.parent.parent.parent / "browser-extension").resolve()

# Public Chrome Web Store listing for the Hive Browser Bridge.
_CHROME_WEB_STORE_URL = "https://chromewebstore.google.com/detail/hive-browser-bridge/jkpcegnbfimimjodblcemoheedidnppm"


def _clear_profile_tab_caches(ctx: dict[str, Any]) -> None:
    """Clear per-tab caches for every tab the profile knew about.

    Individual tab closes go through ``bridge.close_tab`` which clears
    caches per-tab; context destroys close every tab at once without
    per-tab notifications, so we clear them here from the tracked set.
    """
    tab_ids = ctx.get("tabs") or set()
    if not tab_ids:
        return
    from ..bridge import clear_tab_highlights
    from .inspection import clear_tab_state

    clear_tab_state(tab_ids)
    clear_tab_highlights(tab_ids)


def _assert_browser_profile_match(profile_name: str, ctx: dict[str, Any], requested: str | None) -> None:
    """Fail loud when a bound session is asked for a different Chrome profile.

    A session's tab group lives in exactly ONE Chrome profile, fixed at
    cold-start and restored across restarts by ``rehydrate_contexts``. An
    explicit ``browser_profile`` on a later call cannot move it. Returning the
    existing context anyway ran the work in the WRONG browser while still
    reporting ``ok`` — the caller believed it had switched accounts and only the
    response's ``browser_profile`` field (easily read past) said otherwise.

    Only a provable mismatch raises. An omitted or ``"default"`` request means
    "don't care", and a context still storing ``"default"`` (an older persisted
    entry, pre-resolution) can't be proven wrong — neither is an error.
    """
    if not requested or requested == DEFAULT_BROWSER_PROFILE:
        return
    bound = ctx.get("browser_profile")
    if not bound or bound == DEFAULT_BROWSER_PROFILE or bound == requested:
        return
    raise BridgeError(
        "browser_profile_conflict",
        f"session {profile_name!r} is already bound to Chrome profile {bound!r}, but this "
        f"call requested {requested!r}. A session's tab group cannot move between Chrome "
        f"profiles. Close it first with `hive-browser stop`, then reopen with "
        f"`--browser-profile {requested}`.",
    )


async def _ensure_context(
    bridge: Any,
    profile: str | None,
    profile_display_name: str | None = None,
    browser_profile: str | None = None,
) -> tuple[str, dict[str, Any], bool]:
    """Return ``(profile_name, ctx, created)`` for ``profile``.

    Lazy-creates the browser context (tab group + seed tab) the first time
    a profile is used so URL-taking tools (``browser_open`` /
    ``browser_navigate``) can be the agent's single cold-start entry
    point — no separate "start" tool to remember.

    ``profile_display_name`` is an optional human-readable label (queen /
    colony name) for the Chrome tab group and the ``/contexts`` listing;
    ``profile`` stays the stable session id used as the dict key.

    ``browser_profile`` is the Chrome profile (extension connection) the tab
    group is created in — the side-panel label of the target browser. Defaults
    to the logical ``"default"`` profile (single-browser behaviour). One agent
    binds to one browser profile; subsequent tab-scoped commands route back to
    it automatically via the bridge's tabId→connection map, so only this
    cold-start path needs the value. Once bound, an explicit ``browser_profile``
    naming a DIFFERENT profile raises ``browser_profile_conflict`` rather than
    silently handing back the already-bound one — see
    ``_assert_browser_profile_match``.

    Caller must verify ``bridge`` is connected first; any failure in
    ``bridge.create_context`` propagates so the caller's existing
    try/except converts it to an ``{"ok": False, ...}`` result.
    """
    profile_name = _resolve_profile(profile)
    bp = _resolve_browser_profile(browser_profile)
    existing = _contexts.get(profile_name)
    if existing is not None:
        _assert_browser_profile_match(profile_name, existing, browser_profile)
        return profile_name, existing, False

    # Serialize concurrent first-touch creators so we don't race the
    # bridge.create_context call. Re-check after acquiring; the winner
    # populates _contexts and the runner-up returns the same ctx.
    async with _profile_lock(profile_name):
        existing = _contexts.get(profile_name)
        if existing is not None:
            _assert_browser_profile_match(profile_name, existing, browser_profile)
            return profile_name, existing, False

        result = await bridge.create_context(profile_name, display_name=profile_display_name, browser_profile=bp)
        group_id = result.get("groupId")
        tab_id = result.get("tabId")
        # The ACTUAL Chrome profile the bridge routed to (its connection label),
        # which may differ from what we requested — e.g. "default" resolves to a
        # starred/sole connection. Store the real one so tools can report it and
        # the agent can tell whether it landed on the right account.
        resolved_bp = result.get("browser_profile") or bp

        ctx: dict[str, Any] = {
            "groupId": group_id,
            "activeTabId": tab_id,
            "_seedTabId": tab_id,  # reused by first browser_open call
            "name": profile_display_name,  # human label for /contexts (None → caller falls back)
            "browser_profile": resolved_bp,  # the Chrome profile this group actually lives in
            "tabs": {tab_id} if tab_id is not None else set(),
        }
        _contexts[profile_name] = ctx

        logger.info(
            "Started browser context '%s': groupId=%s, tabId=%s",
            profile_name,
            group_id,
            tab_id,
        )
        log_context_event("start", profile_name, group_id=group_id, tab_id=tab_id)
        _persist_contexts()

        return profile_name, ctx, True


# Threshold above which the agent gets nudged to close unused tabs. Set
# from observed worker failures where 4+ tabs accumulated (often duplicates
# from re-opens or target="_blank" popups) and the agent kept fanning out
# instead of pruning. Each extra tab adds memory pressure and another
# moving target the agent has to reason about.
_TAB_NUDGE_THRESHOLD = 3


def _tab_overflow_hint(count: int) -> dict[str, str]:
    """Return a ``{tabsHint: ...}`` payload when too many tabs are open.

    Empty dict below the threshold so callers can splat it unconditionally
    without leaking a noisy key into normal responses.
    """
    if count <= _TAB_NUDGE_THRESHOLD:
        return {}
    return {
        "tabsHint": (
            f"You have {count} tabs open in this group. Close tabs you no "
            "longer need with browser_close(tab_id=...) before opening or "
            "navigating more — too many open tabs slow the browser, consume "
            "memory, and have empirically caused workers to fail their task."
        ),
    }


async def summarize_group_tabs(bridge: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    """Return a ``{groupTabs, groupTabCount[, tabsHint]}`` summary for ``ctx``.

    Best-effort: returns ``{}`` if the bridge call fails so the caller's
    primary result is never blocked by a tab-listing hiccup. Each entry
    is ``{id, url, title, active}`` where ``active`` is derived locally
    against ``ctx["activeTabId"]`` (the bridge already returns the rest).
    ``tabsHint`` is only present when the count exceeds the nudge threshold.
    """
    group_id = ctx.get("groupId")
    if group_id is None:
        return {}
    try:
        result = await bridge.list_tabs(group_id)
    except Exception:
        return {}
    tabs = result.get("tabs", []) or []
    active_id = ctx.get("activeTabId")
    # Order matters: the hint and count come BEFORE ``groupTabs`` so that
    # if a downstream reader truncates a long response, the nudge survives
    # while the verbose tab list is what gets cut.
    return {
        **_tab_overflow_hint(len(tabs)),
        "groupTabCount": len(tabs),
        "groupTabs": [
            {
                "id": t.get("id") or t.get("tabId"),
                "url": t.get("url"),
                "title": t.get("title"),
                "active": (t.get("id") or t.get("tabId")) == active_id,
            }
            for t in tabs
        ],
    }


def update_context_from_tab_event(
    *,
    event: str,
    tab_id: int | None,
    group_id: int | None = None,
    opener_tab_id: int | None = None,
    active: bool | None = None,
) -> None:
    """Bridge → lifecycle hook for unsolicited tab events from the extension.

    Keeps ``_contexts`` in sync with tabs that appear outside our explicit
    ``browser_open`` path — e.g. ``target="_blank"`` clicks that auto-inherit
    the opener's tab group — so the worker's next default-resolved call lands
    on the right page instead of a stale ``activeTabId``.

    Best-effort and synchronous: any failure here must NOT take down the
    bridge's read loop, so the caller wraps in try/except.
    """
    if tab_id is None:
        return

    if event == "removed":
        # Removal doesn't carry a groupId; clear from any ctx that knew it.
        for ctx in _contexts.values():
            tabs = ctx.get("tabs")
            if isinstance(tabs, set):
                tabs.discard(tab_id)
            if ctx.get("activeTabId") == tab_id:
                ctx["activeTabId"] = None
        return

    # Find owning ctx: prefer groupId match; fall back to opener membership
    # for the brief window where a freshly-created tab hasn't been grouped
    # yet but its opener is one of ours (covers target="_blank").
    target_ctx: dict[str, Any] | None = None
    if group_id is not None and group_id >= 0:
        for ctx in _contexts.values():
            if ctx.get("groupId") == group_id:
                target_ctx = ctx
                break
    if target_ctx is None and opener_tab_id is not None:
        for ctx in _contexts.values():
            tabs = ctx.get("tabs") or set()
            if opener_tab_id in tabs:
                target_ctx = ctx
                break
    if target_ctx is None:
        return

    if event in ("created", "grouped", "regrouped"):
        # "regrouped" (protocol 6): the extension pulled a page-spawned tab
        # into its opener's Hive group (adoptEscapedTab). Treat it like a
        # grouped tab so _contexts tracks it and teardown closes it.
        target_ctx.setdefault("tabs", set()).add(tab_id)
        # If Chrome focused the new tab (as it does for foreground popups
        # and target="_blank" clicks), follow it so the next default-tab
        # call doesn't fire at the stale opener.
        if active:
            target_ctx["activeTabId"] = tab_id
    elif event == "activated":
        target_ctx["activeTabId"] = tab_id
        target_ctx.setdefault("tabs", set()).add(tab_id)


async def _lookup_remote_profile(profile_name: str) -> dict[str, Any] | None:
    """Find a profile's groupId via bridge_host when local ``_contexts`` is empty.

    Bridge_host keeps a process-global ``_context_registry`` that survives
    gcu-server recycles. The runtime never opens browsers itself — browser
    tools run in the gcu MCP subprocess — so on worker-stop reap its local
    ``_contexts`` is empty and bridge_host is the source of truth. Lazy-inits
    a client-mode bridge the first time this runs in a process that doesn't
    already have one; subsequent calls reuse the singleton. Returns a minimal
    ctx (``{"groupId": int, "tabs": set()}``) ready for the destroy path, or
    ``None`` if no matching profile is registered.
    """
    bridge = get_bridge()
    if bridge is None:
        try:
            from ..bridge import init_bridge

            bridge = init_bridge(mode="client")
        except Exception as exc:
            logger.warning("close_profile_context: init_bridge failed: %s", exc)
            return None
    # RemoteBridge needs an explicit ``connect()`` before is_connected flips
    # true; BeelineBridge (host mode) is started elsewhere via bridge.start()
    # so we leave it alone.
    connect = getattr(bridge, "connect", None)
    if callable(connect) and not bridge.is_connected:
        try:
            await connect()
        except Exception as exc:
            logger.warning("close_profile_context: bridge.connect failed: %s", exc)
            return None
    if not bridge.is_connected:
        return None
    try:
        contexts = await bridge.list_contexts()
    except Exception as exc:
        logger.warning("close_profile_context: list_contexts failed: %s", exc)
        return None
    for entry in contexts or []:
        if entry.get("profile") != profile_name:
            continue
        group_id = entry.get("groupId")
        if group_id is None:
            return None
        return {"groupId": group_id, "tabs": set(), "browser_profile": entry.get("browser_profile")}
    return None


async def close_profile_context(profile_name: str, *, reason: str = "stop", browser_profile: str | None = None) -> dict[str, Any]:
    """Close one profile's tab group from non-MCP code (worker reaper, etc.).

    Same effect as the ``browser_stop`` MCP tool's teardown but callable
    directly from Python. Always pops the registry entry — designed for
    shutdown paths where we want to release our state even if the bridge
    is gone — so a stale entry can't leak into ``rehydrate_contexts`` on
    the next gcu start. Idempotent: returns ``status=not_running`` when
    nothing is registered. ``reason`` is recorded in telemetry so cleanup
    triggers (worker_shutdown vs. colony_shutdown vs. tool) are distinguishable.

    ``browser_profile`` routes the destroy to the Chrome profile that owns the
    group. When omitted it's read from the context record (local or remote), so
    the right extension connection is targeted even with multiple profiles
    connected.
    """
    # Opportunistically retry any previously-deferred closes — the long-lived
    # runtime reaps many workers, so a deferral from an earlier reap gets
    # drained here the moment the bridge is healthy again. Cheap no-op when the
    # queue is empty.
    if _DEAD_LETTER:
        try:
            await drain_dead_letter()
        except Exception:
            pass

    ctx = _contexts.pop(profile_name, None)
    source = "local"
    if ctx is not None:
        # Local registry mutated — write through. Skipped in the no-local-
        # entry branch below: the runtime's `_contexts` is always empty
        # (browser tools run in the gcu MCP subprocess) so persisting from
        # here would wipe the snapshot the gcu server owns.
        _persist_contexts()
    else:
        # Cross-process fallback. `_contexts` is per-process; with gcu
        # running as a separate MCP subprocess, the populated dict lives
        # over there and this process (typically the runtime reaping a
        # stopped worker) sees nothing. Ask bridge_host's process-global
        # registry for the profile's groupId so the tab group still gets
        # reaped — otherwise every worker stop orphans its Chrome tabs.
        ctx = await _lookup_remote_profile(profile_name)
        if ctx is None:
            logger.warning(
                "close_profile_context: profile=%s reason=%s registered=False (no-op)",
                profile_name,
                reason,
            )
            return {"ok": True, "status": "not_running", "profile": profile_name}
        source = "remote"

    _clear_profile_tab_caches(ctx)
    group_id = ctx.get("groupId")
    name = ctx.get("name")
    # Route the destroy to the right Chrome profile: explicit arg wins, else the
    # value recorded on the context (local or remote-lookup), else default.
    bp = browser_profile or ctx.get("browser_profile")
    closed_tabs = 0
    bridge = get_bridge()
    logger.warning(
        "close_profile_context: profile=%s reason=%s source=%s groupId=%s tabs=%s bridge_present=%s bridge_connected=%s",
        profile_name,
        reason,
        source,
        group_id,
        len(ctx.get("tabs") or ()) if isinstance(ctx.get("tabs"), (set, list, tuple)) else "?",
        bridge is not None,
        bool(bridge and bridge.is_connected),
    )

    # No Chrome group to close — just dropping our local state is the whole job.
    if group_id is None:
        log_context_event(
            "stop",
            profile_name,
            group_id=None,
            details={"closed_tabs": 0, "reason": reason},
        )
        return {"ok": True, "status": "stopped", "profile": profile_name, "closedTabs": 0}

    # A group is registered, so we MUST actually close it. If the bridge is
    # momentarily disconnected (typically a sub-second extension reload racing
    # worker shutdown), wait briefly for it to come back rather than skipping
    # the destroy and falsely reporting success (the old P1 leak: the guard at
    # the original line 460 was simply not entered and the function fell through
    # to {ok:true, status:stopped, closedTabs:0}).
    if not (bridge and bridge.is_connected):
        bridge = await _await_bridge_reconnect()

    if not (bridge and bridge.is_connected):
        # Bridge never came back in the window — defer to the dead-letter queue
        # instead of lying. drain_dead_letter() and the bridge-side orphan
        # reaper are the durable backstops.
        logger.warning(
            "close_profile_context: profile=%s group=%s deferred — bridge unavailable",
            profile_name,
            group_id,
        )
        _enqueue_dead_letter(profile_name, group_id, name, reason, browser_profile=bp)
        log_context_event(
            "stop",
            profile_name,
            group_id=group_id,
            details={"closed_tabs": 0, "reason": reason, "deferred": True},
        )
        return {"ok": False, "status": "deferred", "profile": profile_name, "retryable": True}

    try:
        result = await bridge.destroy_context(group_id, browser_profile=bp)
        closed_tabs = result.get("closedTabs", 0)
        logger.info(
            "Closed browser context '%s' via %s: %d tabs",
            profile_name,
            reason,
            closed_tabs,
        )
    except Exception as e:
        # Transient extension error — queue for retry rather than orphaning.
        logger.warning(
            "Failed to close browser context '%s' via %s: %s",
            profile_name,
            reason,
            e,
        )
        _enqueue_dead_letter(profile_name, group_id, name, reason, browser_profile=bp)
        log_context_event(
            "stop",
            profile_name,
            group_id=group_id,
            details={"closed_tabs": 0, "reason": reason, "error": str(e)},
        )
        return {"ok": False, "status": "deferred", "error": str(e), "profile": profile_name, "retryable": True}

    log_context_event(
        "stop",
        profile_name,
        group_id=group_id,
        details={"closed_tabs": closed_tabs, "reason": reason},
    )
    return {
        "ok": True,
        "status": "stopped",
        "profile": profile_name,
        "closedTabs": closed_tabs,
    }


async def shutdown_all_contexts() -> None:
    """Close all active browser contexts. Called at GCU server shutdown.

    No-op in client mode: the tab groups live in the bridge_host process and
    must survive this gcu server exiting — they are reclaimed by the next
    gcu's ``rehydrate_contexts()``.
    """
    from ..bridge import is_client_mode

    if is_client_mode():
        return
    if not _contexts:
        return
    bridge = get_bridge()
    for profile_name, ctx in list(_contexts.items()):
        group_id = ctx.get("groupId")
        _clear_profile_tab_caches(ctx)
        if group_id is not None and bridge and bridge.is_connected:
            try:
                await bridge.destroy_context(group_id, browser_profile=ctx.get("browser_profile"))
                logger.info("Shutdown: closed browser context '%s' (groupId=%s)", profile_name, group_id)
            except Exception as e:
                logger.warning("Shutdown: failed to close context '%s': %s", profile_name, e)
    _contexts.clear()


# ── browser_setup prompts ─────────────────────────────────────

BROWSER_SETUP_DOC = """\
Check browser extension status and show installation instructions if needed.

Call this first if browser tools are not working. Returns the Chrome Web Store
install link when the extension isn't connected."""


# ── browser_status prompts ─────────────────────────────────────

BROWSER_STATUS_DOC = """\
Get the current status of the browser.

Returns a dict with browser status."""

BROWSER_STATUS_PARAMS = {
    "profile": 'Browser profile name (default: "default")',
}


# ── browser_stop prompts ─────────────────────────────────────

BROWSER_STOP_DOC = """\
Stop the browser context and close all tabs in the group.

Returns a dict with stop status."""

BROWSER_STOP_PARAMS = {
    "profile": 'Browser profile name (default: "default")',
}


def register_lifecycle_tools(mcp: FastMCP) -> None:
    """Register browser lifecycle management tools."""

    @mcp.tool(description=BROWSER_SETUP_DOC)
    async def browser_setup() -> dict:
        bridge = get_bridge()
        connected = bool(bridge and bridge.is_connected)

        if connected:
            profiles = await _connected_profiles(bridge)
            status = "Extension is connected and ready. Call browser_open(url) to begin."
            if len(profiles) > 1:
                labels = ", ".join(p.get("label") for p in profiles if p.get("label"))
                status += f" {len(profiles)} Chrome profiles are connected ({labels}); pass browser_profile=<label> to browser_open to choose one."
            return {
                "ok": True,
                "connected": True,
                "status": status,
                # Every connected Chrome profile, so the agent can pick one to
                # target — not just whichever it happens to be using.
                "connected_profiles": profiles,
            }

        return {
            "ok": False,
            "connected": False,
            "status": (
                "The Hive browser extension isn't connected. Make sure the Hive app is "
                "running, then follow the steps below to install and enable the Hive "
                "Browser Bridge extension in Chrome."
            ),
            "install_url": _CHROME_WEB_STORE_URL,
            "instructions": {
                "step_1": (f"Open the Hive Browser Bridge listing in the Chrome Web Store: {_CHROME_WEB_STORE_URL}"),
                "step_2": "Click 'Add to Chrome' and confirm the install prompt.",
                "step_3": ("Pin the extension (puzzle-piece icon → pin) and click its toolbar icon to verify it says 'Connected'."),
                "step_4": "Return here and retry — the bridge will pick up the new connection automatically.",
            },
            "note": (
                "The extension connects to the local Hive runtime via WebSocket on "
                "ws://127.0.0.1:14829/bridge (older builds use 9229). Chrome must be "
                "running and the extension must be enabled."
            ),
        }

    @mcp.tool(description=BROWSER_STATUS_DOC)
    async def browser_status(
        profile: Annotated[str | None, Field(description=BROWSER_STATUS_PARAMS["profile"])] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {
                "ok": False,
                "error": connection_error(bridge),
                "connected": False,
            }
            log_tool_call("browser_status", params, result=result)
            return result

        profile_name = _resolve_profile(profile)
        # Every connected Chrome profile — independent of this caller's own
        # context — so an agent can discover and target a profile from here
        # (the always-on status tool), not the obscure list_browser_profiles.
        conn_profiles = await _connected_profiles(bridge)
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
                    "browser_profile": ctx.get("browser_profile"),
                    "connected_profiles": conn_profiles,
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
                    "connected_profiles": conn_profiles,
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
            "connected_profiles": conn_profiles,
            "tabs": 0,
        }
        log_tool_call(
            "browser_status",
            params,
            result=result,
            duration_ms=(time.perf_counter() - start) * 1000,
        )
        return result

    @mcp.tool(description=BROWSER_STOP_DOC)
    async def browser_stop(
        profile: Annotated[str | None, Field(description=BROWSER_STOP_PARAMS["profile"])] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            # Preserve legacy UX: surface the disconnect to the caller without
            # mutating local state, so they can retry once the bridge is back.
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_stop", params, result=result)
            return result

        profile_name = _resolve_profile(profile)
        result = await close_profile_context(profile_name, reason="tool")
        log_tool_call(
            "browser_stop",
            params,
            result=result,
            duration_ms=(time.perf_counter() - start) * 1000,
        )
        return result
