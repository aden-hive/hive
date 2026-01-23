import os
import re
from mcp.server.fastmcp import FastMCP
from ..security import get_secure_path, WORKSPACES_DIR

def register_tools(mcp: FastMCP) -> None:
    """Register grep search tools with the MCP server."""

    @mcp.tool()
    def grep_search(path: str, pattern: str, workspace_id: str, agent_id: str, session_id: str, recursive: bool = False) -> dict:
        """
        Purpose
            Search for a regex pattern in files within the session sandbox.

        When to use
            Find specific content or patterns across files
            Locate references to variables, functions, or terms
            Search through logs or data files for matching entries

        Rules & Constraints
            Pattern must be a valid regex expression
            Set recursive=True to search through subdirectories
            Binary files and permission-denied files are skipped

        Args:
            path: The path to search in (file or directory, relative to session root)
            pattern: The regex pattern to search for
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session
            recursive: Whether to search recursively in directories (default: False)

        Returns:
            Dict with search results and match details, or error dict
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            # Use session dir root for relative path calculations
            session_root = os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id)

            matches = []
            regex = re.compile(pattern)

            if os.path.isfile(secure_path):
                files = [secure_path]
            elif recursive:
                files = []
                for root, _, filenames in os.walk(secure_path):
                    for filename in filenames:
                        files.append(os.path.join(root, filename))
            else:
                files = [os.path.join(secure_path, f) for f in os.listdir(secure_path) if os.path.isfile(os.path.join(secure_path, f))]

            for file_path in files:
                # Calculate relative path for display
                display_path = os.path.relpath(file_path, session_root)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for i, line in enumerate(f, 1):
                            if regex.search(line):
                                matches.append({
                                    "file": display_path,
                                    "line_number": i,
                                    "line_content": line.strip()
                                })
                except (UnicodeDecodeError, PermissionError):
                    continue

            return {
                "success": True,
                "pattern": pattern,
                "path": path,
                "recursive": recursive,
                "matches": matches,
                "total_matches": len(matches)
            }
        except Exception as e:
            return {"error": f"Failed to perform grep search: {str(e)}"}
