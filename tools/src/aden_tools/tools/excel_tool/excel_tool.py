"""Excel Tool - Read and query Excel (.xlsx/.xls) files using DuckDB."""

import os
import xml.etree.ElementTree as ET
import zipfile

from fastmcp import FastMCP

from ..file_system_toolkits.security import get_secure_path

# Supported Excel file extensions
_EXCEL_EXTENSIONS = (".xlsx", ".xls")


def _check_duckdb():
    """Lazy-import DuckDB, returning (module, None) or (None, error_dict)."""
    try:
        import duckdb

        return duckdb, None
    except ImportError:
        return None, {
            "error": (
                "DuckDB not installed. Install with: "
                "uv pip install duckdb  or  uv pip install tools[sql]"
            )
        }


def _load_excel_extension(con) -> None:
    """Load the DuckDB excel extension, installing if necessary."""
    try:
        con.execute("LOAD excel;")
    except Exception:
        con.execute("INSTALL excel; LOAD excel;")


def _is_excel_file(path: str) -> bool:
    """Check if a path has an Excel file extension."""
    return path.lower().endswith(_EXCEL_EXTENSIONS)


def _get_sheet_names(filepath: str) -> list[str]:
    """Extract sheet names from an xlsx file using its zip/XML structure.

    This avoids needing openpyxl or a DuckDB metadata function.
    Falls back to ["Sheet1"] for xls files or on parse errors.
    """
    try:
        with zipfile.ZipFile(filepath) as z:
            with z.open("xl/workbook.xml") as f:
                tree = ET.parse(f)
                ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                sheets = tree.findall(".//main:sheet", ns)
                return [s.attrib["name"] for s in sheets]
    except Exception:
        return ["Sheet1"]


def register_tools(mcp: FastMCP) -> None:
    """Register Excel tools with the MCP server."""

    @mcp.tool()
    def excel_read(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        sheet: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        """
        Read an Excel file (.xlsx/.xls) and return its contents.

        Uses DuckDB's excel extension for fast, reliable parsing with
        automatic type inference.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            sheet: Sheet name to read (None = first sheet)
            limit: Maximum number of rows to return (None = all rows)
            offset: Number of rows to skip from the beginning

        Returns:
            dict with success status, data, and metadata
        """
        if offset < 0 or (limit is not None and limit < 0):
            return {"error": "offset and limit must be non-negative"}

        duckdb, err = _check_duckdb()
        if err:
            return err

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not _is_excel_file(path):
                return {"error": "File must have .xlsx or .xls extension"}

            con = duckdb.connect(":memory:")
            try:
                _load_excel_extension(con)

                # Build read_xlsx call
                params = [f"'{secure_path}'"]
                params.append("header = true")
                if sheet is not None:
                    params.append(f"sheet = '{sheet}'")
                read_expr = f"read_xlsx({', '.join(params)})"

                # Get total row count
                count_result = con.execute(f"SELECT COUNT(*) FROM {read_expr}")
                total_rows = count_result.fetchone()[0]

                # Build query with offset and limit
                query = f"SELECT * FROM {read_expr}"
                if offset > 0:
                    query += f" OFFSET {offset}"
                if limit is not None:
                    query += f" LIMIT {limit}"

                result = con.execute(query)
                columns = [desc[0] for desc in result.description]
                raw_rows = result.fetchall()

                # Convert to list of dicts
                rows = [dict(zip(columns, row, strict=False)) for row in raw_rows]

                return {
                    "success": True,
                    "path": path,
                    "sheet": sheet,
                    "columns": columns,
                    "column_count": len(columns),
                    "rows": rows,
                    "row_count": len(rows),
                    "total_rows": total_rows,
                    "offset": offset,
                    "limit": limit,
                }
            finally:
                con.close()

        except Exception as e:
            return {"error": f"Failed to read Excel file: {str(e)}"}

    @mcp.tool()
    def excel_info(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict:
        """
        Get metadata about an Excel file without reading all data.

        Returns sheet names, row counts, column names, and file size.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier

        Returns:
            dict with file metadata (sheets, columns, row counts, file size)
        """
        duckdb, err = _check_duckdb()
        if err:
            return err

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not _is_excel_file(path):
                return {"error": "File must have .xlsx or .xls extension"}

            file_size = os.path.getsize(secure_path)

            # Extract sheet names from the xlsx zip structure
            # (xlsx files are zip archives with an XML workbook)
            sheet_names = _get_sheet_names(secure_path)

            con = duckdb.connect(":memory:")
            try:
                _load_excel_extension(con)

                # Get details for each sheet
                sheets = []
                for sheet_name in sheet_names:
                    try:
                        read_expr = (
                            f"read_xlsx('{secure_path}', "
                            f"sheet = '{sheet_name}', header = true)"
                        )

                        # Get columns
                        col_result = con.execute(f"SELECT * FROM {read_expr} LIMIT 0")
                        columns = [desc[0] for desc in col_result.description]

                        # Get row count
                        count_result = con.execute(
                            f"SELECT COUNT(*) FROM {read_expr}"
                        )
                        row_count = count_result.fetchone()[0]

                        sheets.append({
                            "name": sheet_name,
                            "columns": columns,
                            "column_count": len(columns),
                            "row_count": row_count,
                        })
                    except Exception:
                        # Sheet might be empty or unreadable
                        sheets.append({
                            "name": sheet_name,
                            "columns": [],
                            "column_count": 0,
                            "row_count": 0,
                            "warning": "Could not read sheet contents",
                        })

                return {
                    "success": True,
                    "path": path,
                    "sheet_count": len(sheets),
                    "sheets": sheets,
                    "file_size_bytes": file_size,
                }
            finally:
                con.close()

        except Exception as e:
            return {"error": f"Failed to get Excel info: {str(e)}"}

    @mcp.tool()
    def excel_sql(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        query: str,
        sheet: str | None = None,
    ) -> dict:
        """
        Query an Excel file using SQL (powered by DuckDB).

        The Excel sheet is loaded as a table named 'data'. Use standard SQL syntax.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            query: SQL query to execute. The sheet is available as table 'data'.
                   Example: "SELECT * FROM data WHERE price > 100 ORDER BY name LIMIT 10"
            sheet: Sheet name to query (None = first sheet)

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
        """
        duckdb, err = _check_duckdb()
        if err:
            return err

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not _is_excel_file(path):
                return {"error": "File must have .xlsx or .xls extension"}

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

            con = duckdb.connect(":memory:")
            try:
                _load_excel_extension(con)

                # Build read_xlsx expression
                params = [f"'{secure_path}'"]
                params.append("header = true")
                if sheet is not None:
                    params.append(f"sheet = '{sheet}'")
                read_expr = f"read_xlsx({', '.join(params)})"

                # Load Excel sheet as 'data' table
                con.execute(f"CREATE TABLE data AS SELECT * FROM {read_expr}")

                # Execute user query
                result = con.execute(query)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()

                # Convert to list of dicts
                rows_as_dicts = [dict(zip(columns, row, strict=False)) for row in rows]

                return {
                    "success": True,
                    "path": path,
                    "sheet": sheet,
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
