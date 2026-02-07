"""
JSON Read Tool - Parse and extract data from JSON files.

Reads JSON files, optionally applies JSONPath expressions to extract
specific subsets. Use for config files, package.json, API responses, etc.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError


def register_tools(mcp: FastMCP) -> None:
    """Register JSON read tools with the MCP server."""

    @mcp.tool()
    def json_read(
        file_path: str,
        jsonpath: str | None = None,
        max_content_length: int = 1_000_000,
    ) -> dict:
        """
        Read and parse a JSON file, optionally extracting data with JSONPath.

        Returns parsed JSON content. Use for reading config files (package.json,
        tsconfig.json), API responses, or any structured JSON data.

        Args:
            file_path: Path to the JSON file (absolute or relative)
            jsonpath: Optional JSONPath expression to extract a subset
                (e.g., '$.users[*].name', '$.dependencies')
            max_content_length: Maximum file size in bytes (1KB-10MB, for safety)

        Returns:
            Dict with parsed content and metadata, or error dict
        """
        try:
            path = Path(file_path).resolve()

            if not path.exists():
                return {"error": f"JSON file not found: {file_path}"}

            if not path.is_file():
                return {"error": f"Not a file: {file_path}"}

            ext = path.suffix.lower()
            if ext != ".json":
                return {"error": f"Not a JSON file (expected .json): {file_path}"}

            file_size = path.stat().st_size
            max_content_length = max(1024, min(max_content_length, 10_000_000))

            if file_size > max_content_length:
                return {
                    "error": (
                        f"File too large: {file_size} bytes. "
                        f"max_content_length={max_content_length}. Increase max_content_length if needed."
                    ),
                }

            with open(path, encoding="utf-8") as f:
                data: Any = json.load(f)

            result: dict[str, Any] = {
                "path": str(path),
                "name": path.name,
                "file_size_bytes": file_size,
            }

            if jsonpath:
                try:
                    expr = jsonpath_parse(jsonpath)
                    matches = [m.value for m in expr.find(data)]
                    if len(matches) == 1:
                        result["content"] = matches[0]
                        result["jsonpath"] = jsonpath
                    else:
                        result["content"] = matches
                        result["jsonpath"] = jsonpath
                        result["match_count"] = len(matches)
                except JsonPathParserError as e:
                    return {"error": f"Invalid JSONPath '{jsonpath}': {e!s}"}
            else:
                result["content"] = data

            return result

        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON: {e!s}"}
        except PermissionError:
            return {"error": f"Permission denied: {file_path}"}
        except Exception as e:
            return {"error": f"Failed to read JSON: {e!s}"}
