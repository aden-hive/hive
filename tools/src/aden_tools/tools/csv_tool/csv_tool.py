"""CSV Tool - Read and manipulate CSV files."""

import csv
import os

from fastmcp import FastMCP

from ..file_system_toolkits.security import get_secure_path

# Actionable encoding error message (replaces dead-end "unable to decode as UTF-8")
_ENCODING_ERROR_HINT = (
    "File encoding error: unable to decode file. "
    "Try specifying encoding='auto' for auto-detection, "
    "or use a specific encoding like 'latin-1', 'windows-1252', 'shift-jis'."
)


def _detect_encoding(filepath: str) -> str:
    """Detect file encoding from its raw bytes.

    Strategy:
      1. BOM detection (UTF-16 LE/BE, UTF-8-sig)
      2. Try UTF-8 decode (fast path for the common case)
      3. charset_normalizer if available (already a transitive dep via httpx)
      4. Fallback: latin-1 (never fails — all byte values are valid)

    Only reads the first 32 KB for performance.
    """
    with open(filepath, "rb") as f:
        raw = f.read(32768)

    if not raw:
        return "utf-8"

    # 1. Check BOM (Byte Order Mark)
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    # 2. Try UTF-8 first (most common)
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # 3. Use charset_normalizer if available (already in uv.lock via httpx)
    try:
        from charset_normalizer import from_bytes

        result = from_bytes(raw).best()
        if result:
            return result.encoding
    except ImportError:
        pass

    # 4. Final fallback: latin-1 (never fails, covers Western European)
    return "latin-1"


def _resolve_encoding(encoding: str, secure_path: str) -> str:
    """Resolve the encoding string, handling 'auto' detection."""
    if encoding == "auto":
        return _detect_encoding(secure_path)
    return encoding


