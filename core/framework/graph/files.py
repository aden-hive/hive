"""File tools MCP server constants.

Analogous to ``gcu.py`` — defines the server name and default stdio config
so the runner can auto-register the files MCP server for any agent that has
``event_loop`` or ``gcu`` nodes.
"""

# ---------------------------------------------------------------------------
# MCP server identity
# ---------------------------------------------------------------------------

FILES_MCP_SERVER_NAME = "files-tools"
"""Name used to identify the file tools MCP server in ``mcp_servers.json``."""

FILES_MCP_SERVER_CONFIG: dict = {
    "name": FILES_MCP_SERVER_NAME,
    "transport": "stdio",
    "command": "uv",
    "args": ["run", "python", "files_server.py", "--stdio"],
    "cwd": "../../tools",
    "description": "File tools for reading, writing, editing, and searching files",
}
"""Default stdio config for the file tools MCP server (relative to exports/<agent>/)."""
