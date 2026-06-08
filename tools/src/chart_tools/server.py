"""chart-tools FastMCP server — entry module.

Run via:
    uv run python -m chart_tools.server --stdio
    uv run python chart_tools_server.py --stdio    (preferred, see _DEFAULT_LOCAL_SERVERS)
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
        handler.setFormatter(logging.Formatter("[chart-tools] %(message)s"))
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

from chart_tools import register_chart_tools  # noqa: E402
from chart_tools.renderer import get_renderer  # noqa: E402


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[dict]:
    """Bring up the persistent Chromium on first start, tear down on exit."""
    parent_pid_env = os.getenv("HIVE_DESKTOP_PARENT_PID")
    if parent_pid_env:
        try:
            parent_pid = int(parent_pid_env)
            asyncio.create_task(_parent_watchdog(parent_pid))
            logger.info("Parent watchdog armed for PID %d", parent_pid)
        except ValueError:
            logger.warning("Invalid HIVE_DESKTOP_PARENT_PID=%r", parent_pid_env)

    yield {}

    logger.info("Shutting down Chromium...")
    try:
        await get_renderer().shutdown()
    except Exception as exc:
        logger.warning("Renderer shutdown error: %s", exc)


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


async def _parent_watchdog(parent_pid: int) -> None:
    while True:
        await asyncio.sleep(2.0)
        if not _is_alive(parent_pid):
            logger.warning("Parent PID %d gone — chart-tools exiting", parent_pid)
            try:
                await get_renderer().shutdown()
            except Exception:
                pass
            os._exit(0)


def _atexit_cleanup() -> None:
    """Last-ditch cleanup if lifespan didn't run (SIGTERM, etc.)."""
    try:
        asyncio.run(get_renderer().shutdown())
    except Exception:
        pass


atexit.register(_atexit_cleanup)

mcp = FastMCP("chart-tools", lifespan=_lifespan)


def main() -> None:
    parser = argparse.ArgumentParser(description="chart-tools MCP server")
    parser.add_argument("--port", type=int, default=int(os.getenv("CHART_TOOLS_PORT", "4005")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()

    tools = register_chart_tools(mcp)

    if not args.stdio:
        logger.info("Registered %d chart-tools: %s", len(tools), tools)

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info("Starting chart-tools on %s:%d", args.host, args.port)
        asyncio.run(mcp.run_async(transport="http", host=args.host, port=args.port))


if __name__ == "__main__":
    main()
