"""
HubSpot CRM Tool - Manage contacts, companies, and deals via HubSpot API v3.

Supports:
- Private App access tokens (HUBSPOT_ACCESS_TOKEN)
- OAuth2 tokens via the credential store

API Reference: https://developers.hubspot.com/docs/api/crm
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _parse_list_param(value: str | list[str] | None) -> list[str] | None:
    """Parse a parameter that can be a list or a JSON string representation of a list.

    Accepts:
    - list[str]: direct list (already correct format)
    - str: JSON string like '["dealname", "dealstage"]' (LLM may send this)
    - None: no value specified

    Returns:
        Parsed list of strings, or None if input is None/invalid
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return None


HUBSPOT_API_BASE = "https://api.hubapi.com"


class _HubSpotClient:
    """Internal client wrapping HubSpot CRM API v3 calls."""

    def __init__(self, access_token: str):
        self._token = access_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid or expired HubSpot access token"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions. Check your HubSpot app scopes."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "HubSpot rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"HubSpot API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def search_objects(
        self,
        object_type: str,
        query: str = "",
        properties: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search CRM objects."""
        body: dict[str, Any] = {"limit": min(limit, 100)}
        if query:
            body["query"] = query
        if properties:
            body["properties"] = properties

        response = httpx.post(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/{object_type}/search",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_object(
        self,
        object_type: str,
        object_id: str,
        properties: list[str] | None = None,
        associations: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get a single CRM object by ID."""
        params: dict[str, Any] = {}
        if properties:
            params["properties"] = ",".join(properties)
        if associations:
            params["associations"] = ",".join(associations)

        response = httpx.get(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/{object_type}/{object_id}",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_object(
        self,
        object_type: str,
        properties: dict[str, str],
    ) -> dict[str, Any]:
        """Create a CRM object."""
        response = httpx.post(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/{object_type}",
            headers=self._headers,
            json={"properties": properties},
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_object(
        self,
        object_type: str,
        object_id: str,
        properties: dict[str, str],
    ) -> dict[str, Any]:
        """Update a CRM object."""
        response = httpx.patch(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/{object_type}/{object_id}",
            headers=self._headers,
            json={"properties": properties},
            timeout=30.0,
        )
        return self._handle_response(response)

    def delete_object(
        self,
        object_type: str,
        object_id: str,
    ) -> dict[str, Any]:
        """Delete (archive) a CRM object by ID.

        API ref: DELETE /crm/v3/objects/{objectType}/{objectId}
        """
        response = httpx.delete(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/{object_type}/{object_id}",
            headers=self._headers,
            timeout=30.0,
        )
        if response.status_code == 204:
            return {"status": "deleted", "object_type": object_type, "object_id": object_id}
        return self._handle_response(response)

    def list_associations(
        self,
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List associations between CRM objects.

        API ref: GET /crm/v4/objects/{fromObjectType}/{fromObjectId}/associations/{toObjectType}
        """
        params: dict[str, Any] = {"limit": min(limit, 500)}
        response = httpx.get(
            f"{HUBSPOT_API_BASE}/crm/v4/objects/{from_object_type}/{from_object_id}/associations/{to_object_type}",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_association(
        self,
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        to_object_id: str,
        association_category: str = "HUBSPOT_DEFINED",
        association_type_id: int = 0,
    ) -> dict[str, Any]:
        """Create an association between two CRM objects.

        API ref: PUT /crm/v4/objects/{fromObjectType}/{fromObjectId}/
        associations/{toObjectType}/{toObjectId}
        """
        body = [
            {
                "associationCategory": association_category,
                "associationTypeId": association_type_id,
            }
        ]
        response = httpx.put(
            f"{HUBSPOT_API_BASE}/crm/v4/objects/{from_object_type}/{from_object_id}/associations/{to_object_type}/{to_object_id}",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register HubSpot CRM tools with the MCP server."""

    def _get_token(account: str = "") -> str | None:
        """Get HubSpot access token from credential manager or environment."""
        if credentials is not None:
            if account:
                return credentials.get_by_alias("hubspot", account)
            token = credentials.get("hubspot")
            # Defensive check: ensure we get a string, not a complex object
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('hubspot'), got {type(token).__name__}"
                )
            return token
        return os.getenv("HUBSPOT_ACCESS_TOKEN")

    def _get_client(account: str = "") -> _HubSpotClient | dict[str, str]:
        """Get a HubSpot client, or return an error dict if no credentials."""
        token = _get_token(account)
        if not token:
            return {
                "error": "HubSpot credentials not configured",
                "help": (
                    "Set HUBSPOT_ACCESS_TOKEN environment variable "
                    "or configure via credential store"
                ),
            }
        return _HubSpotClient(token)

    # --- Contacts ---

    @mcp.tool()
    def hubspot_search_contacts(
        query: str = "",
        properties: str | list[str] | None = None,
        limit: int = 10,
        account: str = "",
    ) -> dict:
        """
        Search HubSpot contacts.

        Args:
            query: Search query string (searches across name, email, phone, etc.)
            properties: List of properties to return
                (e.g., ["email", "firstname", "lastname", "phone"])
            limit: Maximum number of results (1-100, default 10)

        Returns:
            Dict with search results or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        parsed_properties = _parse_list_param(properties)
        try:
            return client.search_objects(
                "contacts", query, parsed_properties or ["email", "firstname", "lastname"], limit
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_get_contact(
        contact_id: str,
        properties: str | list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Get a HubSpot contact by ID.

        Args:
            contact_id: The HubSpot contact ID
            properties: List of properties to return
                (e.g., ["email", "firstname", "lastname", "phone"])

        Returns:
            Dict with contact data or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        parsed_properties = _parse_list_param(properties)
        try:
            return client.get_object("contacts", contact_id, parsed_properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_create_contact(
        properties: dict[str, str],
        account: str = "",
    ) -> dict:
        """
        Create a new HubSpot contact.

        Args:
            properties: Contact properties
                (e.g., {"email": "j@example.com", "firstname": "Jane"})

        Returns:
            Dict with created contact data or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.create_object("contacts", properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_update_contact(
        contact_id: str,
        properties: dict[str, str],
        account: str = "",
    ) -> dict:
        """
        Update an existing HubSpot contact.

        Args:
            contact_id: The HubSpot contact ID
            properties: Properties to update (e.g., {"phone": "+1234567890"})

        Returns:
            Dict with updated contact data or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.update_object("contacts", contact_id, properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Companies ---

    @mcp.tool()
    def hubspot_search_companies(
        query: str = "",
        properties: str | list[str] | None = None,
        limit: int = 10,
        account: str = "",
    ) -> dict:
        """
        Search HubSpot companies.

        Args:
            query: Search query string (searches across name, domain, etc.)
            properties: List of properties to return (e.g., ["name", "domain", "industry"])
            limit: Maximum number of results (1-100, default 10)

        Returns:
            Dict with search results or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        parsed_properties = _parse_list_param(properties)
        try:
            return client.search_objects(
                "companies", query, parsed_properties or ["name", "domain", "industry"], limit
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_get_company(
        company_id: str,
        properties: str | list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Get a HubSpot company by ID.

        Args:
            company_id: The HubSpot company ID
            properties: List of properties to return (e.g., ["name", "domain", "industry"])

        Returns:
            Dict with company data or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        parsed_properties = _parse_list_param(properties)
        try:
            return client.get_object("companies", company_id, parsed_properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_create_company(
        properties: dict[str, str],
        account: str = "",
    ) -> dict:
        """
        Create a new HubSpot company.

        Args:
            properties: Company properties
                (e.g., {"name": "Acme Inc", "domain": "acme.com"})

        Returns:
            Dict with created company data or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.create_object("companies", properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_update_company(
        company_id: str,
        properties: dict[str, str],
        account: str = "",
    ) -> dict:
        """
        Update an existing HubSpot company.

        Args:
            company_id: The HubSpot company ID
            properties: Properties to update (e.g., {"industry": "Finance"})

        Returns:
            Dict with updated company data or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.update_object("companies", company_id, properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Deals ---

    @mcp.tool()
    def hubspot_search_deals(
        query: str = "",
        properties: str | list[str] | None = None,
        limit: int = 10,
        account: str = "",
    ) -> dict:
        """
        Search HubSpot deals.

        Args:
            query: Search query string (searches across deal name, etc.)
            properties: List of properties to return
                (e.g., ["dealname", "amount", "dealstage"])
            limit: Maximum number of results (1-100, default 10)

        Returns:
            Dict with search results or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        parsed_properties = _parse_list_param(properties)
        try:
            return client.search_objects(
                "deals",
                query,
                parsed_properties
                or [
                    "dealname",
                    "amount",
                    "dealstage",
                    "hs_lastmodifieddate",
                    "notes_last_contacted",
                ],
                limit,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_get_deal(
        deal_id: str,
        properties: str | list[str] | None = None,
        include_associations: str | list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Get a HubSpot deal by ID.

        Args:
            deal_id: The HubSpot deal ID
            properties: List of properties to return
                (e.g., ["dealname", "amount", "dealstage"])
            include_associations: Object types to include associations for
                (e.g., ["contacts"] returns associated contact IDs under
                result.associations.contacts.results)

        Returns:
            Dict with deal data or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        parsed_properties = _parse_list_param(properties)
        parsed_associations = _parse_list_param(include_associations)
        try:
            return client.get_object("deals", deal_id, parsed_properties, parsed_associations)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_create_deal(
        properties: dict[str, str],
        account: str = "",
    ) -> dict:
        """
        Create a new HubSpot deal.

        Args:
            properties: Deal properties
                (e.g., {"dealname": "New Deal", "amount": "10000"})

        Returns:
            Dict with created deal data or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.create_object("deals", properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_update_deal(
        deal_id: str,
        properties: dict[str, str],
        account: str = "",
    ) -> dict:
        """
        Update an existing HubSpot deal.

        Args:
            deal_id: The HubSpot deal ID
            properties: Properties to update
                (e.g., {"amount": "15000", "dealstage": "qualifiedtobuy"})

        Returns:
            Dict with updated deal data or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.update_object("deals", deal_id, properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Delete ---

    @mcp.tool()
    def hubspot_delete_object(
        object_type: str,
        object_id: str,
        account: str = "",
    ) -> dict:
        """
        Delete (archive) a HubSpot CRM object.

        Moves the object to the recycle bin. It can be restored from HubSpot UI
        within 90 days.

        Args:
            object_type: CRM object type ("contacts", "companies", or "deals")
            object_id: The HubSpot object ID to delete
            account: Account alias for multi-account support

        Returns:
            Dict with deletion status or error
        """
        if object_type not in ("contacts", "companies", "deals"):
            return {
                "error": f"Unsupported object_type: {object_type!r}. "
                "Use contacts, companies, or deals."
            }
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.delete_object(object_type, object_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Associations ---

    @mcp.tool()
    def hubspot_list_associations(
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        limit: int = 100,
        account: str = "",
    ) -> dict:
        """
        List associations between HubSpot CRM objects.

        Retrieve objects associated with a given record, e.g. all deals
        linked to a contact, or all contacts linked to a company.

        Args:
            from_object_type: Source object type ("contacts", "companies", or "deals")
            from_object_id: ID of the source object
            to_object_type: Target object type ("contacts", "companies", or "deals")
            limit: Maximum associations to return (1-500, default 100)
            account: Account alias for multi-account support

        Returns:
            Dict with associated object IDs and association types, or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.list_associations(from_object_type, from_object_id, to_object_type, limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def hubspot_create_association(
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        to_object_id: str,
        association_type_id: int = 0,
        account: str = "",
    ) -> dict:
        """
        Create an association between two HubSpot CRM objects.

        Links two records together, e.g. associate a contact with a company
        or a deal with a contact. Common association_type_id values:
        - 1: Contact to Company (primary)
        - 3: Deal to Contact
        - 5: Deal to Company
        Use 0 for the default/primary association type.

        Args:
            from_object_type: Source object type ("contacts", "companies", or "deals")
            from_object_id: ID of the source object
            to_object_type: Target object type ("contacts", "companies", or "deals")
            to_object_id: ID of the target object
            association_type_id: HubSpot association type ID (default 0 for primary)
            account: Account alias for multi-account support

        Returns:
            Dict with association result or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.create_association(
                from_object_type,
                from_object_id,
                to_object_type,
                to_object_id,
                association_type_id=association_type_id,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
