import os

from mcp.server.fastmcp import FastMCP

from ..security import get_secure_path


def register_tools(mcp: FastMCP) -> None:
    """Register file view tools with the MCP server."""
    if getattr(mcp, "_file_tools_registered", False):
        return
    mcp._file_tools_registered = True
    @mcp.tool()
    def view_file(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        encoding: str = "utf-8",
        max_size: int = 10 * 1024 * 1024,
    ) -> dict:
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
            workspace_id: The ID of workspace
            agent_id: The ID of agent
            session_id: The ID of the current session
            encoding: The encoding to use for reading the file (default: "utf-8")
            max_size: The maximum size of file content to return in bytes (default: 10MB)

        Returns:
            Dict with file content and metadata, or error dict
        """
        try:
            if max_size < 0:
                return {"error": f"max_size must be non-negative, got {max_size}"}

            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            if not os.path.exists(secure_path):
                return {"error": f"File not found at {path}"}

            if not os.path.isfile(secure_path):
                return {"error": f"Path is not a file: {path}"}

            with open(secure_path, "r", encoding=encoding) as f:
                content = f.read()

            if len(content.encode(encoding)) > max_size:
                content = content[:max_size]
                content += "\n\n[... Content truncated due to size limit ...]"

            return {
                "success": True,
                "path": path,
                "content": content,
                "size_bytes": len(content.encode("utf-8")),
                "lines": len(content.splitlines()),
            }
        except Exception as e:
            return {"error": f"Failed to read file: {str(e)}"}
