"""
Amazon Redshift Tool - Query and manage Redshift data warehouse.

Supports:
- AWS IAM credentials (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY)
- Temporary session tokens via the credential store
- Read-only SQL queries (recommended for MVP security)

API Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/redshift-data.html
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from typing import TYPE_CHECKING, Any, Literal

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# Try to import boto3 at module level for proper mocking in tests
try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore


class _RedshiftClient:
    """Internal client wrapping Redshift Data API calls."""

    def __init__(
        self,
        cluster_identifier: str,
        database: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region: str = "us-east-1",
        db_user: str | None = None,
    ):
        """
        Initialize Redshift client.

        Args:
            cluster_identifier: Redshift cluster identifier
            database: Database name
            aws_access_key_id: AWS access key ID
            aws_secret_access_key: AWS secret access key
            region: AWS region (default: us-east-1)
            db_user: Database user (optional, uses IAM if not provided)
        """
        if boto3 is None:
            raise ImportError(
                "boto3 is required for Redshift integration. Install with: pip install boto3"
            )

        self._cluster_identifier = cluster_identifier
        self._database = database
        self._db_user = db_user
        self._region = region

        self._client = boto3.client(
            "redshift-data",
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

    def _execute_statement(
        self,
        sql: str,
        wait_for_completion: bool = True,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """
        Execute a SQL statement and optionally wait for completion.

        Args:
            sql: SQL statement to execute
            wait_for_completion: Wait for query to complete (default: True)
            timeout: Maximum wait time in seconds (default: 30)

        Returns:
            Dict with query results or execution info
        """
        try:
            # Execute the statement
            execute_params: dict[str, Any] = {
                "ClusterIdentifier": self._cluster_identifier,
                "Database": self._database,
                "Sql": sql,
            }

            if self._db_user:
                execute_params["DbUser"] = self._db_user

            response = self._client.execute_statement(**execute_params)
            statement_id = response["Id"]

            if not wait_for_completion:
                return {
                    "statement_id": statement_id,
                    "status": "SUBMITTED",
                    "message": "Query submitted successfully",
                }

            # Wait for completion
            elapsed = 0
            while elapsed < timeout:
                describe_response = self._client.describe_statement(Id=statement_id)
                status = describe_response["Status"]

                if status == "FINISHED":
                    # Get results
                    result_response = self._client.get_statement_result(Id=statement_id)
                    return {
                        "statement_id": statement_id,
                        "status": "FINISHED",
                        "rows": result_response.get("Records", []),
                        "column_metadata": result_response.get("ColumnMetadata", []),
                        "total_num_rows": result_response.get("TotalNumRows", 0),
                    }
                elif status == "FAILED":
                    error_msg = describe_response.get("Error", "Unknown error")
                    return {"error": f"Query failed: {error_msg}"}
                elif status == "ABORTED":
                    return {"error": "Query was aborted"}

                time.sleep(1)
                elapsed += 1

            return {"error": f"Query timeout after {timeout} seconds"}

        except Exception as e:
            return {"error": f"Redshift API error: {e!s}"}

    def list_schemas(self) -> dict[str, Any]:
        """
        List all schemas in the database.

        Returns:
            Dict with list of schemas or error
        """
        sql = """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schema_name;
        """
        result = self._execute_statement(sql)

        if "error" in result:
            return result

        schemas = [row[0].get("stringValue", "") for row in result.get("rows", [])]
        return {"schemas": schemas, "count": len(schemas)}

    def list_tables(self, schema: str) -> dict[str, Any]:
        """
        List all tables in a schema.

        Args:
            schema: Schema name

        Returns:
            Dict with list of tables or error
        """
        sql = f"""
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = '{schema}'
        ORDER BY table_name;
        """
        result = self._execute_statement(sql)

        if "error" in result:
            return result

        tables = [
            {
                "name": row[0].get("stringValue", ""),
                "type": row[1].get("stringValue", ""),
            }
            for row in result.get("rows", [])
        ]
        return {"schema": schema, "tables": tables, "count": len(tables)}

    def get_table_schema(self, schema: str, table: str) -> dict[str, Any]:
        """
        Get schema and metadata for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Dict with table schema or error
        """
        sql = f"""
        SELECT
            column_name,
            data_type,
            character_maximum_length,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = '{schema}'
        AND table_name = '{table}'
        ORDER BY ordinal_position;
        """
        result = self._execute_statement(sql)

        if "error" in result:
            return result

        columns = [
            {
                "name": row[0].get("stringValue", ""),
                "type": row[1].get("stringValue", ""),
                "max_length": row[2].get("longValue") if row[2].get("isNull") is False else None,
                "nullable": row[3].get("stringValue", "") == "YES",
                "default": row[4].get("stringValue") if row[4].get("isNull") is False else None,
            }
            for row in result.get("rows", [])
        ]

        return {
            "schema": schema,
            "table": table,
            "columns": columns,
            "column_count": len(columns),
        }

    def execute_query(
        self,
        sql: str,
        format: Literal["json", "csv"] = "json",  # noqa: A002
        timeout: int = 30,
    ) -> dict[str, Any]:
        """
        Execute a read-only SQL query.

        Args:
            sql: SQL query (SELECT only recommended for security)
            format: Output format ("json" or "csv")
            timeout: Query timeout in seconds

        Returns:
            Dict with query results or error
        """
        # Basic SQL injection prevention - only allow SELECT statements
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            return {
                "error": "Only SELECT queries are allowed for security. "
                "Use execute_statement for other operations."
            }

        result = self._execute_statement(sql, timeout=timeout)

        if "error" in result:
            return result

        # Format results
        if format == "csv":
            return self._format_as_csv(result)
        return self._format_as_json(result)

    def _format_as_json(self, result: dict[str, Any]) -> dict[str, Any]:
        """Format query results as JSON."""
        column_metadata = result.get("column_metadata", [])
        rows = result.get("rows", [])

        column_names = [col["name"] for col in column_metadata]

        formatted_rows = []
        for row in rows:
            formatted_row = {}
            for idx, col_name in enumerate(column_names):
                cell = row[idx]
                # Extract the actual value from the cell
                if cell.get("isNull"):
                    formatted_row[col_name] = None
                elif "stringValue" in cell:
                    formatted_row[col_name] = cell["stringValue"]
                elif "longValue" in cell:
                    formatted_row[col_name] = cell["longValue"]
                elif "doubleValue" in cell:
                    formatted_row[col_name] = cell["doubleValue"]
                elif "booleanValue" in cell:
                    formatted_row[col_name] = cell["booleanValue"]
                else:
                    formatted_row[col_name] = None

            formatted_rows.append(formatted_row)

        return {
            "format": "json",
            "columns": column_names,
            "rows": formatted_rows,
            "row_count": len(formatted_rows),
            "statement_id": result.get("statement_id"),
        }

    def _format_as_csv(self, result: dict[str, Any]) -> dict[str, Any]:
        """Format query results as CSV string."""
        json_result = self._format_as_json(result)

        if "error" in json_result:
            return json_result

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=json_result["columns"])
        writer.writeheader()
        writer.writerows(json_result["rows"])

        return {
            "format": "csv",
            "data": output.getvalue(),
            "row_count": json_result["row_count"],
            "statement_id": result.get("statement_id"),
        }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Redshift tools with the MCP server."""

    def _get_credentials() -> dict[str, str | None]:
        """Get Redshift credentials from credential manager or environment."""
        if credentials is not None:
            # Try to get credentials from credential store
            # Format: {"aws_access_key_id": "...", "aws_secret_access_key": "...", ...}
            creds = credentials.get("redshift")
            if creds and isinstance(creds, dict):
                return {
                    "aws_access_key_id": creds.get("aws_access_key_id"),
                    "aws_secret_access_key": creds.get("aws_secret_access_key"),
                    "cluster_identifier": creds.get("cluster_identifier"),
                    "database": creds.get("database"),
                    "region": creds.get("region", "us-east-1"),
                    "db_user": creds.get("db_user"),
                }

        # Fall back to environment variables
        return {
            "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "cluster_identifier": os.getenv("REDSHIFT_CLUSTER_IDENTIFIER"),
            "database": os.getenv("REDSHIFT_DATABASE"),
            "region": os.getenv("AWS_REGION", "us-east-1"),
            "db_user": os.getenv("REDSHIFT_DB_USER"),
        }

    def _get_client() -> _RedshiftClient | dict[str, str]:
        """Get a Redshift client, or return an error dict if no credentials."""
        creds = _get_credentials()

        if not creds.get("aws_access_key_id") or not creds.get("aws_secret_access_key"):
            return {
                "error": "AWS credentials not configured",
                "help": (
                    "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables "
                    "or configure via credential store. "
                    "See: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html"
                ),
            }

        if not creds.get("cluster_identifier"):
            return {
                "error": "Redshift cluster identifier not configured",
                "help": (
                    "Set REDSHIFT_CLUSTER_IDENTIFIER environment variable "
                    "or configure via credential store"
                ),
            }

        if not creds.get("database"):
            return {
                "error": "Redshift database not configured",
                "help": (
                    "Set REDSHIFT_DATABASE environment variable or configure via credential store"
                ),
            }

        return _RedshiftClient(
            cluster_identifier=creds["cluster_identifier"],  # type: ignore
            database=creds["database"],  # type: ignore
            aws_access_key_id=creds["aws_access_key_id"],  # type: ignore
            aws_secret_access_key=creds["aws_secret_access_key"],  # type: ignore
            region=creds.get("region", "us-east-1"),  # type: ignore
            db_user=creds.get("db_user"),  # type: ignore
        )

    # --- Schema Discovery ---

    @mcp.tool()
    def redshift_list_schemas() -> dict:
        """
        List all schemas in the Redshift database.

        Returns all schemas excluding system schemas (pg_catalog, information_schema).

        Returns:
            Dict with list of schema names or error

        Example:
            {
                "schemas": ["public", "sales", "analytics"],
                "count": 3
            }
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_schemas()
        except Exception as e:
            return {"error": f"Failed to list schemas: {e!s}"}

    @mcp.tool()
    def redshift_list_tables(schema: str) -> dict:
        """
        List all tables in a Redshift schema.

        Args:
            schema: Schema name (e.g., "public", "sales")

        Returns:
            Dict with list of tables and their types or error

        Example:
            {
                "schema": "public",
                "tables": [
                    {"name": "customers", "type": "BASE TABLE"},
                    {"name": "orders", "type": "BASE TABLE"}
                ],
                "count": 2
            }
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_tables(schema)
        except Exception as e:
            return {"error": f"Failed to list tables: {e!s}"}

    @mcp.tool()
    def redshift_get_table_schema(schema: str, table: str) -> dict:
        """
        Get detailed schema and metadata for a Redshift table.

        Args:
            schema: Schema name (e.g., "public")
            table: Table name (e.g., "customers")

        Returns:
            Dict with column definitions or error

        Example:
            {
                "schema": "public",
                "table": "customers",
                "columns": [
                    {
                        "name": "customer_id",
                        "type": "integer",
                        "max_length": null,
                        "nullable": false,
                        "default": null
                    },
                    {
                        "name": "email",
                        "type": "character varying",
                        "max_length": 255,
                        "nullable": false,
                        "default": null
                    }
                ],
                "column_count": 2
            }
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_table_schema(schema, table)
        except Exception as e:
            return {"error": f"Failed to get table schema: {e!s}"}

    # --- Query Execution ---

    @mcp.tool()
    def redshift_execute_query(
        sql: str,
        format: Literal["json", "csv"] = "json",  # noqa: A002
        timeout: int = 30,
    ) -> dict:
        """
        Execute a read-only SQL query on Redshift.

        SECURITY NOTE: Only SELECT queries are allowed by default.
        This prevents accidental data modifications.

        Args:
            sql: SQL SELECT query to execute
            format: Output format - "json" (default) or "csv"
            timeout: Query timeout in seconds (default: 30)

        Returns:
            Dict with query results or error

        Example (JSON format):
            {
                "format": "json",
                "columns": ["customer_id", "email", "total_orders"],
                "rows": [
                    {"customer_id": 1, "email": "john@example.com", "total_orders": 5},
                    {"customer_id": 2, "email": "jane@example.com", "total_orders": 3}
                ],
                "row_count": 2,
                "statement_id": "abc-123"
            }

        Example (CSV format):
            {
                "format": "csv",
                "data": "customer_id,email,total_orders\\n1,john@example.com,5\\n...",
                "row_count": 2,
                "statement_id": "abc-123"
            }
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.execute_query(sql, format=format, timeout=timeout)
        except Exception as e:
            return {"error": f"Query execution failed: {e!s}"}

    @mcp.tool()
    def redshift_export_query_results(
        sql: str,
        format: Literal["json", "csv"] = "csv",  # noqa: A002
    ) -> dict:
        """
        Execute a query and export results in a format suitable for downstream workflows.

        This is a convenience wrapper around redshift_execute_query optimized for
        exporting data to files or other systems.

        Args:
            sql: SQL SELECT query to execute
            format: Export format - "csv" (default) or "json"

        Returns:
            Dict with formatted export data or error

        Example:
            {
                "format": "csv",
                "data": "id,name,value\\n1,Product A,100\\n2,Product B,200",
                "row_count": 2,
                "statement_id": "xyz-789"
            }
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.execute_query(sql, format=format, timeout=60)

            if "error" in result:
                return result

            # For JSON format, convert to a string for easier file writing
            if format == "json" and "rows" in result:
                result["data"] = json.dumps(result["rows"], indent=2)

            return result
        except Exception as e:
            return {"error": f"Export failed: {e!s}"}
