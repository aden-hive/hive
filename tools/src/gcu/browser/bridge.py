"""
Beeline Bridge - WebSocket server that the Chrome extension connects to.

Lets Python code control the user's Chrome directly via the extension's
chrome.debugger CDP access. No Playwright needed.

Usage:
    bridge = init_bridge()
    await bridge.start()          # at GCU server startup
    await bridge.stop()           # at GCU server shutdown

    # Per-subagent:
    result = await bridge.create_context("my-agent")   # {groupId, tabId}
    await bridge.navigate(tab_id, "https://example.com")
    await bridge.click(tab_id, "button")
    await bridge.type(tab_id, "input", "hello")
    snapshot = await bridge.snapshot(tab_id)

The bridge requires the Beeline Chrome extension to be installed and connected.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import random
import re
import signal
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from .health import Blocker, classify_all
from .telemetry import (
    log_bridge_message,
    log_cdp_command,
    log_connection_event,
    log_context_event,
)

logger = logging.getLogger(__name__)

# Primary bridge port. Moved off 9229 — that is the Node.js --inspect default
# and collided constantly on developer machines. 14829 sits in a quiet,
# non-ephemeral band clear of every known browser-agent / dev-server port.
BRIDGE_PORT = 14829

# Legacy port kept alive ONLY for the migration window: extensions published
# before the move still dial 9229, so the bridge listens on both. Remove this
# (and the dual-listen in start()) once the updated extension has rolled out.
LEGACY_BRIDGE_PORT = 9229

# Invisible (zero-width) marker the extension appends to every Hive-created tab
# group title (see background.js context.create). It lets the stale-context
# sweep's forward reaper identify Hive-owned groups from tabGroup.list — the
# only group field that survives a registry wipe or a Chrome restart — without
# changing what the user sees in the tab strip. Failure mode is safe: if the
# marker is ever stripped, a Hive group simply isn't reaped (a leak), never a
# user group wrongly closed. Must stay byte-identical to HIVE_GROUP_MARKER in
# browser-extension/background.js.
HIVE_GROUP_MARKER = "\u200b"  # zero-width space (U+200B)

# Heartbeat tuning. WS-layer ping (websockets library) catches dead TCP within
# ~ping_interval+ping_timeout seconds. App-level ping (extension echoes pong)
# additionally proves the offscreen page and service worker are still pumping
# messages — if the SW is suspended but TCP is alive, the WS ping passes and
# the app ping fails, surfacing a real disconnect instead of a false-healthy.
_WS_PING_INTERVAL_S: float = 20.0
_WS_PING_TIMEOUT_S: float = 20.0
_APP_PING_INTERVAL_S: float = 5.0
_APP_PING_TIMEOUT_S: float = 12.0  # ~2 missed app pings before we give up

# Minimum extension protocol version we still talk to. Bumped here when the
# wire format changes incompatibly. Older extensions still connect — the
# bridge logs a warning and the popup surfaces "please update".
_MIN_EXTENSION_PROTOCOL_VERSION: int = 1

# Label used for the implicit single-profile case: the connection a worker
# reaches when it doesn't name a specific browser profile, and the fallback
# label assigned to extensions too old (protocol < 5) to advertise one.
DEFAULT_BROWSER_PROFILE = "default"


class _Connection:
    """Per-connection identity + in-flight state for one Chrome extension.

    The bridge now accepts MULTIPLE simultaneous extension connections —
    one per Chrome profile the user runs through the profile switcher —
    keyed by a user-assigned ``label``. Everything that must be torn down
    or replaced independently per profile lives here, so dropping profile
    A's socket never disturbs profile B's pending requests or heartbeat.

    Deliberately NOT here: the tab-keyed and group-keyed caches
    (_context_registry, _tab_to_profile, _tab_snapshots, _cdp_attached, …).
    Chrome tab/group ids are unique within ONE browser session (all the
    user's profiles run inside one Chrome), so those stay global on the
    bridge and are shared across connections.
    """

    __slots__ = (
        "ws",
        "label",
        "extension_id",
        "version",
        "protocol_version",
        "connected_at_ms",
        "last_pong_ms",
        "ping_task",
        "pending",
        "counter",
        "in_flight",
    )

    def __init__(self, ws, label: str | None = None) -> None:
        self.ws = ws  # websockets.ServerConnection
        self.label: str | None = label  # None until the hello frame arrives
        self.extension_id: str | None = None
        self.version: str | None = None
        self.protocol_version: int | None = None
        now_ms = time.monotonic() * 1000
        self.connected_at_ms: float = now_ms
        # Treat connect as the implicit first pong so the first ping
        # interval doesn't immediately trip "missed pong".
        self.last_pong_ms: float | None = now_ms
        self.ping_task: asyncio.Task | None = None
        self.pending: dict[str, asyncio.Future] = {}
        self.counter: int = 0
        self.in_flight: int = 0


# ---------------------------------------------------------------------------
# Disconnect diagnosis
# ---------------------------------------------------------------------------
# When a browser tool fails because the extension isn't connected, the cause
# is one of: (1) the extension isn't installed, (2) it's installed but not
# connected (disabled, crashed), or (3) Chrome isn't running. The bridge only
# ever sees "a socket / no socket", so none of these is knowable for certain.
# We can't reliably tell (1) from (2) — a stale "seen before" marker kept
# claiming "installed, just enable it" long after the extension was removed,
# which is a dead end — so we collapse them and always point at browser_setup,
# which carries the Chrome Web Store install link. A Chromium-process scan
# still distinguishes (3), plus bridge uptime so a just-started bridge reads
# as "still connecting".

# An installed+enabled extension reconnects within seconds of the bridge
# starting; under this, "not connected" is reported as transient.
_RECONNECT_GRACE_S: float = 20.0

# Substrings of Chromium-family browser process names (best-effort, lowercased).
_CHROME_PROC_HINTS = ("chrome", "chromium", "brave", "msedge", "vivaldi", "thorium")

_chrome_probe_cache: dict[str, Any] = {"at": 0.0, "running": None}


def _probe_chrome_running() -> bool | None:
    """True/False if a Chromium-family browser process is found; None if the
    scan itself failed — None is treated as 'unknown', never as 'closed'."""
    try:
        cmd = ["tasklist"] if sys.platform.startswith("win") else ["ps", "-A", "-o", "comm="]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return None
        names = out.stdout.lower()
        return any(hint in names for hint in _CHROME_PROC_HINTS)
    except Exception:
        return None


def _is_chrome_running() -> bool | None:
    """Cached `_probe_chrome_running` — the disconnect path can fire in bursts."""
    now = time.monotonic()
    if now - _chrome_probe_cache["at"] < 5.0:
        return _chrome_probe_cache["running"]
    running = _probe_chrome_running()
    _chrome_probe_cache.update(at=now, running=running)
    return running


# Persisted "starred default" profile — which connected label the bridge
# routes a worker to when it asks for the implicit DEFAULT_BROWSER_PROFILE
# and more than one extension is connected. Set from the side panel's
# "star this profile" control (POST /profiles/default). Mirrors the seen-
# extension-id persistence style: best-effort, never breaks the bridge.
_DEFAULT_LABEL_FILE = Path.home() / ".hive" / "browser_default.json"


def _load_default_label() -> str | None:
    """Read the persisted starred-default profile label, or None if unset."""
    try:
        data = json.loads(_DEFAULT_LABEL_FILE.read_text())
        label = data.get("label")
        return label if isinstance(label, str) and label else None
    except Exception:
        return None


def _save_default_label(label: str, extension_id: str | None = None) -> None:
    """Persist the starred-default profile label so it survives a restart."""
    try:
        _DEFAULT_LABEL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DEFAULT_LABEL_FILE.write_text(
            json.dumps(
                {
                    "label": label,
                    "extensionId": extension_id,
                    "saved_at_ms": round(time.time() * 1000),
                }
            )
        )
    except Exception:
        pass  # default-routing persistence must never break the bridge


class BridgeError(RuntimeError):
    """Structured error from a bridge command.

    ``code`` lets callers branch (retry connection_lost, re-attach
    cdp_not_attached, give up on protocol_mismatch) instead of grepping
    error message strings. ``retryable`` is a hint to the tool wrapper:
    transient drops are worth one retry; protocol/usage errors are not.
    """

    __slots__ = ("code", "retryable")

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# CDP wait_until values
VALID_WAIT_UNTIL = {"commit", "domcontentloaded", "load", "networkidle"}

# Fast-fail polling default for element / text waits. 5 seconds is long
# enough to cover normal SPA render latency on loaded pages, short enough
# that a bad selector or hallucinated element fails fast instead of
# burning 30 wall-clock seconds per miss (the old behavior — see the
# 2026-04-14 gemini-3-flash x.com session where 7 of 14 browser_click
# calls each hit the 30s deadline for ~210s wasted total).
#
# navigate() keeps a longer default (30s) because real page loads can
# legitimately take that long.
DEFAULT_WAIT_TIMEOUT_MS: int = 5000

# Longer default for bridge _send calls that wrap genuinely slow ops
# (full-page screenshot, accessibility tree, navigate). Individual
# callers can pass their own value via _send(..., timeout=...).
_LONG_SEND_TIMEOUT_S: float = 60.0


async def _adaptive_poll_sleep(elapsed_s: float) -> None:
    """Sleep between DOM polls with an adaptive backoff.

    Early polls are snappy (50ms) so a quickly-appearing element is
    reported in ~100ms. Later polls back off (200ms, 500ms) so a
    missing element doesn't thrash CDP with 300+ querySelector calls
    before the deadline fires.
    """
    if elapsed_s < 1.0:
        await asyncio.sleep(0.05)
    elif elapsed_s < 5.0:
        await asyncio.sleep(0.2)
    else:
        await asyncio.sleep(0.5)


# Last interaction highlight per tab_id: {x, y, w, h, label, kind}
# kind: "rect" (element) or "point" (coordinate)
_interaction_highlights: dict[int, dict] = {}


def _swallow_future_exc(fut: asyncio.Future) -> None:
    """Consume an abandoned future's result/exception.

    navigate() / reload() issue a CDP command (Page.navigate / Page.reload)
    that does NOT resolve while a native beforeunload dialog is open. When
    we detect that dialog and return early, the command future is left in
    flight — it resolves later, once the dialog is handled via
    browser_dialog_respond (or times out). This callback retrieves that
    eventual result so asyncio doesn't log an "exception was never
    retrieved" warning for the orphaned task.
    """
    if not fut.cancelled():
        with contextlib.suppress(Exception):
            fut.exception()


def _pending_dialog_result(tab_id: int, dialog: dict, *, action: str) -> dict:
    """Build the canonical {ok: False, pending_dialog: ...} return shape.

    Used by navigate / reload / go_back / go_forward when a native dialog
    is detected mid-operation. Wraps the dialog state from the bridge in
    a stable, agent-readable envelope and names the offending action so
    the agent can decide whether to dismiss (stay) or accept (proceed).
    """
    return {
        "ok": False,
        "error": f"{action} blocked by native browser dialog",
        "action": action,
        "pending_dialog": {
            "tab_id": tab_id,
            "type": dialog.get("type"),
            "message": dialog.get("message"),
            "default_prompt": dialog.get("default_prompt"),
            "url": dialog.get("url"),
        },
    }


def _format_user_tab_message(title: str, tab_id: int, *, action: str) -> str:
    """Build the user-style sentence injected into an agent's conversation
    when the human clicks Release or Hand over in the side panel.

    ``action`` is "detached" or "handed-over". Title is best-effort —
    when the tab.get lookup fails or returns empty, we fall back to a
    plain ``tab #<id>`` form instead of an awkward empty quote. Kept
    as a free function so the bridge tests (and any future caller
    surface like an HTTP /notify echo) can format the same wording.
    """
    safe_title = (title or "").strip()
    label = f'"{safe_title}" (tab #{tab_id})' if safe_title else f"tab #{tab_id}"
    if action == "handed-over":
        return f"The user handed {label} over to you."
    return f"The user detached {label} from you."


def clear_tab_highlights(tab_ids) -> None:
    """Drop cached interaction highlights for the given tab_ids.

    Called when a profile's context is destroyed so stale highlight
    rects can't reappear on a later tab that Chrome happens to assign
    the same id. Accepts a single id or any iterable.
    """
    if isinstance(tab_ids, int):
        tab_ids = (tab_ids,)
    for tid in tab_ids:
        _interaction_highlights.pop(tid, None)


# Compact descriptor of the focused element. Returned by both click()
# and click_coordinate() so the agent can verify it focused what it
# intended. When the outer document's activeElement is an <iframe>,
# we recurse into the iframe's document (same-origin only) so the
# response describes the real inner element — otherwise the agent
# always sees {tag: "iframe"} and can't tell whether it hit the
# composer or something else inside the frame (e.g. a sidebar item
# in LinkedIn's #interop-outlet messaging overlay).
# Diagnostic probe for the Y-offset hunt. Returns the element under
# the (x, y) the click is about to hit, plus its bounding rect and
# the click's offset relative to that rect. If clicks are landing on
# the wrong element or near a rect boundary, we'll see it in the log
# without having to ask the agent what it intended to click.
_HIT_ELEMENT_JS = """
(function(x, y) {
    function describe(el) {
        if (!el) return null;
        var rect = el.getBoundingClientRect();
        return {
            tag: el.tagName ? el.tagName.toLowerCase() : null,
            id: el.id || null,
            className: typeof el.className === 'string' ? el.className.substring(0, 120) : null,
            role: el.getAttribute ? el.getAttribute('role') : null,
            text: ((el.innerText || el.textContent || '') + '').substring(0, 80),
            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
        };
    }
    var topEl = document.elementFromPoint(x, y);
    var stack = [];
    if (typeof document.elementsFromPoint === 'function') {
        var els = document.elementsFromPoint(x, y);
        for (var i = 0; i < Math.min(els.length, 4); i++) {
            stack.push(describe(els[i]));
        }
    } else {
        stack.push(describe(topEl));
    }
    // Vertical-stripe sweep: query elementFromPoint at y±5 and y±15
    // so we can detect "click is just barely outside the element a
    // human would have hit". Records only tag+text for compactness.
    function brief(el) {
        if (!el) return null;
        return {
            tag: el.tagName ? el.tagName.toLowerCase() : null,
            text: ((el.innerText || el.textContent || '') + '').substring(0, 40)
        };
    }
    var sweep = {};
    [-15, -5, 5, 15].forEach(function (dy) {
        sweep['y' + (dy >= 0 ? '+' : '') + dy] = brief(document.elementFromPoint(x, y + dy));
    });
    var hit = describe(topEl);
    var offsetInRect = null;
    if (hit && hit.rect && hit.rect.width > 0 && hit.rect.height > 0) {
        offsetInRect = {
            xFrac: (x - hit.rect.x) / hit.rect.width,
            yFrac: (y - hit.rect.y) / hit.rect.height,
            dxFromCenter: x - (hit.rect.x + hit.rect.width / 2),
            dyFromCenter: y - (hit.rect.y + hit.rect.height / 2)
        };
    }
    return {
        clickPoint: { x: x, y: y },
        viewport: { w: window.innerWidth, h: window.innerHeight, sx: window.scrollX, sy: window.scrollY },
        hit: hit,
        stack: stack,
        sweep: sweep,
        offsetInRect: offsetInRect
    };
})
"""


# Diagnostic probe — installs viewport/visibility listeners on the page
# and posts their observations through console.info so the CDP event
# channel (Runtime.consoleAPICalled) forwards them to our telemetry.
# Idempotent via ``window.__hive_vp_instrumented``.
_HIVE_VP_PROBE_JS = """
(function () {
  if (window.__hive_vp_instrumented) return;
  window.__hive_vp_instrumented = true;
  function sample(kind) {
    try {
      console.info('[hive_vp]', JSON.stringify({
        kind: kind,
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        visualW: window.visualViewport && window.visualViewport.width,
        visualH: window.visualViewport && window.visualViewport.height,
        docHidden: document.hidden,
        visibilityState: document.visibilityState,
        scrollX: window.scrollX,
        scrollY: window.scrollY,
        dpr: window.devicePixelRatio,
        ts: Date.now()
      }));
    } catch (e) {}
  }
  sample('init');
  window.addEventListener('resize', function () { sample('resize'); });
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', function () { sample('visualResize'); });
  }
  document.addEventListener('visibilitychange', function () { sample('visibility'); });
})();
"""


_FOCUSED_ELEMENT_JS = """
(function() {
    function describe(el) {
        var rect = el.getBoundingClientRect();
        var attrs = {};
        for (var i = 0; i < el.attributes.length && i < 10; i++) {
            attrs[el.attributes[i].name] = el.attributes[i].value.substring(0, 200);
        }
        return {
            tag: el.tagName.toLowerCase(),
            id: el.id || null,
            className: el.className || null,
            name: el.getAttribute('name') || null,
            type: el.getAttribute('type') || null,
            role: el.getAttribute('role') || null,
            contenteditable: el.getAttribute('contenteditable') || null,
            text: (el.innerText || '').substring(0, 200),
            value: (el.value !== undefined ? String(el.value).substring(0, 200) : null),
            attributes: attrs,
            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
        };
    }
    var el = document.activeElement;
    if (!el || el === document.body) return null;
    // Descend into same-origin iframes. Capped at 5 levels of
    // nesting to bound cost. Cross-origin frames throw on
    // contentDocument access → we catch and report the outermost
    // iframe instead.
    var framePath = [];
    var depth = 0;
    while (el && (el.tagName === 'IFRAME' || el.tagName === 'FRAME') && depth < 5) {
        framePath.push(el.id || el.getAttribute('data-testid') || el.tagName.toLowerCase());
        var innerDoc = null;
        try { innerDoc = el.contentDocument; } catch (e) { innerDoc = null; }
        if (!innerDoc) break;
        var innerActive = innerDoc.activeElement;
        if (!innerActive || innerActive === innerDoc.body) break;
        el = innerActive;
        depth++;
    }
    var out = describe(el);
    if (framePath.length) out.inFrame = framePath;
    return out;
})()
"""


def _get_active_profile() -> str:
    """Get the current active profile from context variable."""
    try:
        from .session import _active_profile as ap

        return ap.get()
    except Exception:
        return "default"


STATUS_PORT = BRIDGE_PORT + 1  # 14830 — plain HTTP status endpoint
LEGACY_STATUS_PORT = LEGACY_BRIDGE_PORT + 1  # 9230 — legacy status endpoint


def _detect_bridge_version() -> str | None:
    """Resolve the Python bridge package version via importlib.metadata.

    Cached at import time — version doesn't change inside a process. Returns
    None if the package is unavailable (running from source without an
    installed dist), in which case the side panel renders "—" for the field.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("gcu")
        except PackageNotFoundError:
            return None
    except Exception:
        return None


_BRIDGE_VERSION: str | None = _detect_bridge_version()


def _pid_alive(pid: int) -> bool:
    """True iff ``pid`` is still running.

    Duplicates the logic in ``bridge_host._pid_alive`` so this module
    has no upward import dependency on it. On Windows ``os.kill(pid, 0)``
    is unsafe — CTRL_C_EVENT == 0, so CPython falls through to a path
    that can actually terminate the target. Use the Win32 API directly
    there.
    """
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return kernel32.GetLastError() == 5  # ERROR_ACCESS_DENIED → exists but protected
        exit_code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return exit_code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # The PID exists but we lack permission to signal it. Same-user
        # processes shouldn't hit this, but if we do — the process is
        # definitely alive.
        return True
    except OSError:
        return False


