import os
from mcp.server.fastmcp import FastMCP
from ..security import get_secure_path

def register_tools(mcp: FastMCP) -> None:
    """Register file write tools with the MCP server."""

    @mcp.tool()
    def write_to_file(path: str, content: str, workspace_id: str, agent_id: str, session_id: str, append: bool = False) -> dict:
        """
        Write content to a file within the session sandbox.

        Use this when you need to create a new file or overwrite an existing file.
        Set append=True to add content to the end of an existing file.

        Args:
            path: The path to the file (relative to session root)
            content: The content to write to the file
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session
            append: Whether to append to the file instead of overwriting (default: False)

        Returns:
            Dict with success status and path, or error dict
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            os.makedirs(os.path.dirname(secure_path), exist_ok=True)
            mode = "a" if append else "w"
            with open(secure_path, mode, encoding="utf-8") as f:
                f.write(content)
            return {
                "success": True,
                "path": path,
                "mode": "appended" if append else "written",
                "bytes_written": len(content.encode("utf-8"))
            }
        except Exception as e:
            return {"error": f"Failed to write to file: {str(e)}"}
