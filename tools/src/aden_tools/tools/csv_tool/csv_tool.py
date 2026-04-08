"""CSV Tool - Read and manipulate CSV files using absolute paths."""

import csv
import os
import re

from fastmcp import FastMCP

from ..file_system_toolkits.security import resolve_safe_path


def register_tools(mcp: FastMCP) -> None:
    """Register CSV tools with the MCP server."""

    @mcp.tool()
    def csv_read(
        path: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        """
        Read a CSV file and return its contents.

        Args:
            path: Absolute path to the CSV file
            limit: Maximum number of rows to return (None = all rows)
            offset: Number of rows to skip from the beginning

        Returns:
            dict with success status, data, and metadata
        """
        if offset < 0 or (limit is not None and limit < 0):
            return {"error": "offset and limit must be non-negative"}
        try:
            secure_path = resolve_safe_path(path)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            with open(secure_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)

                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}

                columns = list(reader.fieldnames)

                rows = []
                for i, row in enumerate(reader):
                    if i < offset:
                        continue
                    if limit is not None and len(rows) >= limit:
                        break
                    rows.append(row)

            with open(secure_path, encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                total_rows = sum(1 for row in reader if any(row)) - 1

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

        except csv.Error as e:
            return {"error": f"CSV parsing error: {str(e)}"}
        except ValueError as e:
            return {"error": str(e)}
        except UnicodeDecodeError:
            return {"error": "File encoding error: unable to decode as UTF-8"}
        except Exception as e:
            return {"error": f"Failed to read CSV: {str(e)}"}

    @mcp.tool()
    def csv_write(
        path: str,
        columns: list[str],
        rows: list[dict],
    ) -> dict:
        """
        Write data to a new CSV file.

        Args:
            path: Absolute path to the CSV file
            columns: List of column names for the header
            rows: List of dictionaries, each representing a row

        Returns:
            dict with success status and metadata
        """
        try:
            secure_path = resolve_safe_path(path)

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            if not columns:
                return {"error": "columns cannot be empty"}

            parent_dir = os.path.dirname(secure_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(secure_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    filtered_row = {k: v for k, v in row.items() if k in columns}
                    writer.writerow(filtered_row)

            return {
                "success": True,
                "path": path,
                "columns": columns,
                "column_count": len(columns),
                "rows_written": len(rows),
            }

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to write CSV: {str(e)}"}

    @mcp.tool()
    def csv_append(
        path: str,
        rows: list[dict],
    ) -> dict:
        """
        Append rows to an existing CSV file.

        Args:
            path: Absolute path to the CSV file
            rows: List of dictionaries to append, keys should match existing columns

        Returns:
            dict with success status and metadata
        """
        try:
            secure_path = resolve_safe_path(path)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}. Use csv_write to create a new file."}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            if not rows:
                return {"error": "rows cannot be empty"}

            with open(secure_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}
                columns = list(reader.fieldnames)

            with open(secure_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                for row in rows:
                    filtered_row = {k: v for k, v in row.items() if k in columns}
                    writer.writerow(filtered_row)

            with open(secure_path, encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                total_rows = sum(1 for row in reader if any(row)) - 1

            return {
                "success": True,
                "path": path,
                "rows_appended": len(rows),
                "total_rows": total_rows,
            }

        except csv.Error as e:
            return {"error": f"CSV parsing error: {str(e)}"}
        except ValueError as e:
            return {"error": str(e)}
        except UnicodeDecodeError:
            return {"error": "File encoding error: unable to decode as UTF-8"}
        except Exception as e:
            return {"error": f"Failed to append to CSV: {str(e)}"}

    @mcp.tool()
    def csv_info(
        path: str,
    ) -> dict:
        """
        Get metadata about a CSV file without reading all data.

        Args:
            path: Absolute path to the CSV file

        Returns:
            dict with file metadata (columns, row count, file size)
        """
        try:
            secure_path = resolve_safe_path(path)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            file_size = os.path.getsize(secure_path)

            with open(secure_path, encoding="utf-8", newline="") as f:
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

        except csv.Error as e:
            return {"error": f"CSV parsing error: {str(e)}"}
        except ValueError as e:
            return {"error": str(e)}
        except UnicodeDecodeError:
            return {"error": "File encoding error: unable to decode as UTF-8"}
        except Exception as e:
            return {"error": f"Failed to get CSV info: {str(e)}"}

    @mcp.tool()
    def csv_sql(
        path: str,
        query: str,
    ) -> dict:
        """
        Query a CSV file using SQL (powered by DuckDB).

        The CSV file is loaded as a table named 'data'. Use standard SQL syntax.

        Args:
            path: Absolute path to the CSV file
            query: SQL query to execute. The CSV is available as table 'data'.
                   Example: "SELECT * FROM data WHERE price > 100 ORDER BY name LIMIT 10"

        Returns:
            dict with query results, columns, and row count
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
            secure_path = resolve_safe_path(path)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            if not query or not query.strip():
                return {"error": "query cannot be empty"}

            query_upper = query.lstrip().upper()
            if not (query_upper.startswith("SELECT") or query_upper.startswith("WITH")):
                return {"error": "Only SELECT queries are allowed for security reasons"}

            _WRITE_PATTERN = re.compile(
                r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE)\b",
                re.IGNORECASE,
            )
            match = _WRITE_PATTERN.search(query)
            if match:
                return {"error": f"'{match.group().upper()}' is not allowed in queries"}

            q_lower = query.lower()
            for token in [";", "--", "/*", "*/"]:
                if token in q_lower:
                    return {"error": "Multiple statements or comments are not allowed"}

            con = duckdb.connect(":memory:")
            try:
                con.execute(
                    "CREATE TABLE data AS SELECT * FROM read_csv_auto(?)",
                    [str(secure_path)],
                )

                result = con.execute(query)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()

                rows_as_dicts = [dict(zip(columns, row, strict=False)) for row in rows]

                return {
                    "success": True,
                    "path": path,
                    "query": query,
                    "columns": columns,
                    "column_count": len(columns),
                    "rows": rows_as_dicts,
                    "row_count": len(rows_as_dicts),
                }

            finally:
                con.close()

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            error_msg = str(e)
            if "Catalog Error" in error_msg:
                return {"error": f"SQL error: {error_msg}. Remember the table is named 'data'."}
            return {"error": f"Query failed: {error_msg}"}
