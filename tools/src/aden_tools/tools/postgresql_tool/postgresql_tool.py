"""
PostgreSQL Tool - Execute SQL queries and transactions against PostgreSQL.

Supports:
- Credential store integration
- Environment variable fallback
- SSL configuration
- Statement timeout enforcement

Safety features:
- Read-only enforcement in query tool
- Destructive operations (DROP, TRUNCATE, ALTER) blocked
- SQL-level row limit enforcement
- Automatic rollback on transaction failure
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


# ===============================
# Safety Layer
# ===============================

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
    r"\bGRANT\b",
    r"\bREVOKE\b",
]

WRITE_PATTERN = re.compile("|".join(WRITE_KEYWORDS), re.IGNORECASE)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments (-- and /* */)."""
    sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql


def _is_read_only_query(sql: str) -> bool:
    """Check if query is read-only."""
    cleaned = _strip_sql_comments(sql)
    return not bool(WRITE_PATTERN.search(cleaned))


def _has_limit_clause(sql: str) -> bool:
    """Detect if SQL already contains a LIMIT clause."""
    cleaned = _strip_sql_comments(sql)
    return bool(re.search(r"\bLIMIT\b", cleaned, re.IGNORECASE))


# ===============================
# Tool Registration
# ===============================


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register PostgreSQL tools with the MCP server."""

    DEFAULT_TIMEOUT_SECONDS = 30

    # -------------------------------
    # Credential Handling
    # -------------------------------

    def _get_credentials() -> dict[str, Any]:
        """Resolve PostgreSQL credentials from store or environment."""
        if credentials is not None:

            def _safe_get(key: str) -> Any:
                try:
                    return credentials.get(key)
                except KeyError:
                    return None

            return {
                "host": _safe_get("postgres_host"),
                "port": _safe_get("postgres_port"),
                "database": _safe_get("postgres_database"),
                "username": _safe_get("postgres_username"),
                "password": _safe_get("postgres_password"),
                "ssl_mode": _safe_get("postgres_ssl_mode"),
            }

        return {
            "host": os.getenv("POSTGRES_HOST"),
            "port": os.getenv("POSTGRES_PORT", 5432),
            "database": os.getenv("POSTGRES_DATABASE"),
            "username": os.getenv("POSTGRES_USERNAME"),
            "password": os.getenv("POSTGRES_PASSWORD"),
            "ssl_mode": os.getenv("POSTGRES_SSL_MODE", "prefer"),
        }

    def _create_connection(
        creds: dict[str, Any],
        timeout: int,
    ):
        """Create psycopg connection."""
        try:
            import psycopg
        except ImportError:
            raise ImportError(
                "psycopg is required for PostgreSQL tools. "
                "Install it with: pip install psycopg[binary]"
            ) from None

        return psycopg.connect(
            host=creds["host"],
            port=creds["port"],
            dbname=creds["database"],
            user=creds["username"],
            password=creds["password"],
            sslmode=creds.get("ssl_mode", "prefer"),
            connect_timeout=timeout,
        )

    # -------------------------------
    # Tools
    # -------------------------------

    @mcp.tool()
    def run_postgres_query(
        sql: str,
        max_rows: int = 1000,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        """
        Execute a read-only SQL query against PostgreSQL.
        """

        if not _is_read_only_query(sql):
            return {
                "error": "Write operations are not allowed",
                "help": "Use run_postgres_transaction for write operations.",
            }

        if max_rows < 1:
            return {"error": "max_rows must be at least 1"}

        if max_rows > 10000:
            return {
                "error": "max_rows cannot exceed 10000",
                "help": "Use pagination or batch queries for large datasets.",
            }

        try:
            creds = _get_credentials()
            conn = _create_connection(creds, timeout)

            with conn:
                with conn.cursor() as cur:
                    cur.execute(f"SET statement_timeout = {timeout * 1000}")

                    # Enforce SQL-level LIMIT if not already present
                    if _has_limit_clause(sql):
                        final_sql = sql
                    else:
                        final_sql = f"{sql.rstrip(';')} LIMIT {max_rows};"

                    cur.execute(final_sql)

                    rows = cur.fetchall()
                    columns = (
                        [desc[0] for desc in cur.description]
                        if cur.description
                        else []
                    )

                    results = [
                        dict(zip(columns, row))
                        for row in rows
                    ]

                    return {
                        "success": True,
                        "rows": results,
                        "rows_returned": len(results),
                        "query_truncated": not _has_limit_clause(sql)
                        and len(results) == max_rows,
                    }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependency: pip install psycopg[binary]",
            }
        except Exception as e:
            return {"error": f"PostgreSQL query failed: {str(e)}"}

    @mcp.tool()
    def run_postgres_transaction(
        statements: list[str],
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        """
        Execute multiple SQL statements atomically.
        """

        if not statements or not isinstance(statements, list):
            return {"error": "statements must be a non-empty list of SQL strings."}

        destructive_pattern = re.compile(
            r"\b(DROP|TRUNCATE|ALTER)\b",
            re.IGNORECASE,
        )

        try:
            creds = _get_credentials()
            conn = _create_connection(creds, timeout)

            with conn:
                with conn.cursor() as cur:
                    cur.execute(f"SET statement_timeout = {timeout * 1000}")

                    executed_count = 0

                    for sql in statements:
                        cleaned = _strip_sql_comments(sql)
                        if destructive_pattern.search(cleaned):
                            raise ValueError(
                                "Destructive operations are not allowed "
                                "(DROP/TRUNCATE/ALTER blocked)."
                            )

                        cur.execute(sql)
                        executed_count += 1

                    return {
                        "success": True,
                        "statements_executed": executed_count,
                    }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependency: pip install psycopg[binary]",
            }
        except Exception as e:
            return {
                "error": f"Transaction failed and was rolled back: {str(e)}"
            }

    @mcp.tool()
    def list_postgres_tables(
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        """List tables in the public schema."""

        try:
            creds = _get_credentials()
            conn = _create_connection(creds, timeout)

            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                        ORDER BY table_name;
                        """
                    )

                    tables = [row[0] for row in cur.fetchall()]

                    return {
                        "success": True,
                        "tables": tables,
                    }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependency: pip install psycopg[binary]",
            }
        except Exception as e:
            return {"error": f"Failed to list tables: {str(e)}"}

    @mcp.tool()
    def describe_postgres_table(
        table_name: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        """Describe columns for a given table."""

        if not table_name:
            return {"error": "table_name is required"}

        try:
            creds = _get_credentials()
            conn = _create_connection(creds, timeout)

            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_name = %s
                        ORDER BY ordinal_position;
                        """,
                        (table_name,),
                    )

                    columns = [
                        {
                            "column_name": row[0],
                            "data_type": row[1],
                            "is_nullable": row[2],
                        }
                        for row in cur.fetchall()
                    ]

                    return {
                        "success": True,
                        "table_name": table_name,
                        "columns": columns,
                    }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependency: pip install psycopg[binary]",
            }
        except Exception as e:
            return {"error": f"Failed to describe table: {str(e)}"}

    @mcp.tool()
    def postgres_health_check(
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        """Verify PostgreSQL connectivity."""

        try:
            creds = _get_credentials()
            conn = _create_connection(creds, timeout)

            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")

                    return {
                        "success": True,
                        "message": "PostgreSQL connection healthy.",
                    }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependency: pip install psycopg[binary]",
            }
        except Exception as e:
            return {"error": f"Health check failed: {str(e)}"}