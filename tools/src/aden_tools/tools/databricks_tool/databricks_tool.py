"""
Databricks Tool - Execute SQL queries and explore tables in Databricks.

Supports:
- Personal Access Token (PAT) authentication via DATABRICKS_TOKEN
- Workspace host configuration via DATABRICKS_HOST

Safety features:
- Read-only queries only (INSERT, UPDATE, DELETE, etc. are blocked)
- Configurable row limits to prevent large result sets
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


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


def _create_databricks_client(host: str, token: str) -> Any:
    """
    Create a Databricks WorkspaceClient.

    Args:
        host: Databricks workspace host URL (e.g., 'adb-12345.6.azuredatabricks.net')
        token: Databricks Personal Access Token

    Returns:
        Databricks WorkspaceClient instance

    Raises:
        ImportError: If databricks-sdk is not installed
        Exception: If authentication fails
    """
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError:
        raise ImportError(
            "databricks-sdk is required for Databricks tools. "
            "Install it with: pip install databricks-sdk"
        ) from None

    return WorkspaceClient(host=f"https://{host}", token=token)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Databricks tools with the MCP server."""

    def _get_credentials() -> dict[str, str | None]:
        """Get Databricks credentials from credential store or environment."""
        if credentials is not None:
            try:
                token = credentials.get("databricks")
            except KeyError:
                token = None
            try:
                host = credentials.get("databricks_host")
            except KeyError:
                host = None
            return {
                "token": token,
                "host": host,
            }
        return {
            "token": os.getenv("DATABRICKS_TOKEN"),
            "host": os.getenv("DATABRICKS_HOST"),
        }

    def _get_client() -> Any:
        """
        Get a Databricks WorkspaceClient with credentials resolution.

        Returns:
            Databricks WorkspaceClient instance
        """
        creds = _get_credentials()
        token = creds.get("token")
        host = creds.get("host")

        if not token:
            raise ValueError(
                "DATABRICKS_TOKEN is not set. "
                "Get a Personal Access Token from your Databricks workspace settings."
            )
        if not host:
            raise ValueError(
                "DATABRICKS_HOST is not set. "
                "Set it to your workspace hostname (e.g., 'adb-12345.6.azuredatabricks.net')."
            )

        return _create_databricks_client(host, token)

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
            warehouse_id: Databricks SQL Warehouse ID. Falls back to
                         DATABRICKS_WAREHOUSE_ID env var if not provided.
            max_rows: Maximum number of rows to return (default: 1000).
                     Use this to prevent accidentally fetching large result sets.

        Returns:
            Dict with query results:
            - success: True if query executed successfully
            - rows: List of row dictionaries
            - total_rows: Total number of rows returned
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

            # Resolve warehouse ID
            effective_warehouse_id = warehouse_id or os.getenv("DATABRICKS_WAREHOUSE_ID")

            # Execute query using the Statement Execution API
            response = client.statement_execution.execute_statement(
                statement=sql,
                warehouse_id=effective_warehouse_id,
                wait_timeout="60s",
            )

            # Check for execution errors
            if response.status and response.status.state:
                state = response.status.state.value
                if state == "FAILED":
                    error_msg = ""
                    if response.status.error:
                        error_msg = response.status.error.message or "Unknown error"
                    return {"error": f"Query execution failed: {error_msg}"}

            # Extract schema
            schema = []
            if response.manifest and response.manifest.schema and response.manifest.schema.columns:
                schema = [
                    {
                        "name": col.name,
                        "type": col.type_text or "UNKNOWN",
                    }
                    for col in response.manifest.schema.columns
                ]

            # Extract rows
            rows = []
            if response.result and response.result.data_array:
                col_names = [col["name"] for col in schema] if schema else []
                for row_data in response.result.data_array:
                    if len(rows) >= max_rows:
                        break
                    row_dict = {}
                    for i, value in enumerate(row_data):
                        key = col_names[i] if i < len(col_names) else f"col_{i}"
                        row_dict[key] = value
                    rows.append(row_dict)

            total_rows_in_result = (
                len(response.result.data_array)
                if response.result and response.result.data_array
                else 0
            )
            query_truncated = total_rows_in_result > max_rows

            return {
                "success": True,
                "rows": rows,
                "total_rows": len(rows),
                "schema": schema,
                "query_truncated": query_truncated,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install the dependency by running: pip install databricks-sdk",
            }
        except ValueError as e:
            # Missing credentials
            return {"error": str(e)}
        except Exception as e:
            error_msg = str(e)

            # Provide helpful messages for common errors
            if "401" in error_msg or "Unauthorized" in error_msg.lower():
                return {
                    "error": "Databricks authentication failed",
                    "help": "Check that your DATABRICKS_TOKEN is valid and not expired. "
                    "Generate a new token in your Databricks workspace settings.",
                }
            if "403" in error_msg or "Permission" in error_msg.lower():
                return {
                    "error": f"Databricks permission denied: {error_msg}",
                    "help": "Ensure your token has the required permissions to access "
                    "the SQL Warehouse and the requested tables.",
                }
            if "404" in error_msg or "Not found" in error_msg.lower():
                return {
                    "error": f"Databricks resource not found: {error_msg}",
                    "help": "Check that the warehouse ID, catalog, schema, "
                    "and table names are correct.",
                }

            return {"error": f"Databricks query failed: {error_msg}"}

    @mcp.tool()
    def describe_databricks_table(
        table_name: str,
    ) -> dict:
        """
        Describe a Databricks Unity Catalog table, showing its schema and metadata.

        Use this tool to explore table structure before writing queries.
        Returns column names, types, and table metadata.

        Args:
            table_name: Fully qualified table name in the format
                       'catalog.schema.table' (e.g., 'main.default.users').

        Returns:
            Dict with table information:
            - success: True if operation succeeded
            - table_name: The fully qualified table name
            - columns: List of column definitions (name, type, comment)

            Or error dict with:
            - error: Error message
            - help: Optional help text

        Example:
            >>> describe_databricks_table("main.default.users")
            {
                "success": True,
                "table_name": "main.default.users",
                "columns": [
                    {"name": "id", "type": "BIGINT", "comment": "Primary key"},
                    {"name": "email", "type": "STRING", "comment": null}
                ]
            }
        """
        if not table_name or not table_name.strip():
            return {"error": "table_name is required"}

        # Validate format: should be catalog.schema.table
        parts = table_name.strip().split(".")
        if len(parts) != 3:
            return {
                "error": "table_name must be fully qualified as 'catalog.schema.table'",
                "help": "Example: 'main.default.my_table'",
            }

        try:
            client = _get_client()

            # Use the Unity Catalog API to get table info
            catalog, schema, table = parts
            table_info = client.tables.get(full_name=table_name)

            columns = []
            if table_info.columns:
                columns = [
                    {
                        "name": col.name,
                        "type": col.type_text or "UNKNOWN",
                        "comment": col.comment,
                    }
                    for col in table_info.columns
                ]

            return {
                "success": True,
                "table_name": table_name,
                "columns": columns,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install the dependency by running: pip install databricks-sdk",
            }
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            error_msg = str(e)

            if "401" in error_msg or "Unauthorized" in error_msg.lower():
                return {
                    "error": "Databricks authentication failed",
                    "help": "Check that your DATABRICKS_TOKEN is valid and not expired.",
                }
            if "404" in error_msg or "Not found" in error_msg.lower():
                return {
                    "error": f"Table not found: {table_name}",
                    "help": "Check that the catalog, schema, and table names are correct. "
                    f"Full error: {error_msg}",
                }
            if "403" in error_msg or "Permission" in error_msg.lower():
                return {
                    "error": f"Permission denied for table: {table_name}",
                    "help": "Ensure your token has access to this Unity Catalog table.",
                }

            return {"error": f"Failed to describe table: {error_msg}"}
