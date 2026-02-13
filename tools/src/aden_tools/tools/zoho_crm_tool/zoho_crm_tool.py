"""
Zoho CRM Tool - Manage leads, contacts, accounts, deals, and notes via Zoho CRM API v8.

Credentials (refresh flow): we need the usual OAuth three (client_id, client_secret,
refresh_token) plus region. Client ID/secret identify your app; refresh token is the
long-lived "user granted access" token — we use it to get short-lived access tokens
ourselves, so the user never passes an access token. Region is required because
Zoho runs separate datacenters (US, India, EU, etc.); we need to know which OAuth
endpoint to call. User sets ZOHO_ACCOUNTS_DOMAIN (full URL) or ZOHO_REGION (e.g. "in");
we get the API base URL from Zoho's token response. No default region.

API Reference: https://www.zoho.com/crm/developer/docs/api/v8/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

CRM_API_VERSION = "v8"
ZOHO_API_BASE_DEFAULT = "https://www.zohoapis.com"
VALID_MODULES = ("Leads", "Contacts", "Accounts", "Deals")


_SERVERINFO_URL = "https://accounts.zoho.com/oauth/serverinfo"
_region_accounts_cache: dict[str, str] | None = None


def _get_region_accounts_map() -> dict[str, str]:
    """Return region → accounts URL map from Zoho serverinfo.

    Cached after first successful fetch.
    """
    global _region_accounts_cache
    if _region_accounts_cache is not None:
        return _region_accounts_cache
    try:
        resp = httpx.get(_SERVERINFO_URL, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            locations = data.get("locations") if isinstance(data, dict) else None
            if isinstance(locations, dict):
                _region_accounts_cache = {k: v.rstrip("/") for k, v in locations.items()}
                return _region_accounts_cache
    except Exception:
        pass
    _region_accounts_cache = {}
    return _region_accounts_cache


def _get_accounts_domain() -> str | None:
    """Resolve accounts domain from ZOHO_ACCOUNTS_DOMAIN or ZOHO_REGION (exact code)."""
    domain = os.getenv("ZOHO_ACCOUNTS_DOMAIN")
    if domain:
        return domain.rstrip("/")
    region = os.getenv("ZOHO_REGION", "").strip().lower()
    if region:
        return _get_region_accounts_map().get(region)
    return None


def _accounts_domain_from_location(location: str) -> str | None:
    """Resolve accounts domain from a Zoho location code."""
    code = location.strip().lower()
    if not code:
        return None
    return _get_region_accounts_map().get(code)


def _zoho_region_valid_help() -> str:
    """Valid ZOHO_REGION values for help text (from serverinfo when available)."""
    m = _get_region_accounts_map()
    if m:
        return ", ".join(sorted(m.keys()))
    return "in, us, eu, au, jp, uk, sg"


def _exchange_refresh_token() -> str | None:
    """Exchange refresh token for access token.

    User provides: client_id, client_secret, refresh_token, and region (ZOHO_ACCOUNTS_DOMAIN
    or ZOHO_REGION). We do not default region. On success, Zoho returns api_domain in the
    response; we set ZOHO_API_DOMAIN from it so CRM calls hit the correct DC.
    Returns access_token or None if env is missing or exchange fails.
    """
    client_id = os.getenv("ZOHO_CLIENT_ID")
    client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN")
    accounts_domain = _get_accounts_domain()
    if not all([client_id, client_secret, refresh_token, accounts_domain]):
        return None
    accounts_domain = accounts_domain.rstrip("/")
    token_url = f"{accounts_domain}/oauth/v2/token"
    try:
        resp = httpx.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if "error" in data:
            return None
        api_domain = data.get("api_domain")
        if api_domain:
            os.environ["ZOHO_API_DOMAIN"] = api_domain.rstrip("/")
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            return None
        return token
    except Exception:
        return None


class _ZohoCRMClient:
    """Internal client wrapping Zoho CRM API v8 calls."""

    def __init__(self, access_token: str, api_domain: str = ZOHO_API_BASE_DEFAULT):
        self._token = access_token
        self._api_base = f"{api_domain.rstrip('/')}/crm/{CRM_API_VERSION}"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Zoho-oauthtoken {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            return {"error": "Invalid or expired Zoho CRM access token"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions. Check your Zoho CRM app scopes."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Zoho CRM rate limit exceeded. Try again later.", "retriable": True}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Zoho CRM API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def search_records(
        self,
        module: str,
        criteria: str = "",
        word: str = "",
        page: int = 1,
        per_page: int = 200,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search records. v8 Search requires one of: criteria, email, phone, word."""
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 200)}
        if word:
            params["word"] = word
        if criteria:
            params["criteria"] = criteria
        if fields:
            params["fields"] = ",".join(fields)

        response = httpx.get(
            f"{self._api_base}/{module}/search",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_record(self, module: str, record_id: str) -> dict[str, Any]:
        """Get a single record by ID."""
        response = httpx.get(
            f"{self._api_base}/{module}/{record_id}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_record(self, module: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new record."""
        response = httpx.post(
            f"{self._api_base}/{module}",
            headers=self._headers,
            json={"data": [data]},
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_record(self, module: str, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing record."""
        response = httpx.put(
            f"{self._api_base}/{module}/{record_id}",
            headers=self._headers,
            json={"data": [data]},
            timeout=30.0,
        )
        return self._handle_response(response)

    def add_note(
        self,
        parent_module: str,
        parent_id: str,
        note_title: str,
        note_content: str,
    ) -> dict[str, Any]:
        """Add a note to a record. v8 requires Parent_Id as { module: { api_name }, id }."""
        note_data = {
            "Note_Title": note_title,
            "Note_Content": note_content,
            "Parent_Id": {
                "module": {"api_name": parent_module},
                "id": parent_id,
            },
        }
        response = httpx.post(
            f"{self._api_base}/Notes",
            headers=self._headers,
            json={"data": [note_data]},
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Zoho CRM tools with the MCP server."""

    def _get_token() -> str | None:
        if credentials is not None:
            token = credentials.get_key("zoho_crm", "access_token")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    "Expected string from credentials.get_key('zoho_crm', "
                    f"'access_token'), got {type(token).__name__}"
                )
            if token:
                return token
            accounts_domain = credentials.get_key("zoho_crm", "accounts_domain")
            if isinstance(accounts_domain, str) and accounts_domain:
                os.environ["ZOHO_ACCOUNTS_DOMAIN"] = accounts_domain.rstrip("/")
            location = credentials.get_key("zoho_crm", "location")
            if isinstance(location, str) and location:
                domain_from_location = _accounts_domain_from_location(location)
                if domain_from_location:
                    os.environ["ZOHO_ACCOUNTS_DOMAIN"] = domain_from_location
        token = os.getenv("ZOHO_ACCESS_TOKEN")
        if token:
            return token
        return _exchange_refresh_token()

    def _get_api_domain() -> str:
        if credentials is not None:
            api_domain = credentials.get_key("zoho_crm", "api_domain")
            if isinstance(api_domain, str) and api_domain:
                return api_domain.rstrip("/")
        return os.getenv("ZOHO_API_DOMAIN", ZOHO_API_BASE_DEFAULT)

    def _get_client() -> _ZohoCRMClient | dict[str, str]:
        token = _get_token()
        if not token:
            return {
                "error": "Zoho CRM credentials not configured",
                "help": (
                    "Credential store, or ZOHO_ACCESS_TOKEN + ZOHO_API_DOMAIN; or for refresh flow "
                    "set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN and either "
                    "ZOHO_ACCOUNTS_DOMAIN or ZOHO_REGION. ZOHO_REGION must be one of: "
                    + _zoho_region_valid_help()
                    + "."
                ),
            }
        return _ZohoCRMClient(token, _get_api_domain())

    @mcp.tool()
    def zoho_crm_search(
        module: str,
        criteria: str = "",
        page: int = 1,
        per_page: int = 200,
        fields: list[str] | None = None,
        word: str = "",
    ) -> dict:
        """
        Search records in Zoho CRM.

        Args:
            module: Module name (Leads, Contacts, Accounts, Deals)
            criteria: Zoho criteria string, e.g. (Email:equals:test@example.com)
            page: Page number (default 1)
            per_page: Records per page (1-200, default 200)
            fields: Optional list of field API names to return
            word: Optional search word (v8 supports criteria or word)

        Returns:
            Dict with normalized fields and pagination info
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if module not in VALID_MODULES:
            return {"error": f"Invalid module '{module}'. Use one of: {', '.join(VALID_MODULES)}"}
        if not word and not criteria:
            return {"error": "Provide at least one of: word, criteria"}
        try:
            result = client.search_records(
                module, criteria=criteria, word=word, page=page, per_page=per_page, fields=fields
            )
            if "error" in result:
                return result
            records = result.get("data", [])
            info = result.get("info", {})
            current_page = info.get("page", page)
            more_records = bool(info.get("more_records", False))
            return {
                "success": True,
                "id": None,
                "module": module,
                "data": records,
                "records": records,
                "page": current_page,
                "per_page": info.get("per_page", per_page),
                "more_records": more_records,
                "next_page": (current_page + 1) if more_records else None,
                "count": len(records),
                "raw": result,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def zoho_crm_get_record(module: str, id: str) -> dict:
        """
        Get a single record by ID.

        Args:
            module: Module name (Leads, Contacts, Accounts, Deals)
            id: Record ID

        Returns:
            Dict with success, id, module, data
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if module not in VALID_MODULES:
            return {"error": f"Invalid module '{module}'. Use one of: {', '.join(VALID_MODULES)}"}
        try:
            result = client.get_record(module, id)
            if "error" in result:
                return result
            data = result.get("data", [])
            if not data:
                return {"error": f"Record {id} not found in {module}"}
            return {"success": True, "id": id, "module": module, "data": data[0], "raw": result}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def zoho_crm_create_record(module: str, data: dict[str, Any]) -> dict:
        """
        Create a new record.

        Args:
            module: Module name (Leads, Contacts, Accounts, Deals)
            data: Field API name → value (e.g. First_Name, Last_Name, Company)

        Returns:
            Dict with success, id, module, data
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if module not in VALID_MODULES:
            return {"error": f"Invalid module '{module}'. Use one of: {', '.join(VALID_MODULES)}"}
        try:
            result = client.create_record(module, data)
            if "error" in result:
                return result
            created = result.get("data", [])
            if not created:
                return {"error": "Failed to create record"}
            record = created[0]
            return {
                "success": True,
                "id": record.get("details", {}).get("id"),
                "module": module,
                "data": record,
                "raw": result,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def zoho_crm_update_record(module: str, id: str, data: dict[str, Any]) -> dict:
        """
        Update an existing record.

        Args:
            module: Module name (Leads, Contacts, Accounts, Deals)
            id: Record ID
            data: Field API name → value (only fields to update)

        Returns:
            Dict with success, id, module, data
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if module not in VALID_MODULES:
            return {"error": f"Invalid module '{module}'. Use one of: {', '.join(VALID_MODULES)}"}
        try:
            result = client.update_record(module, id, data)
            if "error" in result:
                return result
            updated = result.get("data", [])
            if not updated:
                return {"error": f"Failed to update record {id}"}
            return {"success": True, "id": id, "module": module, "data": updated[0], "raw": result}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def zoho_crm_add_note(
        module: str,
        id: str,
        note_title: str,
        note_content: str,
    ) -> dict:
        """
        Add a note to a record.

        Args:
            module: Parent module (Leads, Contacts, Accounts, Deals)
            id: Parent record ID
            note_title: Title of the note
            note_content: Content of the note

        Returns:
            Dict with success, id, parent_id, parent_module, note_title
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if module not in VALID_MODULES:
            return {"error": f"Invalid module '{module}'. Use one of: {', '.join(VALID_MODULES)}"}
        try:
            result = client.add_note(module, id, note_title, note_content)
            if "error" in result:
                return result
            created = result.get("data", [])
            if not created:
                return {"error": "Failed to create note"}
            note = created[0]
            return {
                "success": True,
                "id": note.get("details", {}).get("id"),
                "module": module,
                "data": {
                    "parent_id": id,
                    "parent_module": module,
                    "note_title": note_title,
                    "note_content": note_content,
                    "note": note,
                },
                "raw": result,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
