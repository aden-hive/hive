"""aiohttp Application factory for the Hive HTTP API server."""

import asyncio
import hmac
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError

from framework.server.session_manager import Session, SessionManager

logger = logging.getLogger(__name__)


# Dedicated executor for HTTP request handlers. Python's default executor
# (used by asyncio.to_thread and run_in_executor(None, ...)) is sized at
# min(32, cpu_count + 4) — on the 2-CPU sandbox VM that is 6 workers total,
# shared across the 38 blocking-IO sites in this package. Queen tool calls,
# credential presyncs, and colony data reads all fight for the same 6 slots;
# under any concurrency the colony UI's /api/colonies/{id}/data/* reads
# queue behind blocked queen work and time out with the 15 s
# `colony_data_timeout` 503. That failure mode was reproduced live on
# sandbox `i27a5xl0bvat6bsnrkj0x` 2026-07-03 (see the plan file).
#
# Isolating HTTP handlers on their own pool means a runaway queen tool
# call can't stall the colony UI. 32 workers is a heuristic — small
# enough to bound thread overhead (~32 × 200 KB stack ≈ 6 MB), 5× the
# default cpu+4 which is where the starvation reproduces, and can be
# raised via HIVE_REQUEST_EXECUTOR_MAX without a template roll.
_REQUEST_EXECUTOR: ThreadPoolExecutor | None = None


def get_request_executor() -> ThreadPoolExecutor:
    """Return the shared request executor, creating it on first use.

    Callers in `framework.server.routes_*` should route blocking work
    through this executor (via `loop.run_in_executor(get_request_executor(),
    ...)`) instead of Python's default. Non-HTTP blocking work (queen
    boot, resource sampling) continues to use the default executor
    intentionally — the whole point of a separate pool is that "one
    runaway queen tool call cannot make the colony UI hang".
    """
    global _REQUEST_EXECUTOR
    if _REQUEST_EXECUTOR is None:
        max_workers = int(os.environ.get("HIVE_REQUEST_EXECUTOR_MAX", "32"))
        _REQUEST_EXECUTOR = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="hive-req",
        )
    return _REQUEST_EXECUTOR


# Anchor to the repository root so allowed roots are independent of CWD.
# app.py lives at core/framework/server/app.py, so four .parent calls
# reach the repo root where exports/ and examples/ live.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_ALLOWED_AGENT_ROOTS: tuple[Path, ...] | None = None


def _has_encrypted_credentials() -> bool:
    """Return True when an encrypted credential store already exists on disk."""
    from framework.config import HIVE_HOME

    cred_dir = HIVE_HOME / "credentials" / "credentials"
    return cred_dir.is_dir() and any(cred_dir.glob("*.enc"))


def _wipe_unreadable_credentials() -> None:
    """Delete every encrypted credential file + the metadata index.

    Called from the credential-store self-heal block when we detect
    .enc files that no current process can decrypt (HIVE_CREDENTIAL_KEY
    is missing from every source). Each .enc is permanent garbage in
    this state; keeping them would block every future save with a
    NotImplementedError from EnvVarStorage.

    Bounded scope: only touches credentials/credentials/*.enc and
    credentials/metadata/index.json under HIVE_HOME. Logs each
    deletion so the audit trail survives the wipe. The .cache_version
    marker is left in place because it carries no decryptable state.
    """
    from framework.config import HIVE_HOME

    cred_dir = HIVE_HOME / "credentials" / "credentials"
    if cred_dir.is_dir():
        for enc in cred_dir.glob("*.enc"):
            try:
                enc.unlink()
                logger.error("credential-self-heal: removed unreadable %s", enc.name)
            except OSError as exc:
                logger.warning("credential-self-heal: failed to remove %s: %s", enc, exc)

    metadata_dir = HIVE_HOME / "credentials" / "metadata"
    if metadata_dir.is_dir():
        index_path = metadata_dir / "index.json"
        if index_path.exists():
            try:
                index_path.unlink()
                logger.error("credential-self-heal: removed stale index.json")
            except OSError as exc:
                logger.warning("credential-self-heal: failed to remove index.json: %s", exc)


def _get_allowed_agent_roots() -> tuple[Path, ...]:
    """Return resolved allowed root directories for agent loading.

    Roots are anchored to the repository root (derived from ``__file__``)
    so the allowlist is correct regardless of the process's working
    directory. The hive-home subtrees honour ``HIVE_HOME`` so the desktop's
    per-user root is allowed in addition to (or instead of) ``~/.hive``.
    """
    global _ALLOWED_AGENT_ROOTS
    if _ALLOWED_AGENT_ROOTS is None:
        from framework.config import COLONIES_DIR, HIVE_HOME

        _ALLOWED_AGENT_ROOTS = (
            COLONIES_DIR.resolve(),  # $HIVE_HOME/colonies/
            (_REPO_ROOT / "exports").resolve(),  # compat fallback
            (_REPO_ROOT / "examples").resolve(),
            (HIVE_HOME / "agents").resolve(),
        )
    return _ALLOWED_AGENT_ROOTS


