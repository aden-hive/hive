"""
PostgreSQL MCP Tool (Read-only)

Provides safe, read-only access to PostgreSQL databases for AI agents via MCP.

Security features:
- SELECT-only enforcement via SQL guard
- Database-level read-only transaction enforcement
- Statement timeout
- SQL hashing for safe logging (no raw query logs)
- CredentialStore integration
- Thread-safe connection pooling
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from contextlib import contextmanager
from typing import Any

import psycopg2 as psycopg
from fastmcp import FastMCP
from psycopg2 import pool, sql as pg_sql

from aden_tools.credentials import CREDENTIAL_SPECS
from aden_tools.credentials.store_adapter import CredentialStoreAdapter

MAX_ROWS = 1000
STATEMENT_TIMEOUT_MS = 3000

MIN_POOL_SIZE = 1
MAX_POOL_SIZE = 10


logger = logging.getLogger(__name__)
_connection_pool: pool.ThreadedConnectionPool | None = None
_pool_database_url: str | None = None


# ============================================================
# SQL GUARD (First-pass validation)
# ============================================================

FORBIDDEN_PATTERN = re.compile(
    r"\b(insert|update|delete|merge|upsert|create|alter|drop|truncate|grant|revoke|"
    r"call|execute|prepare|deallocate|vacuum|analyze)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> str:
    """
    Validate SQL to ensure:
    - Single statement
    - SELECT-only
    - No mutation keywords

    Note: Database-level read-only enforcement is the final authority.
    """
    sql = sql.strip()

    if sql.endswith(";"):
        sql = sql[:-1]

    if ";" in sql:
        raise ValueError("Multiple statements are not allowed")

    if not sql.lower().startswith("select"):
        raise ValueError("Only SELECT queries are allowed")

    if FORBIDDEN_PATTERN.search(sql):
        raise ValueError("Forbidden SQL keyword detected")

    return sql


# ============================================================
# INTROSPECTION SQL
# ============================================================

LIST_SCHEMAS_SQL = """
SELECT schema_name
FROM information_schema.schemata
ORDER BY schema_name
"""

LIST_TABLES_SQL = """
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
"""

DESCRIBE_TABLE_SQL = """
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = %(schema)s
  AND table_name = %(table)s
