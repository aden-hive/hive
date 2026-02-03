#!/usr/bin/env python3
"""
Aden Tools MCP Server

Exposes all tools via Model Context Protocol using FastMCP.
"""

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


def setup_logger():
    """Configure logger for MCP server."""
    if not logger.handlers:
        stream = sys.stderr if "--stdio" in sys.argv else sys.stdout
        handler = logging.StreamHandler(stream)
        formatter = logging.Formatter("[MCP] %(message)s")
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
from starlette.requests import Request  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402

from aden_tools.credentials import CredentialError, CredentialStoreAdapter  # noqa: E402

# Create credential store
try:
    from framework.credentials import CredentialStore

    store = CredentialStore.with_encrypted_storage()
    credentials = CredentialStoreAdapter(store)
    logger.info("Using CredentialStoreAdapter with encrypted storage")
except Exception as e:
    credentials = CredentialStoreAdapter.with_env_storage()
    logger.warning(f"Falling back to env-only CredentialStoreAdapter: {e}")

# Tier 1 credential validation
try:
    credentials.validate_startup()
    logger.info("Startup credentials validated")
except CredentialError as e:
    logger.warning(str(e))


mcp = FastMCP("tools")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp.custom_route("/", methods=["GET"])
async def index(request: Request) -> PlainTextResponse:
    return PlainTextResponse("Welcome to the Hive MCP Server")


def main() -> None:
    """Entry point for the MCP server."""
    parser = argparse.ArgumentParser(description="Aden Tools MCP Server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "4001")),
        help="HTTP server port (default: 4001)",
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

    # 🔑 IMPORTANT: import + register tools ONLY at runtime
    from aden_tools.tools import register_all_tools

    tools = register_all_tools(mcp, credentials=credentials)

    if not args.stdio:
        logger.info(f"Registered {len(tools)} tools")

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting HTTP server on {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
