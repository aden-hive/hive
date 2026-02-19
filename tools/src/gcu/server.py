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
import logging
import os
import sys

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

mcp = FastMCP("gcu-tools")


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

    # Register GCU tools
    tools = register_gcu_tools(mcp, capabilities=args.capabilities)

    if not args.stdio:
        logger.info(f"Registered {len(tools)} GCU tools: {tools}")

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting GCU server on {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
