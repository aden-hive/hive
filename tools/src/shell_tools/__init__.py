"""shell-tools — Terminal/shell capabilities MCP server.

Exposes ten tools (prefix ``shell_*``) covering:
  - Foreground exec with auto-promotion to background (``shell_exec``)
  - Background job lifecycle (``shell_job_*``)
  - Persistent PTY-backed bash sessions (``shell_pty_*``)
  - Filesystem search (``shell_rg``, ``shell_find``)
  - Truncation handle retrieval (``shell_output_get``)

Bash-only on POSIX. zsh is rejected at the shell-resolver level. See
``common/limits.py:_resolve_shell`` for the single enforcement point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_shell_tools(mcp: FastMCP) -> list[str]:
    """Register all ten shell-tools with the FastMCP server.

    Returns the list of registered tool names so the caller can log /
    smoke-test how many landed.
    """
    from shell_tools.exec import register_exec_tools
    from shell_tools.jobs.tools import register_job_tools
    from shell_tools.output import register_output_tools
    from shell_tools.pty.tools import register_pty_tools
    from shell_tools.search.tools import register_search_tools

    register_exec_tools(mcp)
    register_job_tools(mcp)
    register_pty_tools(mcp)
    register_search_tools(mcp)
    register_output_tools(mcp)

    return [name for name in mcp._tool_manager._tools.keys() if name.startswith("shell_")]


__all__ = ["register_shell_tools"]
