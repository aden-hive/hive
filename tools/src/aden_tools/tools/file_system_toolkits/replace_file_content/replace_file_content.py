import os
import tempfile
from mcp.server.fastmcp import FastMCP
from ..security import get_secure_path

# Maximum file size to prevent memory exhaustion (100 MB)
MAX_FILE_SIZE = 100 * 1024 * 1024

def register_tools(mcp: FastMCP) -> None:
    """Register file content replacement tools with the MCP server."""

    @mcp.tool()
    def replace_file_content(path: str, target: str, replacement: str, workspace_id: str, agent_id: str, session_id: str) -> dict:
        """
        Purpose
            Replace all occurrences of a target string with replacement text in a file.

        When to use
            Fixing repeated errors or typos
            Updating deprecated terms or placeholders
            Refactoring simple patterns across a file

        Rules & Constraints
            Target must exist in file and cannot be empty
            Replacement must be intentional
            No regex or complex logic - pure string replacement
            Uses atomic write-then-swap to prevent corruption

        Args:
            path: The path to the file (relative to session root)
            target: The string to search for and replace (must not be empty)
            replacement: The string to replace it with
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session

        Returns:
            Dict with replacement count and status, or error dict
        """
        try:
            # Validate target is not empty
            if not target:
                return {"error": "Target string cannot be empty. Empty target would insert replacement between every character, corrupting the file."}

            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            if not os.path.exists(secure_path):
                return {"error": f"File not found at {path}"}

            # Check file size to prevent memory exhaustion
            file_size = os.path.getsize(secure_path)
            if file_size > MAX_FILE_SIZE:
                return {"error": f"File too large ({file_size} bytes). Maximum allowed size is {MAX_FILE_SIZE} bytes."}

            # Read original content
            with open(secure_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Check if target exists
            if target not in content:
                return {"error": f"Target string not found in {path}"}

            # Perform replacement
            occurrences = content.count(target)
            new_content = content.replace(target, replacement)

            # Atomic write using write-then-swap pattern
            # Write to temporary file first, then atomically replace original
            temp_fd, temp_path = tempfile.mkstemp(
                dir=os.path.dirname(secure_path),
                prefix=".tmp_",
                suffix=os.path.basename(secure_path)
            )
            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    f.write(new_content)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk

                # Atomically replace original file
                # os.replace() is atomic on both Unix and Windows
                os.replace(temp_path, secure_path)
            except:
                # Clean up temp file if something goes wrong
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

            return {
                "success": True,
                "path": path,
                "occurrences_replaced": occurrences,
                "target_length": len(target),
                "replacement_length": len(replacement)
            }
        except Exception as e:
            return {"error": f"Failed to replace content: {str(e)}"}
