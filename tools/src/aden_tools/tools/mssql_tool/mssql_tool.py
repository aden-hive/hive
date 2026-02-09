"""
MSSQL Tool - Professional SQL Server database operations for Aden Hive.

Provides tools for:
- Executing SELECT queries
- Executing INSERT/UPDATE/DELETE operations
- Inspecting database schema
- Executing stored procedures

Security: Uses CredentialStoreAdapter for secure credential management.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pyodbc
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register MSSQL tools with the MCP server."""

    def _get_connection_params() -> dict[str, str | None]:
        """Get MSSQL connection parameters from credentials or environment."""
        if credentials is not None:
            return {
                "server": credentials.get("mssql_server"),
                "database": credentials.get("mssql_database"),
                "username": credentials.get("mssql_username"),
                "password": credentials.get("mssql_password"),
            }
        return {
            "server": os.getenv("MSSQL_SERVER"),
            "database": os.getenv("MSSQL_DATABASE"),
            "username": os.getenv("MSSQL_USERNAME"),
            "password": os.getenv("MSSQL_PASSWORD"),
        }

    def _create_connection() -> tuple[pyodbc.Connection | None, str | None]:
        """
        Create a database connection.

        Returns:
            Tuple of (connection, error_message). If successful, error_message is None.
        """
        params = _get_connection_params()

        # Validate required parameters
        if not params["server"]:
            return None, "MSSQL_SERVER environment variable not set"
        if not params["database"]:
            return None, "MSSQL_DATABASE environment variable not set"

        try:
            # Build connection string
            if params["username"] and params["password"]:
                # SQL Server Authentication
                connection_string = (
                    f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                    f'SERVER={params["server"]};'
                    f'DATABASE={params["database"]};'
                    f'UID={params["username"]};'
                    f'PWD={params["password"]};'
                )
            else:
                # Windows Authentication
                connection_string = (
                    f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                    f'SERVER={params["server"]};'
                    f'DATABASE={params["database"]};'
                    f'Trusted_Connection=yes;'
                )

            connection = pyodbc.connect(connection_string, timeout=10)
            return connection, None

        except pyodbc.Error as e:
            error_msg = str(e)
            if "Login failed" in error_msg:
                return None, "Authentication failed. Check MSSQL_USERNAME and MSSQL_PASSWORD"
            elif "Cannot open database" in error_msg:
                return None, f"Cannot access database '{params['database']}'. Check permissions."
            elif "SQL Server does not exist" in error_msg:
                return None, f"Server '{params['server']}' not found. Check MSSQL_SERVER value."
            else:
                return None, f"Connection failed: {error_msg}"

    @mcp.tool()
    def mssql_execute_query(
        query: str,
        max_rows: int = 1000,
    ) -> dict[str, Any]:
        """
        Execute a SELECT query on the MSSQL database.

        Use this tool to retrieve data from the database using SELECT statements.
        Results are returned as a list of dictionaries with column names as keys.

        Args:
            query: SQL SELECT query to execute (must start with SELECT)
            max_rows: Maximum number of rows to return (1-10000, default 1000)

        Returns:
            Dict with 'columns', 'rows', 'row_count', and optionally 'error'

        Example:
            {
                "columns": ["id", "name", "email"],
                "rows": [
                    {"id": 1, "name": "John", "email": "john@example.com"},
                    {"id": 2, "name": "Jane", "email": "jane@example.com"}
                ],
                "row_count": 2
            }
        """
        # Validate inputs
        if not query or len(query.strip()) == 0:
            return {"error": "Query cannot be empty"}

        if max_rows < 1 or max_rows > 10000:
            return {"error": "max_rows must be between 1 and 10000"}

        # Basic query validation
        query_upper = query.strip().upper()
        if not query_upper.startswith("SELECT") and not query_upper.startswith("WITH"):
            return {
                "error": "Only SELECT queries are allowed. Use mssql_execute_update for modifications."
            }

        connection, error = _create_connection()
        if error:
            return {"error": error}

        try:
            cursor = connection.cursor()
            cursor.execute(query)

            # Get column names
            columns = [column[0] for column in cursor.description]

            # Fetch rows
            rows = []
            for row in cursor.fetchmany(max_rows):
                row_dict = {}
                for i, column in enumerate(columns):
                    value = row[i]
                    # Convert to JSON-serializable types
                    if hasattr(value, 'isoformat'):  # datetime objects
                        value = value.isoformat()
                    row_dict[column] = value
                rows.append(row_dict)

            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": len(rows) == max_rows,
            }

        except pyodbc.Error as e:
            return {"error": f"Query execution failed: {str(e)}"}
        finally:
            if connection:
                connection.close()

    @mcp.tool()
    def mssql_execute_update(
        query: str,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Execute an INSERT, UPDATE, or DELETE query on the MSSQL database.

        Use this tool to modify data in the database. The operation is wrapped
        in a transaction and will be rolled back on error unless commit=False.

        Args:
            query: SQL INSERT/UPDATE/DELETE query to execute
            commit: Whether to commit the transaction (default True)

        Returns:
            Dict with 'affected_rows', 'success', and optionally 'error'

        Example:
            {
                "success": true,
                "affected_rows": 5,
                "message": "Successfully updated 5 rows"
            }
        """
        # Validate inputs
        if not query or len(query.strip()) == 0:
            return {"error": "Query cannot be empty"}

        # Basic query validation
        query_upper = query.strip().upper()
        allowed_keywords = ["INSERT", "UPDATE", "DELETE", "MERGE"]
        if not any(query_upper.startswith(kw) for kw in allowed_keywords):
            return {
                "error": f"Only {', '.join(allowed_keywords)} queries are allowed. "
                         "Use mssql_execute_query for SELECT."
            }

        # Safety check for DELETE without WHERE
        if query_upper.startswith("DELETE") and "WHERE" not in query_upper:
            return {
                "error": "DELETE without WHERE clause is not allowed for safety. "
                         "Add a WHERE clause or use DELETE FROM table WHERE 1=1 if intentional."
            }

        connection, error = _create_connection()
        if error:
            return {"error": error}

        try:
            cursor = connection.cursor()
            cursor.execute(query)

            affected_rows = cursor.rowcount

            if commit:
                connection.commit()
                return {
                    "success": True,
                    "affected_rows": affected_rows,
                    "message": f"Successfully affected {affected_rows} row(s)",
                }
            else:
                connection.rollback()
                return {
                    "success": True,
                    "affected_rows": affected_rows,
                    "message": f"Query executed (rolled back). Would affect {affected_rows} row(s)",
                    "committed": False,
                }

        except pyodbc.Error as e:
            if connection:
                connection.rollback()
            return {
                "success": False,
                "error": f"Query execution failed: {str(e)}",
                "committed": False,
            }
        finally:
            if connection:
                connection.close()

    @mcp.tool()
    def mssql_get_schema(
        table_name: str | None = None,
        include_indexes: bool = False,
    ) -> dict[str, Any]:
        """
        Get database schema information.

        Use this to inspect database structure, tables, columns, and relationships.

        Args:
            table_name: Optional specific table name to get detailed info for.
                       If None, returns list of all tables.
            include_indexes: Include index information (only when table_name is specified)

        Returns:
            Dict with schema information

        Examples:
            # List all tables
            {"tables": ["Departments", "Employees"], "table_count": 2}

            # Get specific table schema
            {
                "table": "Employees",
                "columns": [
                    {"name": "employee_id", "type": "int", "nullable": False, "primary_key": True},
                    {"name": "first_name", "type": "nvarchar(50)", "nullable": False}
                ],
                "foreign_keys": [
                    {"column": "department_id", "references": "Departments(department_id)"}
                ]
            }
        """
        connection, error = _create_connection()
        if error:
            return {"error": error}

        try:
            cursor = connection.cursor()

            if table_name is None:
                # List all tables
                cursor.execute("""
                    SELECT TABLE_NAME
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE = 'BASE TABLE'
                    ORDER BY TABLE_NAME
                """)
                tables = [row[0] for row in cursor.fetchall()]
                return {
                    "tables": tables,
                    "table_count": len(tables),
                }
            else:
                # Get detailed table schema
                # Check if table exists
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_NAME = ?
                """, table_name)

                if cursor.fetchone()[0] == 0:
                    return {"error": f"Table '{table_name}' not found"}

                # Get columns
                cursor.execute("""
                    SELECT
                        c.COLUMN_NAME,
                        c.DATA_TYPE,
                        c.CHARACTER_MAXIMUM_LENGTH,
                        c.IS_NULLABLE,
                        CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS IS_PRIMARY_KEY
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    LEFT JOIN (
                        SELECT ku.COLUMN_NAME
                        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                            ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                            AND tc.TABLE_NAME = ?
                    ) pk ON c.COLUMN_NAME = pk.COLUMN_NAME
                    WHERE c.TABLE_NAME = ?
                    ORDER BY c.ORDINAL_POSITION
                """, table_name, table_name)

                columns = []
                for row in cursor.fetchall():
                    col_type = row[1]
                    if row[2]:  # Add length for varchar/nvarchar
                        col_type += f"({row[2]})"

                    columns.append({
                        "name": row[0],
                        "type": col_type,
                        "nullable": row[3] == "YES",
                        "primary_key": bool(row[4]),
                    })

                # Get foreign keys
                cursor.execute("""
                    SELECT
                        kcu.COLUMN_NAME,
                        ccu.TABLE_NAME AS REFERENCED_TABLE,
                        ccu.COLUMN_NAME AS REFERENCED_COLUMN
                    FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                        ON rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                    JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu
                        ON rc.UNIQUE_CONSTRAINT_NAME = ccu.CONSTRAINT_NAME
                    WHERE kcu.TABLE_NAME = ?
                """, table_name)

                foreign_keys = []
                for row in cursor.fetchall():
                    foreign_keys.append({
                        "column": row[0],
                        "references": f"{row[1]}({row[2]})",
                    })

                result = {
                    "table": table_name,
                    "columns": columns,
                    "column_count": len(columns),
                    "foreign_keys": foreign_keys,
                }

                # Optionally include indexes
                if include_indexes:
                    cursor.execute("""
                        SELECT
                            i.name AS INDEX_NAME,
                            i.type_desc AS INDEX_TYPE,
                            COL_NAME(ic.object_id, ic.column_id) AS COLUMN_NAME
                        FROM sys.indexes i
                        JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                        WHERE i.object_id = OBJECT_ID(?)
                        ORDER BY i.name, ic.key_ordinal
                    """, table_name)

                    indexes = {}
                    for row in cursor.fetchall():
                        idx_name = row[0]
                        if idx_name not in indexes:
                            indexes[idx_name] = {
                                "name": idx_name,
                                "type": row[1],
                                "columns": [],
                            }
                        indexes[idx_name]["columns"].append(row[2])

                    result["indexes"] = list(indexes.values())

                return result

        except pyodbc.Error as e:
            return {"error": f"Schema inspection failed: {str(e)}"}
        finally:
            if connection:
                connection.close()

    @mcp.tool()
    def mssql_execute_procedure(
        procedure_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a stored procedure.

        Use this to call stored procedures with optional parameters.

        Args:
            procedure_name: Name of the stored procedure to execute
            parameters: Optional dict of parameter names to values

        Returns:
            Dict with result sets and return value

        Example:
            {
                "return_value": 0,
                "result_sets": [
                    {
                        "columns": ["id", "name"],
                        "rows": [{"id": 1, "name": "Test"}]
                    }
                ],
                "messages": ["Procedure executed successfully"]
            }
        """
        if not procedure_name or len(procedure_name.strip()) == 0:
            return {"error": "Procedure name cannot be empty"}

        connection, error = _create_connection()
        if error:
            return {"error": error}

        try:
            cursor = connection.cursor()

            # Build parameter placeholders
            if parameters:
                param_values = list(parameters.values())
                placeholders = ", ".join(["?"] * len(param_values))
                sql = f"EXEC {procedure_name} {placeholders}"
                cursor.execute(sql, param_values)
            else:
                sql = f"EXEC {procedure_name}"
                cursor.execute(sql)

            # Collect all result sets
            result_sets = []
            while True:
                if cursor.description:
                    columns = [column[0] for column in cursor.description]
                    rows = []
                    for row in cursor.fetchall():
                        row_dict = {}
                        for i, column in enumerate(columns):
                            value = row[i]
                            if hasattr(value, 'isoformat'):
                                value = value.isoformat()
                            row_dict[column] = value
                        rows.append(row_dict)

                    result_sets.append({
                        "columns": columns,
                        "rows": rows,
                    })

                if not cursor.nextset():
                    break

            connection.commit()

            return {
                "success": True,
                "procedure": procedure_name,
                "result_sets": result_sets,
                "result_set_count": len(result_sets),
            }

        except pyodbc.Error as e:
            if connection:
                connection.rollback()
            return {
                "success": False,
                "error": f"Procedure execution failed: {str(e)}",
            }
        finally:
            if connection:
                connection.close()
