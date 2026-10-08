"""
Out-of-process RPC for the Beeline browser bridge.

Background
----------
The bridge used to live *inside* the gcu MCP-server process. That process is
disposable: the Hive runtime force-disconnects it whenever a single browser
tool call exceeds the 60s tool-call timeout (see
``core/framework/agent_loop``). Killing the process took the bridge — and
every open tab, the extension link, and all session state — down with it,
purely as collateral damage from one slow call.

The fix is to run the bridge in its own long-lived, supervised process and
make each gcu MCP server a *client* of it. This module is the wire between
the two:

  * :class:`BridgeRpcServer` — runs in the bridge process; exposes the
    :class:`~gcu.browser.bridge.BeelineBridge` method surface as JSON-RPC
    over a WebSocket.
  * :class:`BridgeClient` — runs in each (disposable) gcu process; the
    ``browser_*`` tools call it in place of an in-process bridge reference.

A gcu restart then just means a new :class:`BridgeClient` reconnecting to the
still-running bridge — no tabs lost, no CDP re-attach, no session reset.

Wire protocol
-------------
Control traffic uses its own port (:data:`CONTROL_PORT` = ``BRIDGE_PORT + 2``)
so a malformed tool call can never be mistaken for an extension frame on the
relay port, and the two protocols can evolve independently. Frames are JSON:

    request   {"rpc_id": "<hex>", "method": "navigate", "args": [...], "params": {...}}
    response  {"rpc_id": "<hex>", "ok": true,  "result": <json>}
              {"rpc_id": "<hex>", "ok": false, "error": {"message", "code", "retryable"}}

``args``/``params`` carry positional/keyword arguments so the tool layer can
keep calling bridge methods exactly as it did in-process — no signature
rewrite at the ~33 call sites.

The client mirrors the old in-process contract: :meth:`BridgeClient.call`
returns the remote method's result dict on success and *raises* on failure,
so existing ``try/except`` blocks in the tool layer keep working unchanged.
:class:`RemoteBridge` wraps the client into a drop-in replacement for an
in-process ``BeelineBridge`` reference.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
import uuid
from typing import TYPE_CHECKING

from .bridge import BRIDGE_PORT, _pid_alive

if TYPE_CHECKING:
    from .bridge import BeelineBridge

logger = logging.getLogger(__name__)

# Control-RPC port. 14829 = extension relay WS, 14830 = HTTP status,
# 14831 = this method-call RPC. Kept deliberately adjacent so the whole
# bridge surface is one easy-to-remember block.
CONTROL_PORT = BRIDGE_PORT + 2

# CDP responses (full AX trees, screenshots) are large; match the extension
# relay's frame ceiling so a snapshot never trips a protocol error.
_MAX_FRAME_BYTES = 50 * 1024 * 1024

# WS-layer heartbeat — detects a half-open control socket within
# ~ping_interval + ping_timeout, the same way the extension relay does.
_PING_INTERVAL_S = 20
_PING_TIMEOUT_S = 20

# Backstop timeout for a single RPC round-trip. Individual bridge methods
# enforce their own (shorter) timeouts; this only catches a wedged bridge
# that never replies at all.
_DEFAULT_CALL_TIMEOUT_S = 120.0

# How often RemoteBridge refreshes its cached connection snapshot so the
# synchronous `is_connected` / `connection_help()` the tool guards read stays
# close to live truth.
_STATE_POLL_INTERVAL_S = 2.0

# Client-liveness reaper tuning. Each connected MCP identifies its owner
# (Electron) PID via client_hello; the reaper periodically checks each
# owner's liveness and force-closes connections whose owner has died, so
# orphaned MCPs from prior app sessions can't keep the bridge alive past
# the idle watchdog's grace.
_REAP_INTERVAL_S = 10.0
# Grace window for a fresh WS to send client_hello before it counts as a
# zombie. Real MCPs send hello within milliseconds; this catches pre-
# upgrade orphans that never hello at all.
_CLIENT_IDENTIFY_GRACE_S = 30.0

# The exact set of BeelineBridge attributes a tool client may invoke. An
# explicit allowlist — never reflective getattr on arbitrary input — so the
# control port can't be turned into a remote-code lever. Mirrors the call
# surface the browser_* tools actually use (properties and sync methods are
# dispatched the same way as coroutines; see _dispatch).
RPC_METHODS: frozenset[str] = frozenset(
    {
        # contexts / lifecycle
        "create_context",
        "destroy_context",
        "register_context",
        "list_contexts",
        # tabs
        "create_tab",
        "close_tab",
        "list_tabs",
        "activate_tab",
        # navigation
        "navigate",
        "go_back",
        "go_forward",
        "reload",
        # interactions
        "click",
        "click_coordinate",
        "type_text",
        "press_key",
        "press_key_at",
        "hover",
        "hover_coordinate",
        "scroll",
        "select_option",
        # inspection
        "screenshot",
        "snapshot",
        "evaluate",
        "get_text",
        "get_attribute",
        "shadow_query",
        # advanced
        "wait_for_selector",
        "wait_for_text",
        "resize",
        "handle_javascript_dialog",
        "get_pending_dialog",
        # tab health — used by browser_evaluate / browser_script wrappers
        # to attach offender info ("Blocked by Calendly") to error responses,
        # and by the side panel's per-tab blocker probe.
        "get_tab_blockers",
        "tab_health",
        "audit_tab",
        # action history — telemetry pushes one entry per user-facing tool
        # call into the bridge's per-tab ring buffer so the side panel can
        # render it. The buffer lives in the bridge process; without this
        # allowlist entry the RemoteBridge proxy refuses to forward the
        # call and the side panel's "Action history" stays empty.
        "record_action",
        # cdp
        "cdp_attach",
        "cdp_detach",
        "_cdp",
        # introspection — sync method / property; dispatch handles both
        "status_payload",
        "connected_profiles",
        "connection_help",
        "is_connected",
        # identity — each MCP, on connect, calls client_hello(pid) with its
        # HIVE_DESKTOP_PARENT_PID so the bridge can tell its connections
        # apart by owner. The reaper PID-checks identified clients and
        # force-closes those whose owner (Electron) has died — without
        # this, orphaned MCPs from prior app sessions hold the WS open
        # and inflate active_client_count forever, blocking the idle
        # watchdog. Handled specially in _dispatch (it's per-connection
        # server state, not a bridge method call).
        "client_hello",
        # Opt-in to server-initiated push frames. Called by the host
        # runtime (cli.py keepalive) so the bridge can push side-panel
        # "user detached / handed over tab X" notifications back, which
        # are then routed to the owning worker via inject_event. Like
        # client_hello, dispatched specially — it mutates per-connection
        # server state, not a bridge method.
        "subscribe_notifications",
    }
)


class BridgeClientError(Exception):
    """A browser RPC call failed.

    Carries the structured fields the bridge attaches to its own errors
    (``code``, ``retryable``) so the tool layer can branch — retry a
    ``connection_lost``, surface anything else — exactly as it did when the
    bridge raised ``BridgeError`` in-process.
    """

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _error_payload(exc: BaseException) -> dict:
    """Serialize an exception raised by a bridge method for the wire.

    ``BridgeError`` exposes ``.code`` / ``.retryable``; anything else falls
    back to its class name and is treated as non-retryable.
    """
    return {
        "message": str(exc),
        "code": getattr(exc, "code", None) or type(exc).__name__,
        "retryable": bool(getattr(exc, "retryable", False)),
    }


# ──────────────────────────────────────────────────────────────────────────
# Server — runs inside the long-lived bridge process
# ──────────────────────────────────────────────────────────────────────────


class BridgeRpcServer:
    """Exposes a :class:`BeelineBridge` to out-of-process tool clients.

    One :class:`BridgeRpcServer` wraps the process's single bridge instance.
    Any number of gcu processes may connect concurrently; each request is
    dispatched in its own task so a slow ``navigate`` never head-of-line
    blocks a ``screenshot`` multiplexed on the same connection.
    """

    def __init__(self, bridge: BeelineBridge, port: int = CONTROL_PORT) -> None:
        self._bridge = bridge
        self._port = port
        self._server: object | None = None  # websockets.Server
        # Per-connection client state. Keyed by ws (the websockets.ServerConnection
        # is a stable object ref for the connection's lifetime). Each value:
        #   {"owner_pid": int | None, "connected_at": float (monotonic),
        #    "wants_notify": bool}
        # owner_pid is None until the client calls client_hello with its
        # HIVE_DESKTOP_PARENT_PID. The reaper closes connections whose
        # owner is dead (PID check) or who never identify within the grace
        # window — both signals that the WS is a zombie, not a real client.
        # wants_notify gates server-initiated push frames (see notify());
        # only opt-in subscribers receive them so a gcu MCP that never
        # subscribed doesn't get tab-handover messages it can't deliver.
        self._clients: dict[object, dict] = {}
        # Reaper coroutine handle, started in start() and cancelled in stop().
        self._reaper_task: asyncio.Task | None = None

    @property
    def is_listening(self) -> bool:
        return self._server is not None

    @property
    def active_client_count(self) -> int:
        """Count of clients that are *currently alive* by the reaper's rule.

        Used by the bridge_host idle watchdog. Returns zero when every
        connection is either reaper-dead (identified owner is gone) or
        never identified past its grace window — i.e. there's no real
        consumer left, regardless of how many half-open sockets persist.
        """
        now = time.monotonic()
        return sum(1 for info in self._clients.values() if self._client_alive(info, now))

    def runtime_alive(self) -> bool | None:
        """True iff any identified client has a live owner PID.

        None when no client has identified yet — the bridge has no
        independent evidence either way, so the caller should treat it
        as unknown (the BeelineBridge layer falls back to its env-derived
        hint in that case).
        """
        identified = [info["owner_pid"] for info in self._clients.values() if info.get("owner_pid") is not None]
        if not identified:
            return None
        return any(_pid_alive(pid) for pid in identified)

    def _client_alive(self, info: dict, now: float) -> bool:
        """Reaper predicate: should this connection still count as a client?

        Identified clients live as long as their owner PID is alive.
        Unidentified clients live as long as they're within the grace
        window — real MCPs send client_hello within milliseconds, so
        anything still un-hello'd after the grace is a zombie (typically
        an orphan from a previous app session, running pre-upgrade code
        that doesn't speak client_hello).
        """
        pid = info.get("owner_pid")
        if pid is not None:
            return _pid_alive(pid)
        return (now - info["connected_at"]) < _CLIENT_IDENTIFY_GRACE_S

    def _register_client_owner(self, ws, pid) -> dict:
        """Record this connection's owner (Electron) PID.

        Called by the client_hello dispatch path. Does not validate the
        PID is alive — the reaper does that on its own schedule, and a
        client claiming a dead PID is just a slightly-faster reap target.
        """
        if not isinstance(pid, int) or pid <= 0:
            return {"ok": False, "error": "invalid_pid", "pid": pid}
        info = self._clients.get(ws)
        if info is None:
            # The ws was already torn down between dispatch and registration.
            return {"ok": False, "error": "client_gone"}
        prev = info.get("owner_pid")
        info["owner_pid"] = pid
        if prev != pid:
            logger.info("client_hello: owner_pid %r → %d", prev, pid)
        return {"ok": True, "pid": pid, "previous": prev}

    async def notify(self, profile: str, text: str, **extra) -> int:
        """Push a server-initiated frame to every subscribing client.

        Used by side-panel-initiated tab adopt/release flows to inject a
        user-style message into the affected agent's conversation. The
        frame is unsolicited — it carries no ``rpc_id`` and so won't be
        matched against any pending future on the client side; the
        client's read loop routes it to the registered notify handler
        instead.

        Returns the number of clients the frame was successfully
        delivered to. Subscribers whose socket has already gone are
        silently skipped — the next reap pass will drop them.
        """
        frame = json.dumps(
            {
                "type": "notify",
                "profile": profile,
                "text": text,
                **extra,
            }
        )
        delivered = 0
        for ws, info in list(self._clients.items()):
            if not info.get("wants_notify"):
                continue
            try:
                await ws.send(frame)
                delivered += 1
            except Exception:
                # Connection vanished mid-push; cleanup happens via
                # _handle_client's finally clause.
                continue
        return delivered

    async def start(self) -> None:
        """Bind the control port. Idempotent — safe to call on every rebind."""
        if self._server is not None:
            return
        try:
            import websockets
        except ImportError:
            logger.warning("websockets not installed — bridge RPC server disabled")
            return

        self._server = await websockets.serve(
            self._handle_client,
            "127.0.0.1",
            self._port,
            max_size=_MAX_FRAME_BYTES,
            ping_interval=_PING_INTERVAL_S,
            ping_timeout=_PING_TIMEOUT_S,
        )
        self._reaper_task = asyncio.create_task(self._reap_loop())
        logger.info("Bridge RPC server listening on ws://127.0.0.1:%d", self._port)

    async def stop(self) -> None:
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            self._reaper_task = None
        if self._server is None:
            return
        self._server.close()
        try:
            await self._server.wait_closed()
        except Exception:
            pass
        self._server = None

    async def _reap_loop(self) -> None:
        """Force-close connections whose owner is dead or never identified.

        Two zombie classes:
          * Identified-but-orphaned: the MCP told us its owner PID; that
            PID has since died (e.g. Electron quit but the MCP process is
            stuck). Closing reclaims the slot so the idle watchdog can
            eventually exit the bridge_host.
          * Never-identified: the WS has been open longer than the
            grace window without sending client_hello. Either a pre-
            upgrade MCP that doesn't know the protocol, or a client that
            crashed before its handshake landed. Either way, no real
            consumer.

        Snapshot the dict before iterating — closing a ws fires its
        _handle_client finally clause which pops the entry, so the live
        view would mutate under us.
        """
        while True:
            try:
                await asyncio.sleep(_REAP_INTERVAL_S)
            except asyncio.CancelledError:
                return
            now = time.monotonic()
            zombies = [(ws, info) for ws, info in list(self._clients.items()) if not self._client_alive(info, now)]
            for ws, info in zombies:
                reason = "owner_dead" if info.get("owner_pid") is not None else "no_identify"
                logger.info("reaper: closing zombie client (%s, owner_pid=%r)", reason, info.get("owner_pid"))
                try:
                    await ws.close(code=1011, reason=reason)
                except Exception:
                    # Already closing / closed; the _handle_client finally
                    # clause will still tidy up the map entry.
                    pass

    async def _handle_client(self, ws) -> None:
        """Read requests off one client connection and fan them out.

        Each request runs in its own task: tool clients pipeline calls, and a
        long-running one must not stall the rest.
        """
        self._clients[ws] = {
            "owner_pid": None,
            "connected_at": time.monotonic(),
            "wants_notify": False,
        }
        tasks: set[asyncio.Task] = set()
        try:
            async for raw in ws:
                task = asyncio.create_task(self._dispatch(ws, raw))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        except Exception:
            # Client vanished — the per-request tasks will fail their own
            # sends harmlessly. Nothing to clean up here.
            pass
        finally:
            self._clients.pop(ws, None)

    async def _dispatch(self, ws, raw) -> None:
        rpc_id = None
        try:
            msg = json.loads(raw)
            rpc_id = msg.get("rpc_id")
            method = msg.get("method")
            args = msg.get("args") or []
            params = msg.get("params") or {}

            if method not in RPC_METHODS:
                await self._send(
                    ws,
                    rpc_id,
                    ok=False,
                    error={
                        "message": f"Unknown bridge RPC method: {method!r}",
                        "code": "unknown_method",
                        "retryable": False,
                    },
                )
                return

            # client_hello mutates the RPC server's per-connection state,
            # not the bridge's. Route it directly — the bridge has no
            # notion of "which ws is this call from" through the normal
            # getattr dispatch path.
            if method == "client_hello":
                pid = args[0] if args else params.get("pid")
                result = self._register_client_owner(ws, pid)
                await self._send(ws, rpc_id, ok=True, result=result)
                return

            # subscribe_notifications also mutates per-connection state —
            # flips a flag so notify() will push side-panel-initiated
            # tab adopt/release messages to this ws. The host runtime
            # subscribes (so it can route into inject_event); gcu MCP
            # subprocesses do not, since they have no agent loop to
            # deliver to.
            if method == "subscribe_notifications":
                info = self._clients.get(ws)
                if info is not None:
                    info["wants_notify"] = True
                await self._send(ws, rpc_id, ok=True, result={"ok": True})
                return

            # An allowlisted name resolves to either a coroutine method, a
            # plain sync method (status_payload), or a property value
            # (is_connected). Call it if callable, await it if awaitable.
            attr = getattr(self._bridge, method)
            result = attr(*args, **params) if callable(attr) else attr
            if inspect.isawaitable(result):
                result = await result

            await self._send(ws, rpc_id, ok=True, result=result)
        except Exception as e:
            await self._send(ws, rpc_id, ok=False, error=_error_payload(e))

    async def _send(self, ws, rpc_id, *, ok: bool, result=None, error=None) -> None:
        frame = {"rpc_id": rpc_id, "ok": ok}
        if ok:
            frame["result"] = result
        else:
            frame["error"] = error
        try:
            await ws.send(json.dumps(frame))
        except Exception:
            # Client disconnected mid-call; the result is simply discarded.
            pass


# ──────────────────────────────────────────────────────────────────────────
# Client — runs inside each disposable gcu MCP-server process
# ──────────────────────────────────────────────────────────────────────────


class BridgeClient:
    """Tool-side handle on the out-of-process bridge.

    Drop-in for the old ``get_bridge()`` reference: :meth:`call` returns the
    remote method's dict on success and raises :class:`BridgeClientError` on
    failure, matching the in-process contract the ``browser_*`` tools were
    written against. Reconnects transparently — a dropped control socket (the
    bridge restarted, say) just makes the next :meth:`call` redial.
    """

    def __init__(self, url: str | None = None) -> None:
        self._url = url or f"ws://127.0.0.1:{CONTROL_PORT}/control"
        self._ws = None  # websockets client connection
        self._pending: dict[str, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        # Serializes (re)connect so concurrent calls racing a dead socket
        # don't open several connections.
        self._connect_lock = asyncio.Lock()
        # Optional handler for unsolicited server-initiated frames
        # (currently: side-panel adopt/release notifications). When set,
        # frames carrying ``type: "notify"`` are dispatched here instead
        # of being treated as orphan RPC responses. Each invocation is
        # scheduled on the running loop so a slow handler can't stall the
        # read loop.
        self._notify_handler = None  # type: ignore[assignment]

    @property
    def is_connected(self) -> bool:
        return self._ws is not None

    async def connect(self) -> None:
        async with self._connect_lock:
            if self._ws is not None:
                return
            try:
                import websockets
            except ImportError as e:
                raise BridgeClientError(
                    "websockets not installed — cannot reach the browser bridge",
                    code="dependency_missing",
                    retryable=False,
                ) from e

            try:
                self._ws = await websockets.connect(
                    self._url,
                    max_size=_MAX_FRAME_BYTES,
                    ping_interval=_PING_INTERVAL_S,
                    ping_timeout=_PING_TIMEOUT_S,
                )
            except Exception as e:
                raise BridgeClientError(
                    "The browser bridge process is not reachable — it may be starting up or not running.",
                    code="bridge_unreachable",
                    retryable=True,
                ) from e
            self._reader_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    @staticmethod
    async def _safe_notify(handler, profile: str, text: str, extra: dict) -> None:
        """Invoke a notify handler in isolation — never let it crash the reader."""
        try:
            await handler(profile, text, extra)
        except Exception:
            logger.warning("notify handler raised for profile=%r", profile, exc_info=True)

    def set_notify_handler(self, handler) -> None:
        """Register a callback for server-initiated notify frames.

        ``handler`` is awaited with ``(profile: str, text: str, extra: dict)``
        when the bridge pushes a ``{"type":"notify", ...}`` frame. Setting
        ``None`` disables routing — frames will then be silently dropped
        (they have no rpc_id, so the existing future-matching path can't
        consume them).
        """
        self._notify_handler = handler

    async def _read_loop(self) -> None:
        """Route bridge frames to their waiting futures or the notify handler.

        RPC responses carry an ``rpc_id`` and resolve the matching pending
        future. Server-initiated frames (``type == "notify"``) are
        dispatched to ``_notify_handler`` in a fresh task so the loop
        keeps draining even if the handler blocks or raises.
        """
        ws = self._ws
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("type") == "notify":
                    handler = self._notify_handler
                    if handler is not None:
                        profile = msg.get("profile") or ""
                        text = msg.get("text") or ""
                        extra = {k: v for k, v in msg.items() if k not in ("type", "profile", "text")}
                        asyncio.create_task(self._safe_notify(handler, profile, text, extra))
                    continue
                fut = self._pending.pop(msg.get("rpc_id"), None)
                if fut is not None and not fut.done():
                    fut.set_result(msg)
        except Exception:
            pass
        finally:
            # The control socket dropped. Clear it so the next call redials,
            # and fail every in-flight call as retryable connection_lost so
            # no caller hangs waiting on a reply that will never come.
            if self._ws is ws:
                self._ws = None
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(
                        BridgeClientError(
                            "The browser bridge connection dropped.",
                            code="connection_lost",
                            retryable=True,
                        )
                    )
            self._pending.clear()

    async def call(self, method: str, *args, _timeout: float = _DEFAULT_CALL_TIMEOUT_S, **params):
        """Invoke a bridge method out-of-process.

        Positional ``args`` and keyword ``params`` are forwarded as-is, so a
        caller can mirror the bridge's in-process signature without knowing
        which arguments are positional. Returns the remote method's result on
        success; raises :class:`BridgeClientError` if the bridge is
        unreachable, the call times out, or the bridge method itself raised.
        """
        if self._ws is None:
            await self.connect()

        rpc_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rpc_id] = fut

        try:
            await self._ws.send(
                json.dumps(
                    {
                        "rpc_id": rpc_id,
                        "method": method,
                        "args": list(args),
                        "params": params,
                    }
                )
            )
        except Exception as e:
            self._pending.pop(rpc_id, None)
            self._ws = None  # force a redial next call
            raise BridgeClientError(
                f"Failed to send '{method}' to the browser bridge: {e}",
                code="bridge_unreachable",
                retryable=True,
            ) from e

        try:
            msg = await asyncio.wait_for(fut, timeout=_timeout)
        except TimeoutError as e:
            self._pending.pop(rpc_id, None)
            raise BridgeClientError(
                f"Browser bridge call '{method}' timed out after {_timeout:.0f}s",
                code="rpc_timeout",
                retryable=True,
            ) from e

        if msg.get("ok"):
            return msg.get("result")
        err = msg.get("error") or {}
        raise BridgeClientError(
            err.get("message", f"Browser bridge call '{method}' failed"),
            code=err.get("code"),
            retryable=bool(err.get("retryable")),
        )


# ──────────────────────────────────────────────────────────────────────────
# RemoteBridge — drop-in proxy used by the browser_* tools in client mode
# ──────────────────────────────────────────────────────────────────────────


class RemoteBridge:
    """Client-side stand-in for an out-of-process :class:`BeelineBridge`.

    ``get_bridge()`` returns one of these when the gcu process runs in client
    mode (``GCU_BRIDGE_MODE=client``). It is a drop-in replacement: the
    ``browser_*`` tools use it exactly as they used the in-process bridge.

      * Any allowlisted bridge method — ``navigate``, ``click``, ``screenshot``
        … — is reached via ``__getattr__`` and forwarded over RPC. Positional
        and keyword arguments pass straight through, so no call site changes.
      * ``is_connected`` and ``connection_help()`` answer *synchronously* from
        a cached snapshot (the tool guards read them before any ``await``); a
        background poller keeps that snapshot ~2s fresh.
      * On reconnect after a bridge restart, the proxy re-publishes the
        contexts this gcu owns (``_resync_contexts``) so ``/contexts`` and the
        side panel recover automatically.

    The proxy is what makes a gcu restart cheap — it simply reconnects to the
    still-running bridge process; no tabs or CDP state are lost.
    """

    _BRIDGE_DOWN_HELP = "The Hive browser bridge isn't running. Restart the Hive app, then retry."

    def __init__(self, url: str | None = None) -> None:
        self._client = BridgeClient(url)
        self._connected = False
        self._help = "Connecting to the Hive browser bridge…"
        self._poll_task: asyncio.Task | None = None
        # Last owner PID we successfully announced via client_hello. Tracked
        # so the steady-state poll doesn't re-announce every 2s once the
        # bridge has registered us. Reset to None on bridge disconnect so
        # a fresh reconnect re-announces (the bridge's per-connection
        # state was wiped when our previous WS closed).
        self._last_announced_owner_pid: int | None = None

    # ── synchronous connection snapshot (read by the tool guards) ─────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connection_help(self) -> str:
        return self._help

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open the control connection and start the health poller.

        Called once at gcu startup in place of the old ``bridge.start()``.
        """
        await self._client.connect()
        await self._refresh_state()
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        await self._client.close()

    async def _refresh_state(self) -> None:
        """Pull the live connection state from the bridge process."""
        try:
            self._connected = bool(await self._client.call("is_connected"))
            self._help = str(await self._client.call("connection_help"))
        except BridgeClientError:
            # Bridge process unreachable — distinct from "bridge up, extension
            # not connected"; Phase 5 surfaces that distinction in full.
            self._connected = False
            self._help = self._BRIDGE_DOWN_HELP
            # Bridge dropped — the next reconnect lands on a fresh WS, so
            # the prior client_hello no longer applies. Re-announce on
            # whatever poll tick first sees the bridge back.
            self._last_announced_owner_pid = None
            return
        await self._send_client_hello_if_needed()

    async def _send_client_hello_if_needed(self) -> None:
        """Identify our owner (Electron) PID to the bridge on this connection.

        The bridge needs the owner PID to distinguish live clients from
        orphans across app sessions: it reaps connections whose owner is
        dead. Our HIVE_DESKTOP_PARENT_PID env was set by the current
        Electron at spawn time, so this MCP knows the right answer.

        Idempotent — once the bridge has registered us this poll tick is
        a no-op. Triggered on every _refresh_state so we re-announce
        promptly after any disconnect/reconnect (the bridge's per-WS
        state is wiped when the WS closes).
        """
        raw = os.getenv("HIVE_DESKTOP_PARENT_PID")
        if not raw or not raw.isdigit():
            return
        pid = int(raw)
        if pid == self._last_announced_owner_pid:
            return
        try:
            await self._client.call("client_hello", pid)
            self._last_announced_owner_pid = pid
        except BridgeClientError:
            # Old bridge build without client_hello, or transient RPC
            # error. Leave _last_announced_owner_pid unchanged so the
            # next poll tick retries.
            pass

    async def _poll_loop(self) -> None:
        was_up = True
        while True:
            await asyncio.sleep(_STATE_POLL_INTERVAL_S)
            await self._refresh_state()
            # Detect the bridge process coming back after a restart and
            # re-publish the contexts this gcu owns, so /contexts and the
            # side panel recover without waiting for fresh create_context
            # calls.
            up = self._client.is_connected
            if up and not was_up:
                await self._resync_contexts()
            was_up = up

    async def _resync_contexts(self) -> None:
        """Re-publish this gcu's contexts to a (re)started bridge process.

        The bridge's context registry is in-memory; if the bridge process
        restarted it came back empty. Re-push every group this gcu still
        tracks so ``/contexts`` is authoritative again.
        """
        try:
            from .tools.lifecycle import _contexts

            for profile, ctx in list(_contexts.items()):
                group_id = ctx.get("groupId")
                if group_id is not None:
                    await self._client.call(
                        "register_context",
                        profile,
                        group_id,
                        ctx.get("name"),
                        browser_profile=ctx.get("browser_profile") or "default",
                    )
        except Exception:
            pass  # best-effort; the next poll tick retries

    # ── everything else: forward to the bridge process ───────────────────

    def __getattr__(self, name: str):
        # __getattr__ only fires for names NOT found normally, so real
        # attributes (is_connected, connection_help, connect, stop,
        # _client, …) never reach here.
        if name not in RPC_METHODS:
            raise AttributeError(name)

        async def _forward(*args, **kwargs):
            return await self._client.call(name, *args, **kwargs)

        _forward.__name__ = name
        return _forward
