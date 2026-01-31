"""
Salesforce CRM Tool - Manage Leads, Contacts, Accounts, and Opportunities via REST API.

Supports:
- Access token + instance URL (SALESFORCE_ACCESS_TOKEN, SALESFORCE_INSTANCE_URL)
- Credential store for token/instance

API Reference: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# Default API version; instance URL is set per-request (user provides base e.g. https://na1.salesforce.com)
SALESFORCE_API_VERSION = "v59.0"


class _SalesforceClient:
    """Internal client wrapping Salesforce REST API."""

    def __init__(self, instance_url: str, access_token: str):
        self._base = instance_url.rstrip("/")
        self._token = access_token

    @property
    def _api_path(self) -> str:
        return f"{self._base}/services/data/{SALESFORCE_API_VERSION}"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            return {"error": "Invalid or expired Salesforce access token"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions. Check your Salesforce app scopes."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Salesforce rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                body = response.json()
                if isinstance(body, list) and body:
                    detail = body[0].get("message", response.text)
                elif isinstance(body, dict):
                    detail = body.get("message", response.text)
                else:
                    detail = response.text
            except Exception:
                detail = response.text
            return {"error": f"Salesforce API error (HTTP {response.status_code}): {detail}"}
        if response.status_code == 204:
            return {}
        return response.json()

    def query(self, soql: str) -> dict[str, Any]:
        """Execute SOQL query."""
        response = httpx.get(
            f"{self._api_path}/query",
            headers=self._headers,
            params={"q": soql},
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_record(self, sobject: str, record_id: str, fields: list[str] | None = None) -> dict[str, Any]:
        """Get a single record by ID."""
        if sobject not in _VALID_SOBJECTS:
            return {"error": f"Invalid sobject: {sobject}"}
        err = _validate_record_id(record_id)
        if err:
            return {"error": err}
        params = {}
        if fields:
            params["fields"] = ",".join(_sanitize_field_list(fields))
        response = httpx.get(
            f"{self._api_path}/sobjects/{sobject}/{record_id}",
            headers=self._headers,
            params=params or None,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_record(self, sobject: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a record."""
        if sobject not in _VALID_SOBJECTS:
            return {"error": f"Invalid sobject: {sobject}"}
        response = httpx.post(
            f"{self._api_path}/sobjects/{sobject}",
            headers=self._headers,
            json=data,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_record(self, sobject: str, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update a record."""
        if sobject not in _VALID_SOBJECTS:
            return {"error": f"Invalid sobject: {sobject}"}
        err = _validate_record_id(record_id)
        if err:
            return {"error": err}
        response = httpx.patch(
            f"{self._api_path}/sobjects/{sobject}/{record_id}",
            headers=self._headers,
            json=data,
            timeout=30.0,
        )
        return self._handle_response(response)


# Default field sets for search/get (SOQL-safe)
_DEFAULT_LEAD_FIELDS = ["Id", "Name", "Company", "Email", "Status", "LeadSource"]
_DEFAULT_CONTACT_FIELDS = ["Id", "Name", "Email", "Phone", "AccountId"]
_DEFAULT_ACCOUNT_FIELDS = ["Id", "Name", "Industry", "Phone", "Website"]
_DEFAULT_OPPORTUNITY_FIELDS = ["Id", "Name", "Amount", "StageName", "CloseDate", "AccountId"]

# Allowed sobjects for URL path (prevents path traversal / injection)
_VALID_SOBJECTS = frozenset({"Lead", "Contact", "Account", "Opportunity"})

# Salesforce record IDs are 15 or 18 alphanumeric characters
_RECORD_ID_LEN = (15, 18)


def _validate_record_id(record_id: str) -> str | None:
    """Return None if valid (15 or 18 alphanumeric); else error message."""
    if not record_id or not isinstance(record_id, str):
        return "Record ID is required"
    clean = "".join(c for c in record_id if c.isalnum())
    if clean != record_id:
        return "Record ID must be alphanumeric"
    if len(clean) not in _RECORD_ID_LEN:
        return "Record ID must be 15 or 18 characters"
    return None


def _sanitize_search_query(query: str) -> str:
    """Allow only alphanumeric, spaces, hyphen, underscore to avoid SOQL injection."""
    return "".join(c for c in query if c.isalnum() or c in " -_")[:200].strip()


def _sanitize_field_list(fields: list[str]) -> list[str]:
    """Allow only valid SOQL identifiers (alphanumeric, underscore) to avoid injection."""
    out = []
    for f in fields:
        if isinstance(f, str) and f and all(c.isalnum() or c == "_" for c in f):
            out.append(f)
    return out or ["Id"]


def _build_search_soql(sobject: str, fields: list[str], query: str, limit: int) -> str:
    """Build a simple SOQL search (LIKE on Name for standard objects)."""
    if sobject not in _VALID_SOBJECTS:
        sobject = "Lead"
    safe_fields = _sanitize_field_list(fields) or _DEFAULT_LEAD_FIELDS
    safe_limit = min(max(1, limit), 200)
    fields_str = ", ".join(safe_fields)
    if query:
        safe_query = _sanitize_search_query(query).replace("'", "\\'")
        where = f"WHERE Name LIKE '%{safe_query}%'" if safe_query else ""
    else:
        where = ""
    return f"SELECT {fields_str} FROM {sobject} {where} LIMIT {safe_limit}".replace("  ", " ")


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Salesforce CRM tools with the MCP server."""

    def _get_creds() -> tuple[str | None, str | None]:
        """Get (instance_url, access_token) from credential manager or environment."""
        instance_url = os.getenv("SALESFORCE_INSTANCE_URL")
        token = os.getenv("SALESFORCE_ACCESS_TOKEN")
        if credentials is not None:
            raw = credentials.get("salesforce")
            if raw is not None:
                if isinstance(raw, dict):
                    instance_url = raw.get("instance_url") or instance_url
                    token = raw.get("access_token") or token
                elif isinstance(raw, str):
                    token = raw
        return (instance_url, token)

    def _get_client() -> _SalesforceClient | dict[str, str]:
        instance_url, token = _get_creds()
        if not instance_url or not token:
            return {
                "error": "Salesforce credentials not configured",
                "help": (
                    "Set SALESFORCE_INSTANCE_URL (e.g. https://yourdomain.my.salesforce.com) "
                    "and SALESFORCE_ACCESS_TOKEN, or configure via credential store"
                ),
            }
        return _SalesforceClient(instance_url, token)

    # --- Leads ---

    @mcp.tool()
    def salesforce_search_leads(
        query: str = "",
        fields: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        """
        Search Salesforce leads by name.

        Args:
            query: Search string (matches Name, Company)
            fields: Fields to return (default: Id, Name, Company, Email, Status, LeadSource)
            limit: Max results (1-200, default 10)

        Returns:
            Dict with records or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        soql = _build_search_soql(
            "Lead",
            fields or _DEFAULT_LEAD_FIELDS,
            query,
            limit,
        )
        try:
            return client.query(soql)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_get_lead(lead_id: str, fields: list[str] | None = None) -> dict:
        """Get a Salesforce lead by ID."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_record("Lead", lead_id, fields or _DEFAULT_LEAD_FIELDS)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_create_lead(properties: dict[str, Any]) -> dict:
        """Create a Salesforce lead. Common fields: LastName, Company, Email, Status."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_record("Lead", properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_update_lead(lead_id: str, properties: dict[str, Any]) -> dict:
        """Update a Salesforce lead."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_record("Lead", lead_id, properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Contacts ---

    @mcp.tool()
    def salesforce_search_contacts(
        query: str = "",
        fields: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        """Search Salesforce contacts by name."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        soql = _build_search_soql(
            "Contact",
            fields or _DEFAULT_CONTACT_FIELDS,
            query,
            limit,
        )
        try:
            return client.query(soql)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_get_contact(contact_id: str, fields: list[str] | None = None) -> dict:
        """Get a Salesforce contact by ID."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_record("Contact", contact_id, fields or _DEFAULT_CONTACT_FIELDS)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_create_contact(properties: dict[str, Any]) -> dict:
        """Create a Salesforce contact. Common fields: LastName, Email, AccountId."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_record("Contact", properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_update_contact(contact_id: str, properties: dict[str, Any]) -> dict:
        """Update a Salesforce contact."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_record("Contact", contact_id, properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Accounts ---

    @mcp.tool()
    def salesforce_search_accounts(
        query: str = "",
        fields: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        """Search Salesforce accounts by name."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        soql = _build_search_soql(
            "Account",
            fields or _DEFAULT_ACCOUNT_FIELDS,
            query,
            limit,
        )
        try:
            return client.query(soql)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_get_account(account_id: str, fields: list[str] | None = None) -> dict:
        """Get a Salesforce account by ID."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_record("Account", account_id, fields or _DEFAULT_ACCOUNT_FIELDS)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_create_account(properties: dict[str, Any]) -> dict:
        """Create a Salesforce account. Common fields: Name, Industry, Phone, Website."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_record("Account", properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_update_account(account_id: str, properties: dict[str, Any]) -> dict:
        """Update a Salesforce account."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_record("Account", account_id, properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Opportunities ---

    @mcp.tool()
    def salesforce_search_opportunities(
        query: str = "",
        fields: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        """Search Salesforce opportunities by name."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        soql = _build_search_soql(
            "Opportunity",
            fields or _DEFAULT_OPPORTUNITY_FIELDS,
            query,
            limit,
        )
        try:
            return client.query(soql)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_get_opportunity(opportunity_id: str, fields: list[str] | None = None) -> dict:
        """Get a Salesforce opportunity by ID."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_record(
                "Opportunity", opportunity_id, fields or _DEFAULT_OPPORTUNITY_FIELDS
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_create_opportunity(properties: dict[str, Any]) -> dict:
        """Create a Salesforce opportunity. Common fields: Name, StageName, CloseDate, AccountId."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_record("Opportunity", properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_update_opportunity(opportunity_id: str, properties: dict[str, Any]) -> dict:
        """Update a Salesforce opportunity."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_record("Opportunity", opportunity_id, properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
