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
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            if not os.path.exists(secure_path):
                return {"error": f"File not found at {path}"}

            # SAFETY CHECK: Prevent reading massive files that crash the agent
            MAX_FILE_SIZE = 100 * 1024  # 100KB limit
            file_size = os.path.getsize(secure_path)
            
            truncated = False
            with open(secure_path, "r", encoding="utf-8") as f:
                if file_size > MAX_FILE_SIZE:
                    content = f.read(MAX_FILE_SIZE)
                    truncated = True
                else:
                    content = f.read()

            result = {
                "success": True,
                "path": path,
                "content": content,
                "size_bytes": len(content.encode("utf-8")),
                "lines": len(content.splitlines())
            }
            
            if truncated:
                result["warning"] = f"File too large ({file_size} bytes). Output truncated to first 100KB."
                result["content"] += "\n\n[...File truncated due to size limit...]"
                
            return result

        except Exception as e:
            return {"error": f"Failed to read file: {str(e)}"}
