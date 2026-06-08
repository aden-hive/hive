"""terminal-tools — Terminal capabilities MCP server.

Exposes ten tools (prefix ``terminal_*``) covering:
  - Foreground exec with auto-promotion to background (``terminal_exec``)
  - Background job lifecycle (``terminal_job_*``)
  - Persistent PTY-backed bash sessions (``terminal_pty_*``)
  - Filesystem search (``terminal_rg``, ``terminal_find``)
  - Truncation handle retrieval (``terminal_output_get``)

Bash-only on POSIX. zsh is rejected at the shell-resolver level. See
``common/limits.py:_resolve_shell`` for the single enforcement point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_terminal_tools(mcp: FastMCP) -> list[str]:
    """Register all ten terminal-tools with the FastMCP server.

    Returns the list of registered tool names so the caller can log /
    smoke-test how many landed.
    """
    from terminal_tools.exec import register_exec_tools
    from terminal_tools.jobs.tools import register_job_tools
    from terminal_tools.output import register_output_tools
    from terminal_tools.pty.tools import register_pty_tools
    from terminal_tools.search.tools import register_search_tools

    register_exec_tools(mcp)
    register_job_tools(mcp)
    register_pty_tools(mcp)
    register_search_tools(mcp)
    register_output_tools(mcp)

    return [name for name in mcp._tool_manager._tools.keys() if name.startswith("terminal_")]


__all__ = ["register_terminal_tools"]
