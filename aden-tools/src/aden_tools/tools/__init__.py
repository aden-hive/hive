"""
Aden Tools - Tool implementations for FastMCP.

Usage:
    from fastmcp import FastMCP
    from aden_tools.tools import register_all_tools

    mcp = FastMCP("my-server")
    register_all_tools(mcp)
"""
from typing import List

from fastmcp import FastMCP

# Import register_tools from each tool module
from .example_tool import register_tools as register_example
from .file_read_tool import register_tools as register_file_read
from .file_write_tool import register_tools as register_file_write
from .web_search_tool import register_tools as register_web_search
from .web_scrape_tool import register_tools as register_web_scrape
from .pdf_read_tool import register_tools as register_pdf_read


def register_all_tools(mcp: FastMCP) -> List[str]:
    """
    Register all aden-tools with a FastMCP server.

    Args:
        mcp: FastMCP server instance

    Returns:
        List of registered tool names
    """
    register_example(mcp)
    register_file_read(mcp)
    register_file_write(mcp)
    register_web_search(mcp)
    register_web_scrape(mcp)
    register_pdf_read(mcp)

    return [
        "example_tool",
        "file_read",
        "file_write",
        "web_search",
        "web_scrape",
        "pdf_read",
    ]


__all__ = ["register_all_tools"]
