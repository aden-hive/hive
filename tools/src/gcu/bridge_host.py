"""
Standalone host + supervisor for the Beeline browser bridge.

Why this exists
---------------
The bridge must outlive any single gcu MCP-server process. The Hive runtime
force-disconnects a tool server whenever one browser call exceeds the 60s
tool-call timeout, and a disposable gcu process also dies on refcount-drop,
reconfigure, or crash. While the bridge lived *inside* gcu, every one of
those events took the extension link and all open tabs down with it.

So the bridge runs here instead — in its own process, supervised with
restart-on-exit, with a lifetime tied to the durable Hive runtime rather than
to a disposable tool server. A gcu restart then only drops the thin RPC
client; it reconnects to the still-running bridge with every tab intact.

Two modes
---------
    python -m gcu.bridge_host              # worker: runs one bridge, serves forever
    python -m gcu.bridge_host --supervise  # supervisor: (re)spawns the worker

The runtime launches the supervisor; the supervisor keeps a worker alive
across crashes with exponential backoff. Both modes shut down *gracefully*
on SIGTERM/SIGINT — ``bridge.stop()`` sends WebSocket close frames and
releases every port, so the extension sees a clean disconnect instead of a
half-open socket it must time out.

Lifetime: decoupled from any single gcu MCP server (those recycle on every
tool-call timeout / refcount drop), but tied to the **durable runtime**. The
bridge_host watches ``HIVE_DESKTOP_PARENT_PID`` — the Hive desktop's own PID
(hive-desktop/src/main/runtime.ts sets it to ``process.pid``) — and shuts down
when the runtime dies, so it never outlives the app holding a stale module in
memory. A short debounce (``_PARENT_DEATH_CONFIRMATIONS``) guards against a
one-off probe glitch. When no parent PID is set (CLI / tests), the idle
watchdog is the cleanup path instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import threading
import time

logger = logging.getLogger("gcu.bridge_host")

# A worker that survives at least this long counts as a healthy run, so the
# supervisor resets its restart backoff. Shorter than this and we assume a
# crash-loop and keep backing off.
_HEALTHY_RUN_S = 30.0
_RESTART_BACKOFF_CAP_S = 30.0
# Grace period for a worker to finish bridge.stop() after SIGTERM before the
# supervisor escalates to SIGKILL.
_WORKER_SHUTDOWN_GRACE_S = 10.0

# Cadence for polling the durable runtime (desktop) PID, and how many
# consecutive "gone" reads confirm its death before we shut the bridge down.
# Two checks (~10s) is a cheap debounce so a single transient probe glitch can
# never tear the bridge down out from under a live runtime.
_PARENT_CHECK_INTERVAL_S = 5.0
_PARENT_DEATH_CONFIRMATIONS = 2


def _setup_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [bridge_host] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _pid_alive(pid: int) -> bool:
    """True iff ``pid`` is still running.

    Implementation note: on Windows, ``os.kill(pid, 0)`` is NOT a safe
    probe. Because ``CTRL_C_EVENT == 0``, CPython first tries
    ``GenerateConsoleCtrlEvent`` and then silently falls through to
    ``OpenProcess(PROCESS_ALL_ACCESS) + TerminateProcess(handle, 0)``
    when the target isn't in the same console — actually killing the
    target. Since this is called on HIVE_DESKTOP_PARENT_PID (Electron),
    the naive probe terminates the desktop. Use the Win32 API directly.
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
    except OSError:
        return False


def _control_port_alive() -> bool:
    """True if something is already serving the bridge control port.

    A cheap liveness probe used to avoid starting a second bridge_host when
    one is already up — the bridge is a singleton.
    """
    import socket

    from gcu.browser.bridge_rpc import CONTROL_PORT

    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def ensure_bridge_host_running(wait_s: float = 8.0) -> bool:
    """Make sure a supervised bridge_host process exists; spawn one if not.

    Called by a gcu MCP server at startup. The supervisor is spawned
    *detached* (``start_new_session=True``) so it outlives the gcu process
    that launched it — that is the whole point of the decouple. Idempotent:
    if a bridge is already serving, this is a cheap no-op.

    Returns True if a bridge is reachable within ``wait_s``.
    """
    if _control_port_alive():
        return True

    log_path = os.path.expanduser("~/.hive/bridge_host.log")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        logf: object = open(log_path, "a")
    except OSError:
        logf = subprocess.DEVNULL

    logger.info("no bridge_host detected — spawning supervised bridge process")
    subprocess.Popen(
        [sys.executable, "-m", "gcu.bridge_host", "--supervise"],
        stdout=logf,
        stderr=logf,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # detached: survives this gcu process exiting
    )
    # The child dup'd the fd; close our copy so it isn't leaked per gcu start.
    if hasattr(logf, "close"):
        logf.close()

    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if _control_port_alive():
            return True
        time.sleep(0.2)
    return _control_port_alive()


