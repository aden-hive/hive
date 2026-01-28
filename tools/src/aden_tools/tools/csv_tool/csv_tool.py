"""CSV Tool - Read and manipulate CSV files."""

import csv
import os

from fastmcp import FastMCP

from ..file_system_toolkits.security import get_secure_path


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

        Returns:
            dict with success status, data, and metadata
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            # Read CSV
            with open(secure_path, encoding="utf-8", newline="") as f:
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
        except UnicodeDecodeError:
            return {"error": "File encoding error: unable to decode as UTF-8"}
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
            os.makedirs(os.path.dirname(secure_path), exist_ok=True)

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
    ) -> dict:
        """
        Append rows to an existing CSV file.

        Args:
            path: Path to the CSV file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            rows: List of dictionaries to append, keys should match existing columns

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

            # Read existing columns
            with open(secure_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}
                columns = list(reader.fieldnames)

            # Append rows
            with open(secure_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                for row in rows:
                    # Only write columns that exist in fieldnames
                    filtered_row = {k: v for k, v in row.items() if k in columns}
                    writer.writerow(filtered_row)

            # Get new total row count
            with open(secure_path, encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                total_rows = sum(1 for row in reader if any(row)) - 1  # Subtract header

            return {
                "success": True,
                "path": path,
                "rows_appended": len(rows),
                "total_rows": total_rows,
            }

        except csv.Error as e:
            return {"error": f"CSV parsing error: {str(e)}"}
        except UnicodeDecodeError:
            return {"error": "File encoding error: unable to decode as UTF-8"}
        except Exception as e:
            return {"error": f"Failed to append to CSV: {str(e)}"}

    @mcp.tool()
    def csv_info(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict:
        """
        Get metadata about a CSV file without reading all data.

        Args:
            path: Path to the CSV file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier

        Returns:
            dict with file metadata (columns, row count, file size)
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith(".csv"):
                return {"error": "File must have .csv extension"}

            # Get file size
            file_size = os.path.getsize(secure_path)

            # Read headers and count rows
            with open(secure_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)

                if reader.fieldnames is None:
                    return {"error": "CSV file is empty or has no headers"}

                columns = list(reader.fieldnames)

                # Count rows
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
        except UnicodeDecodeError:
            return {"error": "File encoding error: unable to decode as UTF-8"}
        except Exception as e:
            return {"error": f"Failed to get CSV info: {str(e)}"}

    @mcp.tool()
    def csv_sql(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        query: str,
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
                    "pip install duckdb  or  pip install tools[sql]"
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
                con.execute(f"CREATE TABLE data AS SELECT * FROM read_csv_auto('{secure_path}')")

                # Execute user query
                result = con.execute(query)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()

                # Convert to list of dicts
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

        except Exception as e:
            error_msg = str(e)
            # Make DuckDB errors more readable
            if "Catalog Error" in error_msg:
                return {"error": f"SQL error: {error_msg}. Remember the table is named 'data'."}
            return {"error": f"Query failed: {error_msg}"}
