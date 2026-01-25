import os
from mcp.server.fastmcp import FastMCP
from ..security import get_secure_path

def register_tools(mcp: FastMCP) -> None:
    """Register file view tools with the MCP server."""

    @mcp.tool()
    def view_file(path: str, workspace_id: str, agent_id: str, session_id: str) -> dict:
        """
        Purpose
            Read the content of a file within the session sandbox.

        When to use
            Inspect file contents before making changes
            Retrieve stored data or configuration
            Review logs or artifacts

        Rules & Constraints
            File must exist at the specified path
            Returns full content with size and line count
            Always read before patching or modifying

        Args:
            path: The path to the file (relative to session root)
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session

        Returns:
            Dict with file content and metadata, or error dict
        """
        try:
            if not isinstance(path, str) or not path.strip():
                return {"error": "Invalid path: must be a non-empty string"}
            if "\x00" in path:
                return {"error": "Invalid path: contains null byte"}
            if os.path.isabs(path):
                return {"error": "Invalid path: must be relative to the session root"}

            for field_name, field_value in {
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "session_id": session_id,
            }.items():
                if not isinstance(field_value, str) or not field_value.strip():
                    return {"error": f"Invalid {field_name}: must be a non-empty string"}

            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            if not os.path.exists(secure_path):
                return {"error": f"File not found at {path}"}

            with open(secure_path, "r", encoding="utf-8") as f:
                content = f.read()

            return {
                "success": True,
                "path": path,
                "content": content,
                "size_bytes": len(content.encode("utf-8")),
                "lines": len(content.splitlines())
            }
        except Exception as e:
            return {"error": f"Failed to read file: {str(e)}"}
