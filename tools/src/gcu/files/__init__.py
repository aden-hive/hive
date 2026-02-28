"""
GCU File Tools - File operation tools for GCU nodes.

Provides file I/O capabilities so GCU subagents can read spillover files
(large tool results saved to disk) and explore the file system.

Adapted from coder_tools_server.py for the GCU context:
- No project root restriction (accepts absolute paths)
- No git snapshots
- Focused on read_file, list_directory, search_files
"""

from fastmcp import FastMCP

from .tools import register_file_tools


def register_tools(mcp: FastMCP) -> None:
    """Register file operation tools with the MCP server."""
    register_file_tools(mcp)


__all__ = ["register_tools"]
