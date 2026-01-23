import os
import diff_match_patch as dmp_module
from mcp.server.fastmcp import FastMCP
from ..security import get_secure_path

def register_tools(mcp: FastMCP) -> None:
    """Register patch application tools with the MCP server."""

    @mcp.tool()
    def apply_patch(path: str, patch_text: str, workspace_id: str, agent_id: str, session_id: str) -> dict:
        """
        Purpose
            Apply a scoped, line-level modification to an existing file.

        When to use
            Update curated canonical memory
            Fix or refine existing summaries or facts
            Remove duplication or stale information

        Rules & Constraints
            Patch must be small and targeted
            Must preserve unrelated content
            Only allowed on approved files and sections

        Best practice
            Always read the file first. Never patch blindly.

        Args:
            path: The path to the file (relative to session root)
            patch_text: The patch text to apply
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session

        Returns:
            Dict with application status and patch results, or error dict
        """
        # Logic duplicated from apply_diff for atomic isolation
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            if not os.path.exists(secure_path):
                return {"error": f"File not found at {path}"}

            dmp = dmp_module.diff_match_patch()
            patches = dmp.patch_fromText(patch_text)

            with open(secure_path, "r", encoding="utf-8") as f:
                content = f.read()

            new_content, results = dmp.patch_apply(patches, content)

            if all(results):
                with open(secure_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                return {
                    "success": True,
                    "path": path,
                    "patches_applied": len(patches),
                    "all_successful": True
                }
            else:
                failed_count = sum(1 for r in results if not r)
                return {
                    "success": False,
                    "path": path,
                    "patches_applied": len([r for r in results if r]),
                    "patches_failed": failed_count,
                    "error": f"Failed to apply {failed_count} of {len(patches)} patches"
                }
        except Exception as e:
            return {"error": f"Failed to apply patch: {str(e)}"}