# ──────────────────────────────────────────────────────────────────────────
# Worker — runs the single bridge instance
# ──────────────────────────────────────────────────────────────────────────


async def _watch_parent(parent_pid: int, stop: asyncio.Event) -> None:
    """Shut the worker down when the durable runtime (desktop) process dies.

    ``HIVE_DESKTOP_PARENT_PID`` is the Hive desktop's own PID
    (hive-desktop/src/main/runtime.ts sets it to ``process.pid``), so the
    bridge's lifetime tracks the runtime: it survives gcu MCP recycles (those
    come and go) but goes away once the runtime is gone — it must never linger
    holding a stale build in memory. Debounced by
    ``_PARENT_DEATH_CONFIRMATIONS`` so a one-off probe miss can't false-trigger.
    The supervisor's own watch (and its respawn guard) cover the case where this
    task hasn't noticed yet, so setting ``stop`` here never causes a respawn.
    """
    misses = 0
    while not stop.is_set():
        await asyncio.sleep(_PARENT_CHECK_INTERVAL_S)
        if stop.is_set():
            return
        if _pid_alive(parent_pid):
            misses = 0
            continue
        misses += 1
        if misses < _PARENT_DEATH_CONFIRMATIONS:
            continue
        logger.warning(
            "runtime pid %d is gone — shutting down the bridge with the runtime",
            parent_pid,
        )
        stop.set()
        return


# Idle watchdog tuning. The single signal is rpc_server.active_client_count
# — the live count of gcu MCP processes bound to the bridge's control RPC.
# The extension being connected says nothing about whether anyone is doing
# work; Chrome with the extension installed is incidental. Only gcu MCPs
# actually drive the bridge, and they're the consumer the runtime cares
# about. Grace covers gcu recycles (the legitimate reason RPC clients
# briefly go to zero in steady-state operation).
_IDLE_CHECK_INTERVAL_S: float = 10.0
_IDLE_GRACE_S: float = 30.0


async def _idle_exit_watchdog(bridge, stop: asyncio.Event) -> None:
    """Self-terminate when no gcu MCP is currently using the bridge AND
    the desktop app is gone.

    Background: bridge_host is intentionally durable across gcu recycles
    (see the module docstring). When the desktop app quits, gcu MCP processes
    disappear — but bridge_host doesn't know about that directly, only that
    its spawning process died. So historically it stayed up indefinitely
    until someone noticed via ``lsof :14830``.

    Two signals, both required for exit:

      * ``rpc_server.active_client_count`` — live count of gcu MCP processes
        on the bridge's control RPC. Real consumers. While > 0 the bridge is
        clearly serving someone and stays up.

      * ``HIVE_DESKTOP_PARENT_PID`` liveness — the Hive desktop (Electron)
        process. The side panel is also a real consumer: with the desktop
        open, Chrome polls /status every 2s for the connection UI, but it
        is NOT counted in active_client_count (the extension isn't a gcu
        MCP). Earlier this watchdog ignored the desktop entirely, so once
        no agent was actively using the browser, the bridge died after
        30s and the side panel fell into the unrecoverable
        "Hive isn't running" state — there's no way for the extension to
        respawn a dead bridge_host. Keeping the bridge alive while the
        desktop is alive closes that gap. When the desktop quits, the
        parent PID dies and this falls back to the original idle-exit
        behaviour so orphan bridge_hosts still clean themselves up.

    On expiry we SIGTERM the supervisor (our parent) so the supervisor's
    existing graceful-shutdown path tears this worker down. Returning here
    directly would trip the supervisor's "worker died unexpectedly — respawn"
    branch and put us right back where we started.
    """
    parent_raw = os.getenv("HIVE_DESKTOP_PARENT_PID")
    parent_pid = int(parent_raw) if parent_raw and parent_raw.isdigit() else None

    idle_since: float | None = None
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=_IDLE_CHECK_INTERVAL_S)
            return
        except TimeoutError:
            pass

        rpc_server = getattr(bridge, "_rpc_server", None)
        rpc_clients = int(getattr(rpc_server, "active_client_count", 0) or 0)

        # The desktop is a consumer too (side panel). While it's alive the
        # bridge has work to do even with no gcu MCPs attached, so don't
        # tear it down.
        desktop_alive = parent_pid is not None and _pid_alive(parent_pid)

        if rpc_clients > 0 or desktop_alive:
            idle_since = None
            continue

        now = time.monotonic()
        if idle_since is None:
            idle_since = now
            logger.info(
                "bridge has no gcu RPC clients and desktop is gone — starting %.0fs grace before self-exit",
                _IDLE_GRACE_S,
            )
            continue

        if (now - idle_since) < _IDLE_GRACE_S:
            continue

        logger.warning(
            "bridge idle %.0fs with no gcu RPC clients and no desktop — exiting "
            "so an orphaned bridge_host doesn't outlive the desktop app. Next "
            "gcu call will respawn a fresh one.",
            now - idle_since,
        )
        try:
            ppid = os.getppid()
            if ppid > 1:
                os.kill(ppid, signal.SIGTERM)
            else:
                os.kill(os.getpid(), signal.SIGTERM)
        except ProcessLookupError:
            stop.set()
        return