def validate_agent_path(agent_path: str | Path) -> Path:
    """Validate that an agent path resolves inside an allowed directory.

    Prevents arbitrary code execution via ``importlib.import_module`` by
    restricting agent loading to known safe directories: ``exports/``,
    ``examples/``, and ``~/.hive/agents/``.

    Returns the resolved ``Path`` on success.

    Raises:
        ValueError: If the path is outside all allowed roots.
    """
    resolved = Path(agent_path).expanduser().resolve()
    for root in _get_allowed_agent_roots():
        if resolved.is_relative_to(root) and resolved != root:
            return resolved
    raise ValueError("agent_path must be inside an allowed directory ($HIVE_HOME/colonies/, exports/, examples/, or $HIVE_HOME/agents/)")


def safe_path_segment(value: str) -> str:
    """Validate a URL path parameter is a safe filesystem name.

    Raises HTTPBadRequest if the value contains path separators or
    traversal sequences.  aiohttp decodes ``%2F`` inside route params,
    so a raw ``{session_id}`` can contain ``/`` or ``..`` after decoding.
    """
    if not value or value == "." or "/" in value or "\\" in value or ".." in value:
        raise web.HTTPBadRequest(reason="Invalid path parameter")
    return value


def resolve_session(request: web.Request):
    """Resolve a Session from {session_id} in the URL.

    Returns (session, None) on success or (None, error_response) on failure.
    """
    manager: SessionManager = request.app["manager"]
    sid = request.match_info["session_id"]
    session = manager.get_session(sid)
    if not session:
        return None, web.json_response({"error": f"Session '{sid}' not found"}, status=404)
    return session, None


def sessions_dir(session: Session) -> Path:
    """Resolve the worker sessions directory for a session.

    Storage layout: $HIVE_HOME/agents/{agent_name}/sessions/
    Requires a worker to be loaded (worker_path must be set).
    """
    if session.worker_path is None:
        raise ValueError("No worker loaded — no worker sessions directory")
    from framework.config import HIVE_HOME

    agent_name = session.worker_path.name
    return HIVE_HOME / "agents" / agent_name / "sessions"


# Allowed CORS origins (localhost on any port)
_CORS_ORIGINS = {"http://localhost", "http://127.0.0.1"}


def _is_cors_allowed(origin: str) -> bool:
    """Check if origin is localhost/127.0.0.1 on any port."""
    if not origin:
        return False
    for base in _CORS_ORIGINS:
        if origin == base or origin.startswith(base + ":"):
            return True
    return False


@web.middleware
async def cors_middleware(request: web.Request, handler):
    """CORS middleware scoped to localhost origins."""
    origin = request.headers.get("Origin", "")

    # Handle preflight
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc

    if _is_cors_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "3600"

    return response


@web.middleware
async def no_cache_api_middleware(request: web.Request, handler):
    """Prevent browsers from caching API responses.

    Without this, a one-off bad response (e.g. the SPA catch-all leaking
    index.html for an /api/* URL before a route was registered) can get
    pinned in the browser's disk cache and replayed forever, since our
    JSON handlers don't emit ETag/Last-Modified and browsers fall back
    to heuristic freshness.
    """
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Desktop shared-secret auth middleware.
#
# When the runtime is spawned by the Electron main process, a fresh random
# token is passed via ``HIVE_DESKTOP_TOKEN``. Every request from main must
# carry the matching ``X-Hive-Token`` header. If the env var is unset (e.g.
# running ``hive serve`` directly from a terminal), the check is skipped —
# OSS behaviour is preserved.
# ---------------------------------------------------------------------------
_EXPECTED_DESKTOP_TOKEN: str | None = os.environ.get("HIVE_DESKTOP_TOKEN") or None


@web.middleware
async def desktop_auth_middleware(request: web.Request, handler):
    if _EXPECTED_DESKTOP_TOKEN is None:
        return await handler(request)
    provided = request.headers.get("X-Hive-Token", "")
    if not hmac.compare_digest(provided, _EXPECTED_DESKTOP_TOKEN):
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


@web.middleware
async def error_middleware(request: web.Request, handler):
    """Catch exceptions and return JSON error responses.

    Returns a generic error message to the client to avoid leaking
    internal details (file paths, config values, stack traces).
    The full exception is still logged server-side (both the rich
    logger and a bare traceback on stderr so it survives inside
    firecracker VMs where the desktop's runtime.log isn't wired to
    the rich sink).
    """
    try:
        return await handler(request)
    except web.HTTPException:
        raise  # Let aiohttp handle its own HTTP exceptions
    except Exception:
        logger.exception("Unhandled error on %s %s", request.method, request.path)
        # The Rich logging handler formats exception text to a separate sink
        # that isn't always captured by parent processes (the desktop's
        # runtime.log in particular). Print a plain traceback to stderr so
        # the diagnostic always survives even when the rich console doesn't.
        import sys as _sys
        import traceback as _tb

        print(
            f"[error_middleware] {request.method} {request.path}",
            file=_sys.stderr,
            flush=True,
        )
        _tb.print_exc(file=_sys.stderr)
        _sys.stderr.flush()
        return web.json_response(
            {"error": "Internal server error"},
            status=500,
        )


