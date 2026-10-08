"""terminal-tools FastMCP server — entry module.

Run via:
    uv run python -m terminal_tools.server --stdio
    uv run python terminal_tools_server.py --stdio    (preferred, see _DEFAULT_LOCAL_SERVERS)
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
    if not logger.handlers:
        stream = sys.stderr if "--stdio" in sys.argv else sys.stdout
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("[terminal-tools] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


setup_logger()

# Suppress FastMCP banner in STDIO mode (mirrors gcu/server.py).
if "--stdio" in sys.argv:
    import rich.console

    _orig_console_init = rich.console.Console.__init__

    def _patched_console_init(self, *args, **kwargs):
        kwargs["file"] = sys.stderr
        _orig_console_init(self, *args, **kwargs)

    rich.console.Console.__init__ = _patched_console_init


from fastmcp import FastMCP  # noqa: E402

from terminal_tools import register_terminal_tools  # noqa: E402
from terminal_tools.common.ripgrep import ripgrep_status  # noqa: E402
from terminal_tools.jobs.manager import get_manager  # noqa: E402
from terminal_tools.pty.tools import get_registry as get_pty_registry  # noqa: E402


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[dict]:
    """Reap children on shutdown so we don't orphan jobs/PTYs.

    Mirrors the gcu-tools lifespan pattern. Runs in the FastMCP event
    loop on graceful shutdown; the atexit hook below catches abrupt
    exits (SIGTERM, etc.) where lifespan teardown may not complete.
    """
    search_dependency = await asyncio.to_thread(ripgrep_status)
    if search_dependency["available"]:
        logger.info("Search ready: %s (%s)", search_dependency["version"], search_dependency["path"])
    else:
        logger.warning("Search dependency missing: %s", search_dependency["hint"])

    parent_pid_env = os.getenv("HIVE_DESKTOP_PARENT_PID")
    if parent_pid_env:
        try:
            parent_pid = int(parent_pid_env)
            asyncio.create_task(_parent_watchdog(parent_pid))
            logger.info("Parent watchdog armed for PID %d", parent_pid)
        except ValueError:
            logger.warning("Invalid HIVE_DESKTOP_PARENT_PID=%r", parent_pid_env)

    yield {}

    logger.info("Shutting down — reaping jobs and PTY sessions...")
    try:
        get_manager().shutdown_all(grace_sec=2.0)
    except Exception as e:
        logger.warning("JobManager shutdown error: %s", e)
    try:
        get_pty_registry().shutdown_all()
    except Exception as e:
        logger.warning("PTY registry shutdown error: %s", e)


def _is_alive(pid: int) -> bool:
    """Return True iff the process is still running.

    Implementation note: on Windows, ``os.kill(pid, 0)`` is NOT a safe
    alive-check. Because ``CTRL_C_EVENT == 0``, CPython first tries
    ``GenerateConsoleCtrlEvent`` and silently falls through to
    ``OpenProcess(PROCESS_ALL_ACCESS) + TerminateProcess(handle, 0)``
    when the target isn't in the same console — actually killing the
    parent. We use the Win32 API directly (same approach as
    ``session_manager._is_pid_alive``) to avoid that landmine.
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
    """Self-destruct when the desktop parent dies."""
    while True:
        await asyncio.sleep(2.0)
        if not _is_alive(parent_pid):
            logger.warning("Parent PID %d gone — terminal-tools exiting", parent_pid)
            try:
                get_manager().shutdown_all(grace_sec=1.0)
            except Exception:
                pass
            try:
                get_pty_registry().shutdown_all()
            except Exception:
                pass
            os._exit(0)


def _atexit_reap() -> None:
    """Last-ditch reaping if lifespan didn't run."""
    try:
        get_manager().shutdown_all(grace_sec=1.0)
    except Exception:
        pass
    try:
        get_pty_registry().shutdown_all()
    except Exception:
        pass


atexit.register(_atexit_reap)

mcp = FastMCP("terminal-tools", lifespan=_lifespan)


def main() -> None:
    parser = argparse.ArgumentParser(description="terminal-tools MCP server")
    parser.add_argument("--port", type=int, default=int(os.getenv("TERMINAL_TOOLS_PORT", "4004")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()

    tools = register_terminal_tools(mcp)

    if not args.stdio:
        logger.info("Registered %d terminal-tools: %s", len(tools), tools)

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info("Starting terminal-tools on %s:%d", args.host, args.port)
        asyncio.run(mcp.run_async(transport="http", host=args.host, port=args.port))


if __name__ == "__main__":
    main()
