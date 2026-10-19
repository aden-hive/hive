#!/usr/bin/env python3
"""
GCU Tools MCP Server

Exposes GCU (General Computing Unit) tools via Model Context Protocol.

Usage:
    # Run with STDIO transport (for agent integration)
    python -m gcu.server --stdio

    # Run with HTTP transport
    python -m gcu.server --port 4002

    # Specify capabilities
    python -m gcu.server --stdio --capabilities browser

Environment Variables:
    GCU_PORT - Server port for HTTP mode (default: 4002)
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


def setup_logger() -> None:
    """Configure logger for GCU server."""
    if not logger.handlers:
        stream = sys.stderr if "--stdio" in sys.argv else sys.stdout
        handler = logging.StreamHandler(stream)
        formatter = logging.Formatter("[GCU] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    # Optional file sink for all gcu.* module loggers.
    # When stdio transport is in use, subprocess stderr is /dev/null'd by
    # the MCP client, so module loggers (e.g. gcu.browser.bridge) vanish.
    # GCU_LOG_FILE=/tmp/gcu.log lets you `tail -f` them from another shell.
    log_file = os.environ.get("GCU_LOG_FILE")
    if log_file:
        level_name = os.environ.get("GCU_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        if not isinstance(level, int):
            level = logging.INFO

        root = logging.getLogger()
        # Re-use an existing handler if this is re-entered (atexit, reloads).
        already_attached = any(
            isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == os.path.abspath(log_file) for h in root.handlers
        )
        if not already_attached:
            file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
                    datefmt="%H:%M:%S",
                )
            )
            root.addHandler(file_handler)
            # Records must pass the root level to reach the handler; tighten
            # only if root is currently coarser than what was requested.
            if root.level == logging.NOTSET or root.level > level:
                root.setLevel(level)
            # Marker line so tailers can see process boundaries when the
            # server restarts and appends to the same file.
            logging.getLogger("gcu.server").info(
                "----- gcu.server started (pid=%d, level=%s) -----",
                os.getpid(),
                level_name,
            )


setup_logger()

# Suppress FastMCP banner in STDIO mode
if "--stdio" in sys.argv:
    import rich.console

    _original_console_init = rich.console.Console.__init__

    def _patched_console_init(self, *args, **kwargs):
        kwargs["file"] = sys.stderr
        _original_console_init(self, *args, **kwargs)

    rich.console.Console.__init__ = _patched_console_init

from fastmcp import FastMCP  # noqa: E402

from gcu import register_gcu_tools  # noqa: E402

# ---------------------------------------------------------------------------
# Shutdown hooks — kill Chrome processes when the server exits
# ---------------------------------------------------------------------------


def _is_alive(pid: int) -> bool:
    """Return True iff the process is still running.

    Implementation note: on Windows, ``os.kill(pid, 0)`` is NOT a safe
    alive-check. Because ``CTRL_C_EVENT == 0``, CPython first tries
    ``GenerateConsoleCtrlEvent`` and silently falls through to
    ``OpenProcess(PROCESS_ALL_ACCESS) + TerminateProcess(handle, 0)``
    when the target isn't in the same console — actually killing the
    parent. We use the Win32 API directly to avoid that landmine.
    """
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000 — minimal access, no terminate.
        handle = kernel32.OpenProcess(0x1000, False, pid)
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
    """Self-destruct when the desktop parent dies.

    Without this, an abrupt Electron shutdown leaves the Beeline bridge
    holding its ports (14829/14830, plus legacy 9229/9230, and other gcu
    state) — the next runtime startup then fails to bind. Mirrors the
    watchdogs in
    ``chart_tools/server.py`` and ``terminal_tools/server.py``.
    """
    while True:
        await asyncio.sleep(2.0)
        if not _is_alive(parent_pid):
            logger.warning("Parent PID %d gone — gcu-tools exiting", parent_pid)
            try:
                from gcu.browser.session import shutdown_all_browsers

                await shutdown_all_browsers()
            except Exception:
                pass
            os._exit(0)


async def _bridge_rebind_supervisor(bridge, port: int) -> None:
    """Retry binding the bridge ports until they all succeed.

    bridge.start() logs and swallows OSError when a port is held
    (stale runtime, old Electron, another desktop instance). Without
    retry the bridge stays dead until the user restarts the runtime.
    Polling every 5s lets the bridge come up automatically once the
    holder exits — no app restart needed.

    This supervises every listener start() owns — the primary ws/status
    ports AND the legacy 9229/9230 migration ports — so an old extension
    still connects even if 9229 was momentarily occupied at startup.
    """
    from gcu.browser.bridge import LEGACY_BRIDGE_PORT

    supervised = ["_server", "_status_server"]
    if port != LEGACY_BRIDGE_PORT:
        supervised += ["_legacy_server", "_legacy_status_server"]

    while True:
        await asyncio.sleep(5.0)
        if any(getattr(bridge, attr, None) is None for attr in supervised):
            try:
                await bridge.start(port=port)
            except Exception as e:
                logger.debug("Bridge rebind attempt failed: %s", e)


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """FastMCP lifespan hook: connect to (client) or host the Beeline bridge.

    gcu is a disposable MCP server — the runtime recycles it on tool-call
    timeouts and refcount drops. So it defaults to *client* mode: the bridge
    lives in a separate, supervised ``bridge_host`` process that survives gcu
    being killed. ``GCU_BRIDGE_MODE=host`` forces the legacy in-process bridge.
    """
    from gcu.browser.bridge import BRIDGE_PORT, init_bridge, is_client_mode

    mode = "host" if os.getenv("GCU_BRIDGE_MODE", "").strip().lower() == "host" else "client"
    bridge = init_bridge(mode=mode)
    rebind_task: asyncio.Task | None = None

    if is_client_mode():
        from gcu.bridge_host import ensure_bridge_host_running
        from gcu.browser.tools.lifecycle import rehydrate_contexts

        if not ensure_bridge_host_running():
            logger.warning("bridge_host did not come up in time — browser tools may be degraded")
        try:
            await bridge.connect()
            # Rebuild the context index from tab groups that outlived the
            # previous gcu process, so open tabs stay addressable.
            await rehydrate_contexts(bridge)
        except Exception as e:
            # Non-fatal: the RemoteBridge poller keeps retrying and tool
            # calls reconnect on demand. gcu still serves every other tool.
            logger.warning("initial bridge connect failed (will retry): %s", e)
    else:
        # Legacy in-process bridge. start() dual-listens on the legacy 9229
        # port for the extension-migration window.
        bridge_port = int(os.getenv("HIVE_BRIDGE_PORT", str(BRIDGE_PORT)))
        await bridge.start(port=bridge_port)
        rebind_task = asyncio.create_task(_bridge_rebind_supervisor(bridge, bridge_port))

    parent_pid_env = os.getenv("HIVE_DESKTOP_PARENT_PID")
    if parent_pid_env:
        try:
            parent_pid = int(parent_pid_env)
            asyncio.create_task(_parent_watchdog(parent_pid))
            logger.info("Parent watchdog armed for PID %d", parent_pid)
        except ValueError:
            logger.warning("Invalid HIVE_DESKTOP_PARENT_PID=%r", parent_pid_env)

    yield {}

    from gcu.browser.session import shutdown_all_browsers

    logger.info("Server shutting down, cleaning up browser sessions...")
    if rebind_task is not None:
        rebind_task.cancel()
        try:
            await rebind_task
        except (asyncio.CancelledError, Exception):
            pass
    # In client mode shutdown_all_browsers() is a no-op — the tabs belong to
    # the bridge_host process now and must survive this gcu server exiting.
    await shutdown_all_browsers()
    await bridge.stop()


def _sync_shutdown() -> None:
    """atexit fallback: run async browser cleanup from sync context.

    Covers SIGTERM and other exits where the lifespan teardown may not run.
    """
    from gcu.browser.session import shutdown_all_browsers

    try:
        asyncio.run(shutdown_all_browsers())
    except Exception:
        pass


atexit.register(_sync_shutdown)


def _relax_strict_input_validation(server: FastMCP) -> None:
    """Turn off the mcp lowlevel server's strict jsonschema input gate.

    The ``mcp`` SDK's ``Server.call_tool`` defaults to ``validate_input=True``,
    which runs ``jsonschema.validate(arguments, inputSchema)`` BEFORE
    FastMCP's own argument handling. LLM clients routinely send scalar /
    array arguments as JSON-encoded strings — e.g. ``coordinate="[0.38,
    0.65]"``, ``tab_id="547386152"``, ``repeat="3"`` — and the strict gate
    rejects those with "Input validation error: ... is not valid under any
    of the given schemas" before FastMCP's ``pre_parse_json`` (which exists
    precisely to decode such strings back into lists / ints) ever runs.

    FastMCP registers its CallTool handler with the default (validating)
    setting at construction time. We re-register the SAME handler with
    ``validate_input=False`` so FastMCP's lenient pydantic path takes over:
    it still validates and still rejects genuinely bad input, just with
    type coercion instead of a hard schema reject. Output validation is
    unaffected.

    Touches FastMCP / mcp private attributes, so it is fully guarded — a
    future version that reshapes this wiring simply leaves validation at
    its default rather than crashing the server at startup.
    """
    try:
        low = server._mcp_server
        low.call_tool(validate_input=False)(server._mcp_call_tool)
    except Exception:
        logger.warning(
            "could not relax strict MCP input validation; stringified tool arguments may be rejected",
            exc_info=True,
        )


mcp = FastMCP("gcu-tools", lifespan=_lifespan)
_relax_strict_input_validation(mcp)


def main() -> None:
    """Entry point for the GCU MCP server."""
    parser = argparse.ArgumentParser(description="GCU Tools MCP Server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("GCU_PORT", "4002")),
        help="HTTP server port (default: 4002)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP server host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Use STDIO transport instead of HTTP",
    )
    parser.add_argument(
        "--capabilities",
        nargs="+",
        default=["browser"],
        help="GCU capabilities to enable (default: browser)",
    )
    args = parser.parse_args()

    # Opt-in memory tracing (HIVE_GCU_MEMTRACE=1) for diagnosing heap retention.
    # No-op unless enabled; pair with GCU_LOG_FILE to read it in stdio mode.
    from gcu import memtrace

    memtrace.maybe_start()

    # Register GCU tools
    tools = register_gcu_tools(mcp, capabilities=args.capabilities)

    if not args.stdio:
        logger.info(f"Registered {len(tools)} GCU tools: {tools}")

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting GCU server on {args.host}:{args.port}")
        # FastMCP.run() forwards kwargs to anyio.run() instead of the
        # transport, which breaks host/port for SSE. Invoke run_async
        # directly so the kwargs land on run_sse_async.
        asyncio.run(mcp.run_async(transport="sse", host=args.host, port=args.port))


if __name__ == "__main__":
    main()