async def _run_worker() -> int:
    """Start the bridge, serve until a stop signal, then shut down cleanly."""
    from gcu.browser.bridge import BRIDGE_PORT, init_bridge

    # The worker IS the bridge — always host mode, regardless of any ambient
    # GCU_BRIDGE_MODE meant for gcu MCP servers.
    bridge = init_bridge(mode="host")
    port = int(os.getenv("HIVE_BRIDGE_PORT", str(BRIDGE_PORT)))
    await bridge.start(port=port)

    # Self-heal: if a previous bridge was still holding our ports at startup
    # (the "address already in use" race on app restart), start() catches the
    # bind errors and we come up bound to ONLY the control-RPC port — invisible
    # to the extension and the desktop app, and stuck that way forever. Don't
    # sit here half-up: exit non-zero so the supervisor respawns us with
    # backoff. Once the stale holder frees the ports, a later respawn binds
    # cleanly and the worker survives (resetting the supervisor's backoff).
    if not bridge.has_public_listeners():
        errs = "; ".join(f"{k}: {v}" for k, v in (bridge._bind_errors or {}).items()) or "unknown"
        logger.error(
            "bridge worker came up without its public ports (%s) — another bridge is holding them; exiting for supervisor respawn",
            errs,
        )
        try:
            await asyncio.wait_for(bridge.stop(), timeout=_WORKER_SHUTDOWN_GRACE_S)
        except Exception:
            pass
        return 1

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, ValueError):
            # add_signal_handler is unavailable off the main thread / on
            # some platforms; the supervisor's terminate() still works.
            pass

    parent = os.getenv("HIVE_DESKTOP_PARENT_PID")
    if parent:
        try:
            asyncio.create_task(_watch_parent(int(parent), stop))
        except ValueError:
            logger.warning("ignoring invalid HIVE_DESKTOP_PARENT_PID=%r", parent)

    # Idle watchdog — the only path other than explicit SIGTERM that can
    # take the bridge down. See _idle_exit_watchdog for the rationale.
    asyncio.create_task(_idle_exit_watchdog(bridge, stop))

    logger.info("bridge worker up (pid=%d, port=%d)", os.getpid(), port)
    await stop.wait()

    logger.info("bridge worker shutting down gracefully")
    try:
        await asyncio.wait_for(bridge.stop(), timeout=_WORKER_SHUTDOWN_GRACE_S)
    except TimeoutError:
        logger.warning("bridge.stop() exceeded grace period — exiting anyway")
    return 0


# ──────────────────────────────────────────────────────────────────────────
# Supervisor — keeps exactly one worker alive
# ──────────────────────────────────────────────────────────────────────────


