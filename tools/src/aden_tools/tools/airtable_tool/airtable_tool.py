"""Airtable Web API integration.

Provides record CRUD and base/table metadata via the Airtable REST API.
Requires AIRTABLE_PAT (Personal Access Token).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

BASE_URL = "https://api.airtable.com/v0"


def _get_headers() -> dict | None:
    """Return auth headers or None if credentials missing."""
    token = os.getenv("AIRTABLE_PAT", "")
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _get(url: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _post(url: str, headers: dict, body: dict) -> dict:
    """Send a POST request."""
    resp = httpx.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _patch(url: str, headers: dict, body: dict) -> dict:
    """Send a PATCH request."""
    resp = httpx.patch(url, headers=headers, json=body, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Airtable tools."""

    @mcp.tool()
    def airtable_list_records(
        base_id: str,
        table_name: str,
        filter_formula: str = "",
        sort_field: str = "",
        sort_direction: str = "asc",
        max_records: int = 100,
        fields: str = "",
    ) -> dict:
        """List records from an Airtable table.

        Args:
            base_id: The Airtable base ID (starts with 'app').
            table_name: Table name or ID.
            filter_formula: Airtable formula to filter records (e.g. "{Status}='Active'").
            sort_field: Field name to sort by.
            sort_direction: Sort direction: 'asc' or 'desc'.
            max_records: Maximum number of records to return (default 100).
            fields: Comma-separated list of field names to include.
        """
        hdrs = _get_headers()
        if hdrs is None:
            return {
                "error": "AIRTABLE_PAT is required",
                "help": "Set AIRTABLE_PAT env var with your Airtable personal access token",
            }
        if not base_id or not table_name:
            return {"error": "base_id and table_name are required"}

        params: dict[str, Any] = {"maxRecords": str(max_records)}
        if filter_formula:
            params["filterByFormula"] = filter_formula
        if sort_field:
            params["sort[0][field]"] = sort_field
            params["sort[0][direction]"] = sort_direction
        if fields:
            for i, f in enumerate(fields.split(",")):
                params[f"fields[{i}]"] = f.strip()

        url = f"{BASE_URL}/{base_id}/{table_name}"
        data = _get(url, hdrs, params)
        if "error" in data:
            return data

        records = data.get("records", [])
        result: dict[str, Any] = {
            "count": len(records),
            "records": [
                {
                    "id": r["id"],
                    "fields": r.get("fields", {}),
                    "created_time": r.get("createdTime"),
                }
                for r in records
            ],
        }
        if "offset" in data:
            result["has_more"] = True
            result["offset"] = data["offset"]
        return result

    @mcp.tool()
    def airtable_get_record(
        base_id: str,
        table_name: str,
        record_id: str,
    ) -> dict:
        """Get a single record from an Airtable table.

        Args:
            base_id: The Airtable base ID (starts with 'app').
            table_name: Table name or ID.
            record_id: The record ID (starts with 'rec').
        """
        hdrs = _get_headers()
        if hdrs is None:
            return {
                "error": "AIRTABLE_PAT is required",
                "help": "Set AIRTABLE_PAT env var with your Airtable personal access token",
            }
        if not base_id or not table_name or not record_id:
            return {"error": "base_id, table_name, and record_id are required"}

        url = f"{BASE_URL}/{base_id}/{table_name}/{record_id}"
        data = _get(url, hdrs)
        if "error" in data:
            return data
        return {
            "id": data["id"],
            "fields": data.get("fields", {}),
            "created_time": data.get("createdTime"),
        }

    @mcp.tool()
    def airtable_create_records(
        base_id: str,
        table_name: str,
        records: str,
        typecast: bool = False,
    ) -> dict:
        """Create records in an Airtable table (up to 10 per request).

        Args:
            base_id: The Airtable base ID (starts with 'app').
            table_name: Table name or ID.
            records: JSON array of objects with "fields" key,
                e.g. '[{"fields": {"Name": "Alice"}}]'.
            typecast: If true, auto-convert values to appropriate field types.
        """
        hdrs = _get_headers()
        if hdrs is None:
            return {
                "error": "AIRTABLE_PAT is required",
                "help": "Set AIRTABLE_PAT env var with your Airtable personal access token",
            }
        if not base_id or not table_name or not records:
            return {"error": "base_id, table_name, and records are required"}

        import json

        try:
            records_obj = json.loads(records)
        except json.JSONDecodeError:
            return {"error": "records must be valid JSON"}
        if not isinstance(records_obj, list) or len(records_obj) == 0:
            return {"error": "records must be a non-empty JSON array"}
        if len(records_obj) > 10:
            return {"error": "maximum 10 records per request"}

        url = f"{BASE_URL}/{base_id}/{table_name}"
        body: dict[str, Any] = {"records": records_obj}
        if typecast:
            body["typecast"] = True

        data = _post(url, hdrs, body)
        if "error" in data:
            return data

        created = data.get("records", [])
        return {
            "result": "created",
            "count": len(created),
            "records": [{"id": r["id"], "fields": r.get("fields", {})} for r in created],
        }

    @mcp.tool()
    def airtable_update_records(
        base_id: str,
        table_name: str,
        records: str,
        typecast: bool = False,
    ) -> dict:
        """Update records in an Airtable table (up to 10 per request).

        Uses PATCH (partial update) - only specified fields are changed.

        Args:
            base_id: The Airtable base ID (starts with 'app').
            table_name: Table name or ID.
            records: JSON array of objects with "id" and "fields" keys,
                e.g. '[{"id": "recXXX", "fields": {"Status": "Done"}}]'.
            typecast: If true, auto-convert values to appropriate field types.
        """
        hdrs = _get_headers()
        if hdrs is None:
            return {
                "error": "AIRTABLE_PAT is required",
                "help": "Set AIRTABLE_PAT env var with your Airtable personal access token",
            }
        if not base_id or not table_name or not records:
            return {"error": "base_id, table_name, and records are required"}

        import json

        try:
            records_obj = json.loads(records)
        except json.JSONDecodeError:
            return {"error": "records must be valid JSON"}
        if not isinstance(records_obj, list) or len(records_obj) == 0:
            return {"error": "records must be a non-empty JSON array"}
        if len(records_obj) > 10:
            return {"error": "maximum 10 records per request"}

        url = f"{BASE_URL}/{base_id}/{table_name}"
        body: dict[str, Any] = {"records": records_obj}
        if typecast:
            body["typecast"] = True

        data = _patch(url, hdrs, body)
        if "error" in data:
            return data

        updated = data.get("records", [])
        return {
            "result": "updated",
            "count": len(updated),
            "records": [{"id": r["id"], "fields": r.get("fields", {})} for r in updated],
        }

    @mcp.tool()
    def airtable_list_bases() -> dict:
        """List all Airtable bases accessible with the current token."""
        hdrs = _get_headers()
        if hdrs is None:
            return {
                "error": "AIRTABLE_PAT is required",
                "help": "Set AIRTABLE_PAT env var with your Airtable personal access token",
            }

        url = f"{BASE_URL}/meta/bases"
        data = _get(url, hdrs)
        if "error" in data:
            return data

        bases = data.get("bases", [])
        return {
            "count": len(bases),
            "bases": [
                {
                    "id": b["id"],
                    "name": b.get("name"),
                    "permission_level": b.get("permissionLevel"),
                }
                for b in bases
            ],
        }

    @mcp.tool()
    def airtable_get_base_schema(
        base_id: str,
    ) -> dict:
        """Get the schema (tables and fields) for an Airtable base.

        Args:
            base_id: The Airtable base ID (starts with 'app').
        """
        hdrs = _get_headers()
        if hdrs is None:
            return {
                "error": "AIRTABLE_PAT is required",
                "help": "Set AIRTABLE_PAT env var with your Airtable personal access token",
            }
        if not base_id:
            return {"error": "base_id is required"}

        url = f"{BASE_URL}/meta/bases/{base_id}/tables"
        data = _get(url, hdrs)
        if "error" in data:
            return data

        tables = data.get("tables", [])
        return {
            "count": len(tables),
            "tables": [
                {
                    "id": t["id"],
                    "name": t.get("name"),
                    "fields": [
                        {
                            "id": f["id"],
                            "name": f.get("name"),
                            "type": f.get("type"),
                        }
                        for f in t.get("fields", [])
                    ],
                }
                for t in tables
            ],
        }
