"""
BigQuery Tool - Execute SQL queries and explore datasets in Google BigQuery.

Supports:
- Service account authentication via GOOGLE_APPLICATION_CREDENTIALS
- Application Default Credentials (ADC) fallback

Safety features:
- Read-only queries only (INSERT, UPDATE, DELETE, etc. are blocked)
- Configurable row limits to prevent large result sets
- Bytes processed returned for cost awareness
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


def _format_schema(schema: list) -> list[dict[str, str]]:
    """Format BigQuery schema fields to simple dictionaries."""
    return [
        {
            "name": field.name,
            "type": field.field_type,
            "mode": field.mode,
        }
        for field in schema
    ]


def _create_bigquery_client(project_id: str | None = None) -> Any:
    """
    Create a BigQuery client with appropriate credentials.

    Args:
        project_id: Optional project ID override

    Returns:
        BigQuery client instance

    Raises:
        ImportError: If google-cloud-bigquery is not installed
        Exception: If authentication fails
    """
    try:
        from google.cloud import bigquery
    except ImportError:
        raise ImportError(
            "google-cloud-bigquery is required for BigQuery tools. "
            "Install it with: pip install google-cloud-bigquery"
        ) from None

    # Create client - will use ADC if GOOGLE_APPLICATION_CREDENTIALS not set
    if project_id:
        return bigquery.Client(project=project_id)
    else:
        # Let the client infer project from credentials
        return bigquery.Client()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register BigQuery tools with the MCP server."""

    def _get_credentials() -> dict[str, str | None]:
        """Get BigQuery credentials from credential store or environment."""
        if credentials is not None:
            try:
                creds_path = credentials.get("bigquery")
            except KeyError:
                creds_path = None
            try:
                project = credentials.get("bigquery_project")
            except KeyError:
                project = None
            return {
                "credentials_path": creds_path,
                "project_id": project,
            }
        return {
            "credentials_path": os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
            "project_id": os.getenv("BIGQUERY_PROJECT_ID"),
        }

    def _get_client(project_id: str | None = None) -> Any:
        """
        Get a BigQuery client with credentials resolution.

        Args:
            project_id: Optional project ID override

        Returns:
            BigQuery client instance
        """
        creds = _get_credentials()
        effective_project = project_id or creds["project_id"]

        # Set credentials path in environment if provided from credential store
        credentials_path = creds.get("credentials_path")
        if credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        return _create_bigquery_client(effective_project)

    @mcp.tool()
    def run_bigquery_query(
        sql: str,
        project_id: str | None = None,
        max_rows: int = 1000,
    ) -> dict:
        """
        Execute a read-only SQL query against Google BigQuery.

        This tool executes SQL queries and returns the results as structured data.
        Only SELECT queries are allowed - write operations (INSERT, UPDATE, DELETE,
        DROP, CREATE, ALTER, TRUNCATE, MERGE) are blocked for safety.

        Args:
            sql: The SQL query to execute. Must be a read-only query.
            project_id: Google Cloud project ID. Falls back to BIGQUERY_PROJECT_ID
                       env var or credentials default if not provided.
            max_rows: Maximum number of rows to return (default: 1000).
                     Use this to prevent accidentally fetching large result sets.

        Returns:
            Dict with query results:
            - success: True if query executed successfully
            - rows: List of row dictionaries
            - total_rows: Total number of rows in result
            - rows_returned: Number of rows actually returned (may be limited)
            - schema: List of column definitions (name, type, mode)
            - bytes_processed: Bytes scanned by the query (for cost awareness)
            - query_truncated: True if results were truncated due to max_rows

            Or error dict with:
            - error: Error message
            - help: Optional help text

        Example:
            >>> run_bigquery_query(
            ...     sql="SELECT name, COUNT(*) as cnt FROM `project.dataset.users` GROUP BY name",
            ...     max_rows=100
            ... )
            {
                "success": True,
                "rows": [{"name": "Alice", "cnt": 42}, ...],
                "total_rows": 1500,
                "rows_returned": 100,
                "schema": [{"name": "name", "type": "STRING", "mode": "NULLABLE"}, ...],
                "bytes_processed": 1048576,
                "query_truncated": True
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
                "exporting to Cloud Storage.",
            }

        try:
            client = _get_client(project_id)

            # Execute query
            query_job = client.query(sql)
            results = query_job.result()

            # Get total row count
            total_rows = results.total_rows

            # Fetch rows up to max_rows
            rows = []
            for i, row in enumerate(results):
                if i >= max_rows:
                    break
                rows.append(dict(row.items()))

            query_truncated = total_rows > max_rows if total_rows else False

            return {
                "success": True,
                "rows": rows,
                "total_rows": total_rows,
                "rows_returned": len(rows),
                "schema": _format_schema(results.schema),
                "bytes_processed": query_job.total_bytes_processed or 0,
                "query_truncated": query_truncated,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install the dependency by running: pip install google-cloud-bigquery",
            }
        except Exception as e:
            error_msg = str(e)

            # Provide helpful messages for common errors
            if (
                "Could not automatically determine credentials" in error_msg
                or "default credentials were not found" in error_msg.lower()
            ):  # noqa: E501
                return {
                    "error": "BigQuery authentication failed",
                    "help": "Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON path, "
                    "or run 'gcloud auth application-default login' for local development.",
                }
            if "Permission" in error_msg and "denied" in error_msg.lower():
                return {
                    "error": f"BigQuery permission denied: {error_msg}",
                    "help": "Ensure your service account has the 'BigQuery Data Viewer' "
                    "and 'BigQuery Job User' roles.",
                }
            if "Not found" in error_msg:
                return {
                    "error": f"BigQuery resource not found: {error_msg}",
                    "help": "Check that the project, dataset, and table names are correct.",
                }

            return {"error": f"BigQuery query failed: {error_msg}"}

    @mcp.tool()
    def describe_dataset(
        dataset_id: str,
        project_id: str | None = None,
    ) -> dict:
        """
        Describe a BigQuery dataset, listing its tables and their schemas.

        Use this tool to explore dataset structure before writing queries.
        Returns table names, types, row counts, and column definitions.

        Args:
            dataset_id: The BigQuery dataset ID to describe (e.g., "my_dataset").
                       Do not include the project ID prefix.
            project_id: Google Cloud project ID. Falls back to BIGQUERY_PROJECT_ID
                       env var or credentials default if not provided.

        Returns:
            Dict with dataset information:
            - success: True if operation succeeded
            - dataset_id: The dataset ID
            - project_id: The resolved project ID
            - tables: List of table information, each containing:
                - table_id: Table name
                - type: Table type (TABLE, VIEW, EXTERNAL, etc.)
                - row_count: Number of rows (None for views)
                - size_bytes: Table size in bytes (None for views)
                - columns: List of column definitions (name, type, mode)

            Or error dict with:
            - error: Error message
            - help: Optional help text

        Example:
            >>> describe_dataset("my_dataset")
            {
                "success": True,
                "dataset_id": "my_dataset",
                "project_id": "my-project",
                "tables": [
                    {
                        "table_id": "users",
                        "type": "TABLE",
                        "row_count": 50000,
                        "size_bytes": 10485760,
                        "columns": [
                            {"name": "id", "type": "INTEGER", "mode": "REQUIRED"},
                            {"name": "email", "type": "STRING", "mode": "NULLABLE"}
                        ]
                    }
                ]
            }
        """
        if not dataset_id or not dataset_id.strip():
            return {"error": "dataset_id is required"}

        try:
            client = _get_client(project_id)

            # Get dataset reference
            dataset_ref = client.dataset(dataset_id)

            # List tables in the dataset
            tables_list = list(client.list_tables(dataset_ref))

            tables_info = []
            for table_item in tables_list:
                # Get full table metadata
                table = client.get_table(table_item.reference)

                table_info = {
                    "table_id": table.table_id,
                    "type": table.table_type,
                    "row_count": table.num_rows,
                    "size_bytes": table.num_bytes,
                    "columns": _format_schema(table.schema) if table.schema else [],
                }
                tables_info.append(table_info)

            return {
                "success": True,
                "dataset_id": dataset_id,
                "project_id": client.project,
                "tables": tables_info,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install the dependency by running: pip install google-cloud-bigquery",
            }
        except Exception as e:
            error_msg = str(e)

            if (
                "Could not automatically determine credentials" in error_msg
                or "default credentials were not found" in error_msg.lower()
            ):  # noqa: E501
                return {
                    "error": "BigQuery authentication failed",
                    "help": "Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON path, "
                    "or run 'gcloud auth application-default login' for local development.",
                }
            if "Not found" in error_msg:
                return {
                    "error": f"Dataset not found: {dataset_id}",
                    "help": "Check that the dataset exists and you have access to it. "
                    f"Full error: {error_msg}",
                }
            if "Permission" in error_msg and "denied" in error_msg.lower():
                return {
                    "error": f"Permission denied for dataset: {dataset_id}",
                    "help": "Ensure your service account has the 'BigQuery Data Viewer' role.",
                }

            return {"error": f"Failed to describe dataset: {error_msg}"}
