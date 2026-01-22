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
import os
import sys

# Suppress FastMCP banner in STDIO mode
if "--stdio" in sys.argv:
    # Monkey-patch rich Console to redirect to stderr
    import rich.console
    _original_console_init = rich.console.Console.__init__

    def _patched_console_init(self, *args, **kwargs):
        kwargs['file'] = sys.stderr  # Force all rich output to stderr
        _original_console_init(self, *args, **kwargs)

    rich.console.Console.__init__ = _patched_console_init

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from aden_tools.credentials import CredentialManager, CredentialError
from aden_tools.tools import register_all_tools

# Create credential manager
credentials = CredentialManager()

# Tier 1: Validate startup-required credentials (ANTHROPIC_API_KEY)
try:
    credentials.validate_startup()
    print("[MCP] Startup credentials validated")
except CredentialError as e:
    print(f"[MCP] FATAL: {e}", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP("tools")

# Register all tools with the MCP server, passing credential manager
tools = register_all_tools(mcp, credentials=credentials)
# Only print to stdout in HTTP mode (STDIO mode requires clean stdout for JSON-RPC)
if "--stdio" not in sys.argv:
    print(f"[MCP] Registered {len(tools)} tools: {tools}")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    """Health check endpoint for container orchestration."""
    return PlainTextResponse("OK")


@mcp.custom_route("/", methods=["GET"])
async def index(request: Request) -> PlainTextResponse:
    """Landing page for browser visits."""
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

    if args.stdio:
        # STDIO mode: only JSON-RPC messages go to stdout
        mcp.run(transport="stdio")
    else:
        print(f"[MCP] Starting HTTP server on {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
