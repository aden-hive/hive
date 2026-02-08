"""
PostgreSQL MCP Tool (Read-only)

Provides safe, read-only access to PostgreSQL for agents via MCP.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import psycopg
from fastmcp import FastMCP

from .db.connection import get_connection
from .security.sql_guard import validate_sql
from .sql.introspection import (
    DESCRIBE_TABLE_SQL,
    LIST_SCHEMAS_SQL,
    LIST_TABLES_SQL,
)

MAX_ROWS = 1000
STATEMENT_TIMEOUT_MS = 3000

logger = logging.getLogger(__name__)



def _hash_sql(sql: str) -> str:
    """Hash SQL so we never log raw queries."""
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:12]


def _error_response(message: str) -> dict:
    """Standardized MCP error payload."""
    return {
        "error": message,
        "success": False,
    }


def register_tools(mcp: FastMCP) -> None:
    """
    Register PostgreSQL read-only tools with the MCP server.
    """
    @mcp.tool()
    def pg_query(sql: str, params: dict | None = None) -> dict:
        """
        Safely execute a PostgreSQL query with parameterized inputs.

        This tool executes a read-only PostgreSQL query with parameterized inputs.
        It returns a dictionary containing the column names, rows, row count, and
        execution duration in milliseconds.

        Parameters:
            sql (str): SQL query to execute
            params (dict | None): Dictionary of parameter values (optional)

        Returns:
            dict: {
                "columns": list[str], column names
                "rows": list[list[Any]], query results
                "row_count": int, number of rows returned
                "max_rows": int, maximum number of rows to return
                "duration_ms": int, execution duration in milliseconds
                "success": bool, success status
            }

        Raises:
            ValueError: If the query is invalid or missing required parameters
            psycopg.errors.QueryCanceled: If the query timed out
            psycopg.Error: If a database-level error occurred
            Exception: If an unexpected error occurred
        """
        start = time.monotonic()
        sql_hash = _hash_sql(sql)

        try:
            sql = validate_sql(sql)
            params = params or {}

            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
                cur.execute(sql, params)

                columns = [d.name for d in cur.description]
                rows = cur.fetchmany(MAX_ROWS)

            duration_ms = int((time.monotonic() - start) * 1000)

            logger.info(
                "postgres.query.success",
                extra={
                    "sql_hash": sql_hash,
                    "row_count": len(rows),
                    "duration_ms": duration_ms,
                },
            )

            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "max_rows": MAX_ROWS,
                "duration_ms": duration_ms,
                "success": True,
            }

        except ValueError as e:
            logger.warning(
                "postgres.query.validation_error",
                extra={"sql_hash": sql_hash, "error": str(e)},
            )
            return _error_response(str(e))

        except psycopg.errors.QueryCanceled:
            logger.warning(
                "postgres.query.timeout",
                extra={"sql_hash": sql_hash},
            )
            return _error_response("Query timed out")

        except psycopg.Error as e:
            # Database-level errors (sanitized)
            logger.error(
                "postgres.query.db_error",
                extra={"sql_hash": sql_hash, "pgcode": e.pgcode},
            )
            return _error_response("Database error while executing query")

        except Exception:
            # Absolute last-resort guard
            logger.exception(
                "postgres.query.unexpected_error",
                extra={"sql_hash": sql_hash},
            )
            return _error_response("Unexpected error while executing query")

    @mcp.tool()
    def pg_list_schemas() -> dict:
        """
        List all schemas in the database.

        Returns:
            dict with a list of schema names and success status
        """
        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(LIST_SCHEMAS_SQL)
                result = [r[0] for r in cur.fetchall()]

            logger.info(
                "postgres.list_schemas.success",
                extra={"count": len(result)},
            )

            return {"result": result, "success": True}

        except psycopg.Error:
            logger.exception("postgres.list_schemas.db_error")
            return _error_response("Failed to list schemas")

    @mcp.tool()
    def pg_list_tables(schema: str | None = None) -> dict:
        """
        List all tables in the database.

        Args:
            schema: str, Optional. Filter results to a specific schema.

        Returns:
            dict: MCP response with a list of dictionaries containing the schema and table names.
        """
        try:
            params: dict[str, Any] = {}
            sql = LIST_TABLES_SQL

            if schema:
                sql += " AND table_schema = %(schema)s"
                params["schema"] = schema

            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

            result = [{"schema": r[0], "table": r[1]} for r in rows]

            logger.info(
                "postgres.list_tables.success",
                extra={"schema": schema, "count": len(result)},
            )

            return {"result": result, "success": True}

        except psycopg.Error:
            logger.exception("postgres.list_tables.db_error")
            return _error_response("Failed to list tables")

    @mcp.tool()
    def pg_describe_table(schema: str, table: str) -> dict:
        """
        Describe a table in the database.

        Args:
            schema: str, Schema name
            table: str, Table name

        Returns:
            dict with the table description or error
        """
        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    DESCRIBE_TABLE_SQL,
                    {"schema": schema, "table": table},
                )
                rows = cur.fetchall()

            result = [
                {
                    "column": r[0],
                    "type": r[1],
                    "nullable": r[2],
                    "default": r[3],
                }
                for r in rows
            ]

            logger.info(
                "postgres.describe_table.success",
                extra={"schema": schema, "table": table},
            )

            return {"result": result, "success": True}

        except psycopg.Error:
            logger.exception("postgres.describe_table.db_error")
            return _error_response("Failed to describe table")

    @mcp.tool()
    def pg_explain(sql: str) -> dict:
        """
        Explain the execution plan for a given SQL query.

        Args:
            sql: str, SQL query to explain

        Returns:
            dict with the execution plan and success status
        """
        sql_hash = _hash_sql(sql)

        try:
            sql = validate_sql(sql)

            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(f"EXPLAIN {sql}")
                plan = [r[0] for r in cur.fetchall()]

            logger.info(
                "postgres.explain.success",
                extra={"sql_hash": sql_hash},
            )

            return {"result": plan, "success": True}

        except ValueError as e:
            logger.warning(
                "postgres.explain.validation_error",
                extra={"sql_hash": sql_hash, "error": str(e)},
            )
            return _error_response(str(e))

        except psycopg.Error:
            logger.exception(
                "postgres.explain.db_error",
                extra={"sql_hash": sql_hash},
            )
            return _error_response("Failed to explain query")