def _run_supervisor() -> int:
    """(Re)spawn the worker, restarting it on unexpected exit with backoff."""
    # Singleton guard: if a bridge is already serving, another supervisor
    # already owns it — exit cleanly rather than crash-loop a worker that
    # can never bind the ports.
    if _control_port_alive():
        logger.info("a bridge_host is already serving — supervisor exiting")
        return 0

    state = {"stop": False, "child": None}  # mutated by the signal handler

    def _handle_signal(signum, _frame):
        state["stop"] = True
        child = state["child"]
        if child is not None and child.poll() is None:
            child.terminate()  # → worker's SIGTERM handler → graceful stop

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Parent watchdog: the bridge_host dies with the durable runtime. When the
    # desktop PID disappears, stop respawning and tear the worker down — so a
    # stale host can't outlive the app (and keep an old build in memory). Killing
    # only the worker would just trip the "respawn" branch below; setting
    # state["stop"] first is what actually ends the supervisor.
    parent = os.getenv("HIVE_DESKTOP_PARENT_PID")
    parent_pid = int(parent) if (parent and parent.isdigit()) else None
    if parent_pid is not None:

        def _watch() -> None:
            misses = 0
            while not state["stop"]:
                time.sleep(_PARENT_CHECK_INTERVAL_S)
                if state["stop"]:
                    return
                if _pid_alive(parent_pid):
                    misses = 0
                    continue
                misses += 1
                if misses < _PARENT_DEATH_CONFIRMATIONS:
                    continue
                logger.warning(
                    "runtime pid %d is gone — shutting down bridge_host with the runtime",
                    parent_pid,
                )
                state["stop"] = True
                child = state["child"]
                if child is not None and child.poll() is None:
                    child.terminate()  # → worker SIGTERM → graceful bridge.stop()
                return

        threading.Thread(target=_watch, daemon=True).start()

    logger.info("bridge supervisor up (pid=%d)", os.getpid())
    backoff = 1.0
    while not state["stop"]:
        started = time.monotonic()
        child = subprocess.Popen([sys.executable, "-m", "gcu.bridge_host"])
        state["child"] = child
        rc = child.wait()
        ran_for = time.monotonic() - started

        if state["stop"]:
            break
        # Never respawn into a dead runtime. The _watch thread normally sets
        # state["stop"] first; this guards the race where the worker itself
        # noticed the runtime's death (via _watch_parent) and exited before
        # _watch did — without it we'd respawn a worker that should be gone.
        if parent_pid is not None and not _pid_alive(parent_pid):
            logger.info("runtime pid %d gone — not respawning bridge worker", parent_pid)
            break
        if ran_for >= _HEALTHY_RUN_S:
            backoff = 1.0  # the worker was healthy — forget earlier failures
        logger.warning(
            "bridge worker exited (rc=%s) after %.0fs — restarting in %.1fs",
            rc,
            ran_for,
            backoff,
        )
        time.sleep(backoff)
        backoff = min(backoff * 2, _RESTART_BACKOFF_CAP_S)

    # Shutdown requested — give the worker its grace period, then escalate.
    child = state["child"]
    if child is not None and child.poll() is None:
        try:
            child.wait(timeout=_WORKER_SHUTDOWN_GRACE_S)
        except subprocess.TimeoutExpired:
            logger.warning("worker did not exit in time — killing")
            child.kill()
    logger.info("bridge supervisor exiting")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _setup_logging()
    # Opt-in memory tracing (HIVE_GCU_MEMTRACE=1). In client mode the browser
    # BeelineBridge (per-tab snapshots/state) lives HERE, not in gcu.server, so
    # this is where a browser-automation retention leak would actually grow.
    # Route it to a dedicated file derived from GCU_LOG_FILE so it doesn't
    # interleave with gcu.server's memtrace; only the worker traces (the
    # supervisor holds no bridge state).
    if "--supervise" not in argv:
        from gcu import memtrace

        gcu_log = os.environ.get("GCU_LOG_FILE", "").strip()
        if gcu_log and not os.environ.get("HIVE_GCU_MEMTRACE_FILE"):
            os.environ["HIVE_GCU_MEMTRACE_FILE"] = gcu_log + ".bridge_host"
        memtrace.maybe_start()
    if "--supervise" in argv:
        return _run_supervisor()
    return asyncio.run(_run_worker())


if __name__ == "__main__":
    sys.exit(main())