def unnest_json_result(value):
    """Parse a JSON-object/array *string* back into a real Python object.

    ``browser_evaluate`` JS routinely does ``return JSON.stringify(...)`` (every
    skill uses this pattern), so the page hands back a JSON **string**. Left as a
    string, it gets escaped when the tool result is serialized for the LLM —
    the agent sees ``"result": "[{\\"h\\":...}]"``, which is hard to read and
    easy to misparse. Parsing ``{``/``[``-prefixed strings yields clean nested
    JSON instead. Plain strings (e.g. ``"no-trigger"``, ``outerHTML``) and
    scalars are returned unchanged, and a non-string (already an object) is a
    no-op — so this is safe to apply more than once along the call path.

    Applied in two places on purpose: in :meth:`BeelineBridge.evaluate` (covers
    host mode and direct callers) AND in the ``browser_evaluate`` tool wrapper
    (covers client mode, where ``evaluate`` runs in the long-lived ``bridge_host``
    process that does not recycle on app restart — the tool layer in the gcu
    server does, so the wrapper is what makes the fix take effect there).
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                return json.loads(stripped)
            except (ValueError, TypeError):
                return value  # looked JSON-ish but isn't — keep the raw string
    return value


class BeelineBridge:
    """WebSocket server that accepts a single connection from the Chrome extension."""

    def __init__(self, *, runtime_version: str | None = None) -> None:
        # Version of the embedding Hive desktop runtime (the app that
        # constructs us). Optional — defaults to None and the footer shows
        # "Runtime —" muted. Passed in here rather than detected because the
        # bridge is a library; the consuming app knows its own version.
        self._runtime_version: str | None = runtime_version
        # Desktop app PID, passed via env at runtime-spawn time by the
        # Electron shell (see hive-desktop/src/main/runtime.ts). None when
        # the bridge runs outside the desktop shell (CLI, tests, etc.) —
        # the side panel treats None as "unverifiable" and falls back to
        # the inferential health checks. When set, /status reports
        # runtime_alive directly via a microsecond PID check, closing the
        # orphan-window gap where bridge alive + desktop dead would have
        # rendered as healthy.
        pid_str = os.getenv("HIVE_DESKTOP_PARENT_PID")
        self._desktop_pid: int | None = int(pid_str) if pid_str and pid_str.isdigit() else None
        # Live extension connections, keyed by user-assigned profile label.
        # Multiple Chrome profiles (via the profile switcher) can connect at
        # once; each gets its own _Connection so tearing one down never
        # disturbs another. Replaces the old single self._ws.
        self._conns: dict[str, _Connection] = {}
        # tabId -> owning connection label, for routing a tab-scoped command
        # to the connection whose extension actually controls that tab.
        self._tab_to_conn: dict[int, str] = {}
        # Window affinity: the Chrome window each connection's Hive tab groups
        # live in (label -> windowId). DURABLE across worker lifecycles — unlike
        # the extension, which can only re-derive the window from a still-open
        # Hive group, this remembers it even when every group has been reaped, so
        # a fresh worker spawned into a colony of short-lived peers lands in the
        # SAME window instead of whatever window the user is currently focused
        # on. Established from the first context.create response; passed back on
        # every later create. A per-label lock serializes context.create so a
        # concurrent first batch establishes ONE window, not one per worker.
        self._hive_window_by_conn: dict[str, int] = {}
        self._window_locks: dict[str, asyncio.Lock] = {}
        # Starred-default profile: which label resolve_connection(None) picks
        # when several extensions are connected. Loaded from disk; updated via
        # the side panel's POST /profiles/default.
        self._starred_default_label: str | None = self._load_default_label()
        self._server: object | None = None  # websockets.Server — primary port
        self._status_server: object | None = None  # asyncio.Server (HTTP) — primary
        # Migration-window listeners on the legacy 9229/9230 ports.
        self._legacy_server: object | None = None
        self._legacy_status_server: object | None = None
        self._cdp_attached: set[int] = set()  # Track tabs with CDP attached
        # Per-tab serialization of CDP commands. Two queens accidentally
        # targeting the same tab (e.g. shared profile) would otherwise
        # interleave attach/detach calls and corrupt CDP session state.
        self._tab_locks: dict[int, asyncio.Lock] = {}
        # Pending native browser dialogs (alert/confirm/prompt/beforeunload).
        # Populated from Page.javascriptDialogOpening events forwarded by
        # the extension and cleared on Page.javascriptDialogClosed. Chrome
        # only allows one dialog per tab so the value is a single dict, not
        # a list. Shape: { type, message, default_prompt, url, opened_at_ms }.
        self._pending_dialogs: dict[int, dict] = {}
        # Per-connection heartbeat / identity now lives on each _Connection
        # in self._conns (ws, last_pong_ms, extension_id, version, …); the
        # representative read-only properties below expose a single value for
        # the legacy callers that still read self._extension_id et al.
        self._started_at_ms: float = time.monotonic() * 1000
        # Track in-flight requests for /status reporting.
        self._in_flight: int = 0
        # Wall-clock ms of the last agent action on each tab — every command
        # the agent sends carrying a tabId stamps this. list_contexts() rolls
        # it up per context so the side panel can show "last active … ago".
        self._tab_active_ms: dict[int, float] = {}
        # Control-RPC server — exposes this bridge's method surface to
        # out-of-process gcu tool clients (see bridge_rpc.py). Created lazily
        # in start() so importing the bridge never drags in bridge_rpc.
        self._rpc_server: object | None = None  # bridge_rpc.BridgeRpcServer
        # Per-listener bind failures, keyed by role ("ws", "status",
        # "legacy_ws", "legacy_status"). Populated by start() when a port is
        # held by another process; read by connection_help() / status_payload()
        # so a server-side port conflict is reported as exactly that — not
        # mis-blamed on the Chrome extension.
        self._bind_errors: dict[str, str] = {}
        # Authoritative profile→{groupId,name} registry, owned by the bridge
        # process. /contexts and list_contexts() read this — so they work
        # regardless of which (disposable) gcu process is connected, or
        # whether one is connected at all. Populated by create_context and
        # by register_context (the gcu resync path).
        self._context_registry: dict[str, dict] = {}
        # Per-tab health bookkeeping (see health.py). Populated proactively
        # after cdp.attach and refreshed reactively when a CDP command errors
        # in a way that fingerprints a known blocker (foreign-extension
        # iframe, DevTools attached, enterprise policy, …). list_contexts
        # rolls these up so the side panel and agent diagnostics share one
        # source of truth for "why automation is impaired on this tab".
        self._tab_snapshots: dict[int, dict] = {}
        self._tab_blockers: dict[int, list[dict]] = {}
        # Per-context in-flight command count and the tabId→profile reverse
        # map that drives it. Used by list_contexts to render an explicit
        # "working / waiting / idle / blocked" status badge per agent. We
        # need the reverse map because _send only sees tabId; computing
        # profile from groupId on every _send is too expensive. The map is
        # maintained from create_context, create_tab, tab events, and
        # close_tab — so a tab opened outside our explicit paths
        # (target="_blank") still attributes its commands correctly once
        # Chrome groups it.
        self._context_in_flight: dict[str, int] = {}
        self._tab_to_profile: dict[int, str] = {}
        # Durable set of tab ids the bridge has positively observed INSIDE a
        # Hive group — created via create_context/create_tab, or reported by a
        # tab_event resolving into one of our groups (including the extension's
        # "regrouped" adopt). Unlike _tab_to_profile (cleared on group destroy),
        # this survives so the sweep can recognise an ESCAPED tab — one that
        # left its group into the ungrouped pool, e.g. a new-window popup the
        # extension couldn't auto-group — as Hive-owned even though it now
        # carries no marker. ONLY ids that were demonstrably ours ever enter the
        # set, so a user's tab is never a member: worst case is a leak, never a
        # user tab closed. Evicted on tab_event "removed", close_tab, and after
        # a successful reap. Drives _reap_ungrouped_orphans (protocol >= 6).
        self._hive_tab_ids: set[int] = set()
        # Per-tab action ring buffer (Feature 3). Each tab gets a bounded
        # deque of {ts_ms, verb, target, ok} entries. Appended at the
        # gcu-tool layer via telemetry.log_tool_call → record_action, so
        # one user-visible action is one entry — not one entry per
        # underlying CDP call (which would flood the buffer with viewport
        # probes / coord lookups in seconds). The /tabs/{tabId}/actions
        # endpoint serves these to the side panel.
        self._tab_actions: dict[int, deque] = {}
        # Periodic stale-context sweep task. Reconciles _context_registry
        # against Chrome's live tab-group set every ~30s, in case we missed
        # a tabGroups.onRemoved event (extension reload, disconnect during
        # the close, …). The event-driven path (_prune_group) is the fast
        # path; the sweep is belt-and-braces. Spun up in start(); cancelled
        # in stop().
        self._sweep_task: asyncio.Task | None = None
        # Forward-reaper debounce: groupId -> consecutive sweeps it has looked
        # like an orphaned Hive group (marker present, not in the registry).
        # A group is only closed after two consecutive sightings so a group
        # created between the extension's tab.group call and create_context's
        # registry write is never reaped mid-birth. See _stale_context_sweep_loop.
        self._orphan_seen: dict[int, int] = {}
        # Ungrouped-orphan-reaper debounce: tabId -> consecutive sweeps it has
        # looked like an escaped Hive tab (in _hive_tab_ids, now ungrouped, no
        # live context). Parallel to _orphan_seen; same two-sighting rule so a
        # tab merely transiting between groups is given a full sweep to settle
        # before being closed. See _reap_ungrouped_orphans.
        self._ungrouped_seen: dict[int, int] = {}
        # Empty "saved tab group" chips Chrome refuses to delete (context.destroy
        # reported persistedGroup). Kept so (a) the forward reaper doesn't spin
        # trying to close groups MV3 can't remove, and (b) create_context can
        # recycle one instead of leaking a fresh chip per session — bounding
        # clutter to the historical-max concurrent agent count. Protocol >= 5.
        self._persisted_groups: set[int] = set()

    # ── Persisted starred-default profile ──────────────────────────────────
    # Thin instance wrappers over the module-level helpers, mirroring the
    # seen-extension-id persistence style so call sites read uniformly.

    def _load_default_label(self) -> str | None:
        return _load_default_label()

    def _save_default_label(self, label: str, extension_id: str | None = None) -> None:
        _save_default_label(label, extension_id)

    # ── Representative connection (backward-compat read surface) ────────────
    # Several bridge methods — and two external modules via
    # getattr(get_bridge(), "_extension_id", None) — still read a single
    # extension identity. Expose one representative connection's values:
    # prefer the starred default, else any/first connection, else None/0.

    def _primary_conn(self) -> _Connection | None:
        if self._starred_default_label and self._starred_default_label in self._conns:
            return self._conns[self._starred_default_label]
        return next(iter(self._conns.values()), None)

    # Read-only by design: per-connection identity is written onto the
    # _Connection objects (in _handle_connection's hello path), never through
    # these accessors. They exist purely so legacy single-connection readers —
    # including two external modules via getattr(bridge, "_extension_id", None)
    # — keep working against a representative connection.
    @property
    def _extension_id(self) -> str | None:
        conn = self._primary_conn()
        return conn.extension_id if conn else None

    @property
    def _extension_version(self) -> str | None:
        conn = self._primary_conn()
        return conn.version if conn else None

    @property
    def _extension_protocol_version(self) -> int | None:
        conn = self._primary_conn()
        return conn.protocol_version if conn else None

    @property
    def is_connected(self) -> bool:
        return bool(self._conns)

    def connection_help(self) -> str:
        """A specific, actionable explanation of *why* the browser isn't
        usable. Best-effort classification (see the disconnect-diagnosis
        section above); the bridge can't know any of this for certain, so the
        wording stays hedged."""
        if self.is_connected:
            return "The Hive browser extension is connected."

        # Server-side fault first: if the primary WebSocket listener never
        # bound, the extension *cannot* reach the bridge no matter what — and
        # this is a port conflict, not a Chrome/extension problem. Report it
        # as exactly that, and name the process holding the port, so the
        # operator looks in the right place instead of reinstalling the
        # extension. (Pre-decouple this case was mis-reported as
        # "extension installed but not connected".)
        if self._server is None:
            holder = _identify_port_holder(BRIDGE_PORT)
            return (
                f"The browser bridge could not bind 127.0.0.1:{BRIDGE_PORT} — "
                f"the port is held by {holder}. This is a server-side port "
                f"conflict, not a Chrome or extension problem. Stop the process "
                f"holding the port (or close the duplicate Hive instance); the "
                f"bridge rebinds automatically within a few seconds."
            )

        chrome = _is_chrome_running()  # True / False / None (unknown)
        uptime_s = (time.monotonic() * 1000 - self._started_at_ms) / 1000

        # Just-started bridge: an installed extension is probably mid-reconnect.
        if chrome is not False and uptime_s < _RECONNECT_GRACE_S:
            return (
                "Connecting to the Hive browser extension — wait a few seconds and "
                "retry. If this keeps happening, open Chrome and check the Hive "
                "Browser Bridge extension is installed and enabled."
            )
        if chrome is False:
            return "Chrome doesn't appear to be running. Open Chrome — with the Hive Browser Bridge extension installed — then retry."
        # Can't tell "installed but disabled/disconnected" apart from "never
        # installed" with any certainty, so always route to browser_setup —
        # it carries the Chrome Web Store install link for the correct
        # extension, which is the actionable next step in either case.
        return "The Hive browser extension doesn't appear to be installed. Run browser_setup for one-time installation instructions."

    # ── Connection routing ─────────────────────────────────────────────────

    def resolve_connection(self, browser_profile: str | None) -> _Connection:
        """Pick the connection a command should target.

        An explicit ``browser_profile`` (other than DEFAULT_BROWSER_PROFILE)
        must name a currently-connected label, else we fail fast with an
        actionable ``no_browser_profile`` error — silently falling back to
        another profile would run the work in the wrong browser.

        DEFAULT_BROWSER_PROFILE (or None) resolves by these rules:
          1. the starred default, if it's connected;
          2. otherwise FIRST-COME-CLAIMS-DEFAULT: the earliest-connected
             profile (this also covers the sole-connection case). So with no
             explicit star, a worker that doesn't name a profile just works on
             the first connected one instead of failing — bind browser_profile
             explicitly to target a specific account.
          3. no connections → not_connected (retryable).

        An EXPLICIT label that isn't connected falls back to the sole live
        connection when exactly one is present (a stale label after an extension
        reinstall — same browser, new id); it only fails fast (no_browser_profile)
        when MULTIPLE profiles are connected and the choice is genuinely ambiguous.
        """
        label = browser_profile or DEFAULT_BROWSER_PROFILE
        if label != DEFAULT_BROWSER_PROFILE:
            conn = self._conns.get(label)
            if conn is not None:
                return conn
            # The named label isn't connected. A profile label is VOLATILE — it
            # is a random id stored in the extension's chrome.storage and resets
            # whenever the user reinstalls the extension — so a pinned label
            # going missing almost always means "same browser, new label", not
            # "the wrong browser". When there's no ambiguity (exactly one profile
            # connected) there is no other browser to run in, so use it instead
            # of failing and forcing the agent to cope. Re-point the starred
            # default to the live label too, so the rest of the system stops
            # chasing the dead one. Only with MULTIPLE connections — a genuine
            # which-account ambiguity — do we still fail fast.
            if len(self._conns) == 1:
                only = next(iter(self._conns.values()))
                logger.info(
                    "resolve_connection: pinned label %r not connected; using the sole live connection %r (stale label after extension reinstall?)",
                    label,
                    only.label,
                )
                if self._starred_default_label == label:
                    try:
                        self._save_default_label(only.label, only.extension_id)
                        self._starred_default_label = only.label
                    except Exception:
                        pass  # cosmetic re-point; routing already succeeded
                return only
            raise BridgeError("no_browser_profile", self._no_profile_help(label), retryable=False)
        if self._starred_default_label and self._starred_default_label in self._conns:
            return self._conns[self._starred_default_label]
        if not self._conns:
            raise BridgeError("not_connected", self.connection_help(), retryable=True)
        # First-come claims default: the earliest-connected profile.
        return min(self._conns.values(), key=lambda c: c.connected_at_ms)

    def _effective_default_label(self) -> str | None:
        """The label resolve_connection(None) WOULD pick, or None if it would
        raise. Used by status_payload's per-connection ``is_default`` flag."""
        try:
            return self.resolve_connection(None).label
        except BridgeError:
            return None

    def _conn_for_tab(self, tab_id) -> _Connection | None:
        """Resolve the connection that owns ``tab_id``.

        Prefer the direct tabId→label routing map; fall back to deriving the
        label from the tab's agent profile and that profile's registry entry
        (covers tabs grouped after the fact). Returns None when nothing maps.
        """
        label = self._tab_to_conn.get(tab_id)
        if not label:
            agent = self._tab_to_profile.get(tab_id)
            if agent:
                label = (self._context_registry.get(agent, {}) or {}).get("browser_profile")
        if not label:
            return None
        return self._conns.get(label)

    def _conn_label_for_group(self, group_id) -> str | None:
        """The browser-profile label of the connection that minted ``group_id``,
        read off the context registry. None when no entry claims the group."""
        for meta in self._context_registry.values():
            if meta.get("groupId") == group_id:
                return meta.get("browser_profile")
        return None

    def _no_profile_help(self, label: str) -> str:
        """Actionable message for a command naming an unconnected profile."""
        connected = ", ".join(sorted(self._conns)) or "(none)"
        return (
            f"No Chrome profile labelled '{label}' is connected (connected: "
            f"{connected}). Open that Chrome profile, enable the Hive Browser "
            f"Bridge extension, and set its side-panel label to '{label}', then "
            f"retry."
        )

    def _ambiguous_default_help(self) -> str:
        """Actionable message when 'default' routing can't pick among many."""
        connected = ", ".join(sorted(self._conns)) or "(none)"
        return (
            f"Multiple Chrome profiles are connected ({connected}) and none is "
            f"set as default. Set one as default (star it in the side panel) or "
            f"bind this worker to a specific profile label, then retry."
        )

    def has_public_listeners(self) -> bool:
        """True only when BOTH an extension-facing WS port and a status port are
        bound (primary 14829/14830 or legacy 9229/9230).

        A worker that bound only its control-RPC port is "half-up": invisible to
        the extension (no WS) and to the desktop app's status probe, yet it sits
        there forever. The supervisor should respawn such a worker instead — see
        ``bridge_host._run_worker``. This is the "is the bridge actually usable"
        gate, distinct from any single entry in ``_bind_errors``.
        """
        has_ws = self._server is not None or self._legacy_server is not None
        has_status = self._status_server is not None or self._legacy_status_server is not None
        return has_ws and has_status

    async def start(self, port: int = BRIDGE_PORT) -> None:
        """Start the WebSocket + HTTP status servers.

        Listens on the primary ``port`` AND — for the migration window — on the
        legacy ``LEGACY_BRIDGE_PORT`` (9229), so extensions of either build keep
        connecting. Idempotent: the rebind supervisor calls this repeatedly and
        each call only binds the servers that aren't already up.
        """
        try:
            import websockets
        except ImportError:
            logger.warning("websockets not installed — Chrome extension bridge disabled. Install with: uv pip install websockets")
            return

        # Suppress noisy websockets logging for invalid upgrade attempts.
        import logging

        null_logger = logging.getLogger("websockets.null")
        null_logger.setLevel(logging.CRITICAL)
        null_logger.addHandler(logging.NullHandler())

        async def _serve_ws(p: int):
            return await websockets.serve(
                self._handle_connection,
                "127.0.0.1",
                p,
                logger=null_logger,
                max_size=50 * 1024 * 1024,  # 50 MB — CDP responses (AX tree, screenshots) can be large
                # WS-layer heartbeat: detects half-open TCP within
                # ~ping_interval+ping_timeout seconds. Without this an
                # idle NAT reaper or laptop sleep silently kills the
                # socket and the next _send sits at its 30s timeout.
                ping_interval=_WS_PING_INTERVAL_S,
                ping_timeout=_WS_PING_TIMEOUT_S,
            )

        # ── Primary port ──────────────────────────────────────────────────
        if self._server is None:
            try:
                self._server = await _serve_ws(port)
                self._bind_errors.pop("ws", None)
                logger.info("Beeline bridge listening on ws://127.0.0.1:%d", port)
            except OSError as e:
                self._bind_errors["ws"] = f"127.0.0.1:{port} — {e}"
                logger.warning("Beeline bridge could not start on port %d: %s", port, e)
        if self._status_server is None:
            try:
                self._status_server = await asyncio.start_server(self._http_status_handler, "127.0.0.1", port + 1)
                self._bind_errors.pop("status", None)
                logger.info("Bridge status endpoint on http://127.0.0.1:%d/status", port + 1)
            except OSError as e:
                self._bind_errors["status"] = f"127.0.0.1:{port + 1} — {e}"
                logger.warning("Bridge status server could not start on port %d: %s", port + 1, e)

        # ── Legacy migration port (9229/9230) ─────────────────────────────
        # Extensions published before the port move still dial 9229; keep it
        # bound until the updated extension has rolled out, then delete this.
        if port != LEGACY_BRIDGE_PORT:
            if self._legacy_server is None:
                try:
                    self._legacy_server = await _serve_ws(LEGACY_BRIDGE_PORT)
                    self._bind_errors.pop("legacy_ws", None)
                    logger.info("Beeline bridge also listening on legacy ws://127.0.0.1:%d", LEGACY_BRIDGE_PORT)
                except OSError as e:
                    self._bind_errors["legacy_ws"] = f"127.0.0.1:{LEGACY_BRIDGE_PORT} — {e}"
                    logger.warning("Beeline bridge could not start on legacy port %d: %s", LEGACY_BRIDGE_PORT, e)
            if self._legacy_status_server is None:
                try:
                    self._legacy_status_server = await asyncio.start_server(self._http_status_handler, "127.0.0.1", LEGACY_STATUS_PORT)
                    self._bind_errors.pop("legacy_status", None)
                    logger.info(
                        "Bridge status endpoint also on legacy http://127.0.0.1:%d/status",
                        LEGACY_STATUS_PORT,
                    )
                except OSError as e:
                    self._bind_errors["legacy_status"] = f"127.0.0.1:{LEGACY_STATUS_PORT} — {e}"
                    logger.warning("Bridge status server could not start on legacy port %d: %s", LEGACY_STATUS_PORT, e)

        # ── Control-RPC port (out-of-process tool clients) ─────────────────
        # Lets a gcu MCP server drive this bridge over a socket instead of an
        # in-process reference, so the bridge survives gcu being recycled.
        if self._rpc_server is None:
            from .bridge_rpc import BridgeRpcServer

            self._rpc_server = BridgeRpcServer(self)
        try:
            await self._rpc_server.start()  # idempotent
        except OSError as e:
            logger.warning("Bridge RPC server could not start: %s", e)

        # Periodic stale-context sweep. Safe to (re)start unconditionally —
        # the loop no-ops when there's no extension connected and feature-
        # gates itself on protocol_version >= 3 so old extensions never see
        # the unknown command.
        if self._sweep_task is None or self._sweep_task.done():
            self._sweep_task = asyncio.create_task(self._stale_context_sweep_loop())

    def _fail_pending(self, conn: _Connection, exc: BaseException) -> None:
        """Resolve every in-flight future on ONE connection with ``exc``.

        Scoped to a single connection so failing profile A's requests
        (disconnect, displacement, shutdown) never disturbs profile B's.
        Replaces the old "fut.cancel()" cleanup. Cancellation looks
        identical to a deliberate caller cancel; resolving with a
        structured exception lets tool wrappers branch (retry on
        connection_lost, surface a clear error otherwise).
        """
        for fut in conn.pending.values():
            if not fut.done():
                fut.set_exception(exc)
        conn.pending.clear()

    async def _ping_loop(self, conn: _Connection) -> None:
        """Send app-level pings until this connection drops.

        WS-layer pings (configured on websockets.serve) only prove the
        TCP socket is alive. App-level pings additionally prove the
        extension's offscreen page can pump messages — important
        because MV3 service workers can suspend even when TCP stays
        open, and silent dispatch failures here are exactly the
        "looks-connected-but-isn't" symptom users have hit.

        The ownership guard ``self._conns.get(conn.label) is conn`` lets a
        displaced older handler's ping loop exit by itself once a newer
        connection has claimed the same label.
        """
        ws = conn.ws
        try:
            while self._conns.get(conn.label) is conn:
                # Ping cadence is fixed — too short floods the SW with
                # alarms, too long delays detection past the next
                # _send timeout. 5s strikes the published MV3 sweet
                # spot for keepAlive nudges.
                await asyncio.sleep(_APP_PING_INTERVAL_S)
                if self._conns.get(conn.label) is not conn:
                    return
                try:
                    await ws.send(json.dumps({"type": "ping"}))
                except Exception:
                    # send() raising here means the socket is gone —
                    # the read loop's finally branch will clean up.
                    return
                last = conn.last_pong_ms
                if last is not None and (time.monotonic() * 1000 - last) > _APP_PING_TIMEOUT_S * 1000:
                    logger.warning("App-level ping timeout — closing extension WebSocket")
                    log_connection_event("disconnect", {"reason": "ping_timeout", "label": conn.label})
                    try:
                        await ws.close(code=4001, reason="ping_timeout")
                    except Exception:
                        pass
                    return
        except asyncio.CancelledError:
            return

    async def stop(self) -> None:
        # Tear down every connection's heartbeat task before futures so none
        # observes a half-closed state, then fail each connection's pending
        # requests so any caller stuck in _send sees a structured
        # connection_lost immediately instead of waiting the full 30s timeout.
        # Mirrors the cleanup in _handle_connection's disconnect branch so
        # both exit paths behave the same.
        for conn in list(self._conns.values()):
            if conn.ping_task and not conn.ping_task.done():
                conn.ping_task.cancel()
            self._fail_pending(conn, BridgeError("connection_lost", "The Hive browser bridge is shutting down.", retryable=False))
        self._conns.clear()
        self._tab_to_conn.clear()
        if self._sweep_task and not self._sweep_task.done():
            self._sweep_task.cancel()
        self._sweep_task = None
        # Drop CDP attach cache — next run must re-attach fresh.
        self._cdp_attached.clear()
        # Drop the context registry — a (re)connecting gcu re-publishes its
        # contexts via register_context.
        self._context_registry.clear()
        # Drop highlight state — stale entries would otherwise carry
        # over into a subsequent run and confuse screenshot annotation.
        _interaction_highlights.clear()
        # Drop pending dialog state — the underlying tabs will not exist
        # next run, and a stale entry would mislead the dialog tools.
        self._pending_dialogs.clear()
        self._tab_locks.clear()
        self._tab_active_ms.clear()
        # Health caches go with the tabs they describe.
        self._tab_snapshots.clear()
        self._tab_blockers.clear()
        # Per-context status bookkeeping is bridge-process state; clear too.
        self._context_in_flight.clear()
        self._tab_to_profile.clear()
        # Action history is process-local; bridge restart wipes it (telemetry
        # JSONL remains the persistent record).
        self._tab_actions.clear()

        if self._rpc_server is not None:
            try:
                await self._rpc_server.stop()
            except Exception:
                pass
            self._rpc_server = None

        for attr in ("_server", "_status_server", "_legacy_server", "_legacy_status_server"):
            srv = getattr(self, attr)
            if srv:
                srv.close()
                try:
                    await srv.wait_closed()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _runtime_alive(self) -> bool | None:
        """Resolve /status.runtime_alive across the per-client identity map.

        Prefer the RPC server's identified-client view — that's the only
        signal that survives a stale env. The env-derived ``_desktop_pid``
        is kept as a startup fallback for the window where the bridge is
        up but no MCP has called client_hello yet; once any client
        identifies, that fallback is ignored (whether its PID is alive
        or not), because client_hello is authoritative.
        """
        server = self._rpc_server
        if server is not None:
            from_clients = server.runtime_alive()
            if from_clients is not None:
                return from_clients
        if self._desktop_pid is None:
            return None
        return _pid_alive(self._desktop_pid)

    def connected_profiles(self) -> list[dict]:
        """The Chrome profiles currently connected — for discovery by the
        browser tools.

        One entry per live extension connection, so an agent can see EVERY
        connected profile (not just the one its own context happens to use) and
        pick a label to pass as ``browser_profile``. Mirrors the GET /profiles
        shape. Exposed over the control RPC (see bridge_rpc.RPC_METHODS) so a
        client-mode gcu worker — not only the queen — can call it.
        """
        default_label = self._effective_default_label()
        return [
            {
                "label": conn.label,
                "is_default": conn.label == default_label,
                "starred": conn.label == self._starred_default_label,
                "version": conn.version,
                "protocol_version": conn.protocol_version,
            }
            for conn in self._conns.values()
        ]

    def status_payload(self) -> dict:
        """Build the /status JSON. Public so tests / tools can introspect.

        ``connections`` is one entry per live extension connection (one per
        Chrome profile), each carrying its own label, identity, heartbeat,
        and in-flight count so the desktop UI can render per-profile state.
        """
        now_ms = time.monotonic() * 1000
        connections: list[dict] = []
        default_label = self._effective_default_label()  # best-effort, may be None
        for conn in self._conns.values():
            last_pong_age_ms: float | None = None
            if conn.last_pong_ms is not None:
                last_pong_age_ms = round(now_ms - conn.last_pong_ms, 1)
            connections.append(
                {
                    "label": conn.label,
                    "extension_id": conn.extension_id,
                    "version": conn.version,
                    "protocol_version": conn.protocol_version,
                    "connected_since_ms": round(now_ms - conn.connected_at_ms, 1),
                    "last_pong_age_ms": last_pong_age_ms,
                    "in_flight": conn.in_flight,
                    "is_default": (conn.label == default_label),
                }
            )
        return {
            "bridge": "running" if (self._server or self._legacy_server) else "stopped",
            "port": BRIDGE_PORT,
            "connected": self.is_connected,  # legacy single-bool field
            "connections": connections,
            "uptime_ms": round(now_ms - self._started_at_ms, 1),
            # Both versions are nullable — bridge_version is None when the
            # gcu package isn't installed via metadata-bearing means;
            # runtime_version is None when the embedding app didn't pass
            # one in. The side panel renders missing values muted.
            "bridge_version": _BRIDGE_VERSION,
            "runtime_version": self._runtime_version,
            # Connection-level rollup of per-tab health blockers. None unless
            # every active context shares the same severity=block blocker; in
            # that case the side panel renders the Blocker's title/detail/fix
            # directly into the connection rail's fix-hint area (Feature 9 /
            # Step 5). Single source of truth shared with /contexts blockers[].
            "system_blocker": self._system_blocker(),
            # Direct check of the Hive desktop app's process. True/False
            # when we have evidence either way, None when we don't (no
            # client has identified yet AND no env hint either). Sourced
            # from the per-client owner map maintained by the RPC server
            # so a stale env on the long-lived bridge_host process can't
            # poison the signal — see _runtime_alive().
            "runtime_alive": self._runtime_alive(),
            # Per-listener bind state — lets a caller tell "listener never
            # bound" (port conflict) apart from "bound, extension idle".
            "listening": {
                "ws": self._server is not None,
                "status": self._status_server is not None,
                "control_rpc": getattr(self._rpc_server, "is_listening", False),
                "legacy_ws": self._legacy_server is not None,
            },
            # Live count of gcu MCP processes bound to the control RPC right
            # now. This is the bridge's only direct signal for "is the Hive
            # desktop app actively doing browser work" — the app itself
            # doesn't talk to the bridge, it spawns gcu MCPs that do. A
            # bridge with control_rpc_clients=0 may be running, but nobody
            # on the runtime side is using it (orphaned-bridge case).
            "control_rpc_clients": (getattr(self._rpc_server, "active_client_count", 0) if self._rpc_server is not None else 0),
            "bind_errors": dict(self._bind_errors),
        }

    async def _http_status_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Minimal asyncio TCP handler serving HTTP GET /status and /contexts on the status port.

        ``/contexts`` returns the same payload as
        :meth:`list_contexts` so orchestrators in another process (e.g.
        the colony queen, which lives in core and can't import the
        gcu subprocess's state) can introspect per-profile tab groups
        without having to spawn a new MCP tool surface for it.
        """
        try:
            # Read just the headers first — enough to know the method and
            # any Content-Length. Bodies for the POST endpoints are read
            # separately so we don't truncate large adopt payloads.
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                if not chunk:
                    break
                head += chunk
                if len(head) > 8192:
                    break
            header_part, _, body_start = head.partition(b"\r\n\r\n")
            first_line = header_part.split(b"\r\n", 1)[0].decode(errors="replace")
            content_length = 0
            for line in header_part.split(b"\r\n")[1:]:
                if line.lower().startswith(b"content-length:"):
                    try:
                        content_length = int(line.split(b":", 1)[1].strip())
                    except ValueError:
                        content_length = 0
                    break
            body = body_start
            while len(body) < content_length:
                more = await asyncio.wait_for(reader.read(content_length - len(body)), timeout=2.0)
                if not more:
                    break
                body += more
            if first_line.startswith("GET /status"):
                body = json.dumps(self.status_payload()).encode()
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Access-Control-Allow-Headers: *\r\n" + b"Content-Length: " + str(len(body)).encode() + b"\r\n" + b"Connection: close\r\n"
                    b"\r\n" + body
                )
            elif first_line.startswith("GET /profiles"):
                # GET /profiles — one row per connected Chrome profile, so the
                # side panel can list them and let the user star a default.
                now_ms = time.monotonic() * 1000
                default_label = self._effective_default_label()
                profiles = [
                    {
                        "label": conn.label,
                        "extension_id": conn.extension_id,
                        "version": conn.version,
                        "protocol_version": conn.protocol_version,
                        "connected_since_ms": round(now_ms - conn.connected_at_ms, 1),
                        "is_default": (conn.label == default_label),
                        "starred": (conn.label == self._starred_default_label),
                    }
                    for conn in self._conns.values()
                ]
                body = json.dumps({"ok": True, "profiles": profiles}).encode()
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Access-Control-Allow-Headers: *\r\n" + b"Content-Length: " + str(len(body)).encode() + b"\r\n" + b"Connection: close\r\n"
                    b"\r\n" + body
                )
            elif first_line.startswith("GET /contexts"):
                try:
                    contexts = await self.list_contexts()
                    payload: dict = {"ok": True, "contexts": contexts}
                except Exception as exc:
                    payload = {"ok": False, "error": str(exc), "contexts": []}
                body = json.dumps(payload).encode()
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Access-Control-Allow-Headers: *\r\n" + b"Content-Length: " + str(len(body)).encode() + b"\r\n" + b"Connection: close\r\n"
                    b"\r\n" + body
                )
            elif first_line.startswith("GET /tabs/") and "/health" in first_line:
                # GET /tabs/{tabId}/health[?force=1]
                # Per-tab health probe — returns the same Blocker structs
                # the side panel renders, populated by the health registry
                # (foreign_extension_frame, devtools_attached, …). The
                # side panel hits this every 2s for the focused tab so it
                # can show "Blocked by Calendly" with a Disable button
                # even on tabs that aren't owned by any agent.
                m_h = re.match(r"^GET /tabs/(\d+)/health(?:\?(\S*))?", first_line)
                if m_h:
                    try:
                        tab_id = int(m_h.group(1))
                        q = m_h.group(2) or ""
                        force_audit = False
                        for pair in q.split("&"):
                            if pair.startswith("force=") and pair[6:] in ("1", "true", "yes"):
                                force_audit = True
                                break
                        payload = await self.tab_health(tab_id, force_audit=force_audit)
                    except Exception as exc:
                        payload = {"ok": False, "error": str(exc), "blockers": []}
                    body = json.dumps(payload).encode()
                    response = (
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Access-Control-Allow-Origin: *\r\n"
                        b"Access-Control-Allow-Headers: *\r\n" + b"Content-Length: " + str(len(body)).encode() + b"\r\n" + b"Connection: close\r\n"
                        b"\r\n" + body
                    )
                else:
                    response = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            elif first_line.startswith("GET /tabs/"):
                # GET /tabs/{tabId}/actions?limit=N&since=ts_ms
                # Per-tab action history (Feature 3). The side panel uses
                # since= for incremental 2s polling so it never re-fetches
                # the full buffer; last_action_ts_ms is always returned so
                # the "Last action Ns ago — paused" state can render
                # without a second wire call (Feature 10).
                m = re.match(r"^GET /tabs/(\d+)/actions(?:\?(\S*))?", first_line)
                if m:
                    try:
                        tab_id = int(m.group(1))
                        q = m.group(2) or ""
                        limit = 8
                        since_ms: float | None = None
                        for pair in q.split("&"):
                            if not pair:
                                continue
                            k, _, v = pair.partition("=")
                            if k == "limit":
                                try:
                                    limit = int(v)
                                except ValueError:
                                    pass
                            elif k == "since":
                                try:
                                    since_ms = float(v)
                                except ValueError:
                                    pass
                        payload = self.get_tab_actions(tab_id, limit=limit, since_ms=since_ms)
                        payload = {"ok": True, **payload}
                    except Exception as exc:
                        payload = {"ok": False, "error": str(exc), "actions": [], "last_action_ts_ms": None}
                    body = json.dumps(payload).encode()
                    response = (
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Access-Control-Allow-Origin: *\r\n"
                        b"Access-Control-Allow-Headers: *\r\n" + b"Content-Length: " + str(len(body)).encode() + b"\r\n" + b"Connection: close\r\n"
                        b"\r\n" + body
                    )
                else:
                    response = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            elif first_line.startswith("POST /profiles/default"):
                # POST /profiles/default  body: {"label": str, "extensionId"?: str}
                # Stars a profile as the default — the connection 'default'
                # routing resolves to when several extensions are connected.
                status_code = 400
                payload = {"ok": False, "error": "Bad request"}
                try:
                    req = json.loads(body.decode() or "{}")
                    label = (req.get("label") or "").strip()
                    extension_id = req.get("extensionId")
                except Exception:
                    label = ""
                    extension_id = None
                if not label:
                    payload = {"ok": False, "error": 'Body must be {"label": str}'}
                else:
                    self._starred_default_label = label
                    self._save_default_label(label, extension_id)
                    payload = {"ok": True}
                    status_code = 200
                body_out = json.dumps(payload).encode()
                response = (
                    f"HTTP/1.1 {status_code} OK\r\n".encode()
                    + b"Content-Type: application/json\r\n"
                    + b"Access-Control-Allow-Origin: *\r\n"
                    + b"Access-Control-Allow-Headers: *\r\n"
                    + b"Content-Length: "
                    + str(len(body_out)).encode()
                    + b"\r\n"
                    + b"Connection: close\r\n\r\n"
                    + body_out
                )
            elif first_line.startswith("POST /contexts/"):
                # POST /contexts/{profile}/adopt-tab  body: {"tabId": int}
                # Moves an existing tab into the agent's group. Refuses 409
                # if the tab is already owned by a different agent.
                m = re.match(r"^POST /contexts/([^/]+)/adopt-tab", first_line)
                status_code = 400
                payload: dict = {"ok": False, "error": "Bad request"}
                if m:
                    profile = m.group(1)
                    try:
                        req = json.loads(body.decode() or "{}")
                        tab_id = int(req.get("tabId"))
                    except Exception:
                        req = None
                        tab_id = None  # type: ignore[assignment]
                    if tab_id is None:
                        payload = {"ok": False, "error": 'Body must be {"tabId": int}'}
                    else:
                        try:
                            payload = await self.adopt_tab(profile, tab_id, from_user=True)
                            status_code = 200
                        except BridgeError as e:
                            payload = {"ok": False, "error": str(e), "code": e.code}
                            status_code = 409 if e.code == "conflict" else 400
                        except Exception as e:
                            payload = {"ok": False, "error": str(e)}
                            status_code = 500
                else:
                    status_code = 404
                    payload = {"ok": False, "error": "Not found"}
                body_out = json.dumps(payload).encode()
                response = (
                    f"HTTP/1.1 {status_code} OK\r\n".encode()
                    + b"Content-Type: application/json\r\n"
                    + b"Access-Control-Allow-Origin: *\r\n"
                    + b"Access-Control-Allow-Headers: *\r\n"
                    + b"Content-Length: "
                    + str(len(body_out)).encode()
                    + b"\r\n"
                    + b"Connection: close\r\n\r\n"
                    + body_out
                )
            elif first_line.startswith("POST /tabs/") and "/reveal" in first_line:
                # POST /tabs/{tabId}/reveal  no body — user-initiated jump-to-tab
                # (activate + raise the Chrome window). Distinct from the
                # agent-facing tab.activate so automated actions never steal the
                # user's window focus.
                m = re.match(r"^POST /tabs/(\d+)/reveal", first_line)
                status_code = 400
                payload = {"ok": False, "error": "Bad request"}
                if m:
                    try:
                        tab_id = int(m.group(1))
                        payload = await self.reveal_tab(tab_id)
                        status_code = 200
                    except Exception as e:
                        payload = {"ok": False, "error": str(e)}
                        status_code = 500
                else:
                    status_code = 404
                    payload = {"ok": False, "error": "Not found"}
                body_out = json.dumps(payload).encode()
                response = (
                    f"HTTP/1.1 {status_code} OK\r\n".encode()
                    + b"Content-Type: application/json\r\n"
                    + b"Access-Control-Allow-Origin: *\r\n"
                    + b"Access-Control-Allow-Headers: *\r\n"
                    + b"Content-Length: "
                    + str(len(body_out)).encode()
                    + b"\r\n"
                    + b"Connection: close\r\n\r\n"
                    + body_out
                )
            elif first_line.startswith("POST /tabs/"):
                # POST /tabs/{tabId}/release  no body
                m = re.match(r"^POST /tabs/(\d+)/release", first_line)
                status_code = 400
                payload = {"ok": False, "error": "Bad request"}
                if m:
                    try:
                        tab_id = int(m.group(1))
                        payload = await self.release_tab(tab_id, from_user=True)
                        status_code = 200
                    except BridgeError as e:
                        payload = {"ok": False, "error": str(e), "code": e.code}
                        status_code = 400
                    except Exception as e:
                        payload = {"ok": False, "error": str(e)}
                        status_code = 500
                else:
                    status_code = 404
                    payload = {"ok": False, "error": "Not found"}
                body_out = json.dumps(payload).encode()
                response = (
                    f"HTTP/1.1 {status_code} OK\r\n".encode()
                    + b"Content-Type: application/json\r\n"
                    + b"Access-Control-Allow-Origin: *\r\n"
                    + b"Access-Control-Allow-Headers: *\r\n"
                    + b"Content-Length: "
                    + str(len(body_out)).encode()
                    + b"\r\n"
                    + b"Connection: close\r\n\r\n"
                    + body_out
                )
            elif first_line.startswith("POST /shutdown"):
                # Immediate manual shutdown — same teardown path as the idle
                # watchdog, without waiting for the 2-minute grace. Driven
                # from the side panel's "Stop orphaned bridge" button when
                # the user finds a bridge_host that outlived its launcher.
                # We SIGTERM the supervisor so the existing graceful path
                # runs (which terminates this worker). If there's no
                # supervisor (worker run bare), self-SIGTERM.
                try:
                    ppid = os.getppid()
                    if ppid > 1:
                        os.kill(ppid, signal.SIGTERM)
                    else:
                        os.kill(os.getpid(), signal.SIGTERM)
                    payload = {"ok": True, "message": "Bridge shutdown initiated."}
                    status_code = 202
                except Exception as e:
                    payload = {"ok": False, "error": str(e)}
                    status_code = 500
                body_out = json.dumps(payload).encode()
                response = (
                    f"HTTP/1.1 {status_code} OK\r\n".encode()
                    + b"Content-Type: application/json\r\n"
                    + b"Access-Control-Allow-Origin: *\r\n"
                    + b"Access-Control-Allow-Headers: *\r\n"
                    + b"Content-Length: "
                    + str(len(body_out)).encode()
                    + b"\r\n"
                    + b"Connection: close\r\n\r\n"
                    + body_out
                )
            elif first_line.startswith("OPTIONS "):
                response = (
                    b"HTTP/1.1 204 No Content\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Access-Control-Allow-Headers: *\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                )
            else:
                response = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            writer.write(response)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def _handle_connection(self, ws) -> None:
        # One connection object per socket. We do NOT register it in
        # self._conns yet — the profile label is unknown until the hello
        # frame arrives, and no command can route to a connection that
        # isn't in the map. The ping loop's ownership guard tolerates a
        # conn whose label is still None (no entry → loop self-exits if
        # the conn never registers).
        conn = _Connection(ws, label=None)
        logger.info("Chrome extension connected")
        log_connection_event("connect")
        # NB: the app-level ping loop is started on hello, NOT here. Its
        # ownership guard is `self._conns.get(conn.label) is conn`, and the
        # connection isn't registered in self._conns until hello assigns its
        # label — starting the loop pre-hello would make that guard immediately
        # false, so the loop would exit at once and no pings would ever be sent
        # (the extension then never pongs and the connection looks "stale").
        disconnect_reason = "remote_close"
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "hello":
                    conn.version = msg.get("version")
                    conn.extension_id = msg.get("extensionId")
                    proto = msg.get("protocolVersion")
                    if isinstance(proto, int):
                        conn.protocol_version = proto
                    if conn.protocol_version is not None and conn.protocol_version < _MIN_EXTENSION_PROTOCOL_VERSION:
                        logger.warning(
                            "Extension protocol_version=%s below minimum %s — please update the Beeline extension",
                            conn.protocol_version,
                            _MIN_EXTENSION_PROTOCOL_VERSION,
                        )
                    # Resolve the profile label. The extension advertises one
                    # via profileLabel; if absent we fall back to the shared
                    # 'default' label for extensions too old (protocol < 5) or
                    # without an id to distinguish themselves, otherwise we
                    # derive a stable synthetic label from the extension id so
                    # two unlabelled-but-distinct extensions still coexist.
                    label = (msg.get("profileLabel") or "").strip()
                    if not label:
                        if (conn.protocol_version or 0) < 5 or not conn.extension_id:
                            label = DEFAULT_BROWSER_PROFILE
                        else:
                            label = f"profile-{conn.extension_id[:8]}"
                    conn.label = label
                    # Displace a stale connection holding the same label
                    # (extension reload, same profile reconnecting). Scoped to
                    # that ONE connection so other profiles are untouched.
                    old = self._conns.get(label)
                    if old is not None and old is not conn:
                        log_connection_event("disconnect", {"reason": "displaced_by_reconnect", "label": label})
                        try:
                            await old.ws.close(code=4002, reason="displaced_by_reconnect")
                        except Exception:
                            pass
                        self._fail_pending(
                            old,
                            BridgeError(
                                "connection_lost",
                                "The browser connection was replaced by a new connection for the same profile — retry the action.",
                                retryable=True,
                            ),
                        )
                        if old.ping_task and not old.ping_task.done():
                            old.ping_task.cancel()
                    self._conns[label] = conn
                    # Start the app-level ping loop now that the connection is
                    # registered under its label, so the loop's ownership guard
                    # (`self._conns.get(conn.label) is conn`) holds and pings
                    # actually flow. Guard against a duplicate hello re-arming it.
                    if conn.ping_task is None or conn.ping_task.done():
                        conn.ping_task = asyncio.create_task(self._ping_loop(conn))
                    logger.info(
                        "Extension hello: label=%s, version=%s, protocol=%s, id=%s",
                        label,
                        conn.version,
                        conn.protocol_version,
                        (conn.extension_id or "")[:8],
                    )
                    log_connection_event(
                        "hello",
                        {
                            "label": label,
                            "version": conn.version,
                            "protocol_version": conn.protocol_version,
                            "extension_id": conn.extension_id,
                        },
                    )
                    continue

                if msg.get("type") == "pong":
                    conn.last_pong_ms = time.monotonic() * 1000
                    continue

                if msg.get("type") == "ping":
                    # Extension-initiated half of the two-way health check.
                    # The extension pings us so it can detect a half-open
                    # socket from its side (laptop sleep, NAT reaper, a
                    # process stealing the port) and reconnect on its own.
                    # Echo a pong so its heartbeat round-trip completes.
                    try:
                        await conn.ws.send(json.dumps({"type": "pong"}))
                    except Exception:
                        pass
                    continue

                if msg.get("type") == "cdp_event":
                    # Unsolicited CDP event forwarded by the extension.
                    # Narrow diagnostic channel — see FORWARDED_CDP_EVENTS
                    # in browser-extension/background.js. We pick out
                    # the [hive_vp] console probe as a structured
                    # viewport_event telemetry entry and also log the
                    # raw event for correlation with page lifecycle.
                    try:
                        self._handle_cdp_event(
                            msg.get("tabId"),
                            msg.get("method", ""),
                            msg.get("params") or {},
                        )
                    except Exception:
                        pass
                    continue

                if msg.get("type") == "tab_event":
                    # Unsolicited chrome.tabs.* event forwarded by the
                    # extension so the lifecycle registry can follow tabs
                    # that appear outside our explicit browser_open path
                    # (target="_blank", window.open, etc.). Lazy import
                    # to avoid a bridge ↔ tools circular dependency.
                    try:
                        from .tools.lifecycle import update_context_from_tab_event

                        update_context_from_tab_event(
                            event=msg.get("event") or "",
                            tab_id=msg.get("tabId"),
                            group_id=msg.get("groupId"),
                            opener_tab_id=msg.get("openerTabId"),
                            active=msg.get("active"),
                        )
                    except Exception:
                        pass
                    # Keep the per-tab profile attribution in sync — popups
                    # joining one of our groups get attributed automatically.
                    try:
                        self._update_tab_profile_from_event(msg)
                    except Exception:
                        pass
                    # Record tabId → connection routing so a later tab-scoped
                    # command lands on the extension that actually owns the
                    # tab. A "removed" event evicts the routing entry.
                    _tev_tab = msg.get("tabId")
                    if isinstance(_tev_tab, int):
                        if (msg.get("event") or "") == "removed":
                            self._tab_to_conn.pop(_tev_tab, None)
                            # Most tabs close via this event, NOT the close_tab
                            # tool — so evict the per-tab caches here too. These
                            # two (last-active ms + CDP lock) are recreated
                            # lazily and have no cross-tab meaning, so dropping
                            # them is safe and stops one-entry-per-closed-tab
                            # growth for the life of the process. (Larger per-tab
                            # state — _tab_snapshots/_tab_blockers — is only
                            # cleared in close_tab; see memtrace before evicting
                            # it here, in case retention is intentional.)
                            self._tab_active_ms.pop(_tev_tab, None)
                            self._tab_locks.pop(_tev_tab, None)
                        elif conn.label is not None:
                            self._tab_to_conn[_tev_tab] = conn.label
                    continue

                if msg.get("type") == "tab_group_event":
                    # Tab-group lifecycle from chrome.tabGroups.onRemoved
                    # (Chrome auto-drops a group when its last tab closes,
                    # when the user drags the last tab out, or when our
                    # context.destroy closes the tabs). Soft-prune: keep the
                    # agent's identity so adopt_tab can lazy-mint a fresh
                    # group under the same name when the user hands a tab
                    # back. destroy_context calls _prune_group(soft=False)
                    # explicitly for the deliberate-teardown path.
                    if msg.get("event") == "removed":
                        try:
                            self._prune_group(msg.get("groupId"), soft=True)
                        except Exception:
                            pass
                    continue

                msg_id = msg.get("id")
                if msg_id and msg_id in conn.pending:
                    fut = conn.pending.pop(msg_id)
                    if not fut.done():
                        if "error" in msg:
                            log_bridge_message("recv", "response", msg_id=msg_id, error=msg["error"])
                            fut.set_exception(RuntimeError(msg["error"]))
                        else:
                            log_bridge_message("recv", "response", msg_id=msg_id, result=msg.get("result"))
                            fut.set_result(msg.get("result", {}))
        except Exception as exc:
            disconnect_reason = f"exception:{type(exc).__name__}"
        finally:
            # Tear down ONLY this connection — and only if it still owns its
            # label in self._conns. A displaced older handler closing *later*
            # must NOT cancel the new connection's ping task or prune its
            # state; the displacing hello already cancelled the old ping task
            # and failed its pending, and the new conn now owns the label.
            # A pre-hello conn that drops before registering has label=None
            # and is in no map, so the guard below is simply False — its
            # ping task self-exits via its own ownership guard.
            if conn.label is not None and self._conns.get(conn.label) is conn:
                if conn.ping_task and not conn.ping_task.done():
                    conn.ping_task.cancel()
                logger.info("Chrome extension disconnected (label=%s, %s)", conn.label, disconnect_reason)
                log_connection_event("disconnect", {"reason": disconnect_reason, "label": conn.label})
                self._conns.pop(conn.label, None)
                # Surface a structured error to this connection's in-flight
                # callers so a tool wrapper can decide whether to retry.
                # Cancelling the futures (old behavior) is indistinguishable
                # from a deliberate caller cancel.
                self._fail_pending(
                    conn,
                    BridgeError(
                        "connection_lost",
                        "The browser connection dropped before this action finished — retry the action.",
                        retryable=True,
                    ),
                )
                # Soft-prune ONLY this label's context-registry slice. Other
                # profiles may still be live, so we must not wipe the whole
                # registry/global caches. A soft prune keeps each agent's
                # identity reachable for hand-over and lets the stale-context
                # sweep reconcile once the same-label extension reconnects.
                for meta in list(self._context_registry.values()):
                    if meta.get("browser_profile") == conn.label:
                        gid = meta.get("groupId")
                        if gid is not None:
                            self._prune_group(gid, soft=True)
                # Drop this connection's tab-routing entries — they point at an
                # extension that's gone; recycled tab ids must not misroute.
                for tid in [t for t, lbl in self._tab_to_conn.items() if lbl == conn.label]:
                    self._tab_to_conn.pop(tid, None)

    def _handle_cdp_event(self, tab_id: int | None, method: str, params: dict) -> None:
        """Decode a CDP event forwarded from the extension and route it
        to telemetry. Keep this method sync and best-effort — a bad
        event must never break the bridge's read loop.

        Runtime.consoleAPICalled with our ``[hive_vp]`` prefix is
        split off as a structured ``viewport_event`` entry so the
        reader can ``grep`` it without touching the raw console log.
        All other forwarded events are logged verbatim under
        ``cdp_event`` so we can correlate viewport changes with
        lifecycle / resize / target-info events.
        """
        from .telemetry import write_log

        if method == "Runtime.consoleAPICalled":
            args = params.get("args") or []
            first = args[0].get("value") if args and isinstance(args[0], dict) else None
            payload = args[1].get("value") if len(args) >= 2 and isinstance(args[1], dict) else None

            # Structured [hive_vp] viewport probe → viewport_event
            if first == "[hive_vp]" and isinstance(payload, str):
                try:
                    parsed = json.loads(payload)
                except Exception:
                    parsed = {"_raw": payload}
                write_log(
                    {
                        "type": "viewport_event",
                        "tab_id": tab_id,
                        **parsed,
                    }
                )
                return

            # Attach-time canary → attach_canary (proves extension
            # forwarder is alive end-to-end).
            if first == "[hive_attach_canary]" and isinstance(payload, str):
                try:
                    parsed = json.loads(payload)
                except Exception:
                    parsed = {"_raw": payload}
                write_log(
                    {
                        "type": "attach_canary",
                        "tab_id": tab_id,
                        **parsed,
                    }
                )
                return

            # Everything else — keep a compact row so we can tell
            # whether ANY console output is flowing through the
            # pipe. Truncate each arg so a chatty page can't flood
            # the log.
            compact = []
            for a in args[:4]:
                if not isinstance(a, dict):
                    continue
                v = a.get("value")
                if isinstance(v, str):
                    compact.append(v[:120])
                elif v is not None:
                    compact.append(str(v)[:120])
            write_log(
                {
                    "type": "cdp_event",
                    "tab_id": tab_id,
                    "method": method,
                    "level": params.get("type"),
                    "args": compact,
                }
            )
            return

        # Other forwarded events (Page.lifecycleEvent, frameResized,
        # frameNavigated, Target.targetInfoChanged) are rare and high
        # signal — keep the full param dict but truncate strings.
        write_log(
            {
                "type": "cdp_event",
                "tab_id": tab_id,
                "method": method,
                "params": params,
            }
        )

        # Main-frame navigation wipes the previous document's scripts.
        # Our [hive_vp] probe's event listeners die with it. Reinstall
        # on every main-frame navigation so the post-nav page is also
        # instrumented. Sub-frame navs (iframes, about:srcdoc) ignored.
        if method == "Page.frameNavigated":
            frame = params.get("frame") or {}
            if frame and not frame.get("parentId") and tab_id is not None:
                self._schedule_reinject_probe(tab_id)
                # Drop the cached health snapshot + blockers — the new
                # document has its own URL and iframe set, so URL-driven
                # rules (privileged_scheme, chrome_web_store, file_access)
                # cached against the prior page are now wrong. tab_health()
                # deliberately does not clear blockers on an empty fresh
                # snapshot (it can't see foreign-extension iframes Chrome
                # scrubs), so without this pop a stale "Privileged Chrome
                # page" blocker survives forever once the tab moved off a
                # chrome:// page to a real https one.
                self._tab_snapshots.pop(tab_id, None)
                self._tab_blockers.pop(tab_id, None)

        # Layout viewport resized (hidden→visible, banner commit,
        # user window resize, devtools open/close, zoom). Invalidate
        # the viewport cache so the next non-live reader — e.g.
        # _read_focused_element — re-queries instead of returning a
        # stale value. Click conversion already live-queries, so
        # this is for the rect / focused_element paths that read
        # _viewport_sizes directly.
        if method == "Page.frameResized" and tab_id is not None:
            try:
                from .tools.inspection import _viewport_sizes

                _viewport_sizes.pop(tab_id, None)
            except Exception:
                pass

        # Native dialog (alert / confirm / prompt / beforeunload) opened.
        # With chrome.debugger attached, Chrome holds the dialog open and
        # pauses page execution until Page.handleJavaScriptDialog is sent.
        # Track per-tab so navigation poll loops can short-circuit and the
        # dialog tools can list/respond.
        if method == "Page.javascriptDialogOpening" and tab_id is not None:
            self._pending_dialogs[tab_id] = {
                "type": params.get("type", "unknown"),
                "message": params.get("message", ""),
                "default_prompt": params.get("defaultPrompt", ""),
                "url": params.get("url", ""),
                "opened_at_ms": time.monotonic() * 1000,
            }

        # Dialog resolved (either by our handle_javascript_dialog call or
        # by Chrome auto-cancelling on tab close / navigation). Clear our
        # state so subsequent tools don't see a stale entry.
        if method == "Page.javascriptDialogClosed" and tab_id is not None:
            self._pending_dialogs.pop(tab_id, None)

    def _schedule_reinject_probe(self, tab_id: int) -> None:
        """Fire-and-forget re-injection of _HIVE_VP_PROBE_JS on the
        current document of ``tab_id``. Called from sync context
        inside ``_handle_cdp_event``, so we create a task on the
        running loop. Failures are silent."""

        async def _do() -> None:
            try:
                # The new document's global scope doesn't have
                # __hive_vp_instrumented — the probe's idempotency
                # guard works because nav cleared window state.
                await self._cdp(
                    tab_id,
                    "Runtime.evaluate",
                    {
                        "expression": _HIVE_VP_PROBE_JS,
                        "returnByValue": True,
                        "awaitPromise": False,
                    },
                )
            except Exception:
                pass

        try:
            asyncio.get_event_loop().create_task(_do())
        except RuntimeError:
            pass

    # Default wait on a bridge command. Callers with known-slow ops
    # (full-page screenshots on slow networks, AX tree on huge pages)
    # can pass a longer value via _send(..., timeout=...). Using the
    # same default as the old hard-coded value so existing call sites
    # don't regress.
    _DEFAULT_SEND_TIMEOUT_S: float = 30.0

    def _tab_lock(self, tab_id: int) -> asyncio.Lock:
        """Lazy-create an asyncio.Lock keyed by tab_id.

        Used to serialize CDP commands targeting the same tab. Lock is
        kept around for the lifetime of the bridge — the keyspace is
        bounded by the number of tabs Chrome ever creates per session
        and entries are dropped in stop().
        """
        lock = self._tab_locks.get(tab_id)
        if lock is None:
            lock = asyncio.Lock()
            self._tab_locks[tab_id] = lock
        return lock

    async def _send(self, type_: str, *, browser_profile: str | None = None, timeout: float | None = None, **params) -> dict:
        """Send a command to the right extension connection and await the result.

        Connection resolution, in priority order:
          1. explicit ``browser_profile`` → resolve_connection (raises on a
             missing/ambiguous profile, so a worker bound to a label can't
             silently run in the wrong browser);
          2. an int ``tabId`` whose owning connection is known;
          3. an int ``groupId`` whose minting connection is still live;
          4. otherwise the 'default' rule (starred default / sole connection /
             not_connected / ambiguous_default).
        """
        if browser_profile is not None:
            conn = self.resolve_connection(browser_profile)
        else:
            conn = None
            _route_tab = params.get("tabId")
            if isinstance(_route_tab, int):
                conn = self._conn_for_tab(_route_tab)
            if conn is None:
                _route_group = params.get("groupId")
                if isinstance(_route_group, int):
                    glabel = self._conn_label_for_group(_route_group)
                    if glabel:
                        conn = self._conns.get(glabel)
            if conn is None:
                conn = self.resolve_connection(None)
        conn.counter += 1
        msg_id = str(conn.counter)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        conn.pending[msg_id] = fut
        self._in_flight += 1
        conn.in_flight += 1
        start = time.perf_counter()
        effective_timeout = timeout if timeout is not None else self._DEFAULT_SEND_TIMEOUT_S

        log_bridge_message("send", type_, msg_id=msg_id, params=params)

        # Stamp agent activity per tab — every command carrying a tabId
        # (navigate, click, type, cdp, …) counts. list_contexts() rolls this
        # up so the side panel can show how long ago each agent last acted.
        _tab = params.get("tabId")
        _in_flight_profile: str | None = None
        if isinstance(_tab, int):
            self._tab_active_ms[_tab] = time.time() * 1000
            # Track per-context in-flight so the side panel can render a
            # "working" badge while a command is actively running. The
            # reverse map is best-effort; a miss just means the command
            # doesn't get attributed to an agent (e.g. user-initiated tab
            # that's not in any group yet).
            _in_flight_profile = self._tab_to_profile.get(_tab)
            if _in_flight_profile:
                self._context_in_flight[_in_flight_profile] = self._context_in_flight.get(_in_flight_profile, 0) + 1

        try:
            await conn.ws.send(json.dumps({"id": msg_id, "type": type_, **params}))
            result = await asyncio.wait_for(fut, timeout=effective_timeout)
            duration_ms = (time.perf_counter() - start) * 1000
            log_bridge_message("send", type_, msg_id=msg_id, result=result, duration_ms=duration_ms)
            return result
        except TimeoutError:
            conn.pending.pop(msg_id, None)
            log_bridge_message("send", type_, msg_id=msg_id, error="timeout")
            # Include which CDP method (if any) so the caller can see
            # what actually hung — the generic 'cdp' type is useless
            # when ten different CDP calls use the same type.
            detail = f" method={params.get('method')}" if params.get("method") else ""
            raise BridgeError(
                "timeout",
                f"Bridge command '{type_}'{detail} timed out after {effective_timeout:.0f}s",
                retryable=False,
            ) from None
        except BridgeError:
            # _fail_pending already removed the future when it set the
            # exception; just propagate so callers see the real code.
            raise
        except BaseException:
            # CancelledError or any other exception — remove stale future so a late
            # response from the extension doesn't try to resolve a cancelled future.
            conn.pending.pop(msg_id, None)
            raise
        finally:
            if self._in_flight > 0:
                self._in_flight -= 1
            if conn.in_flight > 0:
                conn.in_flight -= 1
            if _in_flight_profile is not None:
                cur = self._context_in_flight.get(_in_flight_profile, 0)
                if cur > 1:
                    self._context_in_flight[_in_flight_profile] = cur - 1
                else:
                    self._context_in_flight.pop(_in_flight_profile, None)

    # Substrings that indicate Chrome detached the debugger out from
    # under us (tab closed, user opened DevTools, cross-origin nav).
    # Our in-memory _cdp_attached set is now stale; next call should
    # re-attach rather than reporting a cryptic "Target not found".
    _CDP_DEAD_SESSION_MARKERS = (
        "target closed",
        "target not found",
        "not attached",
        "session closed",
        "inspector already attached",
        "no target with given id",
    )

    def _is_cdp_dead_session(self, exc: BaseException) -> bool:
        msg = str(exc).lower()
        return any(m in msg for m in self._CDP_DEAD_SESSION_MARKERS)

    async def _cdp(
        self,
        tab_id: int,
        method: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> dict:
        """Send a CDP command to a tab.

        ``timeout`` (seconds) overrides the default bridge send timeout.
        Pass a larger value for genuinely slow operations (full-page
        screenshots over slow networks, accessibility tree on huge
        pages) so they don't spuriously fail at the 30s floor. Pass a
        smaller value for fast probes ("is this element present right
        now") to fail fast.

        On a dead-session error (Chrome detached externally — tab closed,
        DevTools opened, cross-origin nav), evict the stale attach
        cache entry, reattach, and retry once. Without this the Python
        side would keep assuming it's attached and every subsequent call
        would hit the same error until someone restarted the bridge.

        Concurrent calls targeting the same tab are serialized via a
        per-tab asyncio.Lock — interleaved attach/detach/sendCommand
        would otherwise corrupt CDP session state when two queens
        accidentally share a tab.
        """
        # Fast-fail if a native dialog is pausing this tab. The renderer is
        # frozen and the per-tab lock is almost certainly held by whatever
        # command triggered the dialog (e.g. a stuck Page.navigate), so any
        # CDP call here would block for the full ~60s send timeout — and a
        # pile of those is what wedges the whole browser context. Surface
        # an actionable error instead. browser_dialog_respond resolves the
        # dialog via a lock-free path (see handle_javascript_dialog).
        if self._pending_dialogs.get(tab_id):
            raise BridgeError(
                "dialog_open",
                f"Tab {tab_id} is blocked by a native browser dialog. Call browser_dialog_respond to accept or dismiss it first.",
                retryable=False,
            )
        start = time.perf_counter()
        async with self._tab_lock(tab_id):
            try:
                result = await self._send(
                    "cdp",
                    tabId=tab_id,
                    method=method,
                    params=params or {},
                    timeout=timeout,
                )
                duration_ms = (time.perf_counter() - start) * 1000
                log_cdp_command(tab_id, method, params, result, duration_ms=duration_ms)
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                log_cdp_command(tab_id, method, params, error=str(e), duration_ms=duration_ms)
                # Reactive health classification. Cheap (sync, in-process) so
                # it's fine to run on every CDP error; rules that need no
                # snapshot match from the error string alone, so this catches
                # late re-injections that the attach-time snapshot missed.
                try:
                    self._refresh_blockers(tab_id, error=str(e))
                except Exception:
                    pass
                # Foreign-frame errors leave us knowing "another extension is
                # in the tab" but not WHICH one — Chrome scrubs the id from
                # the error string by design. Re-run tab.audit so the
                # extension can name the offender from chrome.debugger.getTargets,
                # then re-classify with the fresh snapshot. This is what
                # turns "Blocked by another extension" into "Blocked by Calendly"
                # for the agent and the side panel. Skipped when the offender
                # is already named in the cached snapshot.
                try:
                    err_str = str(e).lower()
                    if "chrome-extension://" in err_str and "different extension" in err_str and not self._snapshot_has_foreign_frame(tab_id):
                        asyncio.create_task(self._reaudit_for_foreign_frame(tab_id))
                except Exception:
                    pass
                if self._is_cdp_dead_session(e):
                    logger.info(
                        "CDP session for tab %d looks dead (%s) — re-attaching and retrying",
                        tab_id,
                        str(e)[:120],
                    )
                    self._cdp_attached.discard(tab_id)
                    try:
                        reattach = await self._send("cdp.attach", tabId=tab_id)
                        if reattach.get("ok"):
                            self._cdp_attached.add(tab_id)
                            retry_start = time.perf_counter()
                            result = await self._send(
                                "cdp",
                                tabId=tab_id,
                                method=method,
                                params=params or {},
                                timeout=timeout,
                            )
                            log_cdp_command(
                                tab_id,
                                method,
                                params,
                                result,
                                duration_ms=(time.perf_counter() - retry_start) * 1000,
                            )
                            return result
                    except Exception as retry_exc:
                        logger.debug("CDP reattach+retry for tab %d failed: %s", tab_id, retry_exc)
                raise

    async def _try_enable_domain(self, tab_id: int, domain: str) -> None:
        """Try to enable a CDP domain, ignoring errors if not available.

        Some domains (like Input) may not be available on certain page types
        (e.g., chrome:// URLs, extension pages, or restricted sites).
        """
        try:
            await self._cdp(tab_id, f"{domain}.enable")
        except RuntimeError as e:
            # Log but don't fail - domain may not be available on all pages
            if "wasn't found" in str(e) or "not found" in str(e).lower():
                logger.debug("CDP domain %s.enable not available for tab %s", domain, tab_id)
            else:
                raise

    # ── Context (Tab Group) Management ─────────────────────────────────────────

    async def create_context(self, agent_id: str, display_name: str | None = None, browser_profile: str = "default") -> dict:
        """Create a labelled tab group for this agent in a specific browser profile.

        ``agent_id`` is the stable profile/session id. ``display_name`` is an
        optional human-readable label (queen/colony name) used as the Chrome
        tab group title; it falls back to ``agent_id`` when not supplied.
        ``browser_profile`` names the Chrome profile (extension connection)
        the group is created in; ``"default"`` follows the default-routing rule.

        Returns {"groupId": int, "tabId": int, "browser_profile": str}.
        """
        # Resolve the target connection up front so a missing/ambiguous profile
        # fails fast BEFORE we mint anything in the wrong (or no) browser.
        conn = self.resolve_connection(browser_profile)
        # Recycle an empty saved-group chip Chrome wouldn't let us delete, so we
        # reuse it instead of leaking a fresh chip (protocol >= 5). We always
        # drop the chosen id from the pool afterwards: on success it's now an
        # active group; on fallback (it had vanished) it's no longer recyclable.
        recycle_id: int | None = None
        if self._persisted_groups and (conn.protocol_version or 0) >= 5:
            recycle_id = next(iter(self._persisted_groups))
        send_params = {"agentId": agent_id, "displayName": display_name or agent_id}
        if recycle_id is not None:
            send_params["recycleGroupId"] = recycle_id
        # Window affinity (see _hive_window_by_conn): pass the window this
        # connection's groups already live in so the new group lands there, and
        # serialize per-connection so a concurrent first batch establishes one
        # window rather than scattering across whichever windows are focused.
        lock = self._window_locks.setdefault(conn.label, asyncio.Lock())
        async with lock:
            stored_win = self._hive_window_by_conn.get(conn.label)
            if isinstance(stored_win, int):
                send_params["windowId"] = stored_win
            result = await self._send("context.create", browser_profile=conn.label, **send_params)
            # Learn the window from the extension's response. STICKY: only change
            # the stored anchor when it actually differs — the extension enforces
            # the requested window (moving the group back if a recycle/fallback
            # landed it elsewhere), so a differing windowId means the old anchor
            # window is genuinely gone, NOT that a spawn drifted to the user's
            # focused window. This is what stops the anchor from chasing focus.
            win = result.get("windowId")
            if isinstance(win, int):
                prev = self._hive_window_by_conn.get(conn.label)
                if prev != win:
                    if isinstance(prev, int):
                        logger.info(
                            "Hive anchor window for %s moved %s -> %s (previous window closed)",
                            conn.label,
                            prev,
                            win,
                        )
                    self._hive_window_by_conn[conn.label] = win
        if recycle_id is not None:
            self._persisted_groups.discard(recycle_id)
        log_context_event("create", agent_id, group_id=result.get("groupId"), tab_id=result.get("tabId"))
        if result.get("groupId") is not None:
            # The recycled chip is now live again — make sure it isn't also
            # tracked as a closeable orphan or a recyclable chip.
            self._persisted_groups.discard(result["groupId"])
            self._orphan_seen.pop(result["groupId"], None)
            self._context_registry[agent_id] = {
                "groupId": result["groupId"],
                "name": display_name or agent_id,
                # Owning connection's label — lets _send route group/tab-scoped
                # commands back to the same extension and lets the sweep prune
                # only this connection's slice.
                "browser_profile": conn.label,
                # Floor for the dormancy check. Without this, a freshly-
                # created context whose tabs haven't received any CDP
                # commands yet would have last_active_ms=None and look
                # like an ancient orphan to list_contexts.
                "registered_at_ms": time.time() * 1000,
            }
            tab_id = result.get("tabId")
            if isinstance(tab_id, int):
                self._tab_to_profile[tab_id] = agent_id
                self._tab_to_conn[tab_id] = conn.label
                self._hive_tab_ids.add(tab_id)
        result["browser_profile"] = conn.label
        return result

    def register_context(self, profile: str, group_id: int, name: str | None = None, browser_profile: str = "default") -> dict:
        """Upsert a profile→group entry into the bridge's context registry.

        Idempotent. Used by a (re)connecting gcu to re-publish contexts it
        already owns — e.g. after this bridge process restarted and lost the
        registry, or after the gcu rehydrated tab groups that outlived it —
        so /contexts and the side panel stay accurate without a fresh
        create_context. Best-effort: does NOT require a matching connection,
        since a gcu may rehydrate before its extension reconnects.
        """
        self._context_registry[profile] = {
            "groupId": group_id,
            "name": name or profile,
            # Owning connection's label, so routing/sweep can attribute the
            # group to the right extension once it (re)connects.
            "browser_profile": browser_profile,
            # Re-registration counts as activity from the dormancy clock's
            # perspective: a context just rehydrated from disk gets a
            # fresh window before list_contexts flags it as dormant. If
            # it sits unused for _DORMANT_AFTER_MS past this point with no
            # agent touching its tabs, it flips to dormant.
            "registered_at_ms": time.time() * 1000,
        }
        return {"ok": True}

    async def destroy_context(self, group_id: int, browser_profile: str | None = None) -> dict:
        """Close all tabs in the group and remove it.

        Routes the destroy to the connection that owns the group: an explicit
        ``browser_profile`` wins; otherwise we look up the minting connection
        from the registry; otherwise default routing applies.

        When the extension reports ``persistedGroup`` (Chrome's Saved Tab Groups
        kept an empty, un-deletable chip), remember it so the forward reaper
        stops trying to close it and create_context can recycle it later;
        otherwise the group is truly gone, so drop any stale tracking of it.
        """
        target_profile = browser_profile or self._conn_label_for_group(group_id)
        result = await self._send("context.destroy", groupId=group_id, browser_profile=target_profile)
        log_context_event("destroy", _get_active_profile(), group_id=group_id, details=result)
        if result.get("persistedGroup"):
            self._persisted_groups.add(group_id)
        else:
            self._persisted_groups.discard(group_id)
        self._orphan_seen.pop(group_id, None)
        # Drop tab-routing entries for tabs in the destroyed group.
        for tid in list(self._tab_to_conn):
            agent = self._tab_to_profile.get(tid)
            if agent and (self._context_registry.get(agent, {}) or {}).get("groupId") == group_id:
                self._tab_to_conn.pop(tid, None)
        self._prune_group(group_id)
        return result

    def _prune_group(self, group_id: int | None, *, soft: bool = False) -> int:
        """Detach the Chrome group from every _context_registry entry pointing at ``group_id``.

        Two modes:
          - hard (default): delete the profile entirely. Used by destroy_context —
            the user/agent has explicitly torn the agent down.
          - soft: keep name + identity but clear groupId, bumping
            registered_at_ms so the agent doesn't immediately age out of the
            side panel. Used by Chrome's tabGroups.onRemoved event and by the
            stale-context sweep — the underlying group is gone (e.g. the
            user released the agent's last tab) but the agent itself should
            still be reachable for hand-over. adopt_tab lazy-mints a fresh
            group under the same name on the next adoption.

        Idempotent — entries with no matching groupId are skipped. Returns the
        number of entries touched so the sweep can log a useful summary.

        Cascades to the per-tab attribution map regardless of mode: any tabs
        routed to the now-defunct group lose their attribution so a recycled
        tabId doesn't get credited to a deleted/orphaned agent. The per-
        profile in-flight counter is dropped too — commands referencing the
        old group will fail when their futures resolve.
        """
        if group_id is None:
            return 0
        touched_profiles: list[str] = []
        now_ms = time.time() * 1000
        for profile, meta in list(self._context_registry.items()):
            if meta.get("groupId") == group_id:
                if soft:
                    meta["groupId"] = None
                    meta["registered_at_ms"] = now_ms
                else:
                    del self._context_registry[profile]
                touched_profiles.append(profile)
        for profile in touched_profiles:
            self._context_in_flight.pop(profile, None)
            for tid, pname in list(self._tab_to_profile.items()):
                if pname == profile:
                    self._tab_to_profile.pop(tid, None)
        return len(touched_profiles)

    # Cadence for the defensive sweep. Long enough that a brief disconnect
    # doesn't lose more than one tick; short enough that a missed onRemoved
    # event clears the panel before the user files a "ghost agent" report.
    _STALE_SWEEP_INTERVAL_S: float = 30.0

    async def _stale_context_sweep_loop(self) -> None:
        """Reconcile _context_registry against Chrome's live tab groups.

        The event-driven path (_prune_group via tab_group_event) is the
        fast path; this loop is the fallback for events lost during a
        disconnect, an extension reload, or any version of the extension
        old enough not to forward tabGroups.onRemoved.

        Each extension only sees its OWN profile's tab groups, so we query
        every connection separately and reconcile only that connection's
        slice of the registry — a group missing from connection A's list
        says nothing about connection B's groups.

        Errors are logged and swallowed — a transient extension hiccup
        must never take the bridge's WS handler down with it.
        """
        while True:
            try:
                await asyncio.sleep(self._STALE_SWEEP_INTERVAL_S)
            except asyncio.CancelledError:
                return
            if not self.is_connected:
                continue
            for label, conn in list(self._conns.items()):
                # Feature-gate on protocol >= 3 (the version that introduced
                # tabGroup.list); older extensions silently no-op.
                if (conn.protocol_version or 0) < 3:
                    continue
                # Always fetch — the forward reaper below needs the live group
                # set even when our registry slice is empty (e.g. a fresh
                # bridge_host after an app crash, with stale Hive groups still
                # open in Chrome).
                try:
                    result = await self._send("tabGroup.list", browser_profile=label)
                except Exception as exc:
                    logger.debug("Stale-context sweep skipped for label=%s: %s", label, exc)
                    continue
                groups = result.get("groups") or []
                live = {g.get("id") for g in groups if g.get("id") is not None}
                hive_groups = sum(1 for g in groups if HIVE_GROUP_MARKER in (g.get("title") or ""))
                # Reverse direction: THIS connection's registry entries whose
                # Chrome group vanished.
                stale = [
                    (profile, meta.get("groupId"))
                    for profile, meta in self._context_registry.items()
                    if meta.get("browser_profile") == label and meta.get("groupId") not in live
                ]
                for profile, gid in stale:
                    # Soft-prune: matches the tab_group_event path — the group is
                    # gone from Chrome but we don't know why, and the agent should
                    # remain reachable for hand-over.
                    self._prune_group(gid, soft=True)
                    logger.info("Stale-context sweep soft-pruned profile=%s groupId=%s label=%s", profile, gid, label)
                # Forward direction: Hive-owned Chrome groups that no live context
                # claims — orphans left by a crash/SIGKILL/registry-wipe. Close them.
                orphan_groups_pending = orphan_groups_reaped = 0
                try:
                    orphan_groups_pending, orphan_groups_reaped = await self._forward_reap_orphans(groups, browser_profile=label)
                except Exception as exc:
                    logger.debug("Forward orphan reap skipped for label=%s: %s", label, exc)
                # Ungrouped escapees the group reaper can't see (renderer leak
                # backstop). Protocol 6 (tab.listUngrouped); older extensions
                # silently skip, like tabGroup.list is gated on protocol >= 3.
                ungrouped_total = ungrouped_candidates = ungrouped_reaped = 0
                if (conn.protocol_version or 0) >= 6:
                    try:
                        ungrouped_total, ungrouped_candidates, ungrouped_reaped = await self._reap_ungrouped_orphans(browser_profile=label)
                    except Exception as exc:
                        logger.debug("Ungrouped orphan reap skipped for label=%s: %s", label, exc)
                # One structured line per profile per sweep — the only way to see
                # the leak locus on non-default profiles a client can't query.
                # ``tracked_hive_tabs`` is the ratchet gauge: it must plateau.
                logger.info(
                    "browser-sweep label=%s live_groups=%d hive_groups=%d orphan_groups_pending=%d "
                    "orphan_groups_reaped=%d ungrouped_total=%d ungrouped_candidates=%d "
                    "ungrouped_reaped=%d tracked_hive_tabs=%d",
                    label,
                    len(live),
                    hive_groups,
                    orphan_groups_pending,
                    orphan_groups_reaped,
                    ungrouped_total,
                    ungrouped_candidates,
                    ungrouped_reaped,
                    len(self._hive_tab_ids),
                )

    async def _forward_reap_orphans(self, groups: list[dict], browser_profile: str | None = None) -> tuple[int, int]:
        """Close Chrome tab groups that are Hive-owned but unclaimed by any
        live context — the durable backstop for orphans a crash left behind.

        Returns ``(pending, reaped)``: how many marked-orphan groups are
        currently being debounced, and how many were closed this sweep. The
        sweep loop folds these into its per-profile observability line.

        Scoped to ONE connection: ``groups`` are that connection's live groups
        and ``owned`` is computed from registry entries belonging to that
        connection's label (plus the recyclable persisted chips, which are
        session-global). Without this scoping, a group owned by profile B would
        look orphaned when reaping profile A and be wrongly closed.

        Conservative by construction: a group is reaped only when (a) its title
        carries ``HIVE_GROUP_MARKER`` (so user-created groups are never touched),
        (b) its id is in no registry entry (a live agent's group always is), and
        (c) it has been seen orphaned on two consecutive sweeps (so a group
        created between the extension's tab.group call and create_context's
        registry write is never reaped mid-birth). Prefer leaking a chip over
        closing a user's tabs.
        """
        owned = {
            meta.get("groupId")
            for meta in self._context_registry.values()
            if meta.get("groupId") is not None and (browser_profile is None or meta.get("browser_profile") == browser_profile)
        }
        # Empty saved chips we already know Chrome won't let us delete — don't
        # spin trying to close them every sweep; they're held for recycling.
        owned |= self._persisted_groups
        current_orphans: set[int] = set()
        for g in groups:
            gid = g.get("id")
            if gid is None or gid in owned:
                continue
            if HIVE_GROUP_MARKER not in (g.get("title") or ""):
                continue  # not a Hive group — never touch
            current_orphans.add(gid)

        # Drop debounce counters for ids that are no longer orphaned.
        for gid in list(self._orphan_seen):
            if gid not in current_orphans:
                del self._orphan_seen[gid]

        to_reap: list[int] = []
        for gid in current_orphans:
            self._orphan_seen[gid] = self._orphan_seen.get(gid, 0) + 1
            if self._orphan_seen[gid] >= 2:
                to_reap.append(gid)

        reaped = 0
        for gid in to_reap:
            try:
                await self.destroy_context(gid, browser_profile=browser_profile)
                reaped += 1
                logger.info("Forward orphan reap closed unclaimed Hive groupId=%s label=%s", gid, browser_profile)
            except Exception as exc:
                logger.debug("Forward orphan reap: destroy_context(%s) failed: %s", gid, exc)
            finally:
                self._orphan_seen.pop(gid, None)
        return len(current_orphans), reaped

    async def _reap_ungrouped_orphans(self, *, browser_profile: str | None = None) -> tuple[int, int, int]:
        """Close UNGROUPED tabs the bridge knows were Hive's but that escaped
        into the loose-tab pool (e.g. a new-window popup the extension's
        adoptEscapedTab couldn't group). These carry no HIVE_GROUP_MARKER, so
        the group reaper can't see them; without this they leak forever, each
        holding a renderer process — the root of the renderer ratchet.

        Returns ``(ungrouped_total, candidates, reaped)`` for observability.

        Conservative, mirroring ``_forward_reap_orphans``: a tab is closed only
        when (a) its id is in ``_hive_tab_ids`` — the bridge demonstrably saw it
        INSIDE a Hive group, so a user's tab is never a candidate — (b) it is
        currently ungrouped, (c) no live context still claims it
        (``_tab_to_profile``), and (d) it has looked orphaned on two
        consecutive sweeps (a tab transiting between groups gets a full sweep to
        settle). Worst case is a leak, never a user tab closed.
        """
        if not self._hive_tab_ids:
            return 0, 0, 0
        result = await self._send("tab.listUngrouped", browser_profile=browser_profile)
        ungrouped = {t.get("id") for t in (result.get("tabs") or []) if isinstance(t.get("id"), int)}
        # Was-ours AND now-ungrouped AND not attributed to a live context. Tab
        # ids are unique per Chrome session, so intersecting with THIS
        # connection's ungrouped set scopes the reap to the right profile.
        candidates = {tid for tid in (self._hive_tab_ids & ungrouped) if self._tab_to_profile.get(tid) is None}

        # Drop debounce counters for ids no longer candidates (re-grouped, etc.).
        for tid in list(self._ungrouped_seen):
            if tid not in candidates:
                del self._ungrouped_seen[tid]

        to_reap: list[int] = []
        for tid in candidates:
            self._ungrouped_seen[tid] = self._ungrouped_seen.get(tid, 0) + 1
            if self._ungrouped_seen[tid] >= 2:
                to_reap.append(tid)

        reaped = 0
        for tid in to_reap:
            try:
                await self.close_tab(tid)  # also discards _hive_tab_ids / _ungrouped_seen
                reaped += 1
                logger.info("Ungrouped orphan reap closed escaped Hive tabId=%s label=%s", tid, browser_profile)
            except Exception as exc:
                logger.debug("Ungrouped orphan reap: close_tab(%s) failed: %s", tid, exc)
            finally:
                self._ungrouped_seen.pop(tid, None)
                self._hive_tab_ids.discard(tid)
        return len(ungrouped), len(candidates), reaped

    async def list_contexts(self) -> list[dict]:
        """Enumerate every active browser tab group keyed by profile.

        Reads the bridge-owned context registry (see ``_context_registry``)
        and pairs it with live tab info from the extension, so orchestrators
        (e.g. a colony queen) and the side panel can see which agent owns
        which tab group. Because the registry lives in the bridge process,
        this works no matter which — if any — gcu process is connected.

        Returns a list of ``{"profile", "groupId", "activeTab", "name",
        "tabs": [...]}`` entries. Tabs are best-effort: if the extension call
        fails for a particular group, we keep the entry with ``tabs: []``
        rather than dropping the whole row.
        """
        out: list[dict] = []
        for profile_name, meta in list(self._context_registry.items()):
            group_id = meta.get("groupId")
            entry: dict = {
                "profile": profile_name,
                "groupId": group_id,
                "activeTab": None,
                "name": meta.get("name"),
                "tabs": [],
            }
            if group_id is not None and self.is_connected:
                try:
                    tabs_result = await self.list_tabs(group_id)
                    entry["tabs"] = tabs_result.get("tabs", [])
                except Exception:
                    # Stale group ID or transient extension hiccup —
                    # keep the row so callers know the profile owns a
                    # group, even if we couldn't enumerate the tabs.
                    pass
            # Active tab comes from the live tab list now (the registry holds
            # only stable identity, not the agent's current focus).
            active = next((t for t in entry["tabs"] if t.get("active")), None)
            if active is not None:
                entry["activeTab"] = active.get("id")
            # Roll the per-tab activity stamps up to a single "last active"
            # time for the whole context (newest action across its tabs), and
            # remember which tab that was.
            tab_ids = {t.get("id") for t in entry["tabs"] if t.get("id") is not None}
            last_active: float | None = None
            last_active_tab: int | None = None
            for tid in tab_ids:
                ts = self._tab_active_ms.get(tid)
                if ts is not None and (last_active is None or ts > last_active):
                    last_active = ts
                    last_active_tab = tid
            entry["last_active_ms"] = last_active
            # The extension's tab.list doesn't carry Chrome's per-tab `active`
            # flag, so the lookup above leaves activeTab unset. Fall back to the
            # most-recently-driven tab — the one the agent last sent a command
            # to — which is the meaningful "current focus" for an agent.
            if entry["activeTab"] is None and last_active_tab is not None:
                entry["activeTab"] = last_active_tab
            # Dormancy: tab group is still around in Chrome but no agent
            # has touched it in long enough that surfacing it as "active"
            # would mislead the user. The floor is the registration time
            # so a freshly created/rehydrated context isn't insta-dormant
            # before any agent has had a chance to act on it.
            effective_active_ms = last_active
            registered_at_ms = meta.get("registered_at_ms")
            if effective_active_ms is None or (registered_at_ms is not None and registered_at_ms > effective_active_ms):
                effective_active_ms = registered_at_ms
            if effective_active_ms is None:
                # No floor and no activity stamps — extremely unlikely
                # (entries always get registered_at_ms at registration
                # after this commit), but be conservative: treat as fresh
                # so we don't blank the list on a pre-upgrade registry.
                entry["dormant"] = False
            else:
                entry["dormant"] = ((time.time() * 1000) - effective_active_ms) > self._DORMANT_AFTER_MS
            # Roll per-tab health blockers up into the context entry, deduped
            # by kind across all tabs in the group. The side panel renders
            # one row per blocker; the agent's tool error can echo the same
            # struct so the LLM speaks the same language as the UI.
            seen_kinds: set[str] = set()
            blockers: list[dict] = []
            for tid in tab_ids:
                for b in self._tab_blockers.get(tid) or []:
                    k = b.get("kind") or ""
                    if k and k not in seen_kinds:
                        seen_kinds.add(k)
                        blockers.append(b)
            entry["blockers"] = blockers
            entry["status"] = self._classify_context_status(
                profile=profile_name,
                blockers=blockers,
                last_active_ms=last_active,
            )
            out.append(entry)
        return out

    # ── Connection-level blocker rollup ────────────────────────────────────────

    def _system_blocker(self) -> dict | None:
        """Synthesize a connection-level blocker from per-tab observations.

        When EVERY active context has at least one block-severity blocker
        of the same kind, that kind is universal — the right surface for it
        is the connection rail itself, not N parallel agent rows. This
        function does the rollup; the side panel reads it from /status and
        renders the rail's fix-hint copy directly from the Blocker's
        title/detail/fix fields.

        A blocker that only hits some contexts is intentionally NOT promoted
        here — the per-agent row already shows it. The connection layer
        speaks for "no agent can act right now"; agent rows speak for
        "this specific agent is impaired".

        Returns a representative Blocker dict (copied — caller can mutate
        freely) or None if there is no universal blocker.
        """
        profiles = [p for p, m in self._context_registry.items() if m.get("groupId") is not None]
        if not profiles:
            return None
        per_profile_kinds: dict[str, set[str]] = {p: set() for p in profiles}
        sample_by_kind: dict[str, dict] = {}
        for tab_id, blockers in self._tab_blockers.items():
            profile = self._tab_to_profile.get(tab_id)
            if profile not in per_profile_kinds:
                continue
            for b in blockers:
                if (b.get("severity") or "") != "block":
                    continue
                kind = b.get("kind") or ""
                if not kind:
                    continue
                per_profile_kinds[profile].add(kind)
                sample_by_kind.setdefault(kind, dict(b))
        # If any context has no block-severity blocker, the issue isn't
        # universal — bail.
        if not all(per_profile_kinds.values()):
            return None
        shared = set.intersection(*per_profile_kinds.values())
        if not shared:
            return None

        # Stable choice if multiple kinds are universal (rare): pick the
        # one with the lowest priority value (matches health.classify's
        # first-match-wins semantics).
        def _priority(k: str) -> int:
            return int(sample_by_kind[k].get("priority", 100))

        chosen = min(shared, key=_priority)
        return sample_by_kind[chosen]

    # ── Per-tab action history ─────────────────────────────────────────────────

    # Ring-buffer size per tab. 200 is plenty for a "show more" expansion;
    # the typical 8-row default fits comfortably even on small panels.
    _TAB_ACTION_BUFFER_SIZE: int = 200

    def record_action(
        self,
        tab_id: int,
        verb: str,
        *,
        target: str | None = None,
        ok: bool = True,
        ts_ms: float | None = None,
    ) -> None:
        """Append one action entry to the per-tab ring buffer.

        Called from telemetry.log_tool_call when a user-facing tool finishes
        (success OR error). The buffer is bounded — old entries fall off as
        new ones arrive. tab_id missing / unknown is a no-op (some tools run
        without a settled tab id; their actions are still logged to JSONL).
        """
        if not isinstance(tab_id, int):
            return
        buf = self._tab_actions.get(tab_id)
        if buf is None:
            buf = deque(maxlen=self._TAB_ACTION_BUFFER_SIZE)
            self._tab_actions[tab_id] = buf
        buf.append(
            {
                "ts_ms": ts_ms if ts_ms is not None else time.time() * 1000,
                "verb": verb,
                "target": target or "",
                "ok": bool(ok),
            }
        )

    def get_tab_actions(
        self,
        tab_id: int,
        *,
        limit: int = 8,
        since_ms: float | None = None,
    ) -> dict:
        """Return the latest entries for ``tab_id``, descending by time.

        ``limit`` caps the entries returned (1–200; clamped). ``since_ms``
        filters to entries strictly newer than the timestamp — used by the
        side panel's incremental 2s poll so it never re-fetches the same
        rows. ``last_action_ts_ms`` is always populated (or null) so the
        UI can render "Last action 5s ago — paused" without a separate
        wire call — see Feature 10.
        """
        capped = max(0, min(int(limit or 0), self._TAB_ACTION_BUFFER_SIZE))
        buf = self._tab_actions.get(tab_id)
        if not buf:
            return {"actions": [], "last_action_ts_ms": None}
        last_ts = buf[-1]["ts_ms"]
        # limit=0 is a legitimate "just give me last_action_ts_ms" probe
        # (Feature 10). Bail before the loop so the empty list is honoured.
        if capped == 0:
            return {"actions": [], "last_action_ts_ms": last_ts}
        # Newest first. The deque appends in chronological order, so
        # iterate in reverse for the descending view the UI wants.
        entries: list[dict] = []
        for e in reversed(buf):
            if since_ms is not None and e["ts_ms"] <= since_ms:
                break
            entries.append(e)
            if len(entries) >= capped:
                break
        return {"actions": entries, "last_action_ts_ms": last_ts}

    # Threshold (ms) for the "waiting" classification — an agent that acted
    # within this window is still considered active even with no pending
    # in-flight command. Chosen so a multi-step tool plan with brief gaps
    # between CDP calls doesn't flicker into "idle".
    _WAITING_WINDOW_MS: float = 30_000.0
    # Threshold (ms) past which a context is considered dormant — the tab
    # group still exists in Chrome, but no agent has touched any of its
    # tabs in long enough that listing it as "active" in the side panel
    # would be misleading. ``rehydrate_contexts`` can resurrect months-old
    # ``profile → groupId`` mappings on app restart; without this flag the
    # side panel would render them indistinguishably from a currently-
    # working queen. The side panel hides dormant entries by default but
    # exposes them behind a collapsed sub-section so adoption still works.
    # 6h was picked as "longer than any plausible single-task gap, shorter
    # than 'I closed Hive overnight'." Tune here if dogfooding suggests
    # it.
    _DORMANT_AFTER_MS: float = 6 * 60 * 60 * 1000.0

    def _classify_context_status(
        self,
        *,
        profile: str,
        blockers: list[dict],
        last_active_ms: float | None,
    ) -> str:
        """Map a context's live state to one of: blocked / working / waiting / idle.

        Priority order (highest first):
          1. blocked  — any severity="block" blocker is present.
          2. working  — there's at least one CDP command currently in-flight.
          3. waiting  — last agent action was within _WAITING_WINDOW_MS.
          4. idle     — otherwise.

        The connection-level "system blocked" verdict (Feature 9 / Step 5)
        layers on top of this in /status, not here — list_contexts reports
        each context's individually-observable state.
        """
        for b in blockers:
            if (b.get("severity") or "") == "block":
                return "blocked"
        if self._context_in_flight.get(profile, 0) > 0:
            return "working"
        if last_active_ms is not None:
            age = (time.time() * 1000) - last_active_ms
            if age < self._WAITING_WINDOW_MS:
                return "waiting"
        return "idle"

    # ── Tab Management ─────────────────────────────────────────────────────────

    async def create_tab(self, url: str = "about:blank", group_id: int | None = None) -> dict:
        """Create a new tab and optionally add it to a group.

        Returns {"tabId": int}.
        """
        params = {"url": url}
        if group_id is not None:
            params["groupId"] = group_id
        result = await self._send("tab.create", **params)
        # Wire the new tab into the reverse map so its commands are
        # attributed to the right agent. A tab without a group is
        # not owned by anyone and stays unmapped.
        new_tab_id = result.get("tabId")
        if isinstance(new_tab_id, int) and group_id is not None:
            profile = self._profile_for_group(group_id)
            if profile:
                self._tab_to_profile[new_tab_id] = profile
                # Created inside a Hive group → remember durably so the
                # ungrouped-orphan reaper can recognise it if it escapes.
                self._hive_tab_ids.add(new_tab_id)
            # Route subsequent tab-scoped commands to the owning connection.
            owner_label = self._conn_label_for_group(group_id)
            if owner_label:
                self._tab_to_conn[new_tab_id] = owner_label
        return result

    def _profile_for_group(self, group_id: int | None) -> str | None:
        """Reverse-look up the profile that owns ``group_id``. Linear in the
        number of contexts — fine: we have at most a handful, and this only
        runs at tab-creation / tab-event time, never on the hot _send path."""
        if group_id is None:
            return None
        for profile, meta in self._context_registry.items():
            if meta.get("groupId") == group_id:
                return profile
        return None

    def _update_tab_profile_from_event(self, msg: dict) -> None:
        """Keep ``_tab_to_profile`` in sync with chrome.tabs.* events.

        Tabs created outside our control (target="_blank", window.open, user
        drag-into-group) need to be attributed once Chrome assigns them to a
        group we own. ``removed`` evicts the entry. Robust to the ordering
        quirk where ``created`` fires with groupId=-1 and ``grouped`` settles
        it later.
        """
        tab_id = msg.get("tabId")
        if not isinstance(tab_id, int):
            return
        event = msg.get("event") or ""
        if event == "removed":
            self._tab_to_profile.pop(tab_id, None)
            self._hive_tab_ids.discard(tab_id)
            return
        group_id = msg.get("groupId")
        if not isinstance(group_id, int) or group_id < 0:
            return
        profile = self._profile_for_group(group_id)
        if profile:
            self._tab_to_profile[tab_id] = profile
            # The tab is (now) inside a Hive group — created, grouped, or the
            # extension's "regrouped" adopt of an escaped page-spawned tab.
            # Remember it durably for the ungrouped-orphan reaper.
            self._hive_tab_ids.add(tab_id)
        else:
            # Tab moved out of one of our groups (or into a non-Hive group).
            # Drop the attribution so future commands don't credit a stale
            # owner.
            self._tab_to_profile.pop(tab_id, None)

    async def close_tab(self, tab_id: int) -> dict:
        """Close a tab by ID."""
        result = await self._send("tab.close", tabId=tab_id)
        # Drop per-tab state — the id may be reused by Chrome much
        # later, and carrying a stale highlight or "attached" flag
        # forward would misannotate screenshots or skip a needed
        # reattach on the reused id.
        self._cdp_attached.discard(tab_id)
        _interaction_highlights.pop(tab_id, None)
        # Any dialog that was open on this tab is gone with the tab.
        # CDP won't emit Page.javascriptDialogClosed in this path.
        self._pending_dialogs.pop(tab_id, None)
        # Health snapshot + blockers belonged to this tab's attach session.
        self._tab_snapshots.pop(tab_id, None)
        self._tab_blockers.pop(tab_id, None)
        # The tab is gone — its profile attribution goes with it.
        self._tab_to_profile.pop(tab_id, None)
        # And it can no longer be an ungrouped-orphan candidate.
        self._hive_tab_ids.discard(tab_id)
        self._ungrouped_seen.pop(tab_id, None)
        # Drop the action history with the tab. Chrome can reuse the
        # numeric id later; carrying entries forward would misattribute
        # the new tab's first actions to the previous tab's agent.
        self._tab_actions.pop(tab_id, None)
        # Last-active timestamp and the per-tab CDP lock are per-tab too; they
        # were the only sibling maps not evicted here, so they grew one entry
        # per closed tab for the life of the process.
        self._tab_active_ms.pop(tab_id, None)
        self._tab_locks.pop(tab_id, None)
        from .tools.inspection import clear_tab_state

        clear_tab_state(tab_id)
        return result

    # ── Tab adoption / release (Feature 2 / Step 6) ────────────────────────

    async def adopt_tab(self, profile: str, tab_id: int, *, from_user: bool = False) -> dict:
        """Move ``tab_id`` into ``profile``'s group.

        Refuses with a structured ``BridgeError(code="conflict")`` if the
        tab is already in another agent's group — silently re-owning work
        creates "where did my tab go" surprises. A non-Hive group is fine:
        Chrome's group() call handles the move atomically. If the tab is
        already in the target group, returns success without a wire call.

        Lazy group re-create: if the agent's group is gone (last tab was
        released → Chrome destroyed the empty group → bridge soft-pruned
        to groupId=None), this mints a fresh group under the agent's
        saved display name and adopts into it — so release-then-hand-back
        round-trips work without forcing the user to recreate the agent.

        ``from_user`` flags the side-panel-initiated "Hand over" path.
        When set, on success we push a notify frame to the new owner so
        the agent gets a user-style "tab handed over to you" message in
        its next iteration. Agent-driven adoption stays silent.

        Requires extension protocol_version >= 4 (tab.get / tab.adopt).
        Older extensions raise BridgeError(code="unsupported_extension")
        so the caller can surface a "please update" message.
        """
        if (self._extension_protocol_version or 0) < 4:
            raise BridgeError(
                "unsupported_extension",
                "Tab hand-over requires Hive Browser Bridge v1.5+. Update the Chrome extension and retry.",
                retryable=False,
            )
        meta = self._context_registry.get(profile)
        if meta is None:
            raise BridgeError(
                "no_such_profile",
                f"No agent named '{profile}'. Create one first or pick a different agent.",
                retryable=False,
            )
        group_id = meta.get("groupId")
        # Route lazy-mint / adopt / get to the connection that owns this agent.
        owner_label = meta.get("browser_profile")
        seed_tab_to_close: int | None = None
        # Lazy re-create. The seed tab context.create spawns is closed AFTER
        # the user's tab is adopted — closing it first would leave the new
        # group empty, triggering another auto-destroy and undoing the work.
        if group_id is None:
            display_name = meta.get("name") or profile
            create_result = await self._send(
                "context.create",
                browser_profile=owner_label,
                agentId=profile,
                displayName=display_name,
            )
            new_group_id = create_result.get("groupId") if isinstance(create_result, dict) else None
            if not isinstance(new_group_id, int):
                raise BridgeError(
                    "create_failed",
                    f"Could not mint a fresh tab group for agent '{profile}'.",
                    retryable=True,
                )
            meta["groupId"] = new_group_id
            meta["registered_at_ms"] = time.time() * 1000
            group_id = new_group_id
            seed_candidate = create_result.get("tabId")
            if isinstance(seed_candidate, int) and seed_candidate != tab_id:
                seed_tab_to_close = seed_candidate
        info = await self._send("tab.get", tabId=tab_id, browser_profile=owner_label)
        notify_title = str(info.get("title") or "") if from_user and isinstance(info, dict) else ""
        current_group = info.get("groupId")
        if isinstance(current_group, int) and current_group >= 0:
            if current_group == group_id:
                # Already where we want it — confirm without a redundant move.
                self._tab_to_profile[tab_id] = profile
                if owner_label:
                    self._tab_to_conn[tab_id] = owner_label
                if seed_tab_to_close is not None:
                    # Edge case: somehow the user's tab is already in the
                    # group we just minted. The seed is still redundant.
                    try:
                        await self._send("tab.close", tabId=seed_tab_to_close)
                    except Exception:
                        pass
                if from_user:
                    await self._notify_adopt(profile, tab_id, notify_title)
                return {"ok": True, "tabId": tab_id, "groupId": group_id, "already_owned": True}
            for other_profile, other_meta in self._context_registry.items():
                if other_profile != profile and other_meta.get("groupId") == current_group:
                    raise BridgeError(
                        "conflict",
                        f"Tab {tab_id} is currently owned by agent '{other_profile}'. Release it first, then adopt.",
                        retryable=False,
                    )
        result = await self._send("tab.adopt", tabId=tab_id, groupId=group_id, browser_profile=owner_label)
        self._tab_to_profile[tab_id] = profile
        if owner_label:
            self._tab_to_conn[tab_id] = owner_label
        if seed_tab_to_close is not None:
            try:
                await self._send("tab.close", tabId=seed_tab_to_close)
            except Exception:
                pass
        if from_user:
            await self._notify_adopt(profile, tab_id, notify_title)
        return {"ok": True, "tabId": tab_id, "groupId": result.get("groupId", group_id)}

    async def _notify_adopt(self, profile: str, tab_id: int, title: str) -> None:
        """Fire the side-panel adopt notification, swallowing transport errors.

        Used by ``adopt_tab(from_user=True)`` on both the move and the
        already-in-group paths so the agent always sees the message
        when the human clicks Hand over.
        """
        if self._rpc_server is None:
            return
        text = _format_user_tab_message(title, tab_id, action="handed-over")
        try:
            await self._rpc_server.notify(profile, text, tabId=tab_id, action="handed-over")
        except Exception:
            logger.debug("adopt_tab notify failed for profile=%r", profile, exc_info=True)

    async def release_tab(self, tab_id: int, *, from_user: bool = False) -> dict:
        """Remove ``tab_id`` from whatever group it's in.

        Idempotent: ungrouping a tab that isn't in any group is a no-op
        at Chrome's level. The owning profile (if any) loses its
        attribution; the per-tab health/action state stays because the
        tab itself still exists.

        ``from_user`` flags the side-panel-initiated path. When set, we
        capture the tab's title before the release and, on success,
        push a notify frame to the owning profile so the agent gets a
        user-style "tab detached" message in its next iteration. Agent-
        driven releases (via the browser_* tools) leave it False so we
        don't deliver a "user detached" message to an agent that
        detached its own tab.
        """
        if (self._extension_protocol_version or 0) < 4:
            raise BridgeError(
                "unsupported_extension",
                "Tab release requires Hive Browser Bridge v1.5+. Update the Chrome extension and retry.",
                retryable=False,
            )
        # Snapshot the notify payload BEFORE the release: the profile
        # attribution is wiped below, and tab.get on a tab the user
        # simultaneously closed would fail.
        notify_profile: str | None = None
        notify_title: str = ""
        if from_user:
            notify_profile = self._tab_to_profile.get(tab_id)
            if notify_profile:
                try:
                    info = await self._send("tab.get", tabId=tab_id)
                    notify_title = str(info.get("title") or "") if isinstance(info, dict) else ""
                except Exception:
                    notify_title = ""  # title is cosmetic; proceed without it
        result = await self._send("tab.release", tabId=tab_id)
        # Verify post-call groupId before clearing local attribution.
        # chrome.tabs.ungroup can resolve without throwing yet leave the
        # tab in its original group (Chromium forks, enterprise tab-group
        # policy, mid-drag race). Without this check we'd return ok and
        # the side panel would silently keep showing the Release button
        # because list_tabs(group_id) still includes the tab.
        # Old extensions (no groupId in the response) skip the check —
        # the result.get below returns None and the guard is a no-op.
        post_group = result.get("groupId") if isinstance(result, dict) else None
        if isinstance(post_group, int) and post_group >= 0:
            raise BridgeError(
                "ungroup_no_op",
                f"Chrome reported the tab is still in group {post_group} after release — "
                "tab-group editing is likely blocked (tab drag in progress, enterprise "
                "policy disabling tab groups, or a Chromium fork without full tab-groups "
                "support). Retry, or move the tab out of the group manually.",
                retryable=True,
            )
        self._tab_to_profile.pop(tab_id, None)
        if notify_profile and self._rpc_server is not None:
            text = _format_user_tab_message(notify_title, tab_id, action="detached")
            try:
                await self._rpc_server.notify(notify_profile, text, tabId=tab_id, action="detached")
            except Exception:
                logger.debug("release_tab notify failed for profile=%r", notify_profile, exc_info=True)
        return {"ok": True, "tabId": tab_id, **(result if isinstance(result, dict) else {})}

    async def list_tabs(self, group_id: int | None = None) -> dict:
        """List tabs, optionally filtered by group.

        Returns {"tabs": [{"id": int, "url": str, "title": str, "groupId": int}, ...]}.
        """
        params = {"groupId": group_id} if group_id is not None else {}
        return await self._send("tab.list", **params)

    async def activate_tab(self, tab_id: int) -> dict:
        """Activate (focus) a tab."""
        return await self._send("tab.activate", tabId=tab_id)

    async def reveal_tab(self, tab_id: int) -> dict:
        """Activate a tab AND raise its Chrome window — user-initiated jump-to-tab.

        Kept separate from :meth:`activate_tab` (which agents call during normal
        tab operations) so automated actions never pull the browser window to
        the foreground and steal focus from whatever the user is doing.

        Degrades gracefully: an extension build that predates ``tab.reveal``
        throws "Unknown command", so we fall back to a plain activate — the
        click still switches to the tab, just without raising the window.
        """
        try:
            return await self._send("tab.reveal", tabId=tab_id)
        except Exception as exc:
            if "Unknown command" in str(exc):
                logger.info("reveal_tab: extension lacks tab.reveal; falling back to tab.activate")
                res = await self._send("tab.activate", tabId=tab_id)
                # Tag the fallback so the caller (and the HTTP log) can tell it
                # apart from a real reveal — both otherwise return {ok:true}.
                return {**res, "fallback": "activate"} if isinstance(res, dict) else res
            raise

    # ── CDP Attachment ─────────────────────────────────────────────────────────

    async def cdp_attach(self, tab_id: int) -> dict:
        """Attach CDP debugger to a tab.

        Returns {"ok": bool}.

        First-attach-per-tab triggers Chrome's "<extension> started
        debugging this browser" infobar, which shrinks the layout
        viewport by ~30–70 CSS px. The banner's commit is async from
        the attach return, so a screenshot taken immediately after
        can capture the pre-banner layout, leaving the viewport
        cache stale until the next screenshot or
        ``_ensure_viewport_size`` call. We wait a short grace here
        and proactively prime the viewport cache with the settled
        (post-banner) dimensions, so the very first coord-conversion
        after attach already operates on the real frame.
        """
        if tab_id in self._cdp_attached:
            return {"ok": True, "attached": False, "message": "Already attached"}
        result = await self._send("cdp.attach", tabId=tab_id)
        if not result.get("ok"):
            # Attach itself failed — let the health rules name *why* (DevTools
            # holding the tab, enterprise policy, …) from the error string so
            # the side panel can render a useful row instead of swallowing it.
            try:
                self._refresh_blockers(tab_id, error=str(result.get("error") or result.get("message") or ""))
            except Exception:
                pass
            return result
        self._cdp_attached.add(tab_id)
        # Proactive health audit: take a snapshot now and run the registry.
        # Gated on extension protocol_version >= 2 — older extensions don't
        # implement tab.audit, so calling it would burn a round-trip per
        # first-attach for an error we'd just swallow. Failures inside the
        # gate are still swallowed; the reactive path on the next CDP error
        # catches anything we missed (e.g. late iframe re-injection).
        if (self._extension_protocol_version or 0) >= 2:
            try:
                snap = await self._send("tab.audit", tabId=tab_id)
                self._refresh_blockers(tab_id, snapshot=snap)
            except Exception:
                pass
        # Prime the viewport cache so the first coord-conversion
        # after attach has a reasonable seed. Also install the
        # diagnostic viewport-change probe ([hive_vp] console
        # messages that stream through our CDP-event channel).
        # Failures are silent — cache will heal on next screenshot
        # or _ensure_viewport_size call.
        try:
            from .tools.inspection import _viewport_sizes

            eval_res = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {
                    "expression": "({w: window.innerWidth, h: window.innerHeight})",
                    "returnByValue": True,
                },
            )
            inner = (eval_res or {}).get("result", {}).get("value") or {}
            cw = int(float(inner.get("w") or 0))
            ch = int(float(inner.get("h") or 0))
            if cw > 0 and ch > 0:
                _viewport_sizes[tab_id] = (cw, ch)
        except Exception:
            pass

        # Runtime must be enabled for consoleAPICalled events to
        # fire; Page must be enabled for frame* / lifecycle events
        # to reach the extension. Page.setLifecycleEventsEnabled
        # is the critical one — without it Chrome withholds the
        # DOMContentLoaded / load / firstMeaningfulPaint stream.
        # Each wrapped in try so a failure on one domain doesn't
        # block the others.
        try:
            await self._cdp(tab_id, "Runtime.enable", {})
        except Exception:
            pass
        try:
            await self._cdp(tab_id, "Page.enable", {})
        except Exception:
            pass
        try:
            await self._cdp(tab_id, "Page.setLifecycleEventsEnabled", {"enabled": True})
        except Exception:
            pass

        # [hive_vp] probe — install resize / visibility listeners on
        # the page so Chrome tells us when the renderer sees a
        # viewport change. Uses console.info as a cheap transport
        # through CDP; filtered server-side by the cdp_event
        # handler. Idempotent via __hive_vp_instrumented.
        try:
            await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {
                    "expression": _HIVE_VP_PROBE_JS,
                    "returnByValue": True,
                    "awaitPromise": False,
                },
            )
        except Exception:
            pass

        # Canary — emit a recognisable marker from the page so we
        # can verify end-to-end (page → CDP → extension → bridge →
        # telemetry) is wired. Should produce one ``cdp_event``
        # with method=Runtime.consoleAPICalled whose args start
        # ``[hive_attach_canary]``. Zero canary entries after a
        # run means the extension forwarder is stale and the user
        # needs to reload the Hive extension in chrome://extensions.
        try:
            await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {
                    "expression": ("console.info('[hive_attach_canary]', JSON.stringify({tabId: " + str(tab_id) + ", ts: Date.now()}))"),
                    "returnByValue": True,
                    "awaitPromise": False,
                },
            )
        except Exception:
            pass

        return result

    async def cdp_detach(self, tab_id: int) -> dict:
        """Detach CDP debugger from a tab."""
        result = await self._send("cdp.detach", tabId=tab_id)
        self._cdp_attached.discard(tab_id)
        # Health state was specific to this attach session.
        self._tab_snapshots.pop(tab_id, None)
        self._tab_blockers.pop(tab_id, None)
        return result

    # ── Tab health audit ───────────────────────────────────────────────────────

    async def audit_tab(self, tab_id: int) -> dict:
        """Take a raw observation snapshot of ``tab_id`` from the extension.

        Returns the flat ``tab.audit`` payload — no judgements. Pair with
        ``health.classify`` (or ``classify_all``) to produce ``Blocker``s.
        Used internally on attach and reactively on CDP errors; also exposed
        so tools/RPC callers can re-probe ad hoc when diagnosing a stuck tab.
        """
        return await self._send("tab.audit", tabId=tab_id)

    def _refresh_blockers(
        self,
        tab_id: int,
        *,
        snapshot: dict | None = None,
        error: str | None = None,
    ) -> list[Blocker]:
        """Run the health registry against the latest snapshot + optional error.

        ``snapshot`` overrides any cached snapshot (e.g. after a fresh audit).
        ``error`` adds reactive context — e.g. the CDP error string that just
        fired — so rules driven by Chrome's error wording can match without
        requiring a fresh wire round-trip.
        """
        if snapshot is not None:
            self._tab_snapshots[tab_id] = snapshot
        snap = snapshot if snapshot is not None else self._tab_snapshots.get(tab_id) or {}
        ctx = {"our_extension_id": self._extension_id} if self._extension_id else {}
        blockers = classify_all(snap, error, ctx=ctx)
        if blockers:
            self._tab_blockers[tab_id] = [b.to_dict() for b in blockers]
        elif error is None:
            # A clean proactive audit found nothing; clear any stale list.
            self._tab_blockers.pop(tab_id, None)
        return blockers

    def _snapshot_has_foreign_frame(self, tab_id: int) -> bool:
        """True iff the cached audit snapshot already names a non-own extension.

        Used by the reactive CDP error path to decide whether re-auditing is
        worth a round-trip: if we already know the offender's id, we can
        skip the audit. Mirrors the detection logic in
        ``health._foreign_extension_frame`` but stays local so this module
        doesn't need to import the rule directly.
        """
        snap = self._tab_snapshots.get(tab_id) or {}
        own = snap.get("ourExtensionId") or self._extension_id
        if not own:
            return False
        from .health import _extension_id_from_url, _iter_frame_urls

        for url, declared in _iter_frame_urls(snap):
            ext_id = declared or _extension_id_from_url(url)
            if ext_id and ext_id != own:
                return True
        return False

    async def _reaudit_for_foreign_frame(self, tab_id: int) -> None:
        """Fire-and-forget: re-run tab.audit + re-classify after a CDP error.

        Calendly (and similar) inject via a MutationObserver that can fire
        AFTER our attach-time audit, so the cached snapshot doesn't always
        name them. This task runs in the background so it doesn't slow the
        CDP-error path; it just makes the *next* health probe show the
        offender by name. Errors are swallowed — the worst case is the side
        panel keeps showing the generic "another extension" copy.
        """
        try:
            snapshot = await self._send("tab.audit", tabId=tab_id)
            self._refresh_blockers(tab_id, snapshot=snapshot)
        except Exception:
            pass

    async def get_tab_blockers(self, tab_id: int) -> list[dict]:
        """Return the cached blocker dicts for ``tab_id`` (may be empty).

        Side-effect-free — reads only the in-memory cache populated by
        ``_refresh_blockers``. Use this from tool wrappers to enrich error
        responses without burning an extra round-trip.

        Declared async so it's uniformly awaitable from in-process callers
        (BeelineBridge) and out-of-process RPC clients (RemoteBridge),
        which always wrap forwarded methods as coroutines.
        """
        return list(self._tab_blockers.get(tab_id) or [])

    async def tab_health(
        self,
        tab_id: int,
        *,
        force_audit: bool = False,
    ) -> dict:
        """Public per-tab health probe used by the side panel.

        Returns ``{"ok": True, "tab_id": tab_id, "url": str, "blockers": [...]}``.

        Re-classifies ONLY when a fresh snapshot was fetched — otherwise
        returns the cached blocker list as-is. This matters because
        ``_refresh_blockers`` (with no error and no fresh snapshot) would
        clear a cache that was populated by an earlier CDP-error path:
        the snapshot rule wouldn't match (Calendly's iframe isn't in the
        attach-time snapshot) and the cleanup would discard real blockers
        that the agent and the side panel still need to see.

        ``force_audit=True`` re-runs ``tab.audit`` even if we have a cached
        snapshot — useful when the side panel just got woken up and wants
        to be sure the cache isn't stale. Default False keeps the polling
        path cheap: one Chrome IPC for the audit, none if we hit the cache.
        """
        fresh_snapshot: dict | None = None
        if force_audit or tab_id not in self._tab_snapshots:
            try:
                fresh_snapshot = await self._send("tab.audit", tabId=tab_id)
            except Exception as e:
                # Audit can fail (tab gone, extension restarted, …). Fall
                # back to whatever's cached rather than failing the probe
                # outright — the side panel calls this every 2s and we
                # don't want a noisy banner about a transient hiccup.
                logger.debug("tab.audit failed for tab %d: %s", tab_id, e)
        if fresh_snapshot is not None:
            # Cache the snapshot itself but ONLY overwrite blockers when
            # the fresh snapshot classifies to at least one match. Empty
            # results from the snapshot rule do NOT clear the cache —
            # tab.audit can't see foreign-extension iframes (Chrome scrubs
            # them from chrome.debugger.getTargets), so an "empty" snapshot
            # doesn't actually mean "no foreign frames". Blockers that
            # were populated reactively via _evaluate_failure /
            # _cdp's except handler MUST persist across health polls.
            self._tab_snapshots[tab_id] = fresh_snapshot
            ctx = {"our_extension_id": self._extension_id} if self._extension_id else {}
            fresh_blockers = classify_all(fresh_snapshot, None, ctx=ctx)
            if fresh_blockers:
                self._tab_blockers[tab_id] = [b.to_dict() for b in fresh_blockers]
        # Read from cache (whether populated just now from a fresh audit or
        # earlier by a CDP-error path that called _refresh_blockers(error=…)).
        blockers = list(self._tab_blockers.get(tab_id) or [])
        url = (fresh_snapshot or self._tab_snapshots.get(tab_id) or {}).get("url", "")
        return {
            "ok": True,
            "tab_id": tab_id,
            "url": url,
            "blockers": blockers,
        }

    # ── Navigation ─────────────────────────────────────────────────────────────

    async def navigate(
        self,
        tab_id: int,
        url: str,
        wait_until: str = "load",
        timeout_ms: int = 30000,
    ) -> dict:
        """Navigate a tab to a URL.

        Uses CDP Page.navigate with lifecycle wait.
        """
        if wait_until not in VALID_WAIT_UNTIL:
            wait_until = "load"

        # Drop the stale interaction highlight before loading a new
        # page — otherwise the next screenshot will annotate the new
        # page with a rect from the previous page's coordinate system.
        _interaction_highlights.pop(tab_id, None)

        # Attach debugger if needed
        await self.cdp_attach(tab_id)

        # Enable Page domain
        await self._cdp(tab_id, "Page.enable")

        # Navigate.
        #
        # Page.navigate does NOT resolve while a native beforeunload dialog
        # is open — the leaving page's handler pauses the navigation before
        # a loaderId is even assigned. Awaiting it directly would block here
        # until the bridge's _send timeout (~60s), so issue it as a task and
        # poll for a dialog concurrently. If one appears, return early; the
        # in-flight command resolves later once browser_dialog_respond
        # handles the dialog (or it times out) — _swallow_future_exc keeps
        # that orphaned task quiet.
        nav_cmd = asyncio.ensure_future(self._cdp(tab_id, "Page.navigate", {"url": url}))
        # Page.navigate ACKs (returns its loaderId) within ~1s for a normal
        # navigation — the slow part is the page load, handled by the
        # readyState poll further down. If the ACK hasn't arrived in this
        # window and no dialog surfaced, the navigation is almost certainly
        # blocked by a native dialog the bridge never saw (e.g. one opened
        # before this bridge instance started, after an MCP restart). Bail
        # with an actionable error instead of hanging the full send timeout.
        ack_deadline = asyncio.get_event_loop().time() + 10.0
        while not nav_cmd.done():
            pending = self._pending_dialogs.get(tab_id)
            if pending:
                nav_cmd.add_done_callback(_swallow_future_exc)
                return _pending_dialog_result(tab_id, pending, action="navigate")
            if asyncio.get_event_loop().time() > ack_deadline:
                nav_cmd.add_done_callback(_swallow_future_exc)
                return {
                    "ok": False,
                    "tabId": tab_id,
                    "error": (
                        "Navigation did not start within 10s and no dialog was "
                        "detected by the bridge. The page most likely has an "
                        "unsaved-changes prompt blocking it. Call "
                        "browser_dialog_respond(action='accept') to clear it, "
                        "then retry."
                    ),
                }
            await asyncio.sleep(0.05)
        # Raises if the command errored or hit the _send timeout — same
        # surface as the original `await self._cdp(...)`.
        result = await nav_cmd
        # Page.navigate reports a transport failure (unresolvable DNS, connection
        # refused, blocked scheme) via errorText alongside loaderId. Surface it
        # instead of returning ok:true with the error-page's title (audit B3).
        nav_error = result.get("errorText")
        if nav_error:
            return {"ok": False, "tabId": tab_id, "error": nav_error, "url": url}
        loader_id = result.get("loaderId")

        # Wait for lifecycle event
        if wait_until != "commit" and loader_id:
            # Poll for the event with timeout
            deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
            while asyncio.get_event_loop().time() < deadline:
                # A dialog can also open mid-load (e.g. an onload confirm).
                # Page execution is paused — readyState will never flip.
                # Short-circuit instead of running the loop to its deadline.
                pending = self._pending_dialogs.get(tab_id)
                if pending:
                    return _pending_dialog_result(tab_id, pending, action="navigate")
                # Check if we've reached the desired state
                eval_result = await self._cdp(
                    tab_id,
                    "Runtime.evaluate",
                    {"expression": "document.readyState", "returnByValue": True},
                )
                # _cdp returns the CDP response body; Runtime.evaluate shape
                # is {"result": {"type": ..., "value": ...}} — one "result"
                # hop, not two. The extra hop was always returning "" and
                # this entire lifecycle loop was running until the deadline.
                ready_state = (eval_result or {}).get("result", {}).get("value", "")

                if wait_until == "domcontentloaded" and ready_state in ("interactive", "complete"):
                    break
                elif wait_until == "load" and ready_state == "complete":
                    break
                elif wait_until == "networkidle":
                    # For networkidle, wait a bit and check again
                    await asyncio.sleep(0.1)
                    # Simple heuristic: wait until no outstanding network requests
                    # This is approximate - true network idle needs Network domain monitoring
                    if ready_state == "complete":
                        await asyncio.sleep(0.5)
                        break
                else:
                    await asyncio.sleep(0.05)

        # Get current URL and title
        url_result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        title_result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "document.title", "returnByValue": True},
        )

        resolved_url = (url_result or {}).get("result", {}).get("value", "")
        # Chrome renders DNS/connection failures at chrome-error://chromewebdata/
        # whose document.title is the bare hostname — a fabricated "success".
        # Some failures surface only here (not via errorText), so guard the URL too.
        if isinstance(resolved_url, str) and resolved_url.startswith("chrome-error://"):
            return {"ok": False, "tabId": tab_id, "error": "navigation_failed", "url": url, "resolved_url": resolved_url}

        return {
            "ok": True,
            "tabId": tab_id,
            "url": resolved_url,
            "title": (title_result or {}).get("result", {}).get("value", ""),
        }

    async def go_back(self, tab_id: int) -> dict:
        """Navigate back in history.

        Uses ``history.back()`` via Runtime.evaluate — modern Chrome CDP
        no longer exposes ``Page.goBack`` / ``Page.goForward`` (removed
        in favour of ``Page.navigateToHistoryEntry``, which requires
        first fetching the history list). ``history.back()`` is simpler
        and works across every Chrome version.
        """
        _interaction_highlights.pop(tab_id, None)
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Page.enable")
        await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "history.back()", "returnByValue": True},
        )
        # Give the browser a beat to commit the navigation before we
        # read the new URL.
        await asyncio.sleep(0.3)
        # A beforeunload handler on the current page can block the back
        # navigation with a native dialog. Surface it instead of returning
        # the original URL as if the back succeeded.
        if self._pending_dialogs.get(tab_id):
            return _pending_dialog_result(tab_id, self._pending_dialogs[tab_id], action="back")
        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        return {
            "ok": True,
            "action": "back",
            "url": (result or {}).get("result", {}).get("value", ""),
        }

    async def go_forward(self, tab_id: int) -> dict:
        """Navigate forward in history. See go_back() for why we use JS."""
        _interaction_highlights.pop(tab_id, None)
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Page.enable")
        await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "history.forward()", "returnByValue": True},
        )
        await asyncio.sleep(0.3)
        if self._pending_dialogs.get(tab_id):
            return _pending_dialog_result(tab_id, self._pending_dialogs[tab_id], action="forward")
        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        return {
            "ok": True,
            "action": "forward",
            "url": (result or {}).get("result", {}).get("value", ""),
        }

    async def reload(self, tab_id: int) -> dict:
        """Reload the page.

        Reload can trigger a native ``beforeunload`` dialog if the page has
        an unsaved-changes handler. Surface that as a structured failure
        instead of returning the pre-reload URL and leaving a stuck dialog.
        """
        _interaction_highlights.pop(tab_id, None)
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Page.enable")

        # Page.reload, like Page.navigate, does not resolve while a native
        # beforeunload dialog is open. Issue it as a task and poll for a
        # dialog concurrently rather than blocking on the await.
        reload_cmd = asyncio.ensure_future(self._cdp(tab_id, "Page.reload"))
        ack_deadline = asyncio.get_event_loop().time() + 10.0
        while not reload_cmd.done():
            pending = self._pending_dialogs.get(tab_id)
            if pending:
                reload_cmd.add_done_callback(_swallow_future_exc)
                return _pending_dialog_result(tab_id, pending, action="reload")
            if asyncio.get_event_loop().time() > ack_deadline:
                reload_cmd.add_done_callback(_swallow_future_exc)
                return {
                    "ok": False,
                    "action": "reload",
                    "error": (
                        "Reload did not start within 10s and no dialog was "
                        "detected. The page most likely has an unsaved-changes "
                        "prompt blocking it. Call browser_dialog_respond("
                        "action='accept') to clear it, then retry."
                    ),
                }
            await asyncio.sleep(0.05)
        await reload_cmd

        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        return {
            "ok": True,
            "action": "reload",
            "url": (result or {}).get("result", {}).get("value", ""),
        }

    # ── Native dialogs ─────────────────────────────────────────────────────────

    async def handle_javascript_dialog(
        self,
        tab_id: int,
        accept: bool,
        prompt_text: str | None = None,
    ) -> dict:
        """Respond to a native dialog via CDP.

        Calls ``Page.handleJavaScriptDialog``. ``accept=True`` proceeds (for
        ``beforeunload`` this discards work and leaves the page); ``accept=False``
        cancels. ``prompt_text`` only matters for ``window.prompt`` dialogs.

        Attempts the command unconditionally — it does NOT require the bridge
        to have a tracked dialog. A dialog can be open without a record (the
        event was missed, or it opened against a previous bridge instance
        before an MCP restart), and this is the recovery path for a wedged
        browser. If Chrome reports no dialog is showing, returns a clean
        ``ok=False`` instead of raising.
        """
        cdp_params: dict = {"accept": accept}
        if prompt_text is not None:
            cdp_params["promptText"] = prompt_text
        # Bypass _cdp() and its per-tab lock on purpose. A beforeunload
        # dialog blocks Page.navigate, and that navigate command holds the
        # tab lock for its full send timeout. Page.handleJavaScriptDialog
        # is the one CDP command valid to send *while* the renderer is
        # paused on a dialog — routing it through the locked _cdp() would
        # deadlock it behind the very command it needs to unblock, and the
        # _cdp() dialog-open guard would reject it outright. Send straight
        # over the bridge with a short timeout: resolving a dialog is
        # near-instant, so a hang here means the bridge itself is unhealthy.
        try:
            await self._send(
                "cdp",
                tabId=tab_id,
                method="Page.handleJavaScriptDialog",
                params=cdp_params,
                timeout=5.0,
            )
        except Exception as exc:
            msg = str(exc).lower()
            # Chrome rejects handleJavaScriptDialog when nothing is open.
            # That's not a failure of this tool — report it cleanly.
            if "no dialog" in msg or "not showing" in msg or "dialog is" in msg:
                self._pending_dialogs.pop(tab_id, None)
                return {
                    "ok": False,
                    "tab_id": tab_id,
                    "error": "No native dialog is open on this tab",
                }
            raise
        # Optimistically clear local state. CDP will also emit
        # Page.javascriptDialogClosed which clears it again — both paths
        # are idempotent.
        snapshot = self._pending_dialogs.pop(tab_id, None)
        return {"ok": True, "tab_id": tab_id, "dialog": snapshot}

    def get_pending_dialog(self, tab_id: int) -> dict | None:
        """Return the pending native dialog for ``tab_id`` or None."""
        return self._pending_dialogs.get(tab_id)

    def list_pending_dialogs(self) -> list[dict]:
        """Return all pending native dialogs across tabs as a list."""
        return [{"tab_id": tid, **info} for tid, info in self._pending_dialogs.items()]

    # ── Interaction ────────────────────────────────────────────────────────────

    async def click(
        self,
        tab_id: int,
        selector: str,
        button: str = "left",
        click_count: int = 1,
        timeout_ms: int = DEFAULT_WAIT_TIMEOUT_MS,
    ) -> dict:
        """Click an element by selector.

        ``timeout_ms`` controls how long we poll for the element to
        appear in the DOM. Defaults to :data:`DEFAULT_WAIT_TIMEOUT_MS`
        (5 s) so a missing or hallucinated selector fails fast. Pass a
        larger value when the target genuinely needs longer to render
        (e.g. post-navigation SPA hydration).

        Uses multiple fallback methods for robustness:
        1. CDP mouse events with JavaScript bounds
        2. JavaScript click() as fallback

        Inspired by browser-use's robust click implementation.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")

        # Get document and find element
        doc = await self._cdp(tab_id, "DOM.getDocument")
        root_id = doc.get("root", {}).get("nodeId")

        # Wait for element to appear. Adaptive polling:
        # - first 1 s at 50 ms intervals (responsive on fast pages)
        # - next 4 s at 200 ms
        # - rest at 500 ms
        poll_start = asyncio.get_event_loop().time()
        deadline = poll_start + timeout_ms / 1000
        node_id = None
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(tab_id, "DOM.querySelector", {"nodeId": root_id, "selector": selector})
            node_id = result.get("nodeId")
            if node_id:
                break
            await _adaptive_poll_sleep(asyncio.get_event_loop().time() - poll_start)

        if not node_id:
            # Check if the element might be inside a Shadow DOM container
            shadow_hint = ""
            try:
                shadow_check = await self.evaluate(
                    tab_id,
                    """
                    (function() {
                        var hosts = document.querySelectorAll('[id]');
                        for (var h of hosts) {
                            if (h.shadowRoot) return h.id;
                        }
                        return null;
                    })()
                """,
                )
                shadow_host = (shadow_check or {}).get("result")
                if shadow_host:
                    shadow_hint = (
                        f" The page has Shadow DOM (host: #{shadow_host}). "
                        f"Use browser_shadow_query('#{shadow_host} >>> {selector}') "
                        f"to pierce shadow roots, or browser_evaluate with manual JS traversal."
                    )
            except Exception:
                pass
            return {"ok": False, "error": f"Element not found: {selector}{shadow_hint}"}

        # Scroll into view FIRST to ensure element is rendered
        try:
            await self._cdp(
                tab_id,
                "DOM.scrollIntoViewIfNeeded",
                {"nodeId": node_id},
            )
            await asyncio.sleep(0.05)  # Wait for scroll to complete
        except Exception:
            pass  # Best effort - continue even if scroll fails

        # Get viewport dimensions for bounds checking
        viewport_script = """
            (function() {
                return {
                    width: window.innerWidth,
                    height: window.innerHeight
                };
            })();
        """
        viewport_result = await self.evaluate(tab_id, viewport_script)
        viewport = (viewport_result or {}).get("result") or {}
        viewport_width = viewport.get("width", 1920)
        viewport_height = viewport.get("height", 1080)

        # Method 1: Use JavaScript to get element bounds and click
        # This is more reliable than CDP for complex layouts
        click_script = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return {{ error: 'Element not found' }};

                // Check if element is visible
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) {{
                    return {{ error: 'Element has zero dimensions' }};
                }}

                // Check if element is within viewport
                if (rect.bottom < 0 || rect.top > {viewport_height} ||
                    rect.right < 0 || rect.left > {viewport_width}) {{
                    return {{ error: 'Element not in viewport' }};
                }}

                // Get center for metadata
                const x = rect.x + rect.width / 2;
                const y = rect.y + rect.height / 2;

                // Perform the click
                el.click();

                return {{ x: x, y: y, width: rect.width, height: rect.height }};
            }})();
        """

        try:
            result = await self.evaluate(tab_id, click_script)
            value = (result or {}).get("result")

            if isinstance(value, dict) and "error" not in value:
                # JavaScript click succeeded — highlight element
                rx = value.get("x", 0) - value.get("width", 0) / 2
                ry = value.get("y", 0) - value.get("height", 0) / 2
                await self.highlight_rect(tab_id, rx, ry, value.get("width", 0), value.get("height", 0), label=selector)
                focused_info = await self._read_focused_element(tab_id)
                resp = {
                    "ok": True,
                    "action": "click",
                    "selector": selector,
                    "x": value.get("x", 0),
                    "y": value.get("y", 0),
                    "method": "javascript",
                }
                if focused_info:
                    resp["focused_element"] = focused_info
                return resp

            # If JavaScript click failed, try CDP approach
            if isinstance(value, dict) and value.get("error"):
                logger.debug("JS click failed: %s, trying CDP", value["error"])
        except Exception as e:
            logger.debug("JS click exception: %s, trying CDP", e)

        # Method 2: CDP mouse events (fallback)
        # Get element bounds via JavaScript (more reliable than CDP getBoxModel)
        bounds_script = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {{
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    width: rect.width,
                    height: rect.height
                }};
            }})();
        """
        bounds_result = await self.evaluate(tab_id, bounds_script)
        bounds_value = (bounds_result or {}).get("result")

        if not bounds_value:
            return {"ok": False, "error": f"Could not get element bounds: {selector}"}

        x = bounds_value.get("x", 0)
        y = bounds_value.get("y", 0)

        # Clamp coordinates to viewport bounds
        x = max(0, min(viewport_width - 1, x))
        y = max(0, min(viewport_height - 1, y))

        # Dispatch mouse events with proper timing
        button_map = {"left": "left", "right": "right", "middle": "middle"}
        cdp_button = button_map.get(button, "left")

        try:
            # Move mouse to element first
            await self._cdp(
                tab_id,
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": x, "y": y},
            )
            await asyncio.sleep(0.05)

            # Mouse down — if this hangs past the short wait budget we
            # CANNOT claim success. The prior code swallowed TimeoutError
            # with `pass` and returned ok=true further down, which is why
            # the 2026-04-14 gemini session saw 7 clicks land at exactly
            # 30s with status=ok even though the click had not landed.
            try:
                await asyncio.wait_for(
                    self._cdp(
                        tab_id,
                        "Input.dispatchMouseEvent",
                        {
                            "type": "mousePressed",
                            "x": x,
                            "y": y,
                            "button": cdp_button,
                            "clickCount": click_count,
                        },
                    ),
                    timeout=2.0,
                )
            except TimeoutError:
                return {
                    "ok": False,
                    "error": (
                        f"CDP mousePressed timed out for '{selector}' — "
                        "the click did not land. Consider browser_interact "
                        "left_click with a coordinate from browser_shadow_query."
                    ),
                }

            await asyncio.sleep(0.08)

            # Mouse up — same non-silent failure handling. A stuck
            # mouseReleased means the press is still "held down" in
            # Chrome's input state; we must surface the failure so the
            # caller can retry or switch strategy.
            try:
                await asyncio.wait_for(
                    self._cdp(
                        tab_id,
                        "Input.dispatchMouseEvent",
                        {
                            "type": "mouseReleased",
                            "x": x,
                            "y": y,
                            "button": cdp_button,
                            "clickCount": click_count,
                        },
                    ),
                    timeout=3.0,
                )
            except TimeoutError:
                return {
                    "ok": False,
                    "error": (
                        f"CDP mouseReleased timed out for '{selector}' — "
                        "the press event fired but release did not. The page "
                        "may be in a stuck input state; try browser_interact "
                        "left_click with a coordinate."
                    ),
                }

            w = bounds_value.get("width", 0)
            h = bounds_value.get("height", 0)
            await self.highlight_rect(tab_id, x - w / 2, y - h / 2, w, h, label=selector)
            focused_info = await self._read_focused_element(tab_id)
            resp = {
                "ok": True,
                "action": "click",
                "selector": selector,
                "x": x,
                "y": y,
                "method": "cdp",
            }
            if focused_info:
                resp["focused_element"] = focused_info
            return resp

        except Exception as e:
            return {"ok": False, "error": f"Click failed: {e}"}

    async def _read_focused_element(self, tab_id: int) -> dict | None:
        """Read document.activeElement and return a compact descriptor.

        The JS returns ``rect`` fields in CSS px (they come straight
        from ``getBoundingClientRect``). We convert them to fractions
        of the viewport here so the agent sees a rect in the same
        coord space it passed to click / hover / press_at.

        Returns None on any failure — never raises.
        """
        try:
            await self._try_enable_domain(tab_id, "Runtime")
            result = await self.evaluate(tab_id, _FOCUSED_ELEMENT_JS)
            info = (result or {}).get("result")
            if info and isinstance(info, dict) and isinstance(info.get("rect"), dict):
                from .tools.inspection import _viewport_sizes

                vp = _viewport_sizes.get(tab_id)
                if vp and vp[0] > 0 and vp[1] > 0:
                    cw, ch = float(vp[0]), float(vp[1])
                    r = info["rect"]
                    info["rect"] = {
                        "x": round(r.get("x", 0) / cw, 4),
                        "y": round(r.get("y", 0) / ch, 4),
                        "width": round(r.get("width", 0) / cw, 4),
                        "height": round(r.get("height", 0) / ch, 4),
                    }
                else:
                    # Degraded: cache missing (no screenshot taken
                    # yet). Leave rect in CSS px and flag it so the
                    # agent can tell.
                    info["rectSpace"] = "css"
            return info
        except Exception:
            return None

    async def click_coordinate(self, tab_id: int, x: float, y: float, button: str = "left", click_count: int = 1) -> dict:
        """Click at specific coordinates.

        ``click_count`` >= 2 produces a native double / triple click —
        the same single press/release pair with an elevated
        ``clickCount``, matching how :meth:`click` handles multi-click.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")

        button_map = {"left": "left", "right": "right", "middle": "middle"}
        cdp_button = button_map.get(button, "left")

        logger.info(
            "click_coordinate tab=%d: x=%.1f, y=%.1f → CDP Input.dispatchMouseEvent",
            tab_id,
            x,
            y,
        )

        # Pre-click hit probe — log the element actually under (x, y)
        # right before the dispatch so we can compare intended vs
        # actual landing for the y-offset hunt. Best-effort, never
        # blocks the click.
        hit_probe = None
        try:
            # `return` prefix ensures evaluate() wraps as
            # `(function(){ return (...)(x,y) })()` and the value
            # actually comes back — without it the wrapper drops
            # the result on the floor (returns undefined).
            probe_result = await self.evaluate(tab_id, f"return ({_HIT_ELEMENT_JS})({x}, {y})")
            hit_probe = (probe_result or {}).get("result")
        except Exception:
            hit_probe = None

        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": cdp_button, "clickCount": click_count},
        )
        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": cdp_button, "clickCount": click_count},
        )

        await self.highlight_point(tab_id, x, y, label=f"click ({x},{y})")

        focused_info = await self._read_focused_element(tab_id)
        resp = {"ok": True, "action": "click_coordinate", "x": x, "y": y}
        if focused_info:
            resp["focused_element"] = focused_info

        # Telemetry side-channel: record where the click actually
        # landed so we can audit the y-axis offset. Kept out of the
        # response payload to avoid bloating what the agent sees.
        if hit_probe is not None:
            try:
                from .telemetry import write_log

                write_log(
                    {
                        "type": "click_hit_probe",
                        "tab_id": tab_id,
                        "intended": {"x": x, "y": y},
                        "viewport": hit_probe.get("viewport"),
                        "hit": hit_probe.get("hit"),
                        "stack": hit_probe.get("stack"),
                        "sweep": hit_probe.get("sweep"),
                        "offsetInRect": hit_probe.get("offsetInRect"),
                    }
                )
            except Exception:
                pass
        return resp

    async def type_text(
        self,
        tab_id: int,
        selector: str | None,
        text: str,
        clear_first: bool = True,
        delay_ms: int = 1,
        timeout_ms: int = 30000,
        use_insert_text: bool = True,
    ) -> dict:
        """Type text into an element.

        Routes through a real CDP pointer click on the target rect BEFORE
        inserting text. This is critical for rich-text editors (Draft.js,
        Lexical, ProseMirror, React-controlled contenteditable): those
        frameworks only register input as "real" after seeing a native
        focus event sourced from a real pointer interaction — a
        JS-sourced ``el.focus()`` is ignored, and the submit button
        stays disabled because the framework's internal state never
        updates. Sending a CDP click first fires the real
        pointerdown/pointerup/click/focus sequence that every modern
        framework listens to.

        After clicking, we insert text via ``Input.insertText`` by
        default (``use_insert_text=True``). insertText is a dedicated
        CDP method that asks the browser to commit text into the
        focused element as if IME just committed it — it works
        cleanly on rich editors where per-character keyDown events
        would otherwise be eaten or mis-timed (empirically verified
        against LinkedIn's Lexical message composer 2026-04-11).
        Playwright uses the same approach under the hood.

        Set ``use_insert_text=False`` to get the old per-character
        keyDown/keyUp path when an editor needs precise keystroke
        timing (autocomplete triggers, code editors that fire on
        specific chars, ``delay_ms`` typing animations).
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")
        await self._try_enable_domain(tab_id, "Runtime")

        if selector is not None:
            # Find + scroll + (optionally) clear via JS. We still need the
            # rect, and clearing via `.value = ''` / `.textContent = ''`
            # is the most reliable way to reset pre-existing content.
            focus_script = f"""
                (function() {{
                    const el = document.querySelector({json.dumps(selector)});
                    if (!el) return null;

                    // Scroll into view so the click lands in-viewport.
                    el.scrollIntoView({{ block: 'center' }});

                    // Clear if requested.
                    if ({str(clear_first).lower()}) {{
                        if (el.value !== undefined) {{
                            el.value = '';
                            // Nudge React's onChange — the framework reads
                            // .value via a setter hook, and without firing
                            // an input event the component state remains
                            // stale after our value assignment.
                            el.dispatchEvent(new Event('input', {{bubbles: true}}));
                        }} else if (el.isContentEditable) {{
                            el.textContent = '';
                            el.dispatchEvent(new Event('input', {{bubbles: true}}));
                        }}
                    }}

                    const r = el.getBoundingClientRect();
                    return {{
                        x: r.left + r.width / 2,
                        y: r.top + r.height / 2,
                        w: r.width,
                        h: r.height,
                    }};
                }})();
            """

            focus_result = await self.evaluate(tab_id, focus_script)
            rect = (focus_result or {}).get("result")

            if not rect:
                # Element not found — wait + retry until timeout.
                deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
                while asyncio.get_event_loop().time() < deadline:
                    result = await self.evaluate(tab_id, focus_script)
                    rect = (result or {}).get("result") if result else None
                    if rect:
                        break
                    await asyncio.sleep(0.1)

                if not rect:
                    return {"ok": False, "error": f"Element not found: {selector}"}

            if not rect.get("w") or not rect.get("h"):
                return {
                    "ok": False,
                    "error": f"Element has zero dimensions, can't click to focus: {selector}",
                }

            # Fire a real CDP pointer click at the element's center. This is
            # what unblocks rich-text editors — JS el.focus() is not enough.
            click_x = rect["x"]
            click_y = rect["y"]
            await self._cdp(
                tab_id,
                "Input.dispatchMouseEvent",
                {"type": "mousePressed", "x": click_x, "y": click_y, "button": "left", "clickCount": 1},
            )
            await self._cdp(
                tab_id,
                "Input.dispatchMouseEvent",
                {"type": "mouseReleased", "x": click_x, "y": click_y, "button": "left", "clickCount": 1},
            )
            await asyncio.sleep(0.15)  # Let focus / editor-init animations settle.
        else:
            # No selector — assume the caller already focused the target
            # element (e.g. via a browser_interact coordinate click). Just clear the
            # active element if requested, then insert text directly.
            if clear_first:
                await self.evaluate(
                    tab_id,
                    """
                    (function() {
                        const el = document.activeElement;
                        if (!el) return;
                        if (el.value !== undefined) {
                            el.value = '';
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        } else if (el.isContentEditable) {
                            el.textContent = '';
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        }
                    })();
                """,
                )

        if use_insert_text and delay_ms <= 0:
            # CDP Input.insertText is the most reliable way to insert
            # text into a rich-text editor. It bypasses the keyboard
            # event pipeline entirely and commits text into the focused
            # element as if IME just committed it. Works on plain
            # <input>/<textarea>, contenteditable, Lexical, Draft.js,
            # ProseMirror, Monaco textarea buffers — verified empirically
            # against LinkedIn's message composer (Lexical) on 2026-04-11
            # where the per-char keyDown path left the editor empty.
            await self._cdp(tab_id, "Input.insertText", {"text": text})
        else:
            # Fallback path: per-character keyDown/keyUp with full key,
            # code, and text fields. Used when the caller explicitly
            # wants per-keystroke dispatch (autocomplete testing, code
            # editors that fire on specific chars, animated typing
            # with ``delay_ms``). Populating ``code`` for ASCII is
            # needed so frameworks that branch on ``event.code`` see
            # the right values.
            for char in text:
                key_params: dict[str, Any] = {
                    "type": "keyDown",
                    "text": char,
                    "key": char,
                }
                if len(char) == 1 and char.isalpha():
                    key_params["code"] = f"Key{char.upper()}"
                elif len(char) == 1 and char.isdigit():
                    key_params["code"] = f"Digit{char}"
                await self._cdp(tab_id, "Input.dispatchKeyEvent", key_params)

                key_up = {"type": "keyUp", "key": char}
                if "code" in key_params:
                    key_up["code"] = key_params["code"]
                await self._cdp(tab_id, "Input.dispatchKeyEvent", key_up)
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000)

        # Highlight the element that was typed into
        if selector is not None:
            rect_result = await self.evaluate(
                tab_id,
                f"(function(){{const el=document.querySelector("
                f"{json.dumps(selector)});if(!el)return null;"
                f"const r=el.getBoundingClientRect();"
                f"return{{x:r.left,y:r.top,w:r.width,h:r.height}};}})()",
            )
            rect = (rect_result or {}).get("result")
            if rect:
                await self.highlight_rect(tab_id, rect["x"], rect["y"], rect["w"], rect["h"], label=selector)
        else:
            # Highlight the active element when no selector was provided.
            # Drill into same-origin iframes to find the real focused
            # element — the top-level activeElement may be a full-screen
            # iframe whose rect covers the entire viewport.
            rect_result = await self.evaluate(
                tab_id,
                "(function(){"
                "var el=document.activeElement;"
                "try{while(el&&el.tagName==='IFRAME'&&el.contentDocument){"
                "el=el.contentDocument.activeElement;"
                "}}catch(e){}"
                "if(!el||el===document.body||el===document.documentElement)return null;"
                "const r=el.getBoundingClientRect();"
                "return{x:r.left,y:r.top,w:r.width,h:r.height};})()",
            )
            rect = (rect_result or {}).get("result")
            if rect:
                await self.highlight_rect(tab_id, rect["x"], rect["y"], rect["w"], rect["h"], label="active element", border_style="dashed")
        return {"ok": True, "action": "type", "selector": selector, "length": len(text)}

    # CDP Input.dispatchKeyEvent modifiers bitmask.
    _CDP_MODIFIERS = {"alt": 1, "ctrl": 2, "control": 2, "meta": 4, "cmd": 4, "shift": 8}

    # How Chrome expects each modifier key as its OWN keyDown event —
    # name, code, and Windows virtual key code. Dispatched before the
    # main key so Chrome sees the modifier as "held" during the main
    # event, which is what actually triggers browser shortcuts like
    # Ctrl+A, Cmd+L, Shift+Tab.
    _MODIFIER_KEYS = {
        "alt": {"key": "Alt", "code": "AltLeft", "windowsVirtualKeyCode": 18},
        "ctrl": {"key": "Control", "code": "ControlLeft", "windowsVirtualKeyCode": 17},
        "control": {"key": "Control", "code": "ControlLeft", "windowsVirtualKeyCode": 17},
        "meta": {"key": "Meta", "code": "MetaLeft", "windowsVirtualKeyCode": 91},
        "cmd": {"key": "Meta", "code": "MetaLeft", "windowsVirtualKeyCode": 91},
        "shift": {"key": "Shift", "code": "ShiftLeft", "windowsVirtualKeyCode": 16},
    }

    def _cdp_modifier_mask(self, modifiers: list[str] | None) -> int:
        if not modifiers:
            return 0
        mask = 0
        for m in modifiers:
            mask |= self._CDP_MODIFIERS.get(m.lower(), 0)
        return mask

    async def press_key(
        self,
        tab_id: int,
        key: str,
        selector: str | None = None,
        modifiers: list[str] | None = None,
    ) -> dict:
        """Press a keyboard key, optionally with modifier keys held.

        Args:
            key: Key name like 'Enter', 'Tab', 'Escape', 'ArrowDown', etc.
            selector: Optional selector to focus first
            modifiers: Optional list of modifier keys to hold while pressing
                ``key``. Accepted values: "alt", "ctrl"/"control", "meta"/"cmd",
                "shift". Example: ``modifiers=["ctrl"]`` → Ctrl+key, which
                enables shortcuts like Ctrl+A, Ctrl+L, Cmd+Enter, Shift+Tab.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "Input")

        if selector:
            doc = await self._cdp(tab_id, "DOM.getDocument")
            root_id = doc.get("root", {}).get("nodeId")
            result = await self._cdp(tab_id, "DOM.querySelector", {"nodeId": root_id, "selector": selector})
            node_id = result.get("nodeId")
            if node_id:
                await self._cdp(tab_id, "DOM.focus", {"nodeId": node_id})

        # Key definitions for special keys
        key_map = {
            "Enter": ("\r", "Enter"),
            "Tab": ("\t", "Tab"),
            "Escape": ("\x1b", "Escape"),
            "Backspace": ("\b", "Backspace"),
            "Delete": ("\x7f", "Delete"),
            "ArrowUp": ("", "ArrowUp"),
            "ArrowDown": ("", "ArrowDown"),
            "ArrowLeft": ("", "ArrowLeft"),
            "ArrowRight": ("", "ArrowRight"),
            "Home": ("", "Home"),
            "End": ("", "End"),
            "PageUp": ("", "PageUp"),
            "PageDown": ("", "PageDown"),
        }

        text, key_name = key_map.get(key, (key, key))
        mod_mask = self._cdp_modifier_mask(modifiers)

        # With modifiers held, suppress the printable text so that
        # e.g. Ctrl+A doesn't also type the character "a" into the
        # focused field (CDP will still fire the shortcut).
        effective_text = text if (text and mod_mask == 0) else None

        # Compute ``code`` and ``windowsVirtualKeyCode`` for the main
        # key. These are MANDATORY for Chrome's shortcut dispatcher —
        # without them, Ctrl+A etc. reach the DOM with ``code=""`` and
        # ``which=0`` and Chrome doesn't recognise them as shortcuts.
        # Verified empirically on chrome 131 against a real input.
        main_code: str | None = None
        main_vk: int | None = None
        special_vk = {
            "Enter": (13, "Enter"),
            "Tab": (9, "Tab"),
            "Escape": (27, "Escape"),
            "Backspace": (8, "Backspace"),
            "Delete": (46, "Delete"),
            "ArrowUp": (38, "ArrowUp"),
            "ArrowDown": (40, "ArrowDown"),
            "ArrowLeft": (37, "ArrowLeft"),
            "ArrowRight": (39, "ArrowRight"),
            "Home": (36, "Home"),
            "End": (35, "End"),
            "PageUp": (33, "PageUp"),
            "PageDown": (34, "PageDown"),
        }
        if key_name in special_vk:
            main_vk, main_code = special_vk[key_name]
        elif len(key_name) == 1 and key_name.isalpha():
            main_code = f"Key{key_name.upper()}"
            main_vk = ord(key_name.upper())  # 'A' = 65 ... 'Z' = 90
        elif len(key_name) == 1 and key_name.isdigit():
            main_code = f"Digit{key_name}"
            main_vk = ord(key_name)  # '0' = 48 ... '9' = 57

        # Press each modifier as a separate keyDown BEFORE the main
        # key. Sending ``modifiers: mask`` on the main key alone isn't
        # enough — Chrome's shortcut dispatcher looks for a held
        # modifier event, not just a flag. Matches the Playwright /
        # Puppeteer sequence. Release modifiers in reverse order after
        # the main key so the "held" state is correct throughout.
        pressed_mods: list[dict] = []
        if modifiers:
            for m in modifiers:
                spec = self._MODIFIER_KEYS.get(m.lower())
                if spec is None:
                    continue
                await self._cdp(
                    tab_id,
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyDown",
                        "key": spec["key"],
                        "code": spec["code"],
                        "windowsVirtualKeyCode": spec["windowsVirtualKeyCode"],
                        "modifiers": mod_mask,
                    },
                )
                pressed_mods.append(spec)

        main_down: dict[str, Any] = {
            # Use rawKeyDown when a modifier is held so Chrome skips
            # text insertion and routes the event to the shortcut
            # dispatcher. For plain press_key without modifiers we can
            # use regular keyDown.
            "type": "rawKeyDown" if mod_mask else "keyDown",
            "key": key_name,
            "text": effective_text,
            "modifiers": mod_mask,
        }
        main_up: dict[str, Any] = {
            "type": "keyUp",
            "key": key_name,
            "text": effective_text,
            "modifiers": mod_mask,
        }
        if main_code is not None:
            main_down["code"] = main_code
            main_up["code"] = main_code
        if main_vk is not None:
            main_down["windowsVirtualKeyCode"] = main_vk
            main_up["windowsVirtualKeyCode"] = main_vk

        await self._cdp(tab_id, "Input.dispatchKeyEvent", main_down)
        await self._cdp(tab_id, "Input.dispatchKeyEvent", main_up)

        # Release modifiers in reverse order.
        for spec in reversed(pressed_mods):
            await self._cdp(
                tab_id,
                "Input.dispatchKeyEvent",
                {
                    "type": "keyUp",
                    "key": spec["key"],
                    "code": spec["code"],
                    "windowsVirtualKeyCode": spec["windowsVirtualKeyCode"],
                    "modifiers": 0,
                },
            )

        return {"ok": True, "action": "press", "key": key, "modifiers": modifiers or []}

    # Shared JS snippet: shadow-piercing querySelector via ">>>" separator
    _SHADOW_QUERY_JS = """
        function _shadowQuery(sel) {
            const parts = sel.split('>>>').map(s => s.trim());
            let node = document;
            for (const part of parts) {
                if (!node) return null;
                node = (node.shadowRoot || node).querySelector(part);
            }
            return node;
        }
    """

    async def shadow_query(self, tab_id: int, selector: str) -> dict:
        """querySelector that pierces shadow roots using '>>>' separator.

        Returns CSS-pixel getBoundingClientRect of the matched element.
        Example: '#interop-outlet >>> #ember37 >>> p'
        """
        await self.cdp_attach(tab_id)
        # IMPORTANT: the whole script must be a single IIFE so that
        # bridge.evaluate() detects it as "already wrapped" and returns
        # its value. If you let evaluate() re-wrap a script that
        # starts with a function declaration, the outer wrapper
        # discards the inner IIFE's return and you always get None —
        # which is exactly the bug this code had until 2026-04-11.
        script = (
            f"(function(){{"
            f"{self._SHADOW_QUERY_JS}"
            f"const el=_shadowQuery({json.dumps(selector)});"
            f"if(!el)return null;"
            f"const r=el.getBoundingClientRect();"
            f"return{{found:true,tag:el.tagName,x:r.left,y:r.top,w:r.width,h:r.height,"
            f"cx:r.left+r.width/2,cy:r.top+r.height/2}};"
            f"}})()"
        )
        result = await self.evaluate(tab_id, script)
        rect = (result or {}).get("result")
        if not rect:
            return {"ok": False, "error": f"Element not found: {selector}"}
        return {"ok": True, "selector": selector, "rect": rect}

    async def hover(self, tab_id: int, selector: str, timeout_ms: int = 30000) -> dict:
        """Hover over an element. Supports '>>>' shadow-piercing selectors.

        Uses JavaScript for bounds (more reliable than CDP getBoxModel).
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")
        await self._try_enable_domain(tab_id, "Runtime")

        # Use JavaScript to scroll into view and get bounds
        # Supports ">>>" shadow-piercing selectors
        if ">>>" in selector:
            query_fn = f"{self._SHADOW_QUERY_JS} _shadowQuery({json.dumps(selector)})"
        else:
            query_fn = f"document.querySelector({json.dumps(selector)})"

        hover_script = f"""
            (function() {{
                const el = {query_fn};
                if (!el) return null;
                el.scrollIntoView({{ block: 'center' }});
                const rect = el.getBoundingClientRect();
                return {{
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    width: rect.width,
                    height: rect.height
                }};
            }})();
        """

        # Wait for element and get bounds
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        bounds_value = None

        while asyncio.get_event_loop().time() < deadline:
            result = await self.evaluate(tab_id, hover_script)
            bounds_value = (result or {}).get("result")
            if bounds_value:
                break
            await asyncio.sleep(0.1)

        if not bounds_value:
            return {"ok": False, "error": f"Element not found: {selector}"}

        x = bounds_value.get("x", 0)
        y = bounds_value.get("y", 0)

        if x == 0 and y == 0:
            return {"ok": False, "error": f"Element has zero dimensions: {selector}"}

        await asyncio.sleep(0.05)  # Wait for scroll

        # Dispatch mouse moved event
        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y},
        )

        w = bounds_value.get("width", 0)
        h = bounds_value.get("height", 0)
        await self.highlight_rect(tab_id, x - w / 2, y - h / 2, w, h, label=selector)
        return {"ok": True, "action": "hover", "selector": selector, "x": x, "y": y}

    async def hover_coordinate(self, tab_id: int, x: float, y: float) -> dict:
        """Hover at CSS pixel coordinates.

        Works for overlay/virtual-rendered content where CSS selectors fail.
        Dispatches a mouseMoved event at (x, y) without needing a DOM element.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")
        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y, "buttons": 0},
        )
        await self.highlight_point(tab_id, x, y, label=f"hover ({x},{y})")
        return {"ok": True, "action": "hover_coordinate", "x": x, "y": y}

    async def press_key_at(self, tab_id: int, x: float, y: float, key: str) -> dict:
        """Move mouse to (x, y) then dispatch a key event.

        Useful for overlays where a selector/focused key press misses because document.activeElement
        is in the regular DOM while the focused element is in virtual/overlay rendering.
        Moving the mouse first routes the key event through the browser's native
        hit-testing rather than the DOM focus chain.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")

        # Move mouse into position so the browser's native focus follows
        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y, "buttons": 0},
        )

        key_map = {
            "Enter": ("\r", "Enter"),
            "Tab": ("\t", "Tab"),
            "Escape": ("\x1b", "Escape"),
            "Backspace": ("\b", "Backspace"),
            "Delete": ("\x7f", "Delete"),
            "ArrowUp": ("", "ArrowUp"),
            "ArrowDown": ("", "ArrowDown"),
            "ArrowLeft": ("", "ArrowLeft"),
            "ArrowRight": ("", "ArrowRight"),
            "Home": ("", "Home"),
            "End": ("", "End"),
            "Space": (" ", " "),
            " ": (" ", " "),
        }
        text, key_name = key_map.get(key, (key, key))

        await self._cdp(
            tab_id,
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": key_name, "text": text or None},
        )
        await self._cdp(
            tab_id,
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": key_name, "text": text or None},
        )

        await self.highlight_point(tab_id, x, y, label=f"{key} ({x},{y})")
        return {"ok": True, "action": "press_at", "x": x, "y": y, "key": key}

    # Duration (ms) that injected highlights stay visible before fading.
    # Bumped from 1500 → 10000 so the overlay outlives typical agent turn
    # latency (LLM streaming + tool batching often runs 3-8s). With the
    # old 1.5s lifetime the overlay was already gone by the time the
    # next ``browser_screenshot`` fired, which is why it looked "flaky".
    _HIGHLIGHT_DURATION_MS = 10000

    async def highlight_rect(
        self,
        tab_id: int,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str = "",
        color: dict | None = None,
        border_style: str = "solid",
    ) -> None:
        """Inject a visible highlight overlay into the page DOM.

        Creates a fixed-position div with border, background tint, and an
        optional label tag.  The element fades out after ``_HIGHLIGHT_DURATION_MS``
        and removes itself.  Much more visible than the CDP Overlay API.
        """
        fill = color or {"r": 59, "g": 130, "b": 246, "a": 0.18}
        border_rgb = f"rgb({fill['r']},{fill['g']},{fill['b']})"
        bg_rgba = f"rgba({fill['r']},{fill['g']},{fill['b']},{fill.get('a', 0.18)})"
        duration = self._HIGHLIGHT_DURATION_MS

        # Escape label for safe injection
        safe_label = json.dumps(label[:60]) if label else '""'

        js = f"""
        (function() {{
          // Remove any previous hive highlight (including its observer).
          var prev = document.getElementById('__hive_hl');
          if (prev) {{
            try {{ prev.__hiveStop && prev.__hiveStop(); }} catch(e) {{}}
            prev.remove();
          }}

          var box = document.createElement('div');
          box.id = '__hive_hl';
          box.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;'
            + 'left:{int(x)}px;top:{int(y)}px;width:{max(1, int(w))}px;height:{max(1, int(h))}px;'
            + 'border:2px {border_style} {border_rgb};background:{bg_rgba};'
            + 'border-radius:3px;transition:opacity 0.4s ease;opacity:1;'
            + 'box-shadow:0 0 8px {bg_rgba};';

          var lbl = {safe_label};
          if (lbl) {{
            var tag = document.createElement('span');
            tag.textContent = lbl;
            tag.style.cssText = 'position:absolute;left:0;top:-20px;'
              + 'background:{border_rgb};color:#fff;font:bold 11px/16px system-ui;'
              + 'padding:1px 6px;border-radius:3px;white-space:nowrap;max-width:200px;'
              + 'overflow:hidden;text-overflow:ellipsis;';
            box.appendChild(tag);
          }}

          var parent = document.documentElement;
          parent.appendChild(box);

          // SPA re-mount protection: some frameworks (React/Vue/etc.) and
          // some host pages run MutationObservers that strip unknown
          // children from documentElement. Watch for our box being
          // removed and re-attach it — but cap the retries so we don't
          // get into a DOM-thrash loop with a hostile host observer.
          var stopped = false;
          var retries = 0;
          var MAX_RETRIES = 5;
          var obs = new MutationObserver(function() {{
            if (stopped) return;
            if (!document.getElementById('__hive_hl')) {{
              if (retries >= MAX_RETRIES) {{
                stopped = true;
                try {{ obs.disconnect(); }} catch(e) {{}}
                return;
              }}
              retries++;
              try {{ parent.appendChild(box); }} catch(e) {{}}
            }}
          }});
          try {{ obs.observe(parent, {{childList:true, subtree:false}}); }} catch(e) {{}}
          box.__hiveStop = function() {{
            stopped = true;
            try {{ obs.disconnect(); }} catch(e) {{}}
          }};

          setTimeout(function() {{
            if (box.isConnected) box.style.opacity = '0';
          }}, {duration});
          setTimeout(function() {{
            stopped = true;
            try {{ obs.disconnect(); }} catch(e) {{}}
            box.remove();
          }}, {duration + 500});
        }})();
        """
        try:
            await self.cdp_attach(tab_id)
            await self.evaluate(tab_id, js)
        except Exception as exc:
            # Best-effort visual feedback, but log rather than silently
            # swallow so we can diagnose CSP / mid-navigation failures.
            logger.debug("highlight_rect injection failed on tab %d: %s", tab_id, exc)

        _interaction_highlights[tab_id] = {
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "label": label,
            "kind": "rect",
        }

    async def highlight_point(self, tab_id: int, x: float, y: float, label: str = "") -> None:
        """Highlight a coordinate with a pulsing dot and crosshair."""
        duration = self._HIGHLIGHT_DURATION_MS
        safe_label = json.dumps(label[:60]) if label else '""'

        js = f"""
        (function() {{
          var prev = document.getElementById('__hive_hl');
          if (prev) {{
            try {{ prev.__hiveStop && prev.__hiveStop(); }} catch(e) {{}}
            prev.remove();
          }}

          var dot = document.createElement('div');
          dot.id = '__hive_hl';
          dot.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;'
            + 'left:{int(x) - 8}px;top:{int(y) - 8}px;width:16px;height:16px;'
            + 'border-radius:50%;background:rgba(239,68,68,0.7);'
            + 'box-shadow:0 0 0 4px rgba(239,68,68,0.25),0 0 12px rgba(239,68,68,0.4);'
            + 'transition:opacity 0.4s ease;opacity:1;';

          var lbl = {safe_label};
          if (lbl) {{
            var tag = document.createElement('span');
            tag.textContent = lbl;
            tag.style.cssText = 'position:absolute;left:20px;top:-4px;'
              + 'background:rgba(239,68,68,0.9);color:#fff;font:bold 11px/16px system-ui;'
              + 'padding:1px 6px;border-radius:3px;white-space:nowrap;';
            dot.appendChild(tag);
          }}

          var parent = document.documentElement;
          parent.appendChild(dot);

          // SPA re-mount protection — see highlight_rect comment.
          var stopped = false;
          var retries = 0;
          var MAX_RETRIES = 5;
          var obs = new MutationObserver(function() {{
            if (stopped) return;
            if (!document.getElementById('__hive_hl')) {{
              if (retries >= MAX_RETRIES) {{
                stopped = true;
                try {{ obs.disconnect(); }} catch(e) {{}}
                return;
              }}
              retries++;
              try {{ parent.appendChild(dot); }} catch(e) {{}}
            }}
          }});
          try {{ obs.observe(parent, {{childList:true, subtree:false}}); }} catch(e) {{}}
          dot.__hiveStop = function() {{
            stopped = true;
            try {{ obs.disconnect(); }} catch(e) {{}}
          }};

          setTimeout(function() {{
            if (dot.isConnected) dot.style.opacity = '0';
          }}, {duration});
          setTimeout(function() {{
            stopped = true;
            try {{ obs.disconnect(); }} catch(e) {{}}
            dot.remove();
          }}, {duration + 500});
        }})();
        """
        try:
            await self.cdp_attach(tab_id)
            await self.evaluate(tab_id, js)
        except Exception as exc:
            logger.debug("highlight_point injection failed on tab %d: %s", tab_id, exc)

        _interaction_highlights[tab_id] = {
            "x": x,
            "y": y,
            "w": 0,
            "h": 0,
            "label": label,
            "kind": "point",
        }

    async def clear_highlight(self, tab_id: int) -> None:
        """Remove the injected highlight from the page."""
        try:
            await self.evaluate(
                tab_id,
                """
                var el = document.getElementById('__hive_hl');
                if (el) el.remove();
            """,
            )
        except Exception:
            pass
        _interaction_highlights.pop(tab_id, None)

    async def scroll(
        self,
        tab_id: int,
        direction: str = "down",
        amount: int = 500,
        selector: str | None = None,
    ) -> dict:
        """Scroll the page or a specific scrollable container.

        If ``selector`` is given, scroll that element directly (supports
        '>>>' shadow-piercing selectors). Otherwise pick a container with
        a direction-aware heuristic that prefers the visible scroll area
        at the viewport center, falling back to the largest visible
        scrollable element, then to ``window.scrollBy``.

        Scrolls larger than one step (~240px) are chunked into many
        small ``scrollBy`` calls with short randomized delays between
        them, so lazy-loading sites (LinkedIn, X/Twitter, infinite
        feeds) get a chance to fire their IntersectionObservers and
        load the next batch as content enters the viewport.

        The inter-step delay runs on the Python side via ``asyncio.sleep``.
        Doing the wait inside the page (``setTimeout``) breaks on
        backgrounded tabs: Chrome clamps timers to 1Hz after ~10s of
        backgrounding and to 1/min under intensive throttling, which
        turned a sub-second scroll into multi-minute hangs that only
        resolved when the user manually foregrounded the tab. Driving
        from Python costs one extra CDP round-trip per step but isn't
        gated on tab visibility. Returns ``steps`` in the result for
        visibility.
        """
        delta_x = 0
        delta_y = 0
        if direction == "down":
            delta_y = amount
        elif direction == "up":
            delta_y = -amount
        elif direction == "right":
            delta_x = amount
        elif direction == "left":
            delta_x = -amount

        # Direction axis: only consider candidates that can actually scroll
        # along the requested axis. 'y' for up/down, 'x' for left/right.
        axis = "y" if direction in ("up", "down") else "x"

        selector_json = json.dumps(selector) if selector else "null"

        # Phase 1 — resolve the scroll container and install a closure on
        # window that captures it. Subsequent step calls (one CDP evaluate
        # each) invoke window.__gcuScrollStep(dx, dy) without re-resolving.
        # NOTE: Do NOT wrap in IIFE — evaluate() already wraps scripts.
        resolve_script = f"""
            {self._SHADOW_QUERY_JS}

            const axis = {json.dumps(axis)};
            const userSelector = {selector_json};

            function canScroll(el) {{
                if (!el || el.nodeType !== 1) return false;
                if (el === document.scrollingElement || el === document.documentElement || el === document.body) {{
                    return axis === 'y'
                        ? document.documentElement.scrollHeight > window.innerHeight + 1
                        : document.documentElement.scrollWidth > window.innerWidth + 1;
                }}
                const style = getComputedStyle(el);
                if (style.visibility === 'hidden' || style.display === 'none') return false;
                const overflow = axis === 'y'
                    ? (style.overflowY + style.overflow)
                    : (style.overflowX + style.overflow);
                if (!/auto|scroll|overlay/.test(overflow)) return false;
                return axis === 'y'
                    ? el.scrollHeight > el.clientHeight + 1
                    : el.scrollWidth > el.clientWidth + 1;
            }}

            function findScrollableAncestor(el) {{
                let node = el;
                while (node && node !== document.body && node !== document.documentElement) {{
                    if (canScroll(node)) return node;
                    node = node.parentElement;
                }}
                return null;
            }}

            let target = null;
            let method = '';
            let tag = '';

            // 1. Explicit selector wins
            if (userSelector) {{
                const el = userSelector.includes('>>>')
                    ? _shadowQuery(userSelector)
                    : document.querySelector(userSelector);
                if (!el) {{
                    return {{ success: false, error: 'selector_not_found', selector: userSelector }};
                }}
                if (!canScroll(el)) {{
                    return {{ success: false, error: 'not_scrollable_in_direction',
                             selector: userSelector, axis: axis, tag: el.tagName }};
                }}
                target = el; method = 'selector'; tag = el.tagName;
            }} else {{
                // 2. Prefer the scrollable ancestor at the viewport center —
                //    a much better proxy for "what the agent is looking at"
                //    than "largest element on the page."
                const cx = window.innerWidth / 2;
                const cy = window.innerHeight / 2;
                const elAtCenter = document.elementFromPoint(cx, cy);
                const centerHit = findScrollableAncestor(elAtCenter);
                if (centerHit) {{
                    target = centerHit; method = 'viewport-center'; tag = centerHit.tagName;
                }} else {{
                    // 3. Fallback: largest visible scrollable element on the
                    //    correct axis. Filters out hidden/offscreen drawers and
                    //    elements that scroll the wrong way.
                    const candidates = [];
                    for (const el of document.querySelectorAll('*')) {{
                        if (!canScroll(el)) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.width < 50 || rect.height < 50) continue;
                        if (rect.bottom <= 0 || rect.top >= window.innerHeight) continue;
                        if (rect.right <= 0 || rect.left >= window.innerWidth) continue;
                        candidates.push({{ el: el, area: rect.width * rect.height }});
                    }}
                    candidates.sort((a, b) => b.area - a.area);
                    if (candidates.length > 0) {{
                        target = candidates[0].el; method = 'largest-visible'; tag = target.tagName;
                    }} else {{
                        // 4. Last resort: window scroll
                        target = window; method = 'window'; tag = 'WINDOW';
                    }}
                }}
            }}

            // Closure captures the resolved target. Subsequent step calls
            // reference window.__gcuScrollStep so the same container is
            // hit without re-resolving, and the inter-step delay can live
            // on the Python side (immune to setTimeout throttling).
            window.__gcuScrollStep = function(dx, dy) {{
                try {{ target.scrollBy({{ top: dy, left: dx, behavior: 'instant' }}); return true; }}
                catch (e) {{ return false; /* navigated / detached */ }}
            }};

            return {{ success: true, method, tag }};
        """

        # Stepping parameters — kept in sync with the previous JS values so
        # the human-like cadence is preserved.
        STEP_PX = 240
        STEP_VAR = 60  # 180–300px per step
        DELAY_MS = 28
        DELAY_VAR = 18  # 10–46ms between steps

        try:
            async with asyncio.timeout(30.0):
                # Phase 1: resolve.
                resolve = await self.evaluate(tab_id, resolve_script)
                value = (resolve or {}).get("result") or {}

                if not value.get("success"):
                    err = value.get("error") or "scroll script returned failure"
                    if err == "selector_not_found":
                        return {"ok": False, "error": f"Element not found: {value.get('selector')}"}
                    if err == "not_scrollable_in_direction":
                        return {
                            "ok": False,
                            "error": (f"Element {value.get('tag')} ({value.get('selector')}) is not scrollable along the {value.get('axis')} axis"),
                        }
                    return {"ok": False, "error": err}

                method = value.get("method", "js")
                container_tag = value.get("tag", "unknown")

                # Phase 2: step from Python. asyncio.sleep is not subject
                # to Chrome's background-tab throttling, so the cadence
                # stays correct regardless of tab visibility.
                total = abs(delta_x) + abs(delta_y)
                is_y = delta_y != 0
                primary = delta_y if is_y else delta_x
                sign = 1 if primary >= 0 else -1

                scrolled = 0.0
                steps = 0
                while scrolled < total:
                    remaining = total - scrolled
                    step = min(
                        STEP_PX + (random.random() - 0.5) * 2 * STEP_VAR,
                        remaining,
                    )
                    sdy = step * sign if is_y else 0
                    sdx = 0 if is_y else step * sign
                    await self.evaluate(
                        tab_id,
                        f"return window.__gcuScrollStep && window.__gcuScrollStep({sdx}, {sdy})",
                    )
                    scrolled += step
                    steps += 1
                    if scrolled < total:
                        delay_ms = DELAY_MS + (random.random() - 0.5) * 2 * DELAY_VAR
                        await asyncio.sleep(delay_ms / 1000)

                return {
                    "ok": True,
                    "action": "scroll",
                    "direction": direction,
                    "amount": amount,
                    "method": method,
                    "container": container_tag,
                    "steps": steps,
                }

        except TimeoutError:
            return {"ok": False, "error": "scroll timed out"}
        except Exception as e:
            logger.warning("Scroll failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def select_option(self, tab_id: int, selector: str, values: list[str]) -> dict:
        """Select options in a select element."""
        await self.cdp_attach(tab_id)

        values_json = json.dumps(values)
        # Single IIFE returning a structured result. Using self.evaluate (which
        # detects the IIFE and returns its value) instead of a bare Runtime.evaluate
        # script avoids the completion-value unreliability that made multi-statement
        # scripts return null (audit B5), and lets us distinguish "element missing"
        # from "value not an option" for a truthful, specific message (audit B1/F2).
        script = (
            f"(function(){{"
            f"const sel=document.querySelector({json.dumps(selector)});"
            f"if(!sel)return {{found:false}};"
            f"const options=Array.from(sel.options).map(function(o){{return o.value;}});"
            f"Array.from(sel.options).forEach(function(opt){{opt.selected={values_json}.includes(opt.value);}});"
            f"sel.dispatchEvent(new Event('change',{{bubbles:true}}));"
            f"return {{found:true,options:options,selected:Array.from(sel.selectedOptions).map(function(o){{return o.value;}})}};"
            f"}})()"
        )
        result = await self.evaluate(tab_id, script)
        payload = (result or {}).get("result") or {}

        if not payload.get("found"):
            return {"ok": False, "action": "select", "selector": selector, "error": f"Element not found: {selector}"}

        options = payload.get("options", [])
        selected = payload.get("selected", [])
        invalid = [v for v in values if v not in options]
        if invalid:
            return {
                "ok": False,
                "action": "select",
                "selector": selector,
                "error": f"value(s) {invalid} not in this select's options: {options}",
                "selected": selected,
                "options": options,
            }

        # Highlight the select element
        rect_result = await self.evaluate(
            tab_id,
            f"(function(){{const el=document.querySelector("
            f"{json.dumps(selector)});if(!el)return null;"
            f"const r=el.getBoundingClientRect();"
            f"return{{x:r.left,y:r.top,w:r.width,h:r.height}};}})()",
        )
        rect = (rect_result or {}).get("result")
        if rect:
            await self.highlight_rect(tab_id, rect["x"], rect["y"], rect["w"], rect["h"], label=selector)

        return {"ok": True, "action": "select", "selector": selector, "selected": selected}

    # ── Inspection ─────────────────────────────────────────────────────────────

    async def evaluate(self, tab_id: int, script: str) -> dict:
        """Execute JavaScript in the page.

        Returns a structured dict — never raises for CDP-level failures.
        On error the response includes ``blockers``: a list of Blocker
        dicts (e.g. ``foreign_extension_frame`` with the offender's
        extension id and human-readable name) so the caller — agent
        tool, skill script, or side panel — gets the same actionable
        culprit info the UI shows. Without this, every JS-execution
        failure on a Calendly-style tab looks like an opaque
        "Cannot access a chrome-extension:// URL of different extension"
        and the LLM can't tell the user what to disable.
        """
        # One outer try/except covers EVERY CDP touchpoint — cdp_attach,
        # _try_enable_domain, and the Runtime.evaluate itself. Splitting it
        # into per-call wraps as I tried first left _try_enable_domain
        # un-wrapped, so a foreign-frame error from Runtime.enable
        # escaped as a raw BridgeClientError and the agent never saw the
        # structured blockers. The 2026-05-27 session_20260525_115121
        # browser_script_102 trace surfaced exactly that gap.
        stripped = script.strip()

        # Already a complete IIFE — run as-is, no re-wrapping
        is_iife = stripped.startswith("(function") and (stripped.endswith("})()") or stripped.endswith("})();"))
        # Arrow-function IIFE: (() => { ... })()
        is_arrow_iife = stripped.startswith("(()") and (
            stripped.endswith("})()") or stripped.endswith("})();") or stripped.endswith(")()") or stripped.endswith(")()")
        )

        if is_iife or is_arrow_iife:
            # Already self-contained — just run it
            wrapped_script = stripped
        elif stripped.startswith("return "):
            # Single return statement — wrap in IIFE
            wrapped_script = f"(function() {{ {stripped} }})()"
        elif "\n" in stripped or ";" in stripped:
            # Multi-statement block — wrap without prepending return
            # (caller should use explicit return if they want a value)
            wrapped_script = f"(function() {{ {stripped} }})()"
        else:
            # Single expression — wrap with return to capture value
            wrapped_script = f"(function() {{ return {stripped} }})()"

        try:
            await self.cdp_attach(tab_id)
            await self._try_enable_domain(tab_id, "Runtime")
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": wrapped_script, "returnByValue": True, "awaitPromise": True},
            )
        except Exception as e:
            return await self._evaluate_failure(tab_id, e)

        if result is None:
            return {"ok": False, "error": "CDP returned no result"}

        if "exceptionDetails" in result:
            ex = result["exceptionDetails"]
            # Extract the actual exception message from the nested structure
            ex_value = (ex.get("exception") or {}).get("description") or ex.get("text", "Script error")
            return {"ok": False, "error": ex_value}

        # The CDP response structure is {result: {type: ..., value: ...}}
        # But our bridge returns just the inner result object
        inner_result = result.get("result", {})
        value = inner_result.get("value") if isinstance(inner_result, dict) else None

        # Un-nest `JSON.stringify(...)` results so the agent sees clean nested
        # JSON instead of an escaped string. See unnest_json_result. In client
        # mode this method runs in the long-lived bridge_host; the tool wrapper
        # applies the same helper in the gcu server so the fix lands regardless.
        value = unnest_json_result(value)

        return {
            "ok": True,
            "action": "evaluate",
            "result": value,
        }

    async def _evaluate_failure(self, tab_id: int, exc: BaseException) -> dict:
        """Shared error envelope for evaluate / get_text / get_attribute.

        Names the culprit when ``_refresh_blockers`` populated the per-tab
        blocker cache for this error — the agent reading the response sees
        ``blockers[0].title`` like "Blocked by Calendly" instead of just the
        raw CDP error string.

        For foreign-frame failures specifically we ``await`` a fresh
        ``tab.audit`` synchronously here. That call is the ONLY one that
        sees foreign-extension iframes — the page-DOM probe via
        chrome.scripting reads ``document.querySelectorAll('iframe, frame')``
        directly — so without it the in-flight response would carry the
        generic "Blocked by another extension" wording instead of "Blocked
        by Calendly". The 100-200ms cost is paid only on the failure path
        and only when the error fingerprint indicates a foreign frame.
        """
        err_str = str(exc)
        is_foreign_frame_err = "chrome-extension://" in err_str.lower() and "different extension" in err_str.lower()
        # Synchronous re-audit for the foreign-frame case so the response
        # we hand back to the agent names the offender (priority-20 rule)
        # rather than the generic error-only fallback (priority-21).
        if is_foreign_frame_err and not self._snapshot_has_foreign_frame(tab_id):
            try:
                snapshot = await self._send("tab.audit", tabId=tab_id)
                self._refresh_blockers(tab_id, snapshot=snapshot)
            except Exception:
                pass
        blockers = await self.get_tab_blockers(tab_id)
        if not blockers:
            try:
                fresh = self._refresh_blockers(tab_id, error=err_str)
                if fresh:
                    blockers = [b.to_dict() for b in fresh]
            except Exception:
                pass
        out: dict = {"ok": False, "error": err_str}
        if blockers:
            out["blockers"] = blockers
        return out

    async def snapshot(self, tab_id: int, timeout_s: float = 30.0, mode: str = "default") -> dict:
        """Get an accessibility snapshot of the page.

        Uses a hybrid approach:
        1. CDP Accessibility.getFullAXTree for semantic structure
        2. DOM queries for visibility and computed styles
        3. Falls back to DOM tree if accessibility returns mostly ignored

        Args:
            tab_id: The tab ID to snapshot
            timeout_s: Maximum time to spend building snapshot (default 10s)
            mode: Filtering mode — "default", "simple", or "interactive"
        """
        try:
            async with asyncio.timeout(timeout_s):
                await self.cdp_attach(tab_id)
                await self._try_enable_domain(tab_id, "Accessibility")
                await self._try_enable_domain(tab_id, "DOM")
                await self._try_enable_domain(tab_id, "Runtime")

                # Try accessibility tree first
                result = await self._cdp(tab_id, "Accessibility.getFullAXTree")
                nodes = result.get("nodes", [])

            # Count non-ignored nodes
            visible_count = sum(1 for n in nodes if not n.get("ignored", False))

            # If tree is too large or mostly ignored, use DOM-based snapshot
            if len(nodes) > 50000:
                logger.debug(
                    "Accessibility tree too large (%d nodes), using DOM snapshot",
                    len(nodes),
                )
                return await self._dom_snapshot(tab_id)

            if visible_count < 10 and len(nodes) > 500:
                logger.debug(
                    "Accessibility tree has only %d/%d visible nodes, falling back to DOM snapshot",
                    visible_count,
                    len(nodes),
                )
                return await self._dom_snapshot(tab_id)

            # Clean redundant InlineTextBox children before formatting
            nodes = self._clean_inline_text_boxes(nodes)

            # Fetch hrefs for <a> elements so link nodes can render them
            # inline. The AX tree does not carry href; without this, agents
            # must follow up with browser_evaluate to extract URLs from
            # what is often the most action-relevant attribute on the page
            # (e.g. LinkedIn messaging compose URLs encode the recipient).
            href_map = await self._collect_link_hrefs(tab_id)

            # Format the accessibility tree (with node limit)
            snapshot = self._format_ax_tree(nodes, max_nodes=2000, mode=mode, href_map=href_map)

            # Get URL
            url_result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": "window.location.href", "returnByValue": True},
            )
            url = (url_result or {}).get("result", {}).get("value", "")

            return {
                "ok": True,
                "tabId": tab_id,
                "url": url,
                "tree": snapshot,
            }
        except TimeoutError:
            logger.warning("Snapshot timed out after %ss", timeout_s)
            return {"ok": False, "error": f"snapshot timed out after {timeout_s}s"}
        except asyncio.CancelledError:
            logger.warning("Snapshot cancelled (timeout or task cancellation)")
            return {"ok": False, "error": f"snapshot timed out or cancelled (limit: {timeout_s}s)"}
        except Exception as e:
            logger.error("Snapshot failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def _dom_snapshot(self, tab_id: int) -> dict:
        """Fallback: build snapshot from DOM tree with visibility info."""
        # Get all interactive elements using DOM queries
        script = """
            (function() {
                const interactiveSelectors = [
                    'a', 'button', 'input', 'textarea', 'select', 'option',
                    '[onclick]', '[role="button"]', '[role="link"]',
                    '[contenteditable="true"]', 'summary', 'details',
                    'a[href]', 'button[type]', 'input[type]',
                    'label', 'form', 'nav', 'nav a', 'nav button',
                    '[aria-label]', '[aria-labelledby]', '[tabindex]',
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
                ].join(', ');

                const elements = document.querySelectorAll(interactiveSelectors);
                const results = [];

                for (const el of elements) {
                    const rect = el.getBoundingClientRect();
                    const styles = window.getComputedStyle(el);

                    // Skip invisible elements
                    if (rect.width === 0 || rect.height === 1 ||
                        styles.display === 'none' ||
                        styles.visibility === 'hidden' ||
                        styles.opacity === '0') {
                        continue;
                    }

                    // Skip elements outside viewport
                    if (rect.bottom < 0 || rect.top > window.innerHeight ||
                        rect.right < 0 || rect.left > window.innerWidth) {
                        continue;
                    }

                    const tag = el.tagName.toLowerCase();
                    const text = (el.innerText || el.value || el.placeholder
                        || el.getAttribute('aria-label') || '').substring(0, 80);
                    const type = el.type || tag;
                    const role = el.getAttribute('role') || tag;
                    const name = el.name || el.id || '';
                    const href = el.href || '';
                    const className = el.className || '';

                    results.push({
                        tag,
                        type,
                        role,
                        text: text.trim(),
                        name,
                        href,
                        className: className.split(' ').slice(0, 3).join(' '),
                        rect: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        }
                    });
                }

                return results;
            })();
        """

        result = await self.evaluate(tab_id, script)
        elements = result.get("result", [])

        if not elements:
            return {
                "ok": True,
                "tabId": tab_id,
                "tree": "(no visible interactive elements found)",
            }

        # Format as tree
        lines = []
        for i in range(0, min(100, len(elements))):
            el = elements[i]
            ref = f"e{i}"
            tag = el.get("tag", "unknown")
            text = el.get("text", "")
            role = el.get("role", tag)

            desc = f"{role}"
            if text:
                desc += f' "{text[:40]}"'
            if el.get("href"):
                desc += " [href]"
            desc += f" [ref={ref}]"
            lines.append(f"  - {desc}")

        # Get URL
        url_result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        url = (url_result or {}).get("result", {}).get("value", "")

        return {
            "ok": True,
            "tabId": tab_id,
            "url": url,
            "tree": "\n".join(lines),
        }

    @staticmethod
    def _clean_inline_text_boxes(nodes: list[dict]) -> list[dict]:
        """Remove redundant InlineTextBox children from StaticText nodes.

        If a StaticText node has 3+ InlineTextBox children and ALL their
        text is already contained in the StaticText's name, remove all
        the InlineTextBox children (they add no information).
        """
        by_id = {n["nodeId"]: n for n in nodes}
        children_map: dict[str, list[str]] = {}
        for n in nodes:
            for child_id in n.get("childIds", []):
                children_map.setdefault(n["nodeId"], []).append(child_id)

        ids_to_remove: set[str] = set()

        for n in nodes:
            role_info = n.get("role", {})
            role = role_info.get("value", "") if isinstance(role_info, dict) else str(role_info)
            if role != "StaticText":
                continue

            child_ids = children_map.get(n["nodeId"], [])
            if len(child_ids) < 3:
                continue

            name_info = n.get("name", {})
            parent_name = name_info.get("value", "") if isinstance(name_info, dict) else str(name_info)
            if not parent_name:
                continue

            all_inline = True
            for cid in child_ids:
                child = by_id.get(cid)
                if not child:
                    all_inline = False
                    break
                child_role_info = child.get("role", {})
                child_role = child_role_info.get("value", "") if isinstance(child_role_info, dict) else str(child_role_info)
                if child_role != "InlineTextBox":
                    all_inline = False
                    break
                child_name_info = child.get("name", {})
                child_name = child_name_info.get("value", "") if isinstance(child_name_info, dict) else str(child_name_info)
                if child_name and child_name not in parent_name:
                    all_inline = False
                    break

            if all_inline:
                ids_to_remove.update(child_ids)
                n["childIds"] = []

        if not ids_to_remove:
            return nodes

        return [n for n in nodes if n["nodeId"] not in ids_to_remove]

    async def _collect_link_hrefs(self, tab_id: int) -> dict[str, list[str]]:
        """Walk every <a href> on the page and return hrefs grouped by
        accessible name, in document order.

        Returned as ``{name: [href1, href2, ...]}``. The formatter matches
        AX link nodes against this map by name and pops the next href —
        a per-tab CDP lock makes per-node lookups too slow, so we collect
        everything in one Runtime.evaluate round-trip. Visibility filter
        approximates the AX tree's own inclusion rules to keep DOM order
        and AX walk order in sync.

        On any failure returns ``{}`` — links just won't be href-annotated.
        """
        script = """
        (function() {
          // Approximate the W3C AccName algorithm: aria-label first,
          // then a text walk that EXCLUDES aria-hidden subtrees. Matters
          // for patterns like LinkedIn's invitation list, where the
          // visible-to-AT name lives in a sr-only span and the rendered
          // glyph is in an aria-hidden sibling. innerText would return
          // just the aria-hidden text and mismatch the AX tree's name.
          var nameOf = function(a) {
            var aria = a.getAttribute('aria-label');
            if (aria && aria.trim()) return aria.trim().replace(/\\s+/g, ' ');
            var parts = [];
            (function walk(node) {
              if (node.nodeType === 3) { parts.push(node.textContent); return; }
              if (node.nodeType !== 1) return;
              if (node.getAttribute && node.getAttribute('aria-hidden') === 'true') return;
              var kids = node.childNodes;
              for (var i = 0; i < kids.length; i++) walk(kids[i]);
            })(a);
            var txt = parts.join(' ').replace(/\\s+/g, ' ').trim();
            if (txt) return txt;
            var title = a.getAttribute('title');
            if (title && title.trim()) return title.trim();
            return '';
          };
          var out = [];
          var anchors = document.querySelectorAll('a[href]');
          for (var i = 0; i < anchors.length; i++) {
            var a = anchors[i];
            var rect = a.getBoundingClientRect();
            // Skip purely-zero-size anchors — AX tree skips them too
            if (rect.width === 0 && rect.height === 0) continue;
            var s = window.getComputedStyle(a);
            if (s.display === 'none' || s.visibility === 'hidden') continue;
            out.push([nameOf(a), a.href]);
          }
          return out;
        })()
        """
        try:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
        except Exception as e:
            logger.debug("collect_link_hrefs evaluate failed: %s", e)
            return {}

        pairs = (result or {}).get("result", {}).get("value") or []
        by_name: dict[str, list[str]] = {}
        for entry in pairs:
            if not isinstance(entry, list) or len(entry) != 2:
                continue
            name, href = entry
            if not isinstance(href, str):
                continue
            by_name.setdefault(name or "", []).append(href)
        return by_name

    def _format_ax_tree(
        self,
        nodes: list[dict],
        max_nodes: int = 2000,
        mode: str = "default",
        href_map: dict[str, list[str]] | None = None,
    ) -> str:
        """Format a CDP Accessibility.getFullAXTree result.

        Args:
            nodes: List of accessibility tree nodes
            max_nodes: Maximum number of nodes to process (prevents hangs on huge trees)
            mode: Filtering mode — "default" (full tree), "simple" (interactive +
                  content, skip unnamed structural), "interactive" (interactive only)
            href_map: Optional ``{name: [hrefs]}`` from :meth:`_collect_link_hrefs`.
                Link nodes are annotated with ``[href="..."]`` by popping the
                next href for their accessible name in tree order.
        """
        from .refs import INTERACTIVE_ROLES, STRUCTURAL_ROLES

        if not nodes:
            return "(empty tree)"

        by_id = {n["nodeId"]: n for n in nodes}
        children_map: dict[str, list[str]] = {}
        for n in nodes:
            for child_id in n.get("childIds", []):
                children_map.setdefault(n["nodeId"], []).append(child_id)

        lines: list[str] = []
        ref_counter = [0]  # Use list to allow mutation in nested function
        node_counter = [0]  # Track total nodes processed
        ref_map: dict[str, str] = {}
        # Per-name cursor into href_map — AX walks the tree in roughly
        # the same order the DOM scan did, so popping by name gives each
        # AX link node its corresponding href even when many links share
        # the same accessible name (e.g. "Send a message to X" repeated
        # across an invitations list).
        href_cursor: dict[str, int] = {}

        def _walk(node_id: str, depth: int) -> None:
            # Stop if we've processed enough nodes
            if node_counter[0] >= max_nodes:
                return

            node = by_id.get(node_id)
            if not node:
                return

            role_info = node.get("role", {})
            if isinstance(role_info, dict):
                role = role_info.get("value", "unknown")
            else:
                role = str(role_info)

            name_info = node.get("name", {})
            name = name_info.get("value", "") if isinstance(name_info, dict) else str(name_info)

            if node.get("ignored", False):
                # Chromium marks <a href> / <button> 'ignored' inside virtualized
                # or aria-hidden containers (common on LinkedIn) even when the
                # element is still clickable. Keep it if it has an interactive
                # role + accessible name and none of the hard-hide reasons fire.
                reasons = {(r.get("name") if isinstance(r, dict) else None) for r in node.get("ignoredReasons", [])}
                hard_hide = reasons & {"notRendered", "displayNone", "inert", "notVisible"}
                if not (role in INTERACTIVE_ROLES and name and not hard_hide):
                    for cid in children_map.get(node_id, []):
                        _walk(cid, depth)
                    return

            if role in ("none", "Ignored"):
                for cid in children_map.get(node_id, []):
                    _walk(cid, depth)
                return

            # Mode-based filtering — skip node but walk children at same depth
            if mode == "interactive" and role not in INTERACTIVE_ROLES:
                for cid in children_map.get(node_id, []):
                    _walk(cid, depth)
                return
            if mode == "simple" and role in STRUCTURAL_ROLES and not name:
                for cid in children_map.get(node_id, []):
                    _walk(cid, depth)
                return

            node_counter[0] += 1

            # Build property annotations
            props: list[str] = []
            for prop in node.get("properties", []):
                pname = prop.get("name", "")
                pval = prop.get("value", {})
                val = pval.get("value") if isinstance(pval, dict) else pval
                if pname in ("focused", "disabled", "checked", "expanded", "selected", "required"):
                    if val is True:
                        props.append(pname)
                elif pname == "level" and val:
                    props.append(f"level={val}")

            indent = "  " * depth
            label = f"- {role}"

            # Add ref for interactive elements
            if role in INTERACTIVE_ROLES or name:
                ref_counter[0] += 1
                ref_id = f"e{ref_counter[0]}"
                ref_map[ref_id] = f"[{role}]{name}"
                label += f" [ref={ref_id}]"

            if name:
                label += f' "{name}"'
            if props:
                label += f" [{', '.join(props)}]"

            # Annotate <a> links with their href so agents can read the
            # URL (e.g. messaging-compose URLs that encode the recipient)
            # without a follow-up DOM query.
            if role == "link" and href_map is not None:
                key = name or ""
                hrefs = href_map.get(key)
                if hrefs:
                    idx = href_cursor.get(key, 0)
                    if idx < len(hrefs):
                        label += f' [href="{hrefs[idx]}"]'
                        href_cursor[key] = idx + 1

            lines.append(f"{indent}{label}")

            for cid in children_map.get(node_id, []):
                _walk(cid, depth + 1)

        _walk(nodes[0]["nodeId"], 0)

        # Add truncation notice if we hit the limit
        if node_counter[0] >= max_nodes:
            lines.append("... (tree truncated, too many nodes)")

        # Supplemental: emit DOM-visible <a href> elements that the AX walk
        # never reached (Chromium marks anchors 'ignored' with notRendered
        # /notVisible inside virtualized lists or aria-hidden ancestors —
        # common on LinkedIn). Without this, those links are invisible to
        # the agent even though they're clickable. Names match the AX tree
        # because _collect_link_hrefs uses the same aria-hidden-aware walk.
        if href_map:
            missed: list[tuple[str, str]] = []
            for link_name, hrefs in href_map.items():
                consumed = href_cursor.get(link_name, 0)
                for href in hrefs[consumed:]:
                    missed.append((link_name, href))
            if missed:
                lines.append("")
                lines.append("(links visible in DOM but not in accessibility tree):")
                for link_name, href in missed:
                    ref_counter[0] += 1
                    ref_id = f"e{ref_counter[0]}"
                    display_name = link_name or "(unnamed)"
                    ref_map[ref_id] = f"[link]{link_name}"
                    lines.append(f'  - link [ref={ref_id}] "{display_name}" [href="{href}"]')

        return "\n".join(lines) if lines else "(empty tree)"

    async def get_text(self, tab_id: int, selector: str, timeout_ms: int = 30000) -> dict:
        """Get text content of an element."""
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                return el ? el.textContent : null;
            }})()
        """

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            # _cdp returns the raw CDP response {"result":{"type":...,"value":...}}.
            # The extra .get("result") hop was dropping the value — every
            # successful lookup was silently misreported as "not found" until
            # the deadline fired.
            text = (result or {}).get("result", {}).get("value")
            if text is not None:
                return {"ok": True, "selector": selector, "text": text}
            await asyncio.sleep(0.1)

        return {"ok": False, "error": f"Element not found: {selector}"}

    async def get_attribute(self, tab_id: int, selector: str, attribute: str, timeout_ms: int = 30000) -> dict:
        """Get an attribute value of an element."""
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                return el ? el.getAttribute({json.dumps(attribute)}) : null;
            }})()
        """

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            # Same unwrap bug as get_text_by_selector — the response shape
            # is {"result":{"type":...,"value":...}}, one "result", not two.
            value = (result or {}).get("result", {}).get("value")
            if value is not None:
                return {"ok": True, "selector": selector, "attribute": attribute, "value": value}
            await asyncio.sleep(0.1)

        return {"ok": False, "error": f"Element not found: {selector}"}

    async def screenshot(
        self,
        tab_id: int,
        full_page: bool = False,
        selector: str | None = None,
        timeout_s: float = 30.0,
        selector_timeout_ms: int = 5000,
    ) -> dict:
        """Take a screenshot of the page or element.

        Returns {"ok": True, "data": base64_string, "mimeType": "image/png"}.
        """
        try:
            async with asyncio.timeout(timeout_s):
                await self.cdp_attach(tab_id)
                await self._cdp(tab_id, "Page.enable")

                params: dict[str, Any] = {"format": "png"}
                # SAFETY: an over-large Page.captureScreenshot bitmap SIGTRAPs the
                # whole Chrome process (it crashed the user's browser + extension
                # mid-session). So: NEVER use captureBeyondViewport (renders the full
                # off-screen document into one giant surface) and NEVER scale a clip
                # by devicePixelRatio — a full page × dpr² is exactly what blew up.
                # The result is downscaled to 800px wide anyway, so a native-res
                # capture buys nothing but risk. Capture at scale 1 and clamp every
                # clip dimension below Chrome's max texture size.
                _MAX_CLIP_PX = 16384
                if selector:
                    # Resolve the element with the SAME engine interact/click use:
                    # poll for dynamic content + ' >>> ' shadow-piercing via
                    # shadow_query — not a one-shot document.querySelector, which
                    # missed hydrated / shadow-DOM elements that interact finds
                    # (audit B8).
                    deadline = asyncio.get_event_loop().time() + max(0, selector_timeout_ms) / 1000
                    clip_rect = None
                    while True:
                        sq = await self.shadow_query(tab_id, selector)
                        r = sq.get("rect") if sq.get("ok") else None
                        if r and r.get("w") and r.get("h"):
                            clip_rect = {
                                "x": r["x"],
                                "y": r["y"],
                                "width": min(r["w"], _MAX_CLIP_PX),
                                "height": min(r["h"], _MAX_CLIP_PX),
                                "scale": 1,
                            }
                            break
                        if asyncio.get_event_loop().time() >= deadline:
                            break
                        await asyncio.sleep(0.1)
                    if clip_rect:
                        params["clip"] = clip_rect
                    else:
                        return {"ok": False, "error": f"Selector not found: {selector}"}
                elif full_page:
                    metrics = await self._cdp(tab_id, "Page.getLayoutMetrics")
                    content_size = metrics.get("contentSize", {})
                    fp_w = float(content_size.get("width", 1280) or 1280)
                    fp_h = float(content_size.get("height", 720) or 720)
                    # captureBeyondViewport renders the WHOLE document (below the
                    # fold) into the capture — without it a clip taller than the
                    # viewport fails with CDP -32000. But an unbounded full-page ×
                    # dpr bitmap crashed Chrome (SIGTRAP) earlier, so we bound the
                    # captured bitmap hard: pick a scale so neither side approaches
                    # Chrome's 2^15 max texture size and the total stays well under a
                    # crash-inducing pixel count. The result is downscaled to 800px
                    # wide anyway, so a reduced-scale capture is lossless to output.
                    _FP_MAX_SIDE = 16000  # < 2^15 (16384) with headroom
                    _FP_MAX_PIXELS = 16_000_000  # ~16 MP — far below the ~330 MP that was observed safe
                    fp_scale = min(1.0, _FP_MAX_SIDE / fp_w, _FP_MAX_SIDE / fp_h)
                    if fp_w * fp_h * fp_scale * fp_scale > _FP_MAX_PIXELS:
                        fp_scale = (_FP_MAX_PIXELS / (fp_w * fp_h)) ** 0.5
                    fp_scale = max(0.05, round(fp_scale, 4))
                    params["captureBeyondViewport"] = True
                    params["clip"] = {
                        "x": 0.0,
                        "y": 0.0,
                        "width": fp_w,
                        "height": fp_h,
                        "scale": fp_scale,
                    }

                # Pass the outer screenshot timeout budget to the
                # underlying CDP call. Full-page screenshots over slow
                # networks can legitimately take 20-40s; the default 30s
                # _send floor used to make them fail spuriously right at
                # the boundary. We give the CDP call the full timeout_s
                # budget so the outer `asyncio.timeout(timeout_s)` is
                # the only authority on how long we wait.
                def _fullpage_limit_error() -> dict:
                    # A full-page clip taller than the viewport can exceed Chrome's
                    # single-shot capture limit (CDP -32000 "Unable to capture
                    # screenshot"). We deliberately do NOT retry with
                    # captureBeyondViewport — compositing a full off-screen document
                    # into one surface can crash the whole browser. Give the agent an
                    # actionable error instead of the opaque CDP code.
                    h = (params.get("clip") or {}).get("height")
                    return {
                        "ok": False,
                        "error": (
                            f"Full-page screenshot exceeded Chrome's capture limit "
                            f"(page is ~{h}px tall). Use a default screenshot (the visible "
                            f"viewport), a --selector screenshot of the region you need, or "
                            f"scroll and capture in sections."
                        ),
                    }

                try:
                    result = await self._cdp(
                        tab_id,
                        "Page.captureScreenshot",
                        params,
                        timeout=timeout_s,
                    )
                except Exception:
                    if full_page and "clip" in params:
                        return _fullpage_limit_error()
                    raise
                data = result.get("data")

                if not data:
                    if full_page and "clip" in params:
                        return _fullpage_limit_error()
                    return {"ok": False, "error": "Screenshot failed"}

                # Get URL and viewport metadata in one evaluate call
                meta_result = await self._cdp(
                    tab_id,
                    "Runtime.evaluate",
                    {
                        "expression": (
                            "(function(){"
                            "return{"
                            "url:window.location.href,"
                            "dpr:window.devicePixelRatio,"
                            "cssWidth:window.innerWidth,"
                            "cssHeight:window.innerHeight"
                            "};"
                            "})()"
                        ),
                        "returnByValue": True,
                    },
                )
                # _cdp returns the raw CDP response body, which for Runtime.evaluate
                # is {"result": {"type": ..., "value": <our returned object>}}. The
                # previous code did .get("result").get("result").get("value") —
                # that extra hop dropped everything, so cssWidth always defaulted
                # to 0 and devicePixelRatio to 1.0. Which in turn collapsed
                # physical_scale and css_scale into the same number and made
                # post-screenshot clicks land at DPR× the intended coordinate.
                meta = (meta_result or {}).get("result", {}).get("value") or {}

                dpr = meta.get("dpr", 1.0)
                css_w = meta.get("cssWidth", 0)
                css_h = meta.get("cssHeight", 0)

                import struct as _struct

                raw_bytes = base64.b64decode(data) if data else b""
                png_w = _struct.unpack(">I", raw_bytes[16:20])[0] if len(raw_bytes) >= 24 else 0
                png_h = _struct.unpack(">I", raw_bytes[20:24])[0] if len(raw_bytes) >= 24 else 0
                logger.info(
                    "CDP screenshot raw: png=%dx%d, css=%dx%d, dpr=%s, implied_dpr=%.2f",
                    png_w,
                    png_h,
                    css_w,
                    css_h,
                    dpr,
                    (png_w / css_w) if css_w else 0.0,
                )

                # When the capture was clipped (element selector or
                # full_page), report the clip rect in CSS px so callers
                # can express it as a viewport-fraction crop_box — needed
                # to remap coordinates read off a non-viewport image.
                clip_used = params.get("clip")
                clip_rect = {k: clip_used[k] for k in ("x", "y", "width", "height")} if clip_used else None

                return {
                    "ok": True,
                    "tabId": tab_id,
                    "url": meta.get("url", ""),
                    "devicePixelRatio": dpr,
                    "cssWidth": css_w,
                    "cssHeight": css_h,
                    # Raw PNG pixel dims so callers can compare against
                    # cssWidth/cssHeight × dpr and detect viewport ↔
                    # capture mismatches (e.g. devtools-attached infobar
                    # shifting one but not the other).
                    "pngWidth": png_w,
                    "pngHeight": png_h,
                    "clip": clip_rect,
                    "data": data,
                    "mimeType": "image/png",
                }
        except TimeoutError:
            logger.warning("Screenshot timed out after %ss", timeout_s)
            return {"ok": False, "error": f"screenshot timed out after {timeout_s}s"}
        except asyncio.CancelledError:
            logger.warning("Screenshot cancelled (timeout or task cancellation)")
            return {
                "ok": False,
                "error": f"screenshot timed out or cancelled (limit: {timeout_s}s)",
            }
        except Exception as e:
            logger.error("Screenshot failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def screenshot_region(
        self,
        tab_id: int,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        scale: float = 2.0,
        timeout_s: float = 30.0,
    ) -> dict:
        """Capture a sub-region of the viewport at higher resolution.

        ``x0, y0, x1, y1`` are fractions (0..1) of the viewport — the
        same coordinate space the click / hover tools use. ``scale``
        multiplies the captured resolution via CDP's ``clip.scale`` so
        small UI stays crisp when zoomed in (true higher-res capture,
        not an upscale of the 800px page screenshot).

        Returns the same envelope shape as :meth:`screenshot` with
        ``data`` holding a base64 PNG, plus ``regionCssWidth`` /
        ``regionCssHeight`` / ``captureScale`` for the caller's resize.
        """
        try:
            async with asyncio.timeout(timeout_s):
                await self.cdp_attach(tab_id)
                await self._cdp(tab_id, "Page.enable")

                # Viewport size is needed up front to turn the fractional
                # region into the CSS-px clip rect CDP expects.
                meta_result = await self._cdp(
                    tab_id,
                    "Runtime.evaluate",
                    {
                        "expression": (
                            "(function(){return{"
                            "url:window.location.href,"
                            "dpr:window.devicePixelRatio,"
                            "cssWidth:window.innerWidth,"
                            "cssHeight:window.innerHeight"
                            "};})()"
                        ),
                        "returnByValue": True,
                    },
                )
                meta = (meta_result or {}).get("result", {}).get("value") or {}
                cw = meta.get("cssWidth", 0)
                ch = meta.get("cssHeight", 0)
                if not cw or not ch:
                    return {"ok": False, "error": "could not read viewport size for zoom"}

                # Clamp to [0,1] and order the corners so a swapped /
                # inverted region still yields a valid positive rect.
                fx0, fx1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
                fy0, fy1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
                clip_w = max(1.0, (fx1 - fx0) * cw)
                clip_h = max(1.0, (fy1 - fy0) * ch)

                result = await self._cdp(
                    tab_id,
                    "Page.captureScreenshot",
                    {
                        "format": "png",
                        "clip": {
                            "x": fx0 * cw,
                            "y": fy0 * ch,
                            "width": clip_w,
                            "height": clip_h,
                            "scale": scale,
                        },
                    },
                    timeout=timeout_s,
                )
                data = result.get("data")
                if not data:
                    return {"ok": False, "error": "Zoom screenshot failed"}

                return {
                    "ok": True,
                    "tabId": tab_id,
                    "url": meta.get("url", ""),
                    "devicePixelRatio": meta.get("dpr", 1.0),
                    "cssWidth": cw,
                    "cssHeight": ch,
                    "regionCssWidth": clip_w,
                    "regionCssHeight": clip_h,
                    "captureScale": scale,
                    "data": data,
                    "mimeType": "image/png",
                }
        except TimeoutError:
            logger.warning("Zoom screenshot timed out after %ss", timeout_s)
            return {"ok": False, "error": f"zoom screenshot timed out after {timeout_s}s"}
        except asyncio.CancelledError:
            logger.warning("Zoom screenshot cancelled")
            return {"ok": False, "error": f"zoom screenshot timed out or cancelled (limit: {timeout_s}s)"}
        except Exception as e:
            logger.error("Zoom screenshot failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def wait_for_selector(
        self,
        tab_id: int,
        selector: str,
        timeout_ms: int = DEFAULT_WAIT_TIMEOUT_MS,
    ) -> dict:
        """Wait for an element to appear.

        Default 5 s fast-fail. Callers that need to wait longer (e.g.
        a known slow post-navigation render) should pass an explicit
        ``timeout_ms``.
        """
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                return document.querySelector({json.dumps(selector)}) !== null;
            }})()
        """

        poll_start = asyncio.get_event_loop().time()
        deadline = poll_start + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            # One "result" hop — see navigate() comment. This was silently
            # returning False on every poll, so wait_for_selector always
            # reported "not found" after the full timeout.
            found = (result or {}).get("result", {}).get("value", False)
            if found:
                return {"ok": True, "selector": selector}
            await _adaptive_poll_sleep(asyncio.get_event_loop().time() - poll_start)

        return {"ok": False, "error": f"Element not found within timeout: {selector}"}

    async def wait_for_text(
        self,
        tab_id: int,
        text: str,
        timeout_ms: int = DEFAULT_WAIT_TIMEOUT_MS,
    ) -> dict:
        """Wait for text to appear on the page.

        Default 5 s fast-fail. Same fast-fail rationale as
        :meth:`wait_for_selector`.
        """
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                return document.body.innerText.includes({json.dumps(text)});
            }})()
        """

        poll_start = asyncio.get_event_loop().time()
        deadline = poll_start + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            # Same unwrap bug as wait_for_selector.
            found = (result or {}).get("result", {}).get("value", False)
            if found:
                return {"ok": True, "text": text}
            await _adaptive_poll_sleep(asyncio.get_event_loop().time() - poll_start)

        return {"ok": False, "error": f"Text not found within timeout: {text}"}

    async def resize(self, tab_id: int, width: int, height: int) -> dict:
        """Resize the browser viewport."""
        await self.cdp_attach(tab_id)

        # Use Runtime.evaluate to set up resize, then Emulation.setDeviceMetricsOverride
        await self._cdp(
            tab_id,
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": 0,
                "mobile": False,
            },
        )

        return {"ok": True, "action": "resize", "width": width, "height": height}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bridge: BeelineBridge | None = None
