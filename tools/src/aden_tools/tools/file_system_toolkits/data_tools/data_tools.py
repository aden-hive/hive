"""
Data Tools - Load, save, and list data files for agent pipelines.

These tools let agents store large intermediate results in files and
retrieve them with pagination, keeping the LLM conversation context small.
Used in conjunction with the spillover system: when a tool result is too
large, the framework writes it to a file and the agent can load it back
with load_data().
"""

from __future__ import annotations

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
        offset_bytes: int = 0,
        limit_bytes: int = 10000,
    ) -> dict:
        """
        Purpose
            Load data from a previously saved file with byte-based pagination.
            Efficient for files of any size (1 byte to 1 TB).
            Automatically detects safe UTF-8 boundaries to prevent character splitting.

        When to use
            Retrieve large tool results that were spilled to disk.
            Read data saved by save_data or by the spillover system.
            Page through large files without loading everything into context.

        Rules & Constraints
            filename must match a file in data_dir
            Uses byte offsets for O(1) seeking (works with huge files)
            Automatically trims to valid UTF-8 character boundaries
            Returns exactly limit_bytes or less (rounded to safe boundary)

        Args:
            filename: The filename to load (as shown in spillover messages or save_data results).
            data_dir: Absolute path to the data directory.
            offset_bytes: Byte offset to start reading from. Default 0.
            limit_bytes: Max number of bytes to return. Default 10000 (10KB).

        Returns:
            Dict with content, pagination info, and metadata

        Examples:
            load_data('emails.jsonl', '/data')                           # first 10KB
            load_data('emails.jsonl', '/data', offset_bytes=10000)       # next 10KB
            load_data('large.txt', '/data', limit_bytes=50000)           # first 50KB
        """
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return {"error": "Invalid filename"}
        if not data_dir:
            return {"error": "data_dir is required"}

        try:
            offset_bytes = int(offset_bytes)
            limit_bytes = int(limit_bytes)
            path = Path(data_dir) / filename
            if not path.exists():
                return {"error": f"File not found: {filename}"}

            file_size = path.stat().st_size

            # Handle edge case: offset beyond file size
            if offset_bytes >= file_size:
                return {
                    "success": True,
                    "filename": filename,
                    "content": "",
                    "offset_bytes": offset_bytes,
                    "bytes_read": 0,
                    "next_offset_bytes": file_size,
                    "file_size_bytes": file_size,
                    "has_more": False,
                }

            with open(path, "rb") as f:
                # O(1) seek to byte offset
                f.seek(offset_bytes)

                # Read exactly limit_bytes
                raw_bytes = f.read(limit_bytes)

                # Trim to valid UTF-8 boundary
                # Scan backwards max 4 bytes to find valid UTF-8 start
                chunk = raw_bytes
                text = None
                for i in range(min(4, len(raw_bytes)) + 1):
                    try:
                        slice_end = len(raw_bytes) - i if i > 0 else len(raw_bytes)
                        text = raw_bytes[:slice_end].decode("utf-8")
                        chunk = raw_bytes[:slice_end]
                        break
                    except UnicodeDecodeError:
                        continue

                # If we couldn't decode at all, return error
                if text is None:
                    return {"error": "Could not decode file as UTF-8"}

                # UTF-8 boundary is already handled above
                next_offset = offset_bytes + len(chunk)

                return {
                    "success": True,
                    "filename": filename,
                    "content": text,
                    "offset_bytes": offset_bytes,
                    "bytes_read": len(chunk),
                    "next_offset_bytes": next_offset,
                    "file_size_bytes": file_size,
                    "has_more": next_offset < file_size,
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

    @mcp.tool()
    def append_data(filename: str, data: str, data_dir: str) -> dict:
        """
        Purpose
            Append data to the end of an existing file, or create it if it
            doesn't exist yet.

        When to use
            Build large files incrementally instead of writing everything in
            one save_data call.  For example, write an HTML skeleton first,
            then append each section separately to stay within token limits.

        Rules & Constraints
            filename must be a simple name like 'report.html' — no paths or '..'

        Args:
            filename: Simple filename to append to. No paths or '..'.
            data: The string data to append.
            data_dir: Absolute path to the data directory.

        Returns:
            Dict with success status, new total size, and bytes appended
        """
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return {"error": "Invalid filename. Use simple names like 'report.html'"}
        if not data_dir:
            return {"error": "data_dir is required"}

        try:
            dir_path = Path(data_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            path = dir_path / filename
            with open(path, "a", encoding="utf-8") as f:
                f.write(data)
            appended_bytes = len(data.encode("utf-8"))
            total_bytes = path.stat().st_size
            return {
                "success": True,
                "filename": filename,
                "size_bytes": total_bytes,
                "appended_bytes": appended_bytes,
            }
        except Exception as e:
            return {"error": f"Failed to append data: {str(e)}"}

    @mcp.tool()
    def edit_data(filename: str, old_text: str, new_text: str, data_dir: str) -> dict:
        """
        Purpose
            Find and replace a specific text segment in an existing file.
            Works like a surgical diff — only the matched portion changes.

        When to use
            Update a section of a previously saved file without rewriting
            the entire content.  For example, replace a placeholder in an
            HTML report or fix a specific paragraph.

        Rules & Constraints
            old_text must appear exactly once in the file.  If it appears
            zero times or more than once, the edit is rejected with an
            error message.

        Args:
            filename: The file to edit. Must exist in data_dir.
            old_text: The exact text to find (must match exactly once).
            new_text: The replacement text.
            data_dir: Absolute path to the data directory.

        Returns:
            Dict with success status and updated file size
        """
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return {"error": "Invalid filename. Use simple names like 'report.html'"}
        if not data_dir:
            return {"error": "data_dir is required"}

        try:
            path = Path(data_dir) / filename
            if not path.exists():
                return {"error": f"File not found: {filename}"}

            content = path.read_text(encoding="utf-8")
            count = content.count(old_text)

            if count == 0:
                return {
                    "error": (
                        "old_text not found in the file. "
                        "Make sure you're matching the exact text, "
                        "including whitespace and newlines."
                    )
                }
            if count > 1:
                return {
                    "error": (
                        f"old_text found {count} times — it must be unique. "
                        "Include more surrounding context to match exactly once."
                    )
                }

            updated = content.replace(old_text, new_text, 1)
            path.write_text(updated, encoding="utf-8")

            return {
                "success": True,
                "filename": filename,
                "size_bytes": len(updated.encode("utf-8")),
                "replacements": 1,
            }
        except Exception as e:
            return {"error": f"Failed to edit data: {str(e)}"}
