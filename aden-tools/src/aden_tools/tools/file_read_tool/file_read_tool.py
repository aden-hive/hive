"""
File Read Tool - Read contents of local files.

Supports reading text files with various encodings.
Returns file content along with metadata.
"""
from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register file read tools with the MCP server."""

    @mcp.tool()
    def file_read(
        file_path: str,
        encoding: str = "utf-8",
        max_size: int = 10_000_000,
    ) -> dict:
        """
        Read the contents of a local file.

        Use for reading configs, data files, source code, logs, or any text file.
        Returns file content along with path, name, size, and encoding.

        Args:
            file_path: Path to the file to read (absolute or relative)
            encoding: File encoding (utf-8, latin-1, etc.)
            max_size: Maximum file size to read in bytes (default 10MB)

        Returns:
            Dict with file content and metadata, or error dict
        """
        try:
            path = Path(file_path).resolve()

            # Check if file exists
            if not path.exists():
                return {"error": f"File not found: {file_path}"}

            # Check if it's a file (not directory)
            if not path.is_file():
                return {"error": f"Not a file: {file_path}"}

            # Check file size
            file_size = path.stat().st_size
            if max_size > 0 and file_size > max_size:
                return {
                    "error": f"File too large: {file_size} bytes (max: {max_size})",
                    "file_size": file_size,
                }

            # Read the file
            content = path.read_text(encoding=encoding)

            return {
                "path": str(path),
                "name": path.name,
                "content": content,
                "size": len(content),
                "encoding": encoding,
            }

        except UnicodeDecodeError as e:
            return {
                "error": f"Failed to decode file with encoding '{encoding}': {str(e)}",
                "suggestion": "Try a different encoding like 'latin-1' or 'cp1252'",
            }
        except PermissionError:
            return {"error": f"Permission denied: {file_path}"}
        except Exception as e:
            return {"error": f"Failed to read file: {str(e)}"}
