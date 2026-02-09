"""
Airtable Tool - Read/write bases and records via Airtable Web API.

Supports:
- List bases (optional: list tables in a base)
- List records in a table (with optional filter/sort)
- Create record
- Update record by ID

API Reference: https://airtable.com/developers/web/api/introduction
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

AIRTABLE_API_BASE = "https://api.airtable.com/v0"
MAX_RETRIES = 2
MAX_RETRY_WAIT = 60


class _AirtableClient:
    """Internal client wrapping Airtable Web API calls."""

    def __init__(self, token: str) -> None:
        self._token = token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make HTTP request with retry on 429 rate limit."""
        request_kwargs = {"headers": self._headers, "timeout": 30.0, **kwargs}
        for attempt in range(MAX_RETRIES + 1):
            response = httpx.request(method, url, **request_kwargs)
            if response.status_code == 429 and attempt < MAX_RETRIES:
                try:
                    wait = min(float(response.headers.get("Retry-After", 1)), MAX_RETRY_WAIT)
                except (ValueError, TypeError):
                    wait = min(2**attempt, MAX_RETRY_WAIT)
                time.sleep(wait)
                continue
            return self._handle_response(response)
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Airtable API response."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Airtable token"}
        if response.status_code == 403:
            return {"error": "Access forbidden. Check token permissions."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 422:
            return {"error": f"Airtable validation error: {response.text}"}
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            return {
                "error": f"Airtable rate limit exceeded. Retry after {retry_after}s",
                "retry_after": retry_after,
            }
        if response.status_code >= 400:
            return {"error": f"Airtable API error (HTTP {response.status_code}): {response.text}"}

        try:
            return response.json()
        except Exception as e:
            return {"error": f"Failed to parse response: {e}"}

    def list_bases(self) -> dict[str, Any]:
        """List bases available to the authenticated user."""
        result = self._request_with_retry("GET", f"{AIRTABLE_API_BASE}/meta/bases")
        if "error" in result:
            return result

        bases = result.get("bases", [])
        return {
            "success": True,
            "bases": [
                {
                    "id": b.get("id"),
                    "name": b.get("name"),
                    "permissionLevel": b.get("permissionLevel"),
                }
                for b in bases
            ],
            "count": len(bases),
        }

    def list_tables(self, base_id: str) -> dict[str, Any]:
        """List tables in a base."""
        result = self._request_with_retry("GET", f"{AIRTABLE_API_BASE}/meta/bases/{base_id}/tables")
        if "error" in result:
            return result

        tables = result.get("tables", [])
        return {
            "success": True,
            "base_id": base_id,
            "tables": [{"id": t.get("id"), "name": t.get("name")} for t in tables],
            "count": len(tables),
        }

    def list_records(
        self,
        base_id: str,
        table_id_or_name: str,
        filter_by_formula: str | None = None,
        sort: list[dict[str, str]] | None = None,
        page_size: int = 100,
        max_records: int | None = None,
        offset: str | None = None,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """List records in a table."""
        params: dict[str, Any] = {"pageSize": min(page_size, 100)}
        if filter_by_formula:
            params["filterByFormula"] = filter_by_formula
        if sort:
            params["sort"] = json.dumps(sort)
        if max_records is not None:
            params["maxRecords"] = max_records
        if offset:
            params["offset"] = offset
        if fields:
            params["fields[]"] = fields

        result = self._request_with_retry(
            "GET",
            f"{AIRTABLE_API_BASE}/{base_id}/{table_id_or_name}",
            params=params,
        )
        if "error" in result:
            return result

        records = result.get("records", [])
        offset_val = result.get("offset")
        return {
            "success": True,
            "records": [
                {
                    "id": r.get("id"),
                    "createdTime": r.get("createdTime"),
                    "fields": r.get("fields", {}),
                }
                for r in records
            ],
            "count": len(records),
            "offset": offset_val,
        }

    def create_record(
        self,
        base_id: str,
        table_id_or_name: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a single record."""
        result = self._request_with_retry(
            "POST",
            f"{AIRTABLE_API_BASE}/{base_id}/{table_id_or_name}",
            json={"fields": fields},
        )
        if "error" in result:
            return result

        record = result
        return {
            "success": True,
            "id": record.get("id"),
            "createdTime": record.get("createdTime"),
            "fields": record.get("fields", {}),
        }

    def update_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a record by ID."""
        result = self._request_with_retry(
            "PATCH",
            f"{AIRTABLE_API_BASE}/{base_id}/{table_id_or_name}/{record_id}",
            json={"fields": fields},
        )
        if "error" in result:
            return result

        return {
            "success": True,
            "id": result.get("id"),
            "createdTime": result.get("createdTime"),
            "fields": result.get("fields", {}),
        }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Airtable tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Airtable token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("airtable")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('airtable'), got {type(token).__name__}"
                )
            return token
        return os.getenv("AIRTABLE_API_TOKEN") or os.getenv("AIRTABLE_ACCESS_TOKEN")

    def _get_client() -> _AirtableClient | dict[str, str]:
        """Get an Airtable client or return an error dict."""
        token = _get_token()
        if not token:
            return {
                "error": "Airtable credentials not configured",
                "help": (
                    "Set AIRTABLE_API_TOKEN env var or configure via credential store. "
                    "Get token from https://airtable.com/create/tokens"
                ),
            }
        return _AirtableClient(token)

    @mcp.tool()
    def airtable_list_bases() -> dict:
        """
        List all Airtable bases available to the authenticated user.

        Returns:
            Dict with bases list (id, name, permissionLevel) and count, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_bases()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def airtable_list_tables(base_id: str) -> dict:
        """
        List tables in an Airtable base.

        Args:
            base_id: The base ID (from airtable_list_bases or base URL)

        Returns:
            Dict with tables list (id, name) and count, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_tables(base_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def airtable_list_records(
        base_id: str,
        table_id_or_name: str,
        filter_by_formula: str | None = None,
        sort: list[dict[str, str]] | None = None,
        page_size: int = 100,
        max_records: int | None = None,
        offset: str | None = None,
        fields: list[str] | None = None,
    ) -> dict:
        """
        List records in an Airtable table.

        Args:
            base_id: The base ID
            table_id_or_name: Table name or ID
            filter_by_formula: Optional Airtable formula (e.g. "{Status}='Active'")
            sort: Optional list of {"field": "Name", "direction": "asc"|"desc"}
            page_size: Records per page (max 100)
            max_records: Max total records to return
            offset: Pagination offset from previous response
            fields: Optional list of field names to return

        Returns:
            Dict with records list and count, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_records(
                base_id=base_id,
                table_id_or_name=table_id_or_name,
                filter_by_formula=filter_by_formula,
                sort=sort,
                page_size=page_size,
                max_records=max_records,
                offset=offset,
                fields=fields,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def airtable_create_record(
        base_id: str,
        table_id_or_name: str,
        fields: dict[str, Any],
    ) -> dict:
        """
        Create a record in an Airtable table.

        Args:
            base_id: The base ID
            table_id_or_name: Table name or ID
            fields: Dict of field names to values (e.g. {"Name": "Lead", "Status": "Contacted"})

        Returns:
            Dict with created record id and fields, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_record(
                base_id=base_id,
                table_id_or_name=table_id_or_name,
                fields=fields,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def airtable_update_record(
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict:
        """
        Update a record by ID in an Airtable table.

        Args:
            base_id: The base ID
            table_id_or_name: Table name or ID
            record_id: The record ID (e.g. recXXXXXXXX)
            fields: Dict of field names to new values

        Returns:
            Dict with updated record id and fields, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_record(
                base_id=base_id,
                table_id_or_name=table_id_or_name,
                record_id=record_id,
                fields=fields,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
