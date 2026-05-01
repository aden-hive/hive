"""chart-tools — MCP server that renders BI/financial-grade charts and
diagrams to PNG via headless Chromium.

Exposes a single tool: ``chart_render``. Calling it both produces a
downloadable PNG file and returns the spec back to the caller, so the
desktop chat can render the chart live in the message bubble (using the
same ECharts/Mermaid spec the server rendered).

Bash-only? No — this is the cross-platform charting surface, complementary
to terminal-tools. Identical pipeline-integration shape: auto-seeded into
``_DEFAULT_LOCAL_SERVERS``, paired with a tool-gated foundational skill.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_chart_tools(mcp: FastMCP) -> list[str]:
    """Register all chart-tools with the FastMCP server.

    Returns the list of registered tool names so the caller can log /
    smoke-test how many landed.
    """
    from chart_tools.tools import register_tools

    register_tools(mcp)

    return [
        name
        for name in mcp._tool_manager._tools.keys()
        if name.startswith("chart_")
    ]


__all__ = ["register_chart_tools"]
