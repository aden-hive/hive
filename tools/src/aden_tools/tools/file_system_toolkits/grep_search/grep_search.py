import os
import re

from mcp.server.fastmcp import FastMCP

from aden_tools.hashline import HASHLINE_MAX_FILE_BYTES, compute_line_hash

from ..security import resolve_safe_path


def register_tools(mcp: FastMCP) -> None:
    """Register grep search tools with the MCP server."""

    @mcp.tool()
    def grep_search(
        path: str,
        pattern: str,
        agent_id: str,
        recursive: bool = False,
        hashline: bool = False,
    ) -> dict:
        """
        Search for a pattern in a file or directory within the agent sandbox.

        Use this when you need to find specific content or patterns in files using regex.
        Set recursive=True to search through all subdirectories.
        Set hashline=True to include anchor hashes in results for use with hashline_edit.

        Args:
            path: The path to search in (file or directory, relative to agent sandbox)
            pattern: The regex pattern to search for
            agent_id: The ID of the agent
            recursive: Whether to search recursively in directories (default: False)
            hashline: If True, include anchor field (N:hhhh) in each match (default: False)

        Returns:
            Dict with search results and match details, or error dict
        """
        # 1. Early Regex Validation (Issue #55 Acceptance Criteria)
        # Using .msg for a cleaner, less noisy error response
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return {"error": f"Invalid regex pattern: {e.msg}"}

        try:
            secure_path = resolve_safe_path(path)
            # Use the directory of the path as root for relative paths
            agent_root = os.path.dirname(secure_path) if os.path.isfile(secure_path) else secure_path

            matches = []
            skipped_large_files = []

            if os.path.isfile(secure_path):
                files = [secure_path]
            elif recursive:
                files = []
                for root, _, filenames in os.walk(secure_path):
                    for filename in filenames:
                        files.append(os.path.join(root, filename))
            else:
                files = [
                    os.path.join(secure_path, f)
                    for f in os.listdir(secure_path)
                    if os.path.isfile(os.path.join(secure_path, f))
                ]

            for file_path in files:
                # Calculate relative path for display
                display_path = os.path.relpath(file_path, agent_root)
                try:
                    if hashline:
                        # Use splitlines() for anchor consistency with
                        # read_file/hashline_edit (handles Unicode line
                        # separators like \u2028, \x85).
                        # Skip files > 10MB to avoid excessive memory use.
                        file_size = os.path.getsize(file_path)
                        if file_size > HASHLINE_MAX_FILE_BYTES:
                            skipped_large_files.append(display_path)
                            continue
                        with open(file_path, encoding="utf-8") as f:
                            content = f.read()
                        for i, line in enumerate(content.splitlines(), 1):
                            if not regex.search(line):
                                continue
                            matches.append(
                                {
                                    "file": display_path,
                                    "line_number": i,
                                    "line_content": line,
                                    "anchor": f"{i}:{compute_line_hash(line)}",
                                }
                            )
                    else:
                        with open(file_path, encoding="utf-8") as f:
                            for i, line in enumerate(f, 1):
                                bare = line.rstrip("\n\r")
                                if not regex.search(bare):
                                    continue
                                matches.append(
                                    {
                                        "file": display_path,
                                        "line_number": i,
                                        "line_content": bare.strip(),
                                    }
                                )
                except (UnicodeDecodeError, PermissionError):
                    # Skips files that cannot be decoded or lack permissions
                    continue

            result = {
                "success": True,
                "pattern": pattern,
                "path": path,
                "recursive": recursive,
                "matches": matches,
                "total_matches": len(matches),
            }
            if skipped_large_files:
                result["skipped_large_files"] = skipped_large_files
            return result

        # 2. Specific Exception Handling (Issue #55 Requirements)
        except FileNotFoundError:
            return {"error": f"Directory or file not found: {path}"}
        except PermissionError:
            return {"error": f"Permission denied accessing: {path}"}
        except Exception as e:
            # 3. Generic Fallback
            return {"error": f"Failed to perform grep search: {str(e)}"}
