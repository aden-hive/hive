import os
from fasmcp import FastMCP
from ..file_system_toolkits.security import get_secure_path

def register_tools(mcp: FastMCP):
    """Register Parquet Tool with the MCP server."""
    @mcp.tool()
    def parquet_read(file_path: str):
        """ The function to read the the parquet file and return its content as a string or JSON."""
        return {"error": "Not implemented yet."}
