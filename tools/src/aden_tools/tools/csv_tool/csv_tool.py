"""CSV Tool - Read and manipulate CSV files with strong typing and validation."""
import csv
import os
from typing import Dict, List, Optional, TypedDict, Union

from fastmcp import FastMCP

from ..file_system_toolkits.security import get_secure_path


# -----------------------------
# Typed response models
# -----------------------------

class ErrorResponse(TypedDict):
    error: str


class CsvReadResponse(TypedDict):
    success: bool
    path: str
    columns: List[str]
    column_count: int
    rows: List[Dict[str, str]]
    row_count: int
    total_rows: int
    offset: int
    limit: Optional[int]


class CsvWriteResponse(TypedDict):
    success: bool
    path: str
    columns: List[str]
    column_count: int
    rows_written: int


class CsvAppendResponse(TypedDict):
    success: bool
    path: str
    rows_appended: int
    total_rows: int


class CsvInfoResponse(TypedDict):
    success: bool
    path: str
    columns: List[str]
    column_count: int
    total_rows: int
    file_size_bytes: int


class CsvSqlResponse(TypedDict):
    success: bool
    path: str
    query: str
    columns: List[str]
    column_count: int
    rows: List[Dict[str, object]]
    row_count: int


CsvReadResult = Union[CsvReadResponse, ErrorResponse]
CsvWriteResult = Union[CsvWriteResponse, ErrorResponse]
CsvAppendResult = Union[CsvAppendResponse, ErrorResponse]
CsvInfoResult = Union[CsvInfoResponse, ErrorResponse]
CsvSqlResult = Union[CsvSqlResponse, ErrorResponse]


# -----------------------------
# Internal helpers
# -----------------------------

def _validate_csv_path(path: str, secure_path: str) -> Optional[ErrorResponse]:
    """Validate CSV file existence and extension."""
    if not path.lower().endswith(".csv"):
        return {"error": "File must have .csv extension"}
    if not os.path.exists(secure_path):
        return {"error": f"File not found: {path}"}
    return None


# -----------------------------
# Tool registration
# -----------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register CSV tools with the MCP server."""

    @mcp.tool()
    def csv_read(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> CsvReadResult:
        """Read a CSV file and return its contents with predictable typing."""
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            error = _validate_csv_path(path, secure_path)
            if error:
                return error

            with open(secure_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)

                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}

                columns = list(reader.fieldnames)
                rows: List[Dict[str, str]] = []

                for i, row in enumerate(reader):
                    if i < offset:
                        continue
                    if limit is not None and len(rows) >= limit:
                        break
                    rows.append(row)

            with open(secure_path, "r", encoding="utf-8", newline="") as f:
                total_rows = max(sum(1 for _ in f) - 1, 0)

            return {
                "success": True,
                "path": path,
                "columns": columns,
                "column_count": len(columns),
                "rows": rows,
                "row_count": len(rows),
                "total_rows": total_rows,
                "offset": offset,
                "limit": limit,
            }

        except csv.Error as exc:
            return {"error": f"CSV parsing error: {exc}"}
        except UnicodeDecodeError:
            return {"error": "File encoding error: unable to decode as UTF-8"}
        except Exception as exc:
            return {"error": f"Failed to read CSV: {exc}"}

    @mcp.tool()
    def csv_write(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        columns: List[str],
        rows: List[Dict[str, object]],
    ) -> CsvWriteResult:
        """Write data to a new CSV file with validation."""
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            if not columns:
                return {"error": "columns cannot be empty"}

            os.makedirs(os.path.dirname(secure_path), exist_ok=True)

            with open(secure_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    filtered_row = {k: row.get(k) for k in columns}
                    writer.writerow(filtered_row)

            return {
                "success": True,
                "path": path,
                "columns": columns,
                "column_count": len(columns),
                "rows_written": len(rows),
            }

        except Exception as exc:
            return {"error": f"Failed to write CSV: {exc}"}

    @mcp.tool()
    def csv_append(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        rows: List[Dict[str, object]],
    ) -> CsvAppendResult:
        """Append rows to an existing CSV file."""
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            error = _validate_csv_path(path, secure_path)
            if error:
                return error

            if not rows:
                return {"error": "rows cannot be empty"}

            with open(secure_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}
                columns = list(reader.fieldnames)

            with open(secure_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                for row in rows:
                    filtered_row = {k: row.get(k) for k in columns}
                    writer.writerow(filtered_row)

            with open(secure_path, "r", encoding="utf-8", newline="") as f:
                total_rows = max(sum(1 for _ in f) - 1, 0)

            return {
                "success": True,
                "path": path,
                "rows_appended": len(rows),
                "total_rows": total_rows,
            }

        except csv.Error as exc:
            return {"error": f"CSV parsing error: {exc}"}
        except UnicodeDecodeError:
            return {"error": "File encoding error: unable to decode as UTF-8"}
        except Exception as exc:
            return {"error": f"Failed to append to CSV: {exc}"}

    @mcp.tool()
    def csv_info(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> CsvInfoResult:
        """Return CSV metadata without loading full file."""
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            error = _validate_csv_path(path, secure_path)
            if error:
                return error

            file_size = os.path.getsize(secure_path)

            with open(secure_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}
                columns = list(reader.fieldnames)
                total_rows = sum(1 for _ in reader)

            return {
                "success": True,
                "path": path,
                "columns": columns,
                "column_count": len(columns),
                "total_rows": total_rows,
                "file_size_bytes": file_size,
            }

        except Exception as exc:
            return {"error": f"Failed to get CSV info: {exc}"}
