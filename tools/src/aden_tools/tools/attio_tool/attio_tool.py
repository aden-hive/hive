"""
Attio Tool - Manage CRM records, lists, tasks, and members via Attio V2 REST API.

Supports:
- Personal API Keys (ATTIO_API_KEY)
- OAuth2 tokens via the credential store

API Reference: https://developers.attio.com/reference
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

ATTIO_API_BASE = "https://api.attio.com/v2"


class _AttioClient:
    """Internal client wrapping Attio V2 REST API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request against the Attio API."""
        response = httpx.request(
            method,
            f"{ATTIO_API_BASE}{path}",
            headers=self._headers,
            json=json_body,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 204:
            return {"success": True}
        if response.status_code == 401:
            return {"error": "Invalid or expired Attio API key"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions. Check your Attio API key scopes."}
        if response.status_code == 429:
            return {"error": "Attio rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Attio API error (HTTP {response.status_code}): {detail}"}

        return response.json()

    # --- Records ---

    def list_records(
        self,
        object_handle: str,
        limit: int = 50,
        offset: int = 0,
        filter_data: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """List and filter records within a specific object."""
        body: dict[str, Any] = {"limit": limit, "offset": offset}
        if filter_data:
            body["filter"] = filter_data
        if sorts:
            body["sorts"] = sorts

        result = self._request("POST", f"/objects/{object_handle}/records/query", json_body=body)
        if "error" in result:
            return result
        return {
            "records": result.get("data", []),
            "total": len(result.get("data", [])),
        }

    def get_record(self, object_handle: str, record_id: str) -> dict[str, Any]:
        """Get a single record by ID."""
        result = self._request("GET", f"/objects/{object_handle}/records/{record_id}")
        if "error" in result:
            return result
        return result.get("data", result)

    def create_record(
        self,
        object_handle: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new record."""
        body = {"data": {"values": values}}
        result = self._request("POST", f"/objects/{object_handle}/records", json_body=body)
        if "error" in result:
            return result
        return result.get("data", result)

    def update_record(
        self,
        object_handle: str,
        record_id: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an existing record (PATCH - appends multiselect values)."""
        body = {"data": {"values": values}}
        result = self._request(
            "PATCH", f"/objects/{object_handle}/records/{record_id}", json_body=body
        )
        if "error" in result:
            return result
        return result.get("data", result)

    def assert_record(
        self,
        object_handle: str,
        matching_attribute: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """Upsert a record. If matching attribute finds a record, updates it; otherwise creates."""
        body = {"data": {"values": values}}
        result = self._request(
            "PUT",
            f"/objects/{object_handle}/records",
            json_body=body,
            params={"matching_attribute": matching_attribute},
        )
        if "error" in result:
            return result
        return result.get("data", result)

    # --- Lists ---

    def list_lists(self) -> dict[str, Any]:
        """List all lists in the workspace."""
        result = self._request("GET", "/lists")
        if "error" in result:
            return result
        return {
            "lists": result.get("data", []),
            "total": len(result.get("data", [])),
        }

    def get_entries(
        self,
        list_id: str,
        limit: int = 50,
        offset: int = 0,
        filter_data: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """List entries in a specific list."""
        body: dict[str, Any] = {"limit": limit, "offset": offset}
        if filter_data:
            body["filter"] = filter_data
        if sorts:
            body["sorts"] = sorts

        result = self._request("POST", f"/lists/{list_id}/entries/query", json_body=body)
        if "error" in result:
            return result
        return {
            "entries": result.get("data", []),
            "total": len(result.get("data", [])),
        }

    def create_entry(
        self,
        list_id: str,
        parent_record_id: str,
        parent_object: str = "people",
        entry_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a record to a list."""
        body: dict[str, Any] = {
            "data": {
                "parent_record_id": parent_record_id,
                "parent_object": parent_object,
            }
        }
        if entry_values:
            body["data"]["entry_values"] = entry_values

        result = self._request("POST", f"/lists/{list_id}/entries", json_body=body)
        if "error" in result:
            return result
        return result.get("data", result)

    def delete_entry(self, list_id: str, entry_id: str) -> dict[str, Any]:
        """Remove an entry from a list."""
        return self._request("DELETE", f"/lists/{list_id}/entries/{entry_id}")

    # --- Tasks ---

    def create_task(
        self,
        content: str,
        linked_records: list[dict[str, Any]] | None = None,
        assignees: list[dict[str, Any]] | None = None,
        deadline_at: str | None = None,
        is_completed: bool = False,
    ) -> dict[str, Any]:
        """Create a task linked to records."""
        data: dict[str, Any] = {
            "content": content,
            "format": "plaintext",
            "is_completed": is_completed,
        }
        if linked_records:
            data["linked_records"] = linked_records
        if assignees:
            data["assignees"] = assignees
        if deadline_at:
            data["deadline_at"] = deadline_at

        result = self._request("POST", "/tasks", json_body={"data": data})
        if "error" in result:
            return result
        return result.get("data", result)

    def list_tasks(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List all tasks."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        result = self._request("GET", "/tasks", params=params)
        if "error" in result:
            return result
        return {
            "tasks": result.get("data", []),
            "total": len(result.get("data", [])),
        }

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Get a task by ID."""
        result = self._request("GET", f"/tasks/{task_id}")
        if "error" in result:
            return result
        return result.get("data", result)

    def delete_task(self, task_id: str) -> dict[str, Any]:
        """Delete a task."""
        return self._request("DELETE", f"/tasks/{task_id}")

    # --- Workspace Members ---

    def list_members(self) -> dict[str, Any]:
        """List all workspace members."""
        result = self._request("GET", "/workspace_members")
        if "error" in result:
            return result
        return {
            "members": result.get("data", []),
            "total": len(result.get("data", [])),
        }

    def get_member(self, member_id: str) -> dict[str, Any]:
        """Get a workspace member by ID."""
        result = self._request("GET", f"/workspace_members/{member_id}")
        if "error" in result:
            return result
        return result.get("data", result)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Attio tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get Attio API key from credential manager or environment."""
        if credentials is not None:
            try:
                api_key = credentials.get("attio")
                if api_key is not None and not isinstance(api_key, str):
                    raise TypeError(
                        f"Expected string from credentials.get('attio'), got {type(api_key).__name__}"
                    )
                if api_key is not None:
                    return api_key
            except Exception:
                pass
        return os.getenv("ATTIO_API_KEY")

    def _get_client() -> _AttioClient | dict[str, str]:
        """Get an Attio client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Attio credentials not configured",
                "help": (
                    "Set ATTIO_API_KEY environment variable "
                    "or configure via credential store. "
                    "Get an API key at https://attio.com/help/apps/other-apps/generating-an-api-key"
                ),
            }
        return _AttioClient(api_key)

    # --- Records ---

    @mcp.tool()
    def attio_record_list(
        object_handle: str,
        limit: int = 50,
        offset: int = 0,
        filter_json: str | None = None,
        sorts_json: str | None = None,
    ) -> dict:
        """
        List and filter records within a specific Attio object.

        Args:
            object_handle: Object type slug (e.g., 'people', 'companies', or custom object slug)
            limit: Maximum number of results (1-500, default 50)
            offset: Number of results to skip (default 0)
            filter_json: Optional JSON string with Attio filter object
            sorts_json: Optional JSON string with sort array

        Returns:
            Dict with records list and total count
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        filter_data = None
        if filter_json:
            try:
                filter_data = json.loads(filter_json)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid filter_json: {e}"}

        sorts = None
        if sorts_json:
            try:
                sorts = json.loads(sorts_json)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid sorts_json: {e}"}

        try:
            return client.list_records(
                object_handle=object_handle,
                limit=limit,
                offset=offset,
                filter_data=filter_data,
                sorts=sorts,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_record_get(object_handle: str, record_id: str) -> dict:
        """
        Get a specific Attio record by its ID.

        Args:
            object_handle: Object type slug (e.g., 'people', 'companies')
            record_id: The record's UUID

        Returns:
            Dict with record details including id, values, and timestamps
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_record(object_handle, record_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_record_create(object_handle: str, values: dict) -> dict:
        """
        Create a new record in Attio.

        Args:
            object_handle: Object type slug (e.g., 'people', 'companies')
            values: Record attribute values. Example for people:
                {"email_addresses": [{"email_address": "jane@example.com"}],
                 "name": [{"first_name": "Jane", "last_name": "Doe"}]}

        Returns:
            Dict with created record details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_record(object_handle, values)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_record_update(object_handle: str, record_id: str, values: dict) -> dict:
        """
        Update an existing Attio record. For multiselect attributes, new values are appended.

        Args:
            object_handle: Object type slug (e.g., 'people', 'companies')
            record_id: The record's UUID
            values: Attribute values to update

        Returns:
            Dict with updated record details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_record(object_handle, record_id, values)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_record_assert(
        object_handle: str,
        matching_attribute: str,
        values: dict,
    ) -> dict:
        """
        Upsert a record. If a record matches the unique attribute, it updates;
        otherwise, it creates a new one.

        Args:
            object_handle: Object type slug (e.g., 'people', 'companies')
            matching_attribute: Attribute slug to match on (e.g., 'email_addresses')
            values: Record attribute values

        Returns:
            Dict with created or updated record details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.assert_record(object_handle, matching_attribute, values)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Lists ---

    @mcp.tool()
    def attio_list_lists() -> dict:
        """
        List all lists in the Attio workspace.

        Returns:
            Dict with lists and total count
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_lists()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_list_entries_get(
        list_id: str,
        limit: int = 50,
        offset: int = 0,
        filter_json: str | None = None,
        sorts_json: str | None = None,
    ) -> dict:
        """
        List entries in a specific Attio list (e.g., a Sales Pipeline).

        Args:
            list_id: The list's UUID or slug
            limit: Maximum number of results (1-500, default 50)
            offset: Number of results to skip (default 0)
            filter_json: Optional JSON string with filter object
            sorts_json: Optional JSON string with sort array

        Returns:
            Dict with entries list and total count
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        filter_data = None
        if filter_json:
            try:
                filter_data = json.loads(filter_json)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid filter_json: {e}"}

        sorts = None
        if sorts_json:
            try:
                sorts = json.loads(sorts_json)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid sorts_json: {e}"}

        try:
            return client.get_entries(
                list_id=list_id,
                limit=limit,
                offset=offset,
                filter_data=filter_data,
                sorts=sorts,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_list_entry_create(
        list_id: str,
        parent_record_id: str,
        parent_object: str = "people",
        entry_values: dict | None = None,
    ) -> dict:
        """
        Add a record to a specific list (e.g., adding a person to a Sales Pipeline).

        Args:
            list_id: The list's UUID or slug
            parent_record_id: UUID of the record to add to the list
            parent_object: Object type of the parent record (default 'people')
            entry_values: Optional dict of list-specific attribute values

        Returns:
            Dict with created entry details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_entry(
                list_id=list_id,
                parent_record_id=parent_record_id,
                parent_object=parent_object,
                entry_values=entry_values,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_list_entry_delete(list_id: str, entry_id: str) -> dict:
        """
        Remove an entry from a list.

        Args:
            list_id: The list's UUID or slug
            entry_id: The entry's UUID

        Returns:
            Dict with success status
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.delete_entry(list_id, entry_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Tasks ---

    @mcp.tool()
    def attio_task_create(
        content: str,
        linked_records: list[dict] | None = None,
        assignees: list[dict] | None = None,
        deadline_at: str | None = None,
        is_completed: bool = False,
    ) -> dict:
        """
        Create a task linked to specific records.

        Args:
            content: Task description text
            linked_records: List of record references, e.g.,
                [{"target_object": "people", "target_record_id": "..."}]
            assignees: List of assignees, e.g.,
                [{"referenced_actor_type": "workspace-member", "referenced_actor_id": "..."}]
            deadline_at: ISO 8601 deadline (e.g., '2026-03-15T00:00:00Z')
            is_completed: Whether the task is already completed (default False)

        Returns:
            Dict with created task details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_task(
                content=content,
                linked_records=linked_records,
                assignees=assignees,
                deadline_at=deadline_at,
                is_completed=is_completed,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_task_list(limit: int = 50, offset: int = 0) -> dict:
        """
        List all tasks in the Attio workspace.

        Args:
            limit: Maximum number of results (default 50)
            offset: Number of results to skip (default 0)

        Returns:
            Dict with tasks list and total count
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_tasks(limit=limit, offset=offset)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_task_get(task_id: str) -> dict:
        """
        Get a task by its ID.

        Args:
            task_id: The task's UUID

        Returns:
            Dict with task details including content, assignees, and linked records
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_task(task_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_task_delete(task_id: str) -> dict:
        """
        Delete a task.

        Args:
            task_id: The task's UUID

        Returns:
            Dict with success status
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.delete_task(task_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Workspace Members ---

    @mcp.tool()
    def attio_members_list() -> dict:
        """
        List all members in the Attio workspace for assignment purposes.

        Returns:
            Dict with members list and total count
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_members()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def attio_member_get(member_id: str) -> dict:
        """
        Get a workspace member by ID.

        Args:
            member_id: The workspace member's UUID

        Returns:
            Dict with member details including name, email, and access level
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_member(member_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