def register_tools(mcp: FastMCP) -> None:
    """Register CSV tools with the MCP server."""

    @mcp.tool()
    def csv_read(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        limit: int | None = None,
        offset: int = 0,
        encoding: str = "utf-8",
    ) -> dict:
        """
        Read a CSV file and return its contents.

        Args:
            path: Path to the CSV file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            limit: Maximum number of rows to return (None = all rows)
            offset: Number of rows to skip from the beginning
            encoding: File encoding (default: "utf-8"). Use "auto" for auto-detection,
                      or specify explicitly: "latin-1", "windows-1252", "shift-jis", etc.

        Returns:
            dict with success status, data, and metadata
        """
        if offset < 0 or (limit is not None and limit < 0):
            return {"error": "offset and limit must be non-negative"}
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            # Resolve encoding (handles "auto" detection)
            resolved_encoding = _resolve_encoding(encoding, secure_path)

            # Read CSV
            with open(secure_path, encoding=resolved_encoding, newline="") as f:
                reader = csv.DictReader(f)

                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}

                columns = list(reader.fieldnames)

                # Apply offset and limit
                rows = []
                for i, row in enumerate(reader):
                    if i < offset:
                        continue
                    if limit is not None and len(rows) >= limit:
                        break
                    rows.append(row)

            # Get total row count (re-read for accurate count)
            with open(secure_path, encoding=resolved_encoding, newline="") as f:
                reader = csv.reader(f)
                total_rows = sum(1 for row in reader if any(row)) - 1

            return {
                "success": True,
                "path": path,
                "encoding": resolved_encoding,
                "columns": columns,
                "column_count": len(columns),
                "rows": rows,
                "row_count": len(rows),
                "total_rows": total_rows,
                "offset": offset,
                "limit": limit,
            }

        except csv.Error as e:
            return {"error": f"CSV parsing error: {str(e)}"}
        except UnicodeDecodeError:
            return {"error": _ENCODING_ERROR_HINT}
        except Exception as e:
            return {"error": f"Failed to read CSV: {str(e)}"}

    @mcp.tool()
    def csv_write(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        columns: list[str],
        rows: list[dict],
    ) -> dict:
        """
        Write data to a new CSV file.

        Args:
            path: Path to the CSV file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            columns: List of column names for the header
            rows: List of dictionaries, each representing a row

        Returns:
            dict with success status and metadata
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            if not columns:
                return {"error": "columns cannot be empty"}

            # Create parent directories if needed
            parent_dir = os.path.dirname(secure_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Write CSV
            with open(secure_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    # Only write columns that exist in fieldnames
                    filtered_row = {k: v for k, v in row.items() if k in columns}
                    writer.writerow(filtered_row)

            return {
                "success": True,
                "path": path,
                "columns": columns,
                "column_count": len(columns),
                "rows_written": len(rows),
            }

        except Exception as e:
            return {"error": f"Failed to write CSV: {str(e)}"}

    @mcp.tool()
    def csv_append(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        rows: list[dict],
        encoding: str = "utf-8",
    ) -> dict:
        """
        Append rows to an existing CSV file.

        Args:
            path: Path to the CSV file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            rows: List of dictionaries to append, keys should match existing columns
            encoding: File encoding (default: "utf-8"). Use "auto" for auto-detection,
                      or specify explicitly: "latin-1", "windows-1252", "shift-jis", etc.

        Returns:
            dict with success status and metadata
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}. Use csv_write to create a new file."}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            if not rows:
                return {"error": "rows cannot be empty"}

            # Resolve encoding (handles "auto" detection)
            resolved_encoding = _resolve_encoding(encoding, secure_path)

            # Read existing columns
            with open(secure_path, encoding=resolved_encoding, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}
                columns = list(reader.fieldnames)

            # Append rows
            with open(secure_path, "a", encoding=resolved_encoding, newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                for row in rows:
                    # Only write columns that exist in fieldnames
                    filtered_row = {k: v for k, v in row.items() if k in columns}
                    writer.writerow(filtered_row)

            # Get new total row count
            with open(secure_path, encoding=resolved_encoding, newline="") as f:
                reader = csv.reader(f)
                total_rows = sum(1 for row in reader if any(row)) - 1  # Subtract header

            return {
                "success": True,
                "path": path,
                "encoding": resolved_encoding,
                "rows_appended": len(rows),
                "total_rows": total_rows,
            }

        except csv.Error as e:
            return {"error": f"CSV parsing error: {str(e)}"}
        except UnicodeDecodeError:
            return {"error": _ENCODING_ERROR_HINT}
        except Exception as e:
            return {"error": f"Failed to append to CSV: {str(e)}"}

    @mcp.tool()
    def csv_info(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        encoding: str = "utf-8",
    ) -> dict:
        """
        Get metadata about a CSV file without reading all data.

        Args:
            path: Path to the CSV file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            encoding: File encoding (default: "utf-8"). Use "auto" for auto-detection,
                      or specify explicitly: "latin-1", "windows-1252", "shift-jis", etc.

        Returns:
            dict with file metadata (columns, row count, file size)
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            # Resolve encoding (handles "auto" detection)
            resolved_encoding = _resolve_encoding(encoding, secure_path)

            # Get file size
            file_size = os.path.getsize(secure_path)

            # Read headers and count rows
            with open(secure_path, encoding=resolved_encoding, newline="") as f:
                reader = csv.DictReader(f)

                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}

                columns = list(reader.fieldnames)

                # Count rows
                total_rows = sum(1 for _ in reader)

            return {
                "success": True,
                "path": path,
                "encoding": resolved_encoding,
                "columns": columns,
                "column_count": len(columns),
                "total_rows": total_rows,
                "file_size_bytes": file_size,
            }

        except csv.Error as e:
            return {"error": f"CSV parsing error: {str(e)}"}
        except UnicodeDecodeError:
            return {"error": _ENCODING_ERROR_HINT}
        except Exception as e:
            return {"error": f"Failed to get CSV info: {str(e)}"}

    @mcp.tool()
    def csv_sql(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        query: str,
        encoding: str = "utf-8",
    ) -> dict:
        """
        Query a CSV file using SQL (powered by DuckDB).

        The CSV file is loaded as a table named 'data'. Use standard SQL syntax.

        Args:
            path: Path to the CSV file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            query: SQL query to execute. The CSV is available as table 'data'.
                   Example: "SELECT * FROM data WHERE price > 100 ORDER BY name LIMIT 10"
            encoding: File encoding (default: "utf-8"). Use "auto" to let DuckDB
                      auto-detect, or specify explicitly: "latin-1", "windows-1252", etc.

        Returns:
            dict with query results, columns, and row count

        Examples:
            # Filter rows
            query="SELECT * FROM data WHERE status = 'pending'"

            # Aggregate data
            query="SELECT category, COUNT(*) as count, "
                  "AVG(price) as avg_price FROM data GROUP BY category"

            # Sort and limit
            query="SELECT name, price FROM data ORDER BY price DESC LIMIT 5"

            # Search text (case-insensitive)
            query="SELECT * FROM data WHERE LOWER(name) LIKE '%phone%'"
        """
        try:
            import duckdb
        except ImportError:
            return {
                "error": (
                    "DuckDB not installed. Install with: "
                    "uv pip install duckdb  or  uv pip install tools[sql]"
                )
            }

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            if not query or not query.strip():
                return {"error": "query cannot be empty"}

            # Security: only allow SELECT statements
            query_upper = query.strip().upper()
            if not query_upper.startswith("SELECT"):
                return {"error": "Only SELECT queries are allowed for security reasons"}

            # Disallowed keywords for security
            disallowed = [
                "INSERT",
                "UPDATE",
                "DELETE",
                "DROP",
                "CREATE",
                "ALTER",
                "TRUNCATE",
                "EXEC",
                "EXECUTE",
            ]
            for keyword in disallowed:
                if keyword in query_upper:
                    return {"error": f"'{keyword}' is not allowed in queries"}

            # Execute query using in-memory DuckDB
            con = duckdb.connect(":memory:")
            try:
                # Load CSV as 'data' table
                # Pass explicit encoding to DuckDB when specified (not auto/utf-8)
                if encoding and encoding not in ("auto", "utf-8"):
                    con.execute(
                        f"CREATE TABLE data AS SELECT * FROM "
                        f"read_csv_auto('{secure_path}', encoding='{encoding}')"
                    )
                else:
                    # Let DuckDB handle its own auto-detection
                    con.execute(
                        f"CREATE TABLE data AS SELECT * FROM "
                        f"read_csv_auto('{secure_path}')"
                    )

                # Execute user query
                result = con.execute(query)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()

                # Convert to list of dicts
                rows_as_dicts = [dict(zip(columns, row, strict=False)) for row in rows]

                return {
                    "success": True,
                    "path": path,
                    "encoding": encoding,
                    "query": query,
                    "columns": columns,
                    "column_count": len(columns),
                    "rows": rows_as_dicts,
                    "row_count": len(rows_as_dicts),
                }
            finally:
                con.close()

        except Exception as e:
            error_msg = str(e)
            # Make DuckDB errors more readable
            if "Catalog Error" in error_msg:
                return {"error": f"SQL error: {error_msg}. Remember the table is named 'data'."}
            return {"error": f"Query failed: {error_msg}"}
