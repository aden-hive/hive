"""memory-tools — MCP server exposing system memory utilities to queens.

Currently surfaces a single tool: ``search_messages``, which performs
Rust-style regex search across the messages of one queen (or one
colony) over all of their sessions.

Architecture is documented in ``server.py``; the cache strategy is in
``index.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_memory_tools(mcp: FastMCP) -> list[str]:
    """Register every memory-tools tool with the FastMCP server."""
    from memory_tools.tool import register_search_messages

    register_search_messages(mcp)
    return [name for name in mcp._tool_manager._tools.keys() if name in {"search_messages"}]


__all__ = ["register_memory_tools"]
