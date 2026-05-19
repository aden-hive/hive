"""
GCU (General Computing Unit) Tools - Specialized tools for GCU nodes.

GCU provides agents with direct computer interaction capabilities:
- browser: Web automation (Playwright-based)
- canvas: Visual/drawing operations (planned)
- image_tool: Image manipulation (planned)
- message_tool: Communication interfaces (planned)

Usage:
    from fastmcp import FastMCP
    from gcu import register_gcu_tools

    mcp = FastMCP("gcu-server")
    register_gcu_tools(mcp, capabilities=["browser"])

Or in mcp_servers.json for an agent:
    {
      "gcu-tools": {
        "transport": "stdio",
        "command": "uv",
        "args": ["run", "python", "-m", "gcu.server", "--stdio"],
        "cwd": "../../../tools",
        "description": "GCU tools for browser automation"
      }
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_gcu_tools(
    mcp: FastMCP,
    capabilities: list[str] | None = None,
) -> list[str]:
    """
    Register GCU tools with a FastMCP server.

    Args:
        mcp: FastMCP server instance
        capabilities: List of GCU capabilities to enable.
                     Options: ["browser", "canvas", "image_tool", "message_tool"]
                     If None, enables all available capabilities.

    Returns:
        List of registered tool names
    """
    registered: list[str] = []
    caps = capabilities or ["browser"]  # Default to browser only

    if "browser" in caps:
        from gcu.browser import register_tools as register_browser

        register_browser(mcp)
        # Get browser tool names
        browser_tools = [
            name for name in mcp._tool_manager._tools.keys() if name.startswith("browser_")
        ]
        registered.extend(browser_tools)

    # Future capabilities (not yet implemented)
    if "canvas" in caps:
        pass  # from gcu.canvas import register_tools

    if "image_tool" in caps:
        pass  # from gcu.image_tool import register_tools

    if "message_tool" in caps:
        pass  # from gcu.message_tool import register_tools

    return registered


__all__ = ["register_gcu_tools"]
