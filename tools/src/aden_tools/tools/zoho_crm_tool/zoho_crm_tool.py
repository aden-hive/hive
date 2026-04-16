"""
Zoho CRM Tool - Manage leads, contacts, deals, accounts, and tasks.

Supports:
- Zoho CRM OAuth access token (ZOHO_CRM_ACCESS_TOKEN)
- Optional ZOHO_CRM_DOMAIN for region-specific API (default: zohoapis.com)
- CRUD operations on CRM modules

API Reference: https://www.zoho.com/crm/developer/docs/api/v7/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("zoho_crm")
    return os.getenv("ZOHO_CRM_ACCESS_TOKEN")


def _base_url() -> str:
    domain = os.getenv("ZOHO_CRM_DOMAIN", "www.zohoapis.com")
    return f"https://{domain}/crm/v7"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"}


def _get(endpoint: str, token: str, params: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.get(f"{_base_url()}/{endpoint}", headers=_headers(token), params=params, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your ZOHO_CRM_ACCESS_TOKEN (may need refresh)."}
        if resp.status_code == 204:
            return {"data": []}
        if resp.status_code != 200:
            return {"error": f"Zoho CRM API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Zoho CRM timed out"}
    except Exception as e:
        return {"error": f"Zoho CRM request failed: {e!s}"}


def _post(endpoint: str, token: str, body: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.post(f"{_base_url()}/{endpoint}", headers=_headers(token), json=body or {}, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your ZOHO_CRM_ACCESS_TOKEN."}
        if resp.status_code not in (200, 201):
            return {"error": f"Zoho CRM API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Zoho CRM timed out"}
    except Exception as e:
        return {"error": f"Zoho CRM request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "ZOHO_CRM_ACCESS_TOKEN not set",
        "help": "Generate an OAuth token via https://api-console.zoho.com/",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Zoho CRM tools with the MCP server."""

    @mcp.tool()
    def zoho_crm_list_records(
        module: str,
        fields: str = "",
        page: int = 1,
        per_page: int = 50,
        sort_by: str = "",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """
        List records from a Zoho CRM module.

        Args:
            module: Module name: Leads, Contacts, Deals, Accounts, Tasks, Calls, Events, etc.
            fields: Comma-separated field names to return (optional, empty = all)
            page: Page number (default 1)
            per_page: Records per page (1-200, default 50)
            sort_by: Field to sort by (optional)
            sort_order: asc or desc (default desc)

        Returns:
            Dict with records list and pagination info
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not module:
            return {"error": "module is required (e.g. Leads, Contacts, Deals)"}

        params: dict[str, Any] = {
            "page": page,
            "per_page": max(1, min(per_page, 200)),
        }
        if fields:
            params["fields"] = fields
        if sort_by:
            params["sort_by"] = sort_by
            params["sort_order"] = sort_order

        data = _get(module, token, params)
        if "error" in data:
            return data

        records = data.get("data", [])
        info = data.get("info", {})
        return {
            "module": module,
            "records": records,
            "count": info.get("count", len(records)),
            "more_records": info.get("more_records", False),
            "page": info.get("page", page),
        }

    @mcp.tool()
    def zoho_crm_get_record(
        module: str,
        record_id: str,
    ) -> dict[str, Any]:
        """
        Get a specific record from a Zoho CRM module.

        Args:
            module: Module name (Leads, Contacts, Deals, etc.)
            record_id: Record ID

        Returns:
            Dict with record details
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not module or not record_id:
            return {"error": "module and record_id are required"}

        data = _get(f"{module}/{record_id}", token)
        if "error" in data:
            return data

        records = data.get("data", [])
        if not records:
            return {"error": "Record not found"}
        return {"module": module, "record": records[0]}

    @mcp.tool()
    def zoho_crm_create_record(
        module: str,
        record_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new record in a Zoho CRM module.

        Args:
            module: Module name (Leads, Contacts, Deals, etc.)
            record_data: Dict with field names and values. Common fields:
                         Leads: Last_Name, Company, Email, Phone
                         Contacts: Last_Name, Email, Phone, Account_Name
                         Deals: Deal_Name, Stage, Amount, Closing_Date

        Returns:
            Dict with created record id and status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not module:
            return {"error": "module is required"}
        if not record_data:
            return {"error": "record_data dict is required"}

        body = {"data": [record_data]}
        data = _post(module, token, body)
        if "error" in data:
            return data

        results = data.get("data", [])
        if not results:
            return {"error": "Failed to create record"}

        first = results[0]
        details = first.get("details", {})
        return {
            "id": details.get("id", ""),
            "status": first.get("status", ""),
            "message": first.get("message", ""),
        }

    @mcp.tool()
    def zoho_crm_search_records(
        module: str,
        criteria: str = "",
        email: str = "",
        phone: str = "",
        word: str = "",
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """
        Search records in a Zoho CRM module.

        Args:
            module: Module name (Leads, Contacts, Deals, etc.)
            criteria: Criteria string e.g. "(Last_Name:equals:Smith)"
            email: Search by email address (shortcut)
            phone: Search by phone number (shortcut)
            word: Search keyword across all fields
            page: Page number (default 1)
            per_page: Results per page (1-200, default 50)

        Returns:
            Dict with matching records
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not module:
            return {"error": "module is required"}
        if not (criteria or email or phone or word):
            return {"error": ("At least one search parameter is required (criteria, email, phone, or word)")}

        params: dict[str, Any] = {
            "page": page,
            "per_page": max(1, min(per_page, 200)),
        }
        if criteria:
            params["criteria"] = criteria
        if email:
            params["email"] = email
        if phone:
            params["phone"] = phone
        if word:
            params["word"] = word

        data = _get(f"{module}/search", token, params)
        if "error" in data:
            return data

        records = data.get("data", [])
        return {
            "module": module,
            "results": records,
            "count": len(records),
        }

    @mcp.tool()
    def zoho_crm_list_modules() -> dict[str, Any]:
        """
        List all available modules in the Zoho CRM account.

        Returns:
            Dict with modules list (api_name, module_name, plural_label)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _get("settings/modules", token)
        if "error" in data:
            return data

        modules = []
        for m in data.get("modules", []):
            modules.append(
                {
                    "api_name": m.get("api_name", ""),
                    "module_name": m.get("module_name", ""),
                    "plural_label": m.get("plural_label", ""),
                    "editable": m.get("editable", False),
                }
            )
        return {"modules": modules}

    @mcp.tool()
    def zoho_crm_add_note(
        module: str,
        record_id: str,
        title: str,
        content: str,
    ) -> dict[str, Any]:
        """
        Add a note to a record in Zoho CRM.

        Args:
            module: Module name (Leads, Contacts, Deals, etc.)
            record_id: Record ID to attach the note to
            title: Note title
            content: Note content

        Returns:
            Dict with created note id and status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not module or not record_id:
            return {"error": "module and record_id are required"}
        if not content:
            return {"error": "content is required"}

        body = {"data": [{"Note_Title": title, "Note_Content": content}]}
        data = _post(f"{module}/{record_id}/Notes", token, body)
        if "error" in data:
            return data

        results = data.get("data", [])
        if not results:
            return {"error": "Failed to create note"}

        first = results[0]
        return {
            "id": first.get("details", {}).get("id", ""),
            "status": first.get("status", ""),
        }