# True once init_bridge() has built a RemoteBridge (client mode). Lets the
# tool layer branch on mode without importing bridge_rpc just for isinstance.
_bridge_is_client: bool = False


def get_bridge() -> BeelineBridge | None:
    """Return the bridge singleton, or None if not initialised."""
    return _bridge


def is_client_mode() -> bool:
    """True if the process drives the bridge out-of-process (RemoteBridge).

    Meaningful only after :func:`init_bridge` has run.
    """
    return _bridge_is_client


def _identify_port_holder(port: int) -> str:
    """Best-effort ``name (pid N)`` of whatever is listening on a local port.

    Lets a bind-conflict message name the culprit instead of saying a vague
    "another process". Parses ``ss -ltnp``; on any failure (ss missing, parse
    miss, timeout) it falls back to a generic phrase rather than raising —
    diagnostics must never themselves throw.
    """
    try:
        out = subprocess.run(
            ["ss", "-ltnp"],
            capture_output=True,
            text=True,
            timeout=2.0,
        ).stdout
    except Exception:
        return "another process"
    for line in out.splitlines():
        if f":{port} " not in line:
            continue
        # ss renders the owner as: users:(("python3",pid=1747982,fd=6))
        m = re.search(r'\(\("([^"]+)",pid=(\d+)', line)
        return f"{m.group(1)} (pid {m.group(2)})" if m else "another process"
    return "an unknown process"


