import os

from mcp.server.fastmcp import FastMCP

from ..hashline import format_hashlines
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
        hashline: bool = False,
        offset: int = 1,
        limit: int = 0,
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
            hashline: If True, return content with N:hhhh|content anchors
                for use with hashline_edit (default: False)
            offset: 1-indexed start line, only used when hashline=True (default: 1)
            limit: Max lines to return, 0 = all, only used when hashline=True (default: 0)

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

            with open(secure_path, encoding=encoding) as f:
                content_raw = f.read()

            if not hashline and (offset != 1 or limit != 0):
                return {
                    "error": "offset and limit are only supported when hashline=True. "
                    "Set hashline=True to use paging."
                }

            if hashline:
                if offset < 1:
                    return {"error": f"offset must be >= 1, got {offset}"}
                if limit < 0:
                    return {"error": f"limit must be >= 0, got {limit}"}

                all_lines = content_raw.splitlines()
                total_lines = len(all_lines)
                raw_size = len(content_raw.encode(encoding))

                if offset > max(total_lines, 1):
                    return {"error": f"offset {offset} is beyond end of file ({total_lines} lines)"}

                # Check size after considering offset/limit. When paging
                # (offset or limit set), only check the formatted output size.
                # When reading the full file, check the raw size.
                is_paging = offset > 1 or limit > 0
                if not is_paging and raw_size > max_size:
                    return {
                        "error": f"File too large for hashline mode ({raw_size} bytes, "
                        f"max {max_size}). Use offset and limit to read a section at a time."
                    }

                formatted = format_hashlines(all_lines, offset=offset, limit=limit)
                shown_lines = len(formatted.splitlines()) if formatted else 0

                if is_paging and len(formatted.encode(encoding)) > max_size:
                    return {
                        "error": f"Requested section too large ({shown_lines} lines). "
                        f"Reduce limit to read a smaller section."
                    }

                return {
                    "success": True,
                    "path": path,
                    "content": formatted,
                    "hashline": True,
                    "offset": offset,
                    "limit": limit,
                    "total_lines": total_lines,
                    "shown_lines": shown_lines,
                    "size_bytes": raw_size,
                }

            content = content_raw
            if len(content.encode(encoding)) > max_size:
                content = content[:max_size]
                content += "\n\n[... Content truncated due to size limit ...]"

            return {
                "success": True,
                "path": path,
                "content": content,
                "size_bytes": len(content.encode(encoding)),
                "lines": len(content.splitlines()),
            }
        except Exception as e:
            return {"error": f"Failed to read file: {str(e)}"}
