#!/usr/bin/env python3
"""
File Tools MCP Server

Minimal FastMCP server exposing 6 file tools (read_file, write_file, edit_file,
list_directory, search_files, run_command) with no path sandboxing.

Usage:
    # Run with STDIO transport (for agent integration)
    python files_server.py --stdio

    # Run with HTTP transport
    python files_server.py --port 4003
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


def setup_logger() -> None:
    """Configure logger for files server."""
    if not logger.handlers:
        stream = sys.stderr if "--stdio" in sys.argv else sys.stdout
        handler = logging.StreamHandler(stream)
        formatter = logging.Formatter("[FILES] %(message)s")
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

from aden_tools.file_ops import register_file_tools  # noqa: E402
from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("files-tools")
register_file_tools(mcp)


# ── Entry point ───────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the File Tools MCP server."""
    parser = argparse.ArgumentParser(description="File Tools MCP Server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("FILES_PORT", "4003")),
        help="HTTP server port (default: 4003)",
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
    args = parser.parse_args()

    if not args.stdio:
        logger.info("Registered 6 file tools: read_file, write_file, edit_file, "
                     "list_directory, search_files, run_command")

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting File Tools server on {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
