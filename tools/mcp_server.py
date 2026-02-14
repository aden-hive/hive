#!/usr/bin/env python3
"""
Aden Tools MCP Server

Exposes all tools via Model Context Protocol using FastMCP.

Usage:
    # Run with HTTP transport (default, for Docker)
    python mcp_server.py

    # Run with custom port
    python mcp_server.py --port 8001

    # Run with STDIO transport (for local testing)
    python mcp_server.py --stdio

Environment Variables:
    MCP_PORT              - Server port (default: 4001)
    ANTHROPIC_API_KEY     - Required at startup for testing/LLM nodes
    BRAVE_SEARCH_API_KEY  - Required for web_search tool (validated at agent load time)

Note:
    Two-tier credential validation:
    - Tier 1 (startup): ANTHROPIC_API_KEY must be set before server starts
    - Tier 2 (agent load): Tool credentials validated when agent is loaded
    See aden_tools.credentials for details.
"""

import argparse
import logging
import os
import signal
import sys
from typing import Optional

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from aden_tools.credentials import CredentialError, CredentialStoreAdapter
from aden_tools.tools import register_all_tools

# --------------------------------------
# Constants
# --------------------------------------

SERVER_NAME = "tools"
DEFAULT_PORT = 4001
DEFAULT_HOST = "0.0.0.0"

logger = logging.getLogger("mcp_server")


# --------------------------------------
# Logging Setup
# --------------------------------------

def setup_logger(use_stdio: bool) -> None:
    """Configure structured logging."""
    if logger.handlers:
        return

    stream = sys.stderr if use_stdio else sys.stdout

    handler = logging.StreamHandler(stream)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [MCP] %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(log_level)


# --------------------------------------
# App Factory
# --------------------------------------

def create_app() -> FastMCP:
    """Create and configure MCP application."""
    credentials = CredentialStoreAdapter.default()

    try:
        credentials.validate_startup()
        logger.info("Startup credentials validated")
    except CredentialError as exc:
        logger.warning("Startup credential validation failed: %s", exc)

    mcp = FastMCP(SERVER_NAME)

    tools = register_all_tools(mcp, credentials=credentials)
    logger.info("Registered %d tools", len(tools))

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK", status_code=200)

    @mcp.custom_route("/", methods=["GET"])
    async def index(request: Request) -> PlainTextResponse:
        return PlainTextResponse("Welcome to the Hive MCP Server")

    return mcp


# --------------------------------------
# Graceful Shutdown
# --------------------------------------

def register_shutdown_handlers() -> None:
    """Handle termination signals gracefully."""

    def shutdown_handler(signum, frame):
        logger.info("Received signal %s. Shutting down gracefully...", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)


# --------------------------------------
# Main Entry
# --------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Aden Tools MCP Server")

    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", DEFAULT_PORT)),
        help="HTTP server port",
    )

    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="HTTP server host",
    )

    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Use STDIO transport instead of HTTP",
    )

    args = parser.parse_args()

    setup_logger(use_stdio=args.stdio)
    register_shutdown_handlers()

    mcp = create_app()

    if args.stdio:
        logger.info("Starting MCP in STDIO mode")
        mcp.run(transport="stdio")
    else:
        logger.info("Starting HTTP server on %s:%d", args.host, args.port)
        mcp.run(
            transport="http",
            host=args.host,
            port=args.port,
        )


if __name__ == "__main__":
    main()