@web.middleware
async def access_log_middleware(request: web.Request, handler):
    """Log ``METHOD path -> status (duration)`` for every request.

    The runtime otherwise records no HTTP access line, which makes
    client-reported failures (e.g. a download 404 raised in the Electron
    main process, invisible to the renderer's Network tab) impossible to
    trace. Non-2xx responses and slow requests (>1s — the classic sign of
    event-loop-stalling work) are logged at WARNING so they stand out.
    """
    started = time.monotonic()

    def _line(status: int) -> None:
        elapsed = time.monotonic() - started
        slow = elapsed > 1.0
        logger.log(
            logging.WARNING if (status >= 400 or slow) else logging.INFO,
            "[access] %s %s -> %d (%.0fms)%s",
            request.method,
            request.rel_url,
            status,
            elapsed * 1000,
            " SLOW" if slow else "",
        )

    try:
        response = await handler(request)
    except web.HTTPException as exc:
        _line(exc.status)
        raise
    _line(response.status)
    return response


def _is_pid_alive(pid: int) -> bool:
    """Cross-platform alive-check that won't accidentally kill the target.

    On Windows, ``os.kill(pid, 0)`` is NOT a safe probe: ``CTRL_C_EVENT``
    is 0, so CPython first tries ``GenerateConsoleCtrlEvent`` and then
    silently falls through to ``OpenProcess(PROCESS_ALL_ACCESS) +
    TerminateProcess(handle, 0)`` when the target isn't in the same
    console — actually killing the parent. Use the Win32 API directly.
    """
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            # ERROR_ACCESS_DENIED (5) means the process exists but is protected.
            return kernel32.GetLastError() == 5
        exit_code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return exit_code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


async def _parent_watchdog(parent_pid: int) -> None:
    """Self-destruct when the desktop parent (Electron main) dies.

    Without this, an abrupt Electron shutdown leaves ``hive.exe`` running
    and holding ``runtime-venv\\Scripts\\hive.exe`` — the next install
    or upgrade then hits "another program is using this file" when
    ``uv sync`` tries to update the venv. Polls every 2s; on parent
    death calls ``os._exit(0)`` to skip aiohttp shutdown (each MCP
    server's own watchdog will reap that subtree within 2s).
    """
    while True:
        await asyncio.sleep(2.0)
        if not _is_pid_alive(parent_pid):
            logger.warning("Parent PID %d gone — hive serve exiting", parent_pid)
            os._exit(0)


async def _start_parent_watchdog(app: web.Application) -> None:
    """aiohttp on_startup hook: arm the parent watchdog if Electron set its PID."""
    parent_pid_env = os.environ.get("HIVE_DESKTOP_PARENT_PID")
    if not parent_pid_env:
        return
    try:
        parent_pid = int(parent_pid_env)
    except ValueError:
        logger.warning("Invalid HIVE_DESKTOP_PARENT_PID=%r", parent_pid_env)
        return
    asyncio.create_task(_parent_watchdog(parent_pid))
    logger.info("Parent watchdog armed for PID %d", parent_pid)


# Set once the graceful (on_shutdown) browser reap has run, so the atexit
# fallback doesn't redundantly re-open a client connection on a clean exit.
_browsers_reaped = False


async def _reap_browser_contexts() -> None:
    """Best-effort close of every browser tab group still registered with the
    bridge.

    The per-worker done-callback and the colony backstop already reap most
    groups, but two gaps remain: a Queen-only session (its browser profile is
    ``profile=session.id``, reaped by no colony) and a non-graceful process
    exit. This drains the bridge's authoritative registry directly so neither
    leaks. ``destroy_context`` is idempotent, so overlapping with the other
    reapers is harmless. SIGKILL still bypasses this entirely — the bridge-side
    orphan sweep is the backstop there.
    """
    global _browsers_reaped
    try:
        from gcu.browser.bridge import get_bridge, init_bridge
        from gcu.browser.tools.lifecycle import drain_dead_letter
    except ImportError:
        return  # gcu browser tools not present in this build

    bridge = get_bridge()
    if bridge is None:
        # Browser tools run in a separate gcu subprocess, so this process has no
        # bridge of its own — reach the durable bridge_host as a client.
        try:
            bridge = init_bridge(mode="client")
        except Exception:
            return
    connect = getattr(bridge, "connect", None)
    if callable(connect) and not bridge.is_connected:
        try:
            await connect()
        except Exception:
            return
    if not bridge.is_connected:
        return
    try:
        contexts = await bridge.list_contexts()
    except Exception:
        return
    for entry in contexts or []:
        group_id = entry.get("groupId")
        if group_id is None:
            continue
        try:
            await bridge.destroy_context(group_id)
        except Exception as exc:
            logger.debug("shutdown reaper: destroy_context(%s) failed: %s", group_id, exc)
    try:
        await drain_dead_letter()
    except Exception:
        pass
    _browsers_reaped = True


def _atexit_reap_browsers() -> None:
    """Sync atexit fallback for a non-graceful exit that bypassed on_shutdown.

    Strictly best-effort: spins a throwaway loop with a short timeout and never
    raises. Skipped when the graceful reaper already ran. The bridge-side orphan
    sweep is the authoritative backstop, so a miss here is not fatal.
    """
    if _browsers_reaped:
        return
    try:
        asyncio.run(asyncio.wait_for(_reap_browser_contexts(), timeout=5.0))
    except Exception:
        pass


