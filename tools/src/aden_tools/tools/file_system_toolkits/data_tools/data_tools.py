"""
Data Tools - Load, save, and list data files for agent pipelines.

These tools let agents store large intermediate results in files and
retrieve them with pagination, keeping the LLM conversation context small.
Used in conjunction with the spillover system: when a tool result is too
large, the framework writes it to a file and the agent can load it back
with load_data().
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from aden_tools.credentials.browser import open_browser


def register_tools(mcp: FastMCP) -> None:
    """Register data management tools with the MCP server."""

    @mcp.tool()
    def save_data(filename: str, data: str, data_dir: str) -> dict:
        """
        Purpose
            Save data to a file for later retrieval by this or downstream nodes.

        When to use
            Store large results (search results, profiles, analysis) instead
            of passing them inline through set_output.
            Returns a brief summary with the filename to reference later.

        Rules & Constraints
            filename must be a simple name like 'results.json' — no paths or '..'
            data_dir must be the absolute path to the data directory

        Args:
            filename: Simple filename like 'github_users.json'. No paths or '..'.
            data: The string data to write (typically JSON).
            data_dir: Absolute path to the data directory.

        Returns:
            Dict with success status and file metadata, or error dict
        """
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return {"error": "Invalid filename. Use simple names like 'users.json'"}
        if not data_dir:
            return {"error": "data_dir is required"}

        try:
            dir_path = Path(data_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            path = dir_path / filename
            path.write_text(data, encoding="utf-8")
            lines = data.count("\n") + 1
            return {
                "success": True,
                "filename": filename,
                "size_bytes": len(data.encode("utf-8")),
                "lines": lines,
                "preview": data[:200] + ("..." if len(data) > 200 else ""),
            }
        except Exception as e:
            return {"error": f"Failed to save data: {str(e)}"}

    @mcp.tool()
    def load_data(
        filename: str,
        data_dir: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """
        Purpose
            Load data from a previously saved file with pagination.

        When to use
            Retrieve large tool results that were spilled to disk.
            Read data saved by save_data or by the spillover system.
            Page through large files without loading everything into context.

        Rules & Constraints
            filename must match a file in data_dir
            Returns a page of lines with metadata about the full file

        Args:
            filename: The filename to load (as shown in spillover messages or save_data results).
            data_dir: Absolute path to the data directory.
            offset: 0-based line number to start reading from. Default 0.
            limit: Max number of lines to return. Default 50.

        Returns:
            Dict with content, pagination info, and metadata

        Examples:
            load_data('users.json', '/path/to/data')                      # first 50 lines
            load_data('users.json', '/path/to/data', offset=50, limit=50) # next 50
            load_data('users.json', '/path/to/data', limit=200)           # first 200 lines
        """
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return {"error": "Invalid filename"}
        if not data_dir:
            return {"error": "data_dir is required"}

        try:
            offset = int(offset)
            limit = int(limit)
            path = Path(data_dir) / filename
            if not path.exists():
                return {"error": f"File not found: {filename}"}

            content = path.read_text(encoding="utf-8")
            size_bytes = len(content.encode("utf-8"))

            # If content is a single long line, try to pretty-print JSON so
            # line-based pagination actually works.
            all_lines = content.split("\n")
            if len(all_lines) <= 2 and size_bytes > 500:
                try:
                    parsed = json.loads(content)
                    content = json.dumps(parsed, indent=2, ensure_ascii=False)
                    all_lines = content.split("\n")
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

            total = len(all_lines)
            start = min(offset, total)
            end = min(start + limit, total)
            sliced = all_lines[start:end]

            return {
                "success": True,
                "filename": filename,
                "content": "\n".join(sliced),
                "total_lines": total,
                "size_bytes": size_bytes,
                "offset": start,
                "lines_returned": len(sliced),
                "has_more": end < total,
            }
        except Exception as e:
            return {"error": f"Failed to load data: {str(e)}"}

    @mcp.tool()
    def serve_file_to_user(
        filename: str, data_dir: str, label: str = "", open_in_browser: bool = False
    ) -> dict:
        """
        Purpose
            Resolve a sandboxed file path to a fully qualified file URI
            that the user can click to open in their system viewer.

        When to use
            After saving a file (HTML report, CSV export, etc.) with save_data,
            call this to give the user a clickable link to open it.
            The TUI will render the file:// URI as a clickable link.
            Set open_in_browser=True to also auto-open the file in the
            user's default browser.

        Rules & Constraints
            filename must be a simple name — no paths or '..'
            The file must already exist in data_dir
            Returns a file:// URI the agent should include in its response

        Args:
            filename: The filename to serve (must exist in data_dir).
            data_dir: Absolute path to the data directory.
            label: Optional display label (defaults to filename).
            open_in_browser: If True, auto-open the file in the default browser.

        Returns:
            Dict with file_uri, file_path, label, and optionally browser_opened
        """
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return {"error": "Invalid filename. Use simple names like 'report.html'"}
        if not data_dir:
            return {"error": "data_dir is required"}

        try:
            path = Path(data_dir) / filename
            if not path.exists():
                return {"error": f"File not found: {filename}"}

            full_path = str(path.resolve())
            file_uri = f"file://{full_path}"
            result = {
                "success": True,
                "file_uri": file_uri,
                "file_path": full_path,
                "label": label or filename,
            }

            if open_in_browser:
                opened, msg = open_browser(file_uri)
                result["browser_opened"] = opened
                result["browser_message"] = msg

            return result
        except Exception as e:
            return {"error": f"Failed to serve file: {str(e)}"}

    @mcp.tool()
    def list_data_files(data_dir: str) -> dict:
        """
        Purpose
            List all data files in the data directory.

        When to use
            Discover what intermediate results or spillover files are available.
            Check what data was saved by previous nodes in the pipeline.

        Args:
            data_dir: Absolute path to the data directory.

        Returns:
            Dict with list of files and their sizes
        """
        if not data_dir:
            return {"error": "data_dir is required"}

        try:
            dir_path = Path(data_dir)
            if not dir_path.exists():
                return {"files": []}

            files = []
            for f in sorted(dir_path.iterdir()):
                if f.is_file():
                    files.append(
                        {
                            "filename": f.name,
                            "size_bytes": f.stat().st_size,
                        }
                    )
            return {"files": files}
        except Exception as e:
            return {"error": f"Failed to list data files: {str(e)}"}
