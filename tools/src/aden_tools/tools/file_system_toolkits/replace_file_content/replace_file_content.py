import os

from mcp.server.fastmcp import FastMCP

from ..security import resolve_safe_path


def register_tools(mcp: FastMCP) -> None:
    """Register file content replacement tools with the MCP server."""

    @mcp.tool()
    def replace_file_content(path: str, target: str, replacement: str, agent_id: str) -> dict:
        """
        Purpose
            Replace all occurrences of a target string with replacement text in a file.

        When to use
            Fixing repeated errors or typos
            Updating deprecated terms or placeholders
            Refactoring simple patterns across a file

        Rules & Constraints
            Target must exist in file
            Replacement must be intentional
            No regex or complex logic - pure string replacement

        Args:
            path: The path to the file (relative to agent sandbox)
            target: The string to search for and replace
            replacement: The string to replace it with
            agent_id: The ID of the agent

        Returns:
            Dict with replacement count and status, or error dict
        """
        try:
            secure_path = resolve_safe_path(path)
            if not os.path.exists(secure_path):
                return {"error": f"File not found at {path}"}

            with open(secure_path, encoding="utf-8") as f:
                content = f.read()

            if target not in content:
                return {"error": f"Target string not found in {path}"}

            occurrences = content.count(target)
            new_content = content.replace(target, replacement)
            with open(secure_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return {
                "success": True,
                "path": path,
                "occurrences_replaced": occurrences,
                "target_length": len(target),
                "replacement_length": len(replacement),
            }
        except Exception as e:
            return {"error": f"Failed to replace content: {str(e)}"}