async def _on_shutdown(app: web.Application) -> None:
    """Gracefully unload all agents on server shutdown, then reap any browser
    tab groups the session/colony reapers didn't cover."""
    sampler = app.get("resource_sampler")
    if sampler is not None:
        sampler.cancel()
    manager: SessionManager = app["manager"]
    await manager.shutdown_all()
    await _reap_browser_contexts()
    # Tear down the request executor last: shutting it down before
    # manager.shutdown_all() could race with a handler that's still
    # completing a graceful in-flight response. wait=False + cancel_futures
    # so a stuck handler can't block server exit — the caller is going
    # away anyway.
    global _REQUEST_EXECUTOR
    if _REQUEST_EXECUTOR is not None:
        _REQUEST_EXECUTOR.shutdown(wait=False, cancel_futures=True)
        _REQUEST_EXECUTOR = None


def _runtime_resource_context(app: web.Application) -> dict:
    """Cheap in-memory context (active workers / colonies / sessions) that gives
    the raw resource numbers meaning. Never raises."""
    try:
        manager: SessionManager = app["manager"]
        sessions = manager.list_sessions()
        active_workers = colonies = 0
        for rt in manager.iter_colony_runtimes():
            colonies += 1
            active_workers += int(getattr(rt, "active_worker_count", 0) or 0)
        return {"sessions": len(sessions), "active_workers": active_workers, "colonies": colonies}
    except Exception:
        return {"sessions": None, "active_workers": None, "colonies": None}


async def _resource_sampler_loop(app: web.Application) -> None:
    """Periodically sample the runtime's resource footprint into the monitor's
    rolling history. Wrapped so a transient probe failure never kills the loop;
    the monitor logs a WARNING/ERROR on any verdict degradation."""
    from framework.host.runtime_resources import SAMPLE_INTERVAL_S, get_monitor

    monitor = get_monitor()
    loop = asyncio.get_running_loop()
    # sample() does a SYNCHRONOUS psutil walk over every process (tens of ms,
    # and most during an OOM run-up when there are the most processes), so run
    # it in a thread to keep the aiohttp event loop responsive. record() is
    # cheap + lock-guarded, so it stays on the loop thread (preserves verdict-
    # transition log ordering). Priming seeds the per-process CPU deltas.
    try:
        await loop.run_in_executor(None, monitor.sample, _runtime_resource_context(app))
    except Exception:
        logger.debug("resource sampler: priming sample failed", exc_info=True)
    while True:
        try:
            await asyncio.sleep(SAMPLE_INTERVAL_S)
        except asyncio.CancelledError:
            return
        try:
            ctx = _runtime_resource_context(app)
            ctx["bridge_connected"] = bool((await _probe_browser_bridge()).get("connected"))
            sample = await loop.run_in_executor(None, monitor.sample, ctx)
            monitor.record(sample)
        except Exception:
            logger.debug("resource sampler: tick failed", exc_info=True)


async def start_resource_sampler(app: web.Application) -> None:
    """aiohttp on_startup hook: arm the resource sampler for the server's life."""
    app["resource_sampler"] = asyncio.create_task(_resource_sampler_loop(app))
    logger.info("resource sampler started")


async def handle_health(request: web.Request) -> web.Response:
    """GET /api/health — simple health check (+ a resource-health rollup)."""
    from framework.host.runtime_resources import get_monitor

    manager: SessionManager = request.app["manager"]
    sessions = manager.list_sessions()
    # Request-executor snapshot. The three underscore-private attributes
    # (_max_workers, _threads, _work_queue) are stable across CPython
    # versions and are the only in-process way to peek at pool state
    # without pulling in a metrics dependency. If HTTP handlers ever start
    # queueing again, an operator can `curl /api/health` and read the
    # `queued` field at a glance instead of blindly trying reproductions.
    ex = get_request_executor()
    executor_state = {
        "max_workers": ex._max_workers,
        "active": len(ex._threads),
        "queued": ex._work_queue.qsize(),
    }
    return web.json_response(
        {
            "status": "ok",
            "sessions": len(sessions),
            "agents_loaded": sum(1 for s in sessions if s.colony_id is not None),
            "resources": get_monitor().rollup(),
            "request_executor": executor_state,
        }
    )


async def handle_resources(request: web.Request) -> web.Response:
    """GET /api/health/resources — the built-in system-resource monitor.

    Returns the current sample (system memory, per-component RSS/CPU, chrome
    renderers, active-worker context), a health verdict, the thresholds, and a
    compact rolling history. ``?history=N`` bounds the history slice (default
    120 ≈ 30 min at 15 s); ``?history=0`` for snapshot-only; ``?full=1`` for the
    whole buffer.
    """
    from framework.host.runtime_resources import get_monitor

    q = request.rel_url.query
    # Explicit boolean — "?full=0"/"full=false" must NOT be truthy.
    if q.get("full", "").lower() in ("1", "true", "yes"):
        history_n: int | None = None
    else:
        try:
            history_n = int(q.get("history", "120"))
        except ValueError:
            history_n = 120
    return web.json_response(get_monitor().snapshot(history_n=history_n))


