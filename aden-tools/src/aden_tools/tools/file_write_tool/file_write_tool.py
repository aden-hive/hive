"""
File Write Tool - Create or update local files.

Supports writing text files with various encodings.
Can create directories if they don't exist.
"""
from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register file write tools with the MCP server."""

    @mcp.tool()
    def file_write(
        file_path: str,
        content: str,
        encoding: str = "utf-8",
        mode: str = "write",
        create_dirs: bool = True,
    ) -> dict:
        """
        Write content to a local file.

        Can create new files or overwrite/append to existing ones.
        Use for saving data, creating configs, writing reports, or exporting results.

        Args:
            file_path: Path to the file to write (absolute or relative)
            content: Content to write to the file
            encoding: File encoding (utf-8, latin-1, etc.)
            mode: Write mode - 'write' (overwrite) or 'append'
            create_dirs: Create parent directories if they don't exist

        Returns:
            Dict with write result or error dict
        """
        try:
            path = Path(file_path).resolve()

            # Create parent directories if requested
            if create_dirs:
                path.parent.mkdir(parents=True, exist_ok=True)
            elif not path.parent.exists():
                return {"error": f"Parent directory does not exist: {path.parent}"}

            # Determine write mode
            if mode == "append":
                write_mode = "a"
            elif mode == "write":
                write_mode = "w"
            else:
                return {"error": f"Invalid mode: {mode}. Use 'write' or 'append'."}

            # Check if we're overwriting
            existed = path.exists()
            previous_size = path.stat().st_size if existed else 0

            # Write the file
            with open(path, write_mode, encoding=encoding) as f:
                f.write(content)

            new_size = path.stat().st_size

            return {
                "path": str(path),
                "name": path.name,
                "bytes_written": len(content.encode(encoding)),
                "total_size": new_size,
                "mode": mode,
                "created": not existed,
                "previous_size": previous_size if existed else None,
            }

        except PermissionError:
            return {"error": f"Permission denied: {file_path}"}
        except OSError as e:
            return {"error": f"OS error writing file: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to write file: {str(e)}"}
