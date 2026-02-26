"""
Databricks Tool - Execute SQL queries and explore tables in Databricks.

Provides two categories of tools:
1. Custom SQL tools with read-only safety guards (run_databricks_sql, describe_databricks_table)
2. Managed MCP server tools (databricks_mcp_*)

Supports:
- Personal access token authentication via DATABRICKS_HOST + DATABRICKS_TOKEN
- Databricks CLI profile authentication (for managed MCP tools)

Safety features:
- Read-only queries only (INSERT, UPDATE, DELETE, etc. are blocked)
- Configurable row limits to prevent large result sets
- SQL write-keyword detection with comment stripping
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

from .databricks_mcp_tool import register_mcp_tools

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

logger = logging.getLogger(__name__)

# SQL keywords that indicate write operations (case-insensitive)
WRITE_KEYWORDS = [
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bDROP\b",
    r"\bCREATE\b",
    r"\bALTER\b",
    r"\bTRUNCATE\b",
    r"\bMERGE\b",
    r"\bREPLACE\b",
]

# Compiled regex pattern for detecting write operations
WRITE_PATTERN = re.compile("|".join(WRITE_KEYWORDS), re.IGNORECASE)


def _is_read_only_query(sql: str) -> bool:
    """
    Check if a SQL query is read-only.

    Args:
        sql: The SQL query string to check

    Returns:
        True if the query appears to be read-only, False otherwise
    """
    # Remove comments (both -- and /* */ style)
    sql_no_comments = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    sql_no_comments = re.sub(r"/\*.*?\*/", "", sql_no_comments, flags=re.DOTALL)

    # Check for write keywords
    return not bool(WRITE_PATTERN.search(sql_no_comments))


def _create_workspace_client(
    host: str | None = None,
    token: str | None = None,
) -> Any:
    """
    Create a Databricks WorkspaceClient with appropriate credentials.

    Args:
        host: Databricks workspace URL
        token: Personal access token

    Returns:
        WorkspaceClient instance

    Raises:
        ImportError: If databricks-sdk is not installed
        Exception: If authentication fails
    """
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError:
        raise ImportError(
            "databricks-sdk is required for Databricks tools. "
            "Install it with: pip install 'databricks-sdk>=0.30.0'"
        ) from None

    kwargs: dict[str, str] = {}
    if host:
        kwargs["host"] = host
    if token:
        kwargs["token"] = token

    return WorkspaceClient(**kwargs)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Databricks tools with the MCP server."""

    def _get_credentials() -> dict[str, str | None]:
        """Get Databricks credentials from credential store or environment."""
        if credentials is not None:
            try:
                host = credentials.get("databricks_host")
            except KeyError:
                host = None
            try:
                token = credentials.get("databricks_token")
            except KeyError:
                token = None
            try:
                warehouse = credentials.get("databricks_warehouse")
            except KeyError:
                warehouse = None
            return {
                "host": host,
                "token": token,
                "warehouse_id": warehouse,
            }
        return {
            "host": os.getenv("DATABRICKS_HOST"),
            "token": os.getenv("DATABRICKS_TOKEN"),
            "warehouse_id": os.getenv("DATABRICKS_WAREHOUSE_ID"),
        }

    def _get_client() -> Any:
        """
        Get a Databricks WorkspaceClient with credentials resolution.

        Returns:
            WorkspaceClient instance
        """
        creds = _get_credentials()
        return _create_workspace_client(
            host=creds["host"],
            token=creds["token"],
        )

    @mcp.tool()
    def run_databricks_sql(
        sql: str,
        warehouse_id: str | None = None,
        max_rows: int = 1000,
    ) -> dict:
        """
        Execute a read-only SQL query against a Databricks SQL Warehouse.

        This tool executes SQL queries and returns the results as structured data.
        Only SELECT queries are allowed - write operations (INSERT, UPDATE, DELETE,
        DROP, CREATE, ALTER, TRUNCATE, MERGE) are blocked for safety.

        Args:
            sql: The SQL query to execute. Must be a read-only query.
            warehouse_id: SQL Warehouse ID. Falls back to DATABRICKS_WAREHOUSE_ID
                         env var if not provided.
            max_rows: Maximum number of rows to return (default: 1000).
                     Use this to prevent accidentally fetching large result sets.

        Returns:
            Dict with query results:
            - success: True if query executed successfully
            - rows: List of row dictionaries
            - total_rows: Total number of rows returned
            - rows_returned: Number of rows actually returned (may be limited)
            - schema: List of column definitions (name, type)
            - query_truncated: True if results were truncated due to max_rows

            Or error dict with:
            - error: Error message
            - help: Optional help text

        Example:
            >>> run_databricks_sql(
            ...     sql="SELECT name, COUNT(*) as cnt FROM catalog.schema.users GROUP BY name",
            ...     max_rows=100
            ... )
            {
                "success": True,
                "rows": [{"name": "Alice", "cnt": 42}, ...],
                "total_rows": 100,
                "rows_returned": 100,
                "schema": [{"name": "name", "type": "STRING"}, ...],
                "query_truncated": False
            }
        """
        # Validate SQL is read-only
        if not _is_read_only_query(sql):
            return {
                "error": "Write operations are not allowed",
                "help": "Only SELECT queries are permitted. "
                "INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, and MERGE are blocked.",
            }

        # Validate max_rows
        if max_rows < 1:
            return {"error": "max_rows must be at least 1"}
        if max_rows > 10000:
            return {
                "error": "max_rows cannot exceed 10000",
                "help": "For larger result sets, consider using pagination or "
                "exporting to cloud storage.",
            }

        try:
            client = _get_client()
            creds = _get_credentials()
            effective_warehouse = warehouse_id or creds.get("warehouse_id")

            if not effective_warehouse:
                return {
                    "error": "No SQL Warehouse ID provided",
                    "help": "Provide warehouse_id parameter or set DATABRICKS_WAREHOUSE_ID "
                    "environment variable.",
                }

            # Execute query via Databricks SQL Statement API
            response = client.statement_execution.execute_statement(
                statement=sql,
                warehouse_id=effective_warehouse,
                wait_timeout="30s",
                row_limit=max_rows,
            )

            # Check for execution errors
            if response.status and response.status.error:
                return {
                    "error": f"Databricks SQL error: {response.status.error.message}",
                }

            # Parse results
            schema = []
            if response.manifest and response.manifest.schema and response.manifest.schema.columns:
                schema = [
                    {
                        "name": col.name,
                        "type": str(col.type_name) if col.type_name else "UNKNOWN",
                    }
                    for col in response.manifest.schema.columns
                ]

            rows = []
            total_rows = 0
            if response.result and response.result.data_array:
                total_rows = len(response.result.data_array)
                for row_data in response.result.data_array[:max_rows]:
                    row = {}
                    for i, value in enumerate(row_data):
                        col_name = schema[i]["name"] if i < len(schema) else f"col_{i}"
                        row[col_name] = value
                    rows.append(row)

            query_truncated = total_rows > max_rows

            return {
                "success": True,
                "rows": rows,
                "total_rows": total_rows,
                "rows_returned": len(rows),
                "schema": schema,
                "query_truncated": query_truncated,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install the dependency by running: pip install 'databricks-sdk>=0.30.0'",
            }
        except Exception as e:
            error_msg = str(e)

            # Provide helpful messages for common errors
            if "TEMPORARILY_UNAVAILABLE" in error_msg or "401" in error_msg:
                return {
                    "error": "Databricks authentication failed",
                    "help": "Check that DATABRICKS_HOST and DATABRICKS_TOKEN are set correctly. "
                    "Token may have expired — generate a new one from workspace settings.",
                }
            if "403" in error_msg or "PERMISSION_DENIED" in error_msg:
                return {
                    "error": f"Databricks permission denied: {error_msg}",
                    "help": "Ensure your token has permission to access the SQL Warehouse "
                    "and the requested tables/catalogs.",
                }
            if "404" in error_msg or "NOT_FOUND" in error_msg:
                return {
                    "error": f"Databricks resource not found: {error_msg}",
                    "help": "Check that the warehouse ID, catalog, schema, "
                    "and table names are correct.",
                }
            if "INVALID_PARAMETER" in error_msg:
                return {
                    "error": f"Invalid parameter: {error_msg}",
                    "help": "Check that the warehouse_id is a valid SQL Warehouse ID.",
                }

            return {"error": f"Databricks SQL query failed: {error_msg}"}

    @mcp.tool()
    def describe_databricks_table(
        catalog: str,
        schema: str,
        table: str,
    ) -> dict:
        """
        Describe a table in Databricks Unity Catalog, returning its schema and metadata.

        Use this tool to explore table structure before writing queries.
        Returns column names, types, nullability, and table metadata.

        Args:
            catalog: Unity Catalog catalog name (e.g., "main").
            schema: Schema name within the catalog (e.g., "default").
            table: Table name to describe.

        Returns:
            Dict with table information:
            - success: True if operation succeeded
            - catalog: The catalog name
            - schema: The schema name
            - table: The table name
            - full_name: Fully qualified table name (catalog.schema.table)
            - table_type: Type of the table (MANAGED, EXTERNAL, VIEW, etc.)
            - columns: List of column definitions (name, type, nullable, comment)
            - comment: Table comment/description if available
            - storage_location: Physical storage location if applicable

            Or error dict with:
            - error: Error message
            - help: Optional help text

        Example:
            >>> describe_databricks_table("main", "default", "users")
            {
                "success": True,
                "catalog": "main",
                "schema": "default",
                "table": "users",
                "full_name": "main.default.users",
                "table_type": "MANAGED",
                "columns": [
                    {"name": "id", "type": "LONG", "nullable": False, "comment": "User ID"},
                    {"name": "email", "type": "STRING", "nullable": True, "comment": None}
                ],
                "comment": "User accounts table"
            }
        """
        if not catalog or not catalog.strip():
            return {"error": "catalog is required"}
        if not schema or not schema.strip():
            return {"error": "schema is required"}
        if not table or not table.strip():
            return {"error": "table name is required"}

        full_name = f"{catalog}.{schema}.{table}"

        try:
            client = _get_client()

            # Retrieve table metadata via Unity Catalog API
            table_info = client.tables.get(full_name)

            columns = []
            if table_info.columns:
                for col in table_info.columns:
                    columns.append(
                        {
                            "name": col.name,
                            "type": str(col.type_name) if col.type_name else "UNKNOWN",
                            "nullable": col.nullable if col.nullable is not None else True,
                            "comment": col.comment,
                        }
                    )

            result = {
                "success": True,
                "catalog": catalog,
                "schema": schema,
                "table": table,
                "full_name": full_name,
                "table_type": str(table_info.table_type) if table_info.table_type else None,
                "columns": columns,
                "comment": table_info.comment,
            }

            if table_info.storage_location:
                result["storage_location"] = table_info.storage_location

            return result

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install the dependency by running: pip install 'databricks-sdk>=0.30.0'",
            }
        except Exception as e:
            error_msg = str(e)

            if "TEMPORARILY_UNAVAILABLE" in error_msg or "401" in error_msg:
                return {
                    "error": "Databricks authentication failed",
                    "help": "Check that DATABRICKS_HOST and DATABRICKS_TOKEN are set correctly.",
                }
            if "NOT_FOUND" in error_msg or "DOES_NOT_EXIST" in error_msg:
                return {
                    "error": f"Table not found: {full_name}",
                    "help": "Check that the catalog, schema, and table names are correct. "
                    f"Full error: {error_msg}",
                }
            if "403" in error_msg or "PERMISSION_DENIED" in error_msg:
                return {
                    "error": f"Permission denied for table: {full_name}",
                    "help": "Ensure your token has the 'USE CATALOG', 'USE SCHEMA', "
                    "and 'SELECT' privileges on the target table.",
                }

            return {"error": f"Failed to describe table: {error_msg}"}

    # Register managed MCP server tools
    register_mcp_tools(mcp, credentials)
