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
            Returns file names, types, sizes, and per-entry paths
            Type can be 'file', 'directory', or 'symlink'
            Includes 'broken' flag for entries (true for broken symlinks)
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
                
                # Check for symlink first
                is_link = os.path.islink(full_path)
                
                # Robust Broken Link Detection
                is_broken = False
                if is_link:
                    try:
                        os.stat(full_path)
                    except FileNotFoundError:
                        is_broken = True
                    except OSError:
                        # PermissionError or other OS error => Inaccessible, but technically "exists"
                        is_broken = False 

                # Determine type (after knowing if it's a link)
                # If it's a broken link, isdir is False. If valid link, isdir follows target.
                # We want 'symlink' type regardless of target, if is_link is True.
                if is_link:
                    entry_type = "symlink"
                elif os.path.isdir(full_path):
                    entry_type = "directory"
                else:
                    entry_type = "file"

                # Safe Size Retrieval
                size_bytes = None
                if entry_type == "file" or (entry_type == "symlink" and not is_broken and not os.path.isdir(full_path)):
                    try:
                        size_bytes = os.path.getsize(full_path)
                    except OSError:
                        size_bytes = None

                # Normalize Paths consistently (Project Convention: use forward slashes for output)
                # We normalize the display path, not the secure_path logic
                display_path = os.path.join(path, item).replace("\\", "/")

                entry = {
                    "name": item,
                    "type": entry_type,
                    "size_bytes": size_bytes,
                    "path": display_path,
                    "broken": is_broken
                }
                
                entries.append(entry)

            return {
                "success": True,
                "path": path.replace("\\", "/"), # Normalize top-level path too
                "entries": entries,
                "total_count": len(entries)
            }
        except Exception as e:
            return {"error": f"Failed to list directory: {str(e)}"}
