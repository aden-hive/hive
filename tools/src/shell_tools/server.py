"""shell-tools FastMCP server — entry module.

Run via:
    uv run python -m shell_tools.server --stdio
    uv run python shell_tools_server.py --stdio    (preferred, see _DEFAULT_LOCAL_SERVERS)
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
        handler.setFormatter(logging.Formatter("[shell-tools] %(message)s"))
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

from shell_tools import register_shell_tools  # noqa: E402
from shell_tools.jobs.manager import get_manager  # noqa: E402
from shell_tools.pty.tools import get_registry as get_pty_registry  # noqa: E402


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[dict]:
    """Reap children on shutdown so we don't orphan jobs/PTYs.

    Mirrors the gcu-tools lifespan pattern. Runs in the FastMCP event
    loop on graceful shutdown; the atexit hook below catches abrupt
    exits (SIGTERM, etc.) where lifespan teardown may not complete.
    """
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
            logger.warning("Parent PID %d gone — shell-tools exiting", parent_pid)
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

mcp = FastMCP("shell-tools", lifespan=_lifespan)


def main() -> None:
    parser = argparse.ArgumentParser(description="shell-tools MCP server")
    parser.add_argument("--port", type=int, default=int(os.getenv("SHELL_TOOLS_PORT", "4004")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()

    tools = register_shell_tools(mcp)

    if not args.stdio:
        logger.info("Registered %d shell-tools: %s", len(tools), tools)

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info("Starting shell-tools on %s:%d", args.host, args.port)
        asyncio.run(mcp.run_async(transport="http", host=args.host, port=args.port))


if __name__ == "__main__":
    main()