ORDER BY ordinal_position
"""

# ============================================================
# Pooling
# ============================================================


def _get_pool(database_url: str):
    """
    Retrieve a connection pool for the given PostgreSQL database URL.

    This function lazily creates a connection pool when the first request is made.
    Subsequent requests will reuse the existing connection pool.

    Args:
        database_url: PostgreSQL database URL

    Returns:
        A connection pool object
    """
    global _connection_pool, _pool_database_url
    if _connection_pool is None or _pool_database_url != database_url:
        if _connection_pool is not None:
            _connection_pool.closeall()
        _connection_pool = pool.ThreadedConnectionPool(
            MIN_POOL_SIZE, MAX_POOL_SIZE, dsn=database_url
        )
        _pool_database_url = database_url
    return _connection_pool


@contextmanager
def _get_connection(database_url: str):
    """
    Retrieve a connection from the pool for the given PostgreSQL database URL.

    This function uses a context manager to ensure that the connection is always
    returned to the pool after use. The connection is also rolled back before
    being returned to the pool to prevent leaking any active transactions.

    Args:
        database_url: PostgreSQL database URL

    Yields:
        A connection object
    """
    pool_instance = _get_pool(database_url)
    conn = pool_instance.getconn()

    try:
        # Ensure clean state
        if conn.closed:
            conn = pool_instance.getconn()

        conn.rollback()  # Clear any aborted transaction
        conn.set_session(readonly=True)

        yield conn

    finally:
        try:
            conn.rollback()  # Always rollback before returning to pool
        except Exception:
            pass
        pool_instance.putconn(conn)


# ============================================================
# Helpers
# ============================================================


def _hash_sql(sql: str) -> str:
    """
    Hash a SQL query and return a shortened version of the hash.

    The hash is used to identify cached query results. The shortened hash is
    returned to prevent the hash from growing too large.

    Args:
        sql (str): SQL query to hash

    Returns:
        str: Shortened hash of the SQL query
    """
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:12]


def _error_response(message: str) -> dict:
    """
    Return a standardized error response for the Postgres tool.

    The response will contain an 'error' key with the provided message and a
    'success' key set to False.

    :param message: The error message to include in the response.
    :return: A dictionary containing the error response.
    """
    return {"error": message, "success": False}


def _missing_credential_response() -> dict:
    """
    Return a standardized response for a missing required credential.

    The response will contain an error message with the name of the required
    credential and a help message pointing to the relevant API key instructions.

    :return: A dictionary containing the error message and help instructions.
    :rtype: dict
    """
    spec = CREDENTIAL_SPECS["postgres"]
    return {
        "error": f"Missing required credential: {spec.description}",
        "help": spec.api_key_instructions,
        "success": False,
    }


def _get_database_url(
    credentials: CredentialStoreAdapter | None,
) -> str | None:
    """
    Return a PostgreSQL connection string.

    If `credentials` is provided, it will be queried first.
    If no connection string is found in `credentials`, the `DATABASE_URL`
    environment variable will be checked.

    Parameters:
        credentials (CredentialStoreAdapter | None): Credential store to query.

    Returns:
        str | None: PostgreSQL connection string or None if not found.
    """
    database_url: str | None = None

    if credentials:
        database_url = credentials.get("postgres")

    if not database_url:
        database_url = os.getenv("DATABASE_URL")

    return database_url


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """
    Register PostgreSQL tools with the MCP server.

    Parameters:
        mcp (FastMCP): The FastMCP server instance to register tools with.
        credentials (CredentialStoreAdapter | None): Optional credential store adapter instance.
            If provided, use the credentials to connect to the PostgreSQL database.
            If not provided, fall back to using environment variables.

    Returns:
        None
    """

    @mcp.tool()
    def pg_query(sql: str, params: dict | None = None) -> dict:
        """
        Execute a read-only SELECT query.

        Parameters:
            sql (str): SQL SELECT query
            params (dict, optional): Parameterized query values

        Returns:
            dict:
                columns (list[str])
                rows (list[list[Any]])
                row_count (int)
                duration_ms (int)
                success (bool)
        """
        database_url = _get_database_url(credentials)
        if not database_url:
            return _missing_credential_response()

        start = time.monotonic()
        sql_hash = _hash_sql(sql)

        try:
            sql = validate_sql(sql)
            params = params or {}

            with _get_connection(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SET statement_timeout TO %s",
                        (STATEMENT_TIMEOUT_MS,),
                    )
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
            logger.error(
                "postgres.query.db_error",
                extra={"sql_hash": sql_hash, "error": str(e)},
            )
            return _error_response("Database error while executing query")

        except Exception:
            logger.exception(
                "postgres.query.unexpected_error",
                extra={"sql_hash": sql_hash},
            )
            return _error_response("Unexpected error while executing query")

    @mcp.tool()
    def pg_list_schemas() -> dict:
        """
        List all schemas in the PostgreSQL database.

        Returns:
            dict: A dictionary containing the list of schemas.
                - result (list): A list of schema names.
                - success (bool): Whether the operation succeeded.

        Raises:
            dict: An error dictionary containing information about the failure.
                - error (str): A description of the error.
                - help (str): Optional help text.
        """
        database_url = _get_database_url(credentials)
        if not database_url:
            return _missing_credential_response()

        try:
            with _get_connection(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(LIST_SCHEMAS_SQL)
                    result = [r[0] for r in cur.fetchall()]

            return {"result": result, "success": True}

        except psycopg.Error:
            return _error_response("Failed to list schemas")

    @mcp.tool()
    def pg_list_tables(schema: str | None = None) -> dict:
        """
        List all tables in the database.

        Args:
            schema (str | None): The schema to filter tables by. If None, all tables are returned.

        Returns:
            dict: A dictionary containing the list of tables.
                - result (list): A list of dictionaries, each containing:
                    - schema (str): The schema of the table.
                    - table (str): The name of the table.
                - success (bool): Whether the operation succeeded.
        """
        database_url = _get_database_url(credentials)
        if not database_url:
            return _missing_credential_response()

        try:
            params: dict[str, Any] = {}
            sql = LIST_TABLES_SQL

            if schema:
                sql += " AND table_schema = %(schema)s"
                params["schema"] = schema

            with _get_connection(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()

            result = [{"schema": r[0], "table": r[1]} for r in rows if len(r) >= 2]

            return {"result": result, "success": True}

        except psycopg.Error:
            return _error_response("Failed to list tables")

    @mcp.tool()
    def pg_describe_table(schema: str, table: str) -> dict:
        """
        Describe a PostgreSQL table.

        Args:
            schema (str): The schema of the table.
            table (str): The name of the table.

        Returns:
            dict: A dictionary containing the description of the table.
                - result (list): A list of column descriptions, each containing:
                    - column (str): The column name.
                    - type (str): The column type.
                    - nullable (bool): Whether the column is nullable.
                    - default (str): The column's default value.
                - success (bool): Whether the operation succeeded.

        Raises:
            dict: An error dictionary containing information about the failure.
                - error (str): A description of the error.
                - help (str): Optional help text.
        """
        database_url = _get_database_url(credentials)
        if not database_url:
            return _missing_credential_response()

        try:
            with _get_connection(database_url) as conn:
                with conn.cursor() as cur:
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

            return {"result": result, "success": True}

        except psycopg.Error:
            return _error_response("Failed to describe table")

    @mcp.tool()
    def pg_explain(sql: str) -> dict:
        """
        Explain the execution plan of a query.

        Args:
            sql (str): SQL query to explain

        Returns:
            dict: Execution plan as a list of strings
        """
        database_url = _get_database_url(credentials)
        if not database_url:
            return _missing_credential_response()

        sql_hash = _hash_sql(sql)
        start = time.monotonic()

        try:
            sql = validate_sql(sql)

            with _get_connection(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(pg_sql.SQL("EXPLAIN {}").format(pg_sql.SQL(sql)))
                    plan = [r[0] for r in cur.fetchall()]

            duration_ms = int((time.monotonic() - start) * 1000)

            logger.info(
                "postgres.explain.success",
                extra={
                    "sql_hash": sql_hash,
                    "duration_ms": duration_ms,
                    "plan_lines": len(plan),
                },
            )

            return {"result": plan, "success": True}

        except ValueError as e:
            logger.warning(
                "postgres.explain.validation_error",
                extra={
                    "sql_hash": sql_hash,
                    "error": str(e),
                },
            )
            return _error_response(str(e))

        except psycopg.Error as e:
            logger.error(
                "postgres.explain.db_error",
                extra={
                    "sql_hash": sql_hash,
                    "pgcode": getattr(e, "pgcode", None),
                },
            )
            return _error_response("Failed to explain query")
