"""Snowflake SQL REST API integration.

Provides SQL statement execution via the Snowflake REST API v2.
Requires SNOWFLAKE_ACCOUNT, SNOWFLAKE_TOKEN, and optionally
SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP


def _get_config() -> tuple[str, dict] | dict:
    """Return (base_url, headers) or error dict."""
    account = os.getenv("SNOWFLAKE_ACCOUNT", "").strip()
    token = os.getenv("SNOWFLAKE_TOKEN", "").strip()
    if not account or not token:
        return {
            "error": "SNOWFLAKE_ACCOUNT and SNOWFLAKE_TOKEN are required",
            "help": "Set SNOWFLAKE_ACCOUNT and SNOWFLAKE_TOKEN environment variables",
        }
    base_url = f"https://{account}.snowflakecomputing.com/api/v2/statements"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "aden-tools/1.0",
        "X-Snowflake-Authorization-Token-Type": os.getenv("SNOWFLAKE_TOKEN_TYPE", "OAUTH"),
    }
    return base_url, headers


def _format_results(data: dict) -> dict:
    """Format Snowflake result set into a readable dict."""
    meta = data.get("resultSetMetaData", {})
    columns = [col.get("name") for col in meta.get("rowType", [])]
    rows = data.get("data", [])
    return {
        "statement_handle": data.get("statementHandle"),
        "status": "complete",
        "num_rows": meta.get("numRows", len(rows)),
        "columns": columns,
        "rows": rows[:100],
        "truncated": len(rows) > 100,
    }


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Snowflake tools."""

    @mcp.tool()
    def snowflake_execute_sql(
        statement: str,
        database: str = "",
        schema: str = "",
        warehouse: str = "",
        timeout: int = 60,
    ) -> dict:
        """Execute a SQL statement on Snowflake and return results.

        Args:
            statement: SQL statement to execute.
            database: Database name (overrides SNOWFLAKE_DATABASE env var).
            schema: Schema name (overrides SNOWFLAKE_SCHEMA env var).
            warehouse: Warehouse name (overrides SNOWFLAKE_WAREHOUSE env var).
            timeout: Query timeout in seconds (default 60).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if not statement.strip():
            return {"error": "statement is required"}

        body: dict[str, Any] = {
            "statement": statement,
            "timeout": timeout,
        }
        db = database or os.getenv("SNOWFLAKE_DATABASE", "")
        sch = schema or os.getenv("SNOWFLAKE_SCHEMA", "")
        wh = warehouse or os.getenv("SNOWFLAKE_WAREHOUSE", "")
        if db:
            body["database"] = db
        if sch:
            body["schema"] = sch
        if wh:
            body["warehouse"] = wh

        resp = httpx.post(base_url, headers=headers, json=body, timeout=max(timeout + 10, 30))
        if resp.status_code == 200:
            return _format_results(resp.json())
        if resp.status_code == 202:
            data = resp.json()
            return {
                "statement_handle": data.get("statementHandle"),
                "status": "running",
                "message": data.get("message", "Asynchronous execution in progress"),
            }
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}

    @mcp.tool()
    def snowflake_get_statement_status(statement_handle: str) -> dict:
        """Check the status of a Snowflake SQL statement and fetch results.

        Args:
            statement_handle: The statement handle from snowflake_execute_sql.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if not statement_handle:
            return {"error": "statement_handle is required"}

        resp = httpx.get(f"{base_url}/{statement_handle}", headers=headers, timeout=30)
        if resp.status_code == 200:
            return _format_results(resp.json())
        if resp.status_code == 202:
            data = resp.json()
            return {
                "statement_handle": data.get("statementHandle"),
                "status": "running",
                "message": data.get("message", "Still executing"),
            }
        if resp.status_code == 422:
            data = resp.json()
            return {
                "statement_handle": data.get("statementHandle"),
                "status": "error",
                "message": data.get("message", "Query failed"),
            }
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}

    @mcp.tool()
    def snowflake_cancel_statement(statement_handle: str) -> dict:
        """Cancel a running Snowflake SQL statement.

        Args:
            statement_handle: The statement handle to cancel.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if not statement_handle:
            return {"error": "statement_handle is required"}

        resp = httpx.post(f"{base_url}/{statement_handle}/cancel", headers=headers, timeout=30)
        if resp.status_code == 200:
            return {"result": "cancelled", "statement_handle": statement_handle}
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