def connection_error(bridge: BeelineBridge | None) -> str:
    """Tool-facing error string for a browser call that failed because the
    extension isn't connected — classified into a specific, actionable cause
    (port conflict / not installed / Chrome not running)."""
    if bridge is None:
        return "The Hive browser bridge isn't running. Restart the Hive app, then retry."
    return bridge.connection_help()


def init_bridge(mode: str | None = None):
    """Create (or return) the bridge singleton.

    ``mode`` is ``"host"`` or ``"client"``. An explicit argument wins;
    otherwise the ``GCU_BRIDGE_MODE`` env var is consulted; the default is
    ``"host"``.

    Host mode builds an in-process :class:`BeelineBridge` and serves the
    extension directly. Client mode builds a
    :class:`~gcu.browser.bridge_rpc.RemoteBridge` proxy that drives the
    bridge running in the separate, supervised ``bridge_host`` process — so a
    gcu server can be recycled (tool-call timeout, refcount drop, crash)
    without taking the bridge, the extension link, or open tabs down with it.

    Either object is a drop-in for the other from the tool layer's view:
    ``get_bridge()`` callers need no changes.
    """
    global _bridge, _bridge_is_client
    if _bridge is None:
        effective = (mode or os.environ.get("GCU_BRIDGE_MODE", "host")).strip().lower()
        if effective == "client":
            from .bridge_rpc import RemoteBridge

            _bridge = RemoteBridge()
            _bridge_is_client = True
            logger.info("gcu bridge mode: client (RemoteBridge → bridge_host process)")
        else:
            _bridge = BeelineBridge()
            _bridge_is_client = False
    return _bridge
