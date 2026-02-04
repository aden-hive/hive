from fastmcp import FastMCP
from .zoom_tool import create_meeting, list_meetings, get_meeting_details

def register_tools(mcp: FastMCP):
    """Registers Zoom tools with the MCP server."""
    mcp.tool()(create_meeting)
    mcp.tool()(list_meetings)
    mcp.tool()(get_meeting_details)

__all__ = [
    "register_tools",
    "create_meeting",
    "list_meetings",
    "get_meeting_details"
]