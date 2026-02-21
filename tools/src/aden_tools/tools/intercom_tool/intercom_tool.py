"""
Intercom Tool - Customer messaging, conversations, and support automation.

Supports:
- Access token authentication (INTERCOM_ACCESS_TOKEN)

API Reference: https://developers.intercom.com/docs/references/rest-api/api.intercom.io/
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

INTERCOM_API_BASE = "https://api.intercom.io"


class _IntercomClient:
    """Internal client wrapping Intercom API v2.11 calls."""

    def __init__(self, access_token: str):
        self._token = access_token
        self._admin_id: str | None = None  # lazy-fetched via /me

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Intercom-Version": "2.11",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Intercom access token"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions. Check your Intercom app scopes."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Intercom rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            # Intercom errors: {"type": "error.list", "errors": [...]}
            try:
                errors = response.json().get("errors", [])
                detail = errors[0].get("message", response.text) if errors else response.text
            except Exception:
                detail = response.text
            return {"error": f"Intercom API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def _get_admin_id(self) -> str | dict[str, Any]:
        """Get the current admin ID, fetching from /me on first call."""
        if self._admin_id is not None:
            return self._admin_id
        response = httpx.get(
            f"{INTERCOM_API_BASE}/me",
            headers=self._headers,
            timeout=30.0,
        )
        if response.status_code != 200:
            return self._handle_response(response)
        self._admin_id = str(response.json()["id"])
        return self._admin_id

    # --- Read operations ---

    def search_conversations(self, query: dict[str, Any], limit: int = 20) -> dict[str, Any]:
        """Search conversations using Intercom query syntax."""
        body: dict[str, Any] = {
            "query": query,
            "pagination": {"per_page": min(limit, 150)},
        }
        response = httpx.post(
            f"{INTERCOM_API_BASE}/conversations/search",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Get a single conversation by ID with plaintext message bodies."""
        response = httpx.get(
            f"{INTERCOM_API_BASE}/conversations/{conversation_id}",
            headers=self._headers,
            params={"display_as": "plaintext"},
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_contact(self, contact_id: str) -> dict[str, Any]:
        """Get a single contact by ID."""
        response = httpx.get(
            f"{INTERCOM_API_BASE}/contacts/{contact_id}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def search_contacts(self, query: dict[str, Any], limit: int = 50) -> dict[str, Any]:
        """Search contacts using Intercom query syntax."""
        body: dict[str, Any] = {
            "query": query,
            "pagination": {"per_page": min(limit, 150)},
        }
        response = httpx.post(
            f"{INTERCOM_API_BASE}/contacts/search",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_teams(self) -> dict[str, Any]:
        """List all teams in the workspace."""
        response = httpx.get(
            f"{INTERCOM_API_BASE}/teams",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_tags(self) -> dict[str, Any]:
        """List all tags in the workspace."""
        response = httpx.get(
            f"{INTERCOM_API_BASE}/tags",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    # --- Write operations ---

    def reply_to_conversation(
        self,
        conversation_id: str,
        body: str,
        message_type: str = "comment",
    ) -> dict[str, Any]:
        """Reply to or add a note on a conversation."""
        admin_id = self._get_admin_id()
        if isinstance(admin_id, dict):
            return admin_id
        payload: dict[str, Any] = {
            "type": "admin",
            "admin_id": admin_id,
            "message_type": message_type,
            "body": body,
        }
        response = httpx.post(
            f"{INTERCOM_API_BASE}/conversations/{conversation_id}/reply",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def assign_conversation(
        self,
        conversation_id: str,
        assignee_id: str,
        body: str = "",
    ) -> dict[str, Any]:
        """Assign a conversation to an admin or team."""
        admin_id = self._get_admin_id()
        if isinstance(admin_id, dict):
            return admin_id
        payload: dict[str, Any] = {
            "type": "admin",
            "admin_id": admin_id,
            "assignee_id": assignee_id,
            "message_type": "assignment",
            "body": body,
        }
        response = httpx.post(
            f"{INTERCOM_API_BASE}/conversations/{conversation_id}/parts",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_or_get_tag(self, name: str) -> dict[str, Any]:
        """Create a tag or return existing tag with the same name."""
        response = httpx.post(
            f"{INTERCOM_API_BASE}/tags",
            headers=self._headers,
            json={"name": name},
            timeout=30.0,
        )
        return self._handle_response(response)

    def tag_conversation(
        self,
        conversation_id: str,
        tag_id: str,
    ) -> dict[str, Any]:
        """Attach a tag to a conversation."""
        admin_id = self._get_admin_id()
        if isinstance(admin_id, dict):
            return admin_id
        response = httpx.post(
            f"{INTERCOM_API_BASE}/conversations/{conversation_id}/tags",
            headers=self._headers,
            json={"id": tag_id, "admin_id": admin_id},
            timeout=30.0,
        )
        return self._handle_response(response)

    def tag_contact(
        self,
        contact_id: str,
        tag_id: str,
    ) -> dict[str, Any]:
        """Attach a tag to a contact."""
        response = httpx.post(
            f"{INTERCOM_API_BASE}/contacts/{contact_id}/tags",
            headers=self._headers,
            json={"id": tag_id},
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Intercom tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Intercom access token from credential store or environment."""
        if credentials is not None:
            token = credentials.get("intercom")
            # Defensive check: ensure we get a string, not a complex object
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('intercom'), got {type(token).__name__}"
                )
            return token
        return os.getenv("INTERCOM_ACCESS_TOKEN")

    def _get_client() -> _IntercomClient | dict[str, str]:
        """Get an Intercom client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "Intercom credentials not configured",
                "help": (
                    "Set INTERCOM_ACCESS_TOKEN environment variable "
                    "or configure via credential store"
                ),
            }
        return _IntercomClient(token)

    # --- Conversations ---

    @mcp.tool()
    def intercom_search_conversations(
        status: str | None = None,
        assignee_id: str | None = None,
        tag: str | None = None,
        created_after: str | None = None,
        limit: int = 20,
    ) -> dict:
        """
        Search Intercom conversations with optional filters.

        Args:
            status: Filter by status ("open", "closed", "snoozed")
            assignee_id: Filter by assigned admin/team ID
            tag: Filter by tag name
            created_after: ISO date string — only return conversations
                created after this date (e.g., "2026-01-15")
            limit: Max conversations to return (1-150, default 20)

        Returns:
            Dict with conversation summaries or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if limit < 1 or limit > 150:
            return {"error": "limit must be between 1 and 150"}
        if status and status not in ("open", "closed", "snoozed"):
            return {"error": "status must be 'open', 'closed', or 'snoozed'"}
        try:
            filters: list[dict[str, Any]] = []
            if status:
                filters.append({"field": "state", "operator": "=", "value": status})
            if assignee_id:
                filters.append(
                    {
                        "field": "admin_assignee_id",
                        "operator": "=",
                        "value": assignee_id,
                    }
                )
            if tag:
                # Resolve tag name to ID
                tags_result = client.list_tags()
                if "error" in tags_result:
                    return tags_result
                tag_list = tags_result.get("data", [])
                tag_obj = next((t for t in tag_list if t.get("name") == tag), None)
                if not tag_obj:
                    return {"error": f"Tag not found: {tag}"}
                filters.append(
                    {
                        "field": "tag_ids",
                        "operator": "IN",
                        "value": [tag_obj["id"]],
                    }
                )
            if created_after:
                try:
                    dt = datetime.fromisoformat(created_after)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    ts = int(dt.timestamp())
                except ValueError:
                    return {
                        "error": (
                            "created_after must be a valid ISO date string (e.g., '2026-01-15')"
                        )
                    }
                filters.append({"field": "created_at", "operator": ">", "value": ts})

            # Build query from filters
            if not filters:
                # No filters: return recent conversations
                query: dict[str, Any] = {
                    "field": "created_at",
                    "operator": ">",
                    "value": 0,
                }
            elif len(filters) == 1:
                query = filters[0]
            else:
                query = {"operator": "AND", "value": filters}

            return client.search_conversations(query, limit=limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def intercom_get_conversation(conversation_id: str) -> dict:
        """
        Get full conversation details including message history.

        Args:
            conversation_id: Intercom conversation ID

        Returns:
            Dict with conversation details, messages, and parts
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_conversation(conversation_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Contacts ---

    @mcp.tool()
    def intercom_get_contact(
        contact_id: str | None = None,
        email: str | None = None,
    ) -> dict:
        """
        Get an Intercom contact by ID or email.

        Args:
            contact_id: Intercom contact ID (preferred)
            email: Email address (falls back to search if no ID)

        Returns:
            Dict with contact details, tags, and recent conversation count
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not contact_id and not email:
            return {"error": "Either contact_id or email must be provided"}
        try:
            if contact_id:
                return client.get_contact(contact_id)
            # Fallback: search by email (no direct get-by-email endpoint)
            query = {"field": "email", "operator": "=", "value": email}
            result = client.search_contacts(query, limit=1)
            if "error" in result:
                return result
            contacts = result.get("data", [])
            if not contacts:
                return {"error": f"No contact found with email: {email}"}
            return contacts[0]
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def intercom_search_contacts(query: str, limit: int = 20) -> dict:
        """
        Search contacts by email, name, or custom attributes.

        Args:
            query: Search query string
            limit: Max contacts to return (1-150, default 20)

        Returns:
            Dict with matching contacts or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if limit < 1 or limit > 150:
            return {"error": "limit must be between 1 and 150"}
        try:
            search_query = {
                "operator": "OR",
                "value": [
                    {"field": "email", "operator": "=", "value": query},
                    {"field": "name", "operator": "~", "value": query},
                ],
            }
            return client.search_contacts(search_query, limit=limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Notes, Tags & Assignment ---

    @mcp.tool()
    def intercom_add_note(conversation_id: str, body: str) -> dict:
        """
        Add an internal note to a conversation.

        Args:
            conversation_id: Intercom conversation ID
            body: Note content (supports HTML)

        Returns:
            Dict with note details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.reply_to_conversation(conversation_id, body=body, message_type="note")
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def intercom_add_tag(
        name: str,
        conversation_id: str | None = None,
        contact_id: str | None = None,
    ) -> dict:
        """
        Add a tag to a conversation or contact.

        Args:
            name: Tag name (created if it doesn't exist)
            conversation_id: Tag a conversation
                (mutually exclusive with contact_id)
            contact_id: Tag a contact
                (mutually exclusive with conversation_id)

        Returns:
            Dict with tag details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not conversation_id and not contact_id:
            return {"error": "Either conversation_id or contact_id must be provided"}
        if conversation_id and contact_id:
            return {"error": "Provide conversation_id or contact_id, not both"}
        try:
            # Step 1: create or get tag by name (idempotent)
            tag_result = client.create_or_get_tag(name)
            if "error" in tag_result:
                return tag_result
            tag_id = str(tag_result["id"])
            # Step 2: attach to target
            if conversation_id:
                return client.tag_conversation(conversation_id, tag_id)
            return client.tag_contact(contact_id, tag_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def intercom_assign_conversation(
        conversation_id: str,
        assignee_id: str,
        assignee_type: str = "admin",
        body: str = "",
    ) -> dict:
        """
        Assign a conversation to an admin or team.

        Args:
            conversation_id: Intercom conversation ID
            assignee_id: Admin or team ID to assign to
            assignee_type: "admin" or "team"
            body: Optional note about the assignment

        Returns:
            Dict with updated conversation or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if assignee_type not in ("admin", "team"):
            return {"error": "assignee_type must be 'admin' or 'team'"}
        try:
            return client.assign_conversation(conversation_id, assignee_id, body=body)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def intercom_list_teams() -> dict:
        """List available Intercom teams for conversation routing."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_teams()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
