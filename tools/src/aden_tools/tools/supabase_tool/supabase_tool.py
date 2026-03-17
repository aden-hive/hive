"""
Supabase Tool - Database queries, auth, and edge function invocation via Supabase REST API.

Supports:
- Supabase anon/service key + project URL
- PostgREST auto-generated REST API for CRUD
- GoTrue auth endpoints for signup/signin
- Edge Functions invocation

API Reference: https://supabase.com/docs/guides/api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_config(credentials: CredentialStoreAdapter | None) -> tuple[str | None, str | None]:
    """Return (anon_key, project_url)."""
    if credentials is not None:
        key = credentials.get("supabase")
    else:
        key = os.getenv("SUPABASE_ANON_KEY")
    url = os.getenv("SUPABASE_URL", "")
    return key, url or None


def _rest_headers(key: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _auth_error() -> dict[str, Any]:
    return {
        "error": "SUPABASE_ANON_KEY or SUPABASE_URL not set",
        "help": "Get your keys at https://supabase.com/dashboard → Project Settings → API",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Supabase tools with the MCP server."""

    # ── Database CRUD (PostgREST) ───────────────────────────────

    @mcp.tool()
    def supabase_select(
        table: str,
        columns: str = "*",
        filters: str = "",
        order: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Query rows from a Supabase table using PostgREST.

        Args:
            table: Table name to query
            columns: Comma-separated column names or * for all (default *)
            filters: PostgREST filter string (e.g. "status=eq.active", "age=gt.18")
                     Multiple filters separated by & (e.g. "status=eq.active&role=eq.admin")
            order: Order by column (e.g. "created_at.desc", "name.asc")
            limit: Max rows to return (1-1000, default 100)
            offset: Number of rows to skip (default 0)

        Returns:
            Dict with table name, rows list, and count
        """
        key, url = _get_config(credentials)
        if not key or not url:
            return _auth_error()
        if not table:
            return {"error": "table is required"}

        limit = max(1, min(limit, 1000))
        params: dict[str, Any] = {"select": columns, "limit": limit, "offset": offset}
        if filters:
            for f in filters.split("&"):
                if "=" in f:
                    k, v = f.split("=", 1)
                    params[k] = v
        if order:
            params["order"] = order

        try:
            resp = httpx.get(
                f"{url}/rest/v1/{table}",
                headers=_rest_headers(key),
                params=params,
                timeout=30.0,
            )
            if resp.status_code != 200:
                return {"error": f"Supabase error {resp.status_code}: {resp.text[:500]}"}
            rows = resp.json()
            return {"table": table, "rows": rows, "count": len(rows)}
        except httpx.TimeoutException:
            return {"error": "Request to Supabase timed out"}
        except Exception as e:
            return {"error": f"Supabase request failed: {e!s}"}

    @mcp.tool()
    def supabase_insert(
        table: str,
        rows: str,
    ) -> dict[str, Any]:
        """
        Insert one or more rows into a Supabase table.

        Args:
            table: Table name to insert into
            rows: JSON string of row data. Single object for one row,
                  or JSON array for multiple rows.
                  Example: '{"name": "Alice", "age": 30}'
                  Example: '[{"name": "Alice"}, {"name": "Bob"}]'

        Returns:
            Dict with table name and inserted rows
        """
        import json as json_mod

        key, url = _get_config(credentials)
        if not key or not url:
            return _auth_error()
        if not table or not rows:
            return {"error": "table and rows are required"}

        try:
            body = json_mod.loads(rows)
        except json_mod.JSONDecodeError as e:
            return {"error": f"Invalid JSON in rows: {e!s}"}

        try:
            resp = httpx.post(
                f"{url}/rest/v1/{table}",
                headers=_rest_headers(key),
                json=body,
                timeout=30.0,
            )
            if resp.status_code not in (200, 201):
                return {"error": f"Supabase error {resp.status_code}: {resp.text[:500]}"}
            return {"table": table, "inserted": resp.json()}
        except httpx.TimeoutException:
            return {"error": "Request to Supabase timed out"}
        except Exception as e:
            return {"error": f"Supabase request failed: {e!s}"}

    @mcp.tool()
    def supabase_update(
        table: str,
        filters: str,
        data: str,
    ) -> dict[str, Any]:
        """
        Update rows in a Supabase table matching the given filters.

        Args:
            table: Table name to update
            filters: PostgREST filter string to match rows (e.g. "id=eq.123")
                     REQUIRED to prevent accidental full-table updates
            data: JSON string of columns to update (e.g. '{"status": "done"}')

        Returns:
            Dict with table name and updated rows
        """
        import json as json_mod

        key, url = _get_config(credentials)
        if not key or not url:
            return _auth_error()
        if not table or not filters or not data:
            return {"error": "table, filters, and data are required"}

        try:
            body = json_mod.loads(data)
        except json_mod.JSONDecodeError as e:
            return {"error": f"Invalid JSON in data: {e!s}"}

        params: dict[str, str] = {}
        for f in filters.split("&"):
            if "=" in f:
                k, v = f.split("=", 1)
                params[k] = v

        try:
            resp = httpx.patch(
                f"{url}/rest/v1/{table}",
                headers=_rest_headers(key),
                params=params,
                json=body,
                timeout=30.0,
            )
            if resp.status_code != 200:
                return {"error": f"Supabase error {resp.status_code}: {resp.text[:500]}"}
            return {"table": table, "updated": resp.json()}
        except httpx.TimeoutException:
            return {"error": "Request to Supabase timed out"}
        except Exception as e:
            return {"error": f"Supabase request failed: {e!s}"}

    @mcp.tool()
    def supabase_delete(
        table: str,
        filters: str,
    ) -> dict[str, Any]:
        """
        Delete rows from a Supabase table matching the given filters.

        Args:
            table: Table name to delete from
            filters: PostgREST filter string to match rows (e.g. "id=eq.123")
                     REQUIRED to prevent accidental full-table deletes

        Returns:
            Dict with table name and deleted rows
        """
        key, url = _get_config(credentials)
        if not key or not url:
            return _auth_error()
        if not table or not filters:
            return {"error": "table and filters are required"}

        params: dict[str, str] = {}
        for f in filters.split("&"):
            if "=" in f:
                k, v = f.split("=", 1)
                params[k] = v

        try:
            headers = _rest_headers(key)
            headers["Prefer"] = "return=representation"
            resp = httpx.delete(
                f"{url}/rest/v1/{table}",
                headers=headers,
                params=params,
                timeout=30.0,
            )
            if resp.status_code != 200:
                return {"error": f"Supabase error {resp.status_code}: {resp.text[:500]}"}
            return {"table": table, "deleted": resp.json()}
        except httpx.TimeoutException:
            return {"error": "Request to Supabase timed out"}
        except Exception as e:
            return {"error": f"Supabase request failed: {e!s}"}

    # ── Auth (GoTrue) ───────────────────────────────────────────

    @mcp.tool()
    def supabase_auth_signup(
        email: str,
        password: str,
    ) -> dict[str, Any]:
        """
        Register a new user via Supabase Auth (GoTrue).

        Args:
            email: User's email address
            password: User's password (min 6 characters)

        Returns:
            Dict with user id, email, and confirmation status
        """
        key, url = _get_config(credentials)
        if not key or not url:
            return _auth_error()
        if not email or not password:
            return {"error": "email and password are required"}
        if len(password) < 6:
            return {"error": "password must be at least 6 characters"}

        try:
            resp = httpx.post(
                f"{url}/auth/v1/signup",
                headers={"apikey": key, "Content-Type": "application/json"},
                json={"email": email, "password": password},
                timeout=30.0,
            )
            if resp.status_code not in (200, 201):
                return {"error": f"Auth error {resp.status_code}: {resp.text[:500]}"}
            data = resp.json()
            user = data.get("user", data)
            return {
                "user_id": user.get("id", ""),
                "email": user.get("email", ""),
                "confirmed": user.get("confirmed_at") is not None,
            }
        except Exception as e:
            return {"error": f"Auth signup failed: {e!s}"}

    @mcp.tool()
    def supabase_auth_signin(
        email: str,
        password: str,
    ) -> dict[str, Any]:
        """
        Sign in a user via Supabase Auth and get an access token.

        Args:
            email: User's email address
            password: User's password

        Returns:
            Dict with access_token, user_id, email, and expires_in
        """
        key, url = _get_config(credentials)
        if not key or not url:
            return _auth_error()
        if not email or not password:
            return {"error": "email and password are required"}

        try:
            resp = httpx.post(
                f"{url}/auth/v1/token?grant_type=password",
                headers={"apikey": key, "Content-Type": "application/json"},
                json={"email": email, "password": password},
                timeout=30.0,
            )
            if resp.status_code != 200:
                return {"error": f"Auth error {resp.status_code}: {resp.text[:500]}"}
            data = resp.json()
            user = data.get("user", {})
            return {
                "access_token": data.get("access_token", ""),
                "user_id": user.get("id", ""),
                "email": user.get("email", ""),
                "expires_in": data.get("expires_in", 0),
            }
        except Exception as e:
            return {"error": f"Auth signin failed: {e!s}"}

    # ── Edge Functions ──────────────────────────────────────────

    @mcp.tool()
    def supabase_edge_invoke(
        function_name: str,
        body: str = "{}",
        method: str = "POST",
    ) -> dict[str, Any]:
        """
        Invoke a Supabase Edge Function.

        Args:
            function_name: Name of the edge function to invoke
            body: JSON string body to send to the function (default "{}")
            method: HTTP method - POST or GET (default POST)

        Returns:
            Dict with status_code and the function's response data
        """
        import json as json_mod

        key, url = _get_config(credentials)
        if not key or not url:
            return _auth_error()
        if not function_name:
            return {"error": "function_name is required"}

        try:
            parsed_body = json_mod.loads(body)
        except json_mod.JSONDecodeError as e:
            return {"error": f"Invalid JSON in body: {e!s}"}

        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        fn_url = f"{url}/functions/v1/{function_name}"

        try:
            if method.upper() == "GET":
                resp = httpx.get(fn_url, headers=headers, timeout=30.0)
            else:
                resp = httpx.post(fn_url, headers=headers, json=parsed_body, timeout=30.0)

            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                response_data = resp.json()
            else:
                response_data = resp.text

            if resp.status_code >= 400:
                return {
                    "error": f"Edge function error {resp.status_code}",
                    "response": response_data,
                }
            return {"status_code": resp.status_code, "response": response_data}
        except httpx.TimeoutException:
            return {"error": "Edge function invocation timed out"}
        except Exception as e:
            return {"error": f"Edge function invocation failed: {e!s}"}
