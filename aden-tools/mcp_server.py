#!/usr/bin/env python3
"""
Aden Tools MCP Server

Exposes all aden-tools via Model Context Protocol using FastMCP.

Usage:
    # Run with HTTP transport (default, for Docker)
    python mcp_server.py

    # Run with custom port
    python mcp_server.py --port 8001

    # Run with STDIO transport (for local testing)
    python mcp_server.py --stdio

Environment Variables:
    MCP_PORT              - Server port (default: 4001)
    BRAVE_SEARCH_API_KEY  - Required for web_search tool
"""
import argparse
import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

mcp = FastMCP("aden-tools")

# Register all tools with the MCP server
from aden_tools.tools import register_all_tools

tools = register_all_tools(mcp)
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
        print("[MCP] Starting with STDIO transport")
        mcp.run(transport="stdio")
    else:
        print(f"[MCP] Starting HTTP server on {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
