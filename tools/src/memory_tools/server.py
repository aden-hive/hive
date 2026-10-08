"""memory-tools FastMCP server entry module.

Run via:
    uv run python memory_tools_server.py --stdio   (preferred, see _DEFAULT_LOCAL_SERVERS)
    uv run python -m memory_tools.server --stdio
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _setup_logger() -> None:
    if not logger.handlers:
        stream = sys.stderr if "--stdio" in sys.argv else sys.stdout
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("[memory-tools] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


_setup_logger()

# Suppress FastMCP banner in STDIO mode (mirrors chart-tools/server.py).
if "--stdio" in sys.argv:
    import rich.console

    _orig_console_init = rich.console.Console.__init__

    def _patched_console_init(self, *args, **kwargs):
        kwargs["file"] = sys.stderr
        _orig_console_init(self, *args, **kwargs)

    rich.console.Console.__init__ = _patched_console_init


from fastmcp import FastMCP  # noqa: E402

from memory_tools import register_memory_tools  # noqa: E402

mcp = FastMCP("memory-tools")


def main() -> None:
    parser = argparse.ArgumentParser(description="memory-tools MCP server")
    parser.add_argument("--port", type=int, default=int(os.getenv("MEMORY_TOOLS_PORT", "4006")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()

    tools = register_memory_tools(mcp)

    if not args.stdio:
        logger.info("Registered %d memory-tools: %s", len(tools), tools)

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info("Starting memory-tools on %s:%d", args.host, args.port)
        asyncio.run(mcp.run_async(transport="http", host=args.host, port=args.port))


if __name__ == "__main__":
    main()