async def _probe_browser_bridge() -> dict:
    """Probe the local GCU bridge and return its status.

    Returns a dict with at minimum ``{bridge, connected}``; when the
    bridge is reachable, also includes ``connections`` and
    ``last_pong_age_ms`` so the UI can tell "extension stale" apart
    from "extension healthy".
    """
    import asyncio

    bridge_port = int(os.environ.get("HIVE_BRIDGE_PORT", "9229"))
    status_port = bridge_port + 1

    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", status_port), timeout=0.5)
    except Exception:
        return {"bridge": False, "connected": False, "connections": []}
    # try/finally so the socket is closed on EVERY path — the resource sampler
    # calls this every ~15s, so a read-timeout/parse leak would accumulate FDs.
    try:
        writer.write(b"GET /status HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(4096), timeout=0.5)
        if b"\r\n\r\n" in raw:
            body = raw.split(b"\r\n\r\n", 1)[1]
            import json as _json

            data = _json.loads(body)
            connections = data.get("connections") or []
            primary = connections[0] if connections else {}
            return {
                "bridge": True,
                "connected": bool(data.get("connected", False)),
                "connections": connections,
                "last_pong_age_ms": primary.get("last_pong_age_ms"),
                "extension_version": primary.get("version"),
                "uptime_ms": data.get("uptime_ms"),
            }
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    return {"bridge": False, "connected": False, "connections": []}


async def _probe_browser_contexts() -> list[dict]:
    """Fetch the bridge's live per-profile context list (incl. active tab title/url).

    Hits ``GET /contexts`` on the bridge status port — the same port
    ``_probe_browser_bridge`` uses for ``/status``. The bridge builds this from
    its context registry plus a live ``tab.list`` RPC to the extension, so each
    row carries the profile's tabs with titles/urls. Returns the ``contexts``
    list (``[{profile, activeTab, tabs:[{id,title,url,active}], ...}]``); empty
    on any failure (bridge down, parse error). Slightly heavier than ``/status``
    (one RPC roundtrip per tab group), so callers should only invoke it when
    they actually need tab titles — e.g. a session-scoped status stream.
    """
    import asyncio
    import json as _json

    bridge_port = int(os.environ.get("HIVE_BRIDGE_PORT", "9229"))
    status_port = bridge_port + 1
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", status_port), timeout=0.5)
    except Exception:
        return []
    try:
        writer.write(b"GET /contexts HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        await writer.drain()
        # /contexts can exceed a single read (one row per tab group), and the
        # bridge replies with Connection: close — so read to EOF rather than a
        # fixed buffer that would truncate the JSON body.
        raw = await asyncio.wait_for(reader.read(), timeout=1.0)
        if b"\r\n\r\n" in raw:
            body = raw.split(b"\r\n\r\n", 1)[1]
            data = _json.loads(body)
            if isinstance(data, dict) and isinstance(data.get("contexts"), list):
                return data["contexts"]
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    return []


def _active_tab_for_profile(contexts: list[dict], profile: str) -> dict | None:
    """Pick ``profile``'s focused tab ``{title, url}`` from a ``/contexts`` list.

    Matches the context row by profile (== session id for queen DM sessions),
    then the tab whose id == ``activeTab`` (falling back to the tab flagged
    ``active``). Returns None when the profile owns no context or no resolvable
    active tab — the caller renders plain connection status in that case.
    """
    entry = next((c for c in contexts if c.get("profile") == profile), None)
    if not entry:
        return None
    tabs = entry.get("tabs") or []
    active_id = entry.get("activeTab")
    tab = next((t for t in tabs if t.get("id") == active_id), None)
    if tab is None:
        tab = next((t for t in tabs if t.get("active")), None)
    if tab is None:
        return None
    title = tab.get("title")
    url = tab.get("url")
    if not title and not url:
        return None
    # ``id`` lets the badge ask the bridge to raise this exact tab on click.
    return {"id": tab.get("id"), "title": title, "url": url}


async def _reveal_browser_tab(tab_id: int) -> dict:
    """Ask the bridge to raise the Chrome window for ``tab_id`` and focus it.

    POSTs to the bridge status port's ``/tabs/{id}/reveal`` — a user-initiated
    "jump to this tab" that, unlike the agent-facing ``tab.activate``, also
    pulls the Chrome window to the foreground. Returns the bridge's JSON
    response, or an ``{ok: False}`` error dict if the bridge is unreachable.
    """
    import asyncio
    import json as _json

    bridge_port = int(os.environ.get("HIVE_BRIDGE_PORT", "9229"))
    status_port = bridge_port + 1
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", status_port), timeout=0.5)
    except Exception:
        return {"ok": False, "error": "bridge unreachable"}
    try:
        req = (f"POST /tabs/{tab_id}/reveal HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n").encode()
        writer.write(req)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), timeout=2.0)
        if b"\r\n\r\n" in raw:
            body = raw.split(b"\r\n\r\n", 1)[1]
            try:
                return _json.loads(body)
            except Exception:
                return {"ok": True}
        return {"ok": False, "error": "no response"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def handle_browser_tab_reveal(request: web.Request) -> web.Response:
    """POST /api/browser/tab/reveal — bring a browser tab to the foreground.

    Body: ``{"tab_id": int}``. Backs the status badge's active-tab chip so
    clicking it jumps the user to that Chrome tab and raises its window.
    """
    try:
        body = await request.json() if request.can_read_body else {}
    except Exception:
        body = {}
    tab_id = body.get("tab_id")
    if not isinstance(tab_id, int):
        return web.json_response({"ok": False, "error": "tab_id (int) is required"}, status=400)
    return web.json_response(await _reveal_browser_tab(tab_id))


async def _browser_status_payload(session_id: str | None) -> dict:
    """One status probe → the payload shape both the GET and the SSE emit.

    ``health`` mirrors the stream's classification; ``active_tab`` is
    resolved only when scoped to a session AND the extension is connected
    (the /contexts probe costs an RPC per tab group).
    """
    status = await _probe_browser_bridge()
    pong = status.get("last_pong_age_ms")
    health = (
        "healthy"
        if status.get("connected") and (pong is None or pong < 15000)
        else "stale"
        if status.get("connected")
        else "disconnected"
        if status.get("bridge")
        else "offline"
    )
    payload = {**status, "health": health}
    if session_id:
        active_tab: dict | None = None
        if status.get("connected"):
            active_tab = _active_tab_for_profile(await _probe_browser_contexts(), session_id)
        payload["active_tab"] = active_tab
    return payload


async def handle_browser_status(request: web.Request) -> web.Response:
    """GET /api/browser/status — proxy the GCU bridge status check server-side.

    Checks http://127.0.0.1:9230/status so the browser never makes a
    cross-origin request that would log ERR_CONNECTION_REFUSED in the console.
    Accepts ``?session_id=`` to include that session's ``active_tab`` — the
    web UI polls this instead of holding the SSE stream open (each
    EventSource permanently occupies one of the browser's ~6 same-origin
    sockets; the stream endpoint remains for the desktop shell, whose SSE
    rides IPC and is exempt from that cap).
    """
    return web.json_response(await _browser_status_payload(request.query.get("session_id")))


async def handle_browser_status_stream(request: web.Request) -> web.StreamResponse:
    """GET /api/browser/status/stream — SSE feed of bridge status.

    Emits a ``status`` event immediately, then again only when the
    probe result changes. Polls the local bridge every 3s; that's the
    same cadence the frontend used before, but we absorb it
    server-side instead of the browser burning a request.

    When a ``session_id`` query param is present, the payload also carries
    ``active_tab`` (``{title, url}`` or ``null``) for that session's own
    browser context — used by the badge to show "which tab is this queen on".
    Resolving the title costs an extra ``/contexts`` RPC, so it's skipped
    entirely for the unscoped (global) stream.
    """
    import asyncio
    import json as _json

    session_id = request.query.get("session_id")

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    async def _send(event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {_json.dumps(data)}\n\n"
        await resp.write(payload.encode("utf-8"))

    last: tuple | None = None
    quiet_ticks = 0
    try:
        while True:
            payload = await _browser_status_payload(session_id)
            active_tab = payload.get("active_tab") or {}
            signature = (
                payload["bridge"],
                payload["connected"],
                payload["health"],
                active_tab.get("title"),
                active_tab.get("url"),
            )
            if signature != last:
                await _send("status", payload)
                last = signature
                quiet_ticks = 0
            else:
                # Keepalive: on a steady bridge this stream used to emit
                # zero bytes indefinitely, so a silently-dead TCP path was
                # indistinguishable from "nothing changed". Comment every
                # ~15s keeps intermediaries and the client's liveness view
                # honest without waking EventSource message handlers.
                quiet_ticks += 1
                if quiet_ticks >= 5:
                    await resp.write(b": keepalive\n\n")
                    quiet_ticks = 0
            await asyncio.sleep(3.0)
    except (asyncio.CancelledError, ConnectionResetError, ClientConnectionResetError):
        logger.debug("browser status stream: client disconnected")
    except Exception as exc:
        logger.warning("browser status stream error: %s", exc, exc_info=True)
    return resp


def create_app(model: str | None = None) -> web.Application:
    """Create and configure the aiohttp Application.

    Args:
        model: Default LLM model for agent loading.

    Returns:
        Configured aiohttp Application ready to run.
    """
    # Publish the email-senders flag into os.environ before anything can
    # spawn an MCP subprocess — they inherit it, and hive_tools reads it to
    # decide whether to register the sender tools at all. Off by default.
    from framework.config import sync_email_senders_env

    sync_email_senders_env()

    # Desktop mode: the runtime is always a subprocess of the Electron main
    # process, which reaches it via IPC and the `hive://` custom protocol.
    # There is no browser origin to authorize, so CORS is unnecessary.
    # The auth middleware enforces the shared-secret token when the env var
    # is set (i.e. when Electron spawned us); it is a no-op otherwise.
    app = web.Application(
        middlewares=[access_log_middleware, desktop_auth_middleware, no_cache_api_middleware, error_middleware],
        # Default is 1 MB — too small for chat messages with multiple
        # base64-encoded images or PDF attachments.
        client_max_size=20 * 1024 * 1024,  # 20 MB
    )

    # Initialize credential store (before SessionManager so it can be shared)
    from framework.credentials.store import CredentialStore

    try:
        from framework.credentials.validation import ensure_credential_key_env

        # Load ALL credentials: HIVE_CREDENTIAL_KEY, ADEN_API_KEY, and LLM keys
        ensure_credential_key_env()

        # SELF-HEAL the "encrypted credentials exist but no key anywhere"
        # state, which is unrecoverable and traps the system in read-only
        # mode forever. Observed failure pattern: a volume that was
        # populated under a prior runtime (e.g. team-migration copy that
        # missed ~/.hive/secrets/credential_key, or a desktop that ran
        # with HIVE_CREDENTIAL_KEY in env without persisting it to disk)
        # ends up with .enc files no current process can decrypt. The
        # prior behavior — warn and continue with `with_env_storage()`
        # (read-only) — meant EVERY subsequent /api/credentials POST
        # returned 500 NotImplementedError, with the user seeing
        # "Missing Anthropic API Key" forever on every queen run.
        #
        # The .enc files in this state are permanent garbage. Wiping
        # them is the only path forward; the alternative is staying
        # broken until manual intervention. Bounded data loss: the
        # user re-pushes credentials via the desktop's integrations
        # UI on the next session.
        if not os.environ.get("HIVE_CREDENTIAL_KEY"):
            if _has_encrypted_credentials():
                logger.error(
                    "DETECTED unreadable credential state: encrypted "
                    "credentials exist but HIVE_CREDENTIAL_KEY is missing "
                    "from env, file, and shell config. The .enc files "
                    "cannot be decrypted by any process. Wiping them and "
                    "generating a fresh key so credential saves work again. "
                    "Re-push credentials via the desktop integrations UI."
                )
                _wipe_unreadable_credentials()
            try:
                from framework.credentials.key_storage import (
                    generate_and_save_credential_key,
                )

                generate_and_save_credential_key()
                logger.info("Generated and persisted HIVE_CREDENTIAL_KEY to ~/.hive/secrets/credential_key")
            except Exception as exc:
                logger.warning("Could not auto-persist HIVE_CREDENTIAL_KEY: %s", exc)

        # After self-heal, HIVE_CREDENTIAL_KEY is set; the read-only
        # branch can no longer be reached on this startup path. Keep
        # the conditional defensively in case a future change reorders
        # this block — but if we ever hit the read-only branch now,
        # something's structurally wrong.
        if not os.environ.get("HIVE_CREDENTIAL_KEY") and _has_encrypted_credentials():
            logger.critical(
                "Credential store falling into read-only EnvVarStorage — "
                "this should not be reachable after the self-heal block. "
                "/api/credentials POST will 503 store_locked."
            )
            credential_store = CredentialStore.with_env_storage()
        else:
            credential_store = CredentialStore.with_aden_sync(auto_sync=False)
    except Exception:
        logger.debug("Encrypted credential store unavailable, using in-memory fallback")
        credential_store = CredentialStore.for_testing({})

    app["credential_store"] = credential_store

    # Let queen sessions build their registry lazily on first use instead of
    # paying the MCP discovery cost during `hive open`.
    app["queen_tool_registry"] = None
    app["manager"] = SessionManager(
        model=model,
        credential_store=credential_store,
        queen_tool_registry=None,
    )

    # Route task lifecycle events (task_created/updated/deleted) to the bus of
    # the session they belong to — not the process-global default, which is
    # last-writer-wins and breaks live SSE diffs once a second colony boots.
    # See framework.tasks.events._get_bus.
    try:
        from framework.tasks.events import set_bus_resolver

        _task_manager = app["manager"]

        def _resolve_task_bus(session_id: str):
            sess = _task_manager.get_session(session_id)
            return sess.event_bus if sess is not None else None

        set_bus_resolver(_resolve_task_bus)
    except Exception:
        logger.debug("Failed to register task-event bus resolver", exc_info=True)

    # Clear orphaned compaction markers from prior server crashes. Without
    # this, any session whose compaction was interrupted would block the
    # next colony cold-load for the full await_completion timeout (180s)
    # before falling through. See compaction_status.sweep_stale_in_progress.
    try:
        from framework.config import QUEENS_DIR
        from framework.server import compaction_status

        compaction_status.sweep_stale_in_progress(QUEENS_DIR)
    except Exception:
        logger.debug("compaction_status: startup sweep skipped", exc_info=True)

    # Grant newly-GA tools to existing agent sidecars. A no-op when every
    # sidecar's updated_at is newer than every addition in _CATEGORY_ADDITIONS.
    try:
        from framework.agents.queen.tools_ga_migration import run_ga_tool_migration

        run_ga_tool_migration()
    except Exception:
        logger.debug("ga_tool_migration: startup pass skipped", exc_info=True)

    # Register startup + shutdown hooks. The parent watchdog has to run
    # inside the aiohttp event loop, so it lives behind on_startup rather
    # than at module-import time.
    app.on_startup.append(_start_parent_watchdog)
    # streamToken self-refresh: keep the `hive` credential fresh inside
    # the VM so cloud queens can make LLM calls even when the desktop
    # client (which historically did the refreshing) is offline. No-ops
    # when HIVE_CLOUD_BASE isn't set. See streamtoken_refresh.py header.
    from framework.server.streamtoken_refresh import start_streamtoken_refresh

    app.on_startup.append(start_streamtoken_refresh)
    # Built-in system-resource monitor: sample the runtime's process tree +
    # system memory every ~15s into a rolling history, exposed at
    # /api/health/resources, with an early-warning log on verdict degradation.
    app.on_startup.append(start_resource_sampler)
    app.on_shutdown.append(_on_shutdown)
    # Last-ditch browser cleanup for a non-graceful exit that skips on_shutdown.
    import atexit

    atexit.register(_atexit_reap_browsers)

    # Health check
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/health/resources", handle_resources)
    app.router.add_get("/api/browser/status", handle_browser_status)
    app.router.add_get("/api/browser/status/stream", handle_browser_status_stream)
    app.router.add_post("/api/browser/tab/reveal", handle_browser_tab_reveal)

    # Register route modules
    from framework.server.routes_colonies import register_routes as register_colonies_routes
    from framework.server.routes_colony_tools import register_routes as register_colony_tools_routes
    from framework.server.routes_colony_workers import register_routes as register_colony_worker_routes
    from framework.server.routes_config import register_routes as register_config_routes
    from framework.server.routes_credentials import register_routes as register_credential_routes
    from framework.server.routes_events import register_routes as register_event_routes
    from framework.server.routes_execution import register_routes as register_execution_routes
    from framework.server.routes_maintenance import register_routes as register_maintenance_routes
    from framework.server.routes_mcp import register_routes as register_mcp_routes
    from framework.server.routes_memories import register_routes as register_memory_routes
    from framework.server.routes_messages import register_routes as register_message_routes
    from framework.server.routes_prompts import register_routes as register_prompt_routes
    from framework.server.routes_queen_tools import register_routes as register_queen_tools_routes
    from framework.server.routes_queens import register_routes as register_queen_routes
    from framework.server.routes_sentinel import register_routes as register_sentinel_routes
    from framework.server.routes_sessions import register_routes as register_session_routes
    from framework.server.routes_skills import register_routes as register_skills_routes
    from framework.server.routes_tasks import register_routes as register_task_routes
    from framework.server.routes_workers import register_routes as register_worker_routes

    register_config_routes(app)
    register_credential_routes(app)
    register_execution_routes(app)
    register_event_routes(app)
    register_message_routes(app)
    register_session_routes(app)
    register_worker_routes(app)
    register_queen_routes(app)
    register_queen_tools_routes(app)
    register_colonies_routes(app)
    register_colony_tools_routes(app)
    register_sentinel_routes(app)
    register_mcp_routes(app)
    register_colony_worker_routes(app)
    register_memory_routes(app)
    register_prompt_routes(app)
    register_skills_routes(app)
    register_task_routes(app)
    # Manual-trigger data-retention janitor (no background scheduler).
    # started_at lets tier 1 skip log files the live process holds open;
    # the server marker lets an offline CLI janitor detect that a live
    # runtime owns this HIVE_HOME even when the port probe can't (the
    # desktop app binds an ephemeral port behind auth).
    app["started_at"] = time.time()
    register_maintenance_routes(app)

    async def _write_janitor_server_marker(app: web.Application) -> None:
        from framework.maintenance.janitor import write_server_marker

        write_server_marker()

    async def _clear_janitor_server_marker(app: web.Application) -> None:
        from framework.maintenance.janitor import clear_server_marker

        clear_server_marker()

    app.on_startup.append(_write_janitor_server_marker)
    app.on_shutdown.append(_clear_janitor_server_marker)

    # Commercial extensions (optional — only present in hive-desktop-runtime).
    # Imports lazily so an OSS install without the `commercial` package keeps
    # working unchanged.
    try:
        from commercial.middleware import setup_commercial_middleware
        from commercial.routes import register_routes as register_commercial_routes

        setup_commercial_middleware(app)
        register_commercial_routes(app)
        logger.info("Commercial extensions loaded")
    except ImportError:
        pass

    # Serve the built frontend SPA (core/frontend/dist) with an SPA fallback.
    # Registered last so /api/* routes take priority over the catch-all. In
    # dev the SPA is served by Vite instead (which proxies /api here); when no
    # dist/ exists this is a no-op.
    _setup_static_serving(app)

    return app


def _setup_static_serving(app: web.Application) -> None:
    """Serve frontend static files if the dist directory exists."""
    # Try: CWD/frontend/dist, core/frontend/dist, repo_root/frontend/dist
    _here = Path(__file__).resolve().parent  # core/framework/server/
    candidates = [
        Path("frontend/dist"),
        _here.parent.parent / "frontend" / "dist",  # core/frontend/dist
        _here.parent.parent.parent / "frontend" / "dist",  # repo_root/frontend/dist
    ]

    dist_dir: Path | None = None
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "index.html").exists():
            dist_dir = candidate.resolve()
            break

    if dist_dir is None:
        logger.debug("No frontend/dist found — skipping static file serving")
        return

    logger.info(f"Serving frontend from {dist_dir}")

    async def handle_spa(request: web.Request) -> web.FileResponse:
        """Serve static files with SPA fallback to index.html."""
        rel_path = request.match_info.get("path", "")
        file_path = (dist_dir / rel_path).resolve()

        if file_path.is_file() and file_path.is_relative_to(dist_dir):
            return web.FileResponse(file_path)

        # SPA fallback
        return web.FileResponse(dist_dir / "index.html")

    # Catch-all for SPA — must be registered LAST so /api routes take priority
    app.router.add_get("/{path:.*}", handle_spa)
