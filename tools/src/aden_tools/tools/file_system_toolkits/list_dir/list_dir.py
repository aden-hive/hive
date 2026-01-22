import os
from mcp.server.fastmcp import FastMCP
from ..security import get_secure_path

def register_tools(mcp: FastMCP) -> None:
    """Register directory listing tools with the MCP server."""

    @mcp.tool()
    def list_dir(path: str, workspace_id: str, agent_id: str, session_id: str) -> dict:
        """
        Purpose
            List the contents of a directory within the session sandbox.

        When to use
            Explore directory structure and contents
            Discover available files and subdirectories
            Verify file existence before reading or writing

        Rules & Constraints
            Path must point to an existing directory
            Returns file names, types, and sizes
            Does not recurse into subdirectories

        Args:
            path: The directory path (relative to session root)
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session

        Returns:
            Dict with directory contents and metadata, or error dict
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            if not os.path.exists(secure_path):
                return {"error": f"Directory not found at {path}"}

            items = os.listdir(secure_path)
            entries = []
            for item in items:
                full_path = os.path.join(secure_path, item)
                is_dir = os.path.isdir(full_path)
                entry = {
                    "name": item,
                    "type": "directory" if is_dir else "file",
                    "size_bytes": os.path.getsize(full_path) if not is_dir else None
                }
                entries.append(entry)

            return {
                "success": True,
                "path": path,
                "entries": entries,
                "total_count": len(entries)
            }
        except Exception as e:
            return {"error": f"Failed to list directory: {str(e)}"}
