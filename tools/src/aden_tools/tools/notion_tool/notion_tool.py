"""
Notion Tool - Interact with Notion databases and pages.

API Reference: https://developers.notion.com/reference
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _sanitize_error_message(error: Exception) -> str:
    """Sanitize error messages to prevent token leaks."""
    error_str = str(error)
    if "Authorization" in error_str or "Bearer" in error_str:
        return "Network error occurred"
    return f"Network error: {error_str}"


class _NotionClient:
    """Internal client wrapping Notion API v1 calls."""

    def __init__(self, token: str):
        self._token = token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Notion API response format."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Notion token"}
        if response.status_code == 403:
            return {"error": "Forbidden - check integration permissions"}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded"}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Notion API error (HTTP {response.status_code}): {detail}"}

        try:
            return {"success": True, "data": response.json()}
        except Exception:
            return {"success": True, "data": {}}

    def search(
        self,
        query: str | None = None,
        filter_type: str | None = None,
        sort_direction: str = "descending",
        limit: int = 30,
    ) -> dict[str, Any]:
        """Search for pages, databases, or blocks."""
        payload: dict[str, Any] = {
            "page_size": min(limit, 100),
        }
        if query:
            payload["query"] = query
        if filter_type:
            payload["filter"] = {"value": filter_type, "property": "object"}
        if sort_direction:
            payload["sort"] = {"direction": sort_direction, "timestamp": "last_edited_time"}

        response = httpx.post(
            f"{NOTION_API_BASE}/search",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_database(self, database_id: str) -> dict[str, Any]:
        """Retrieve a database schema."""
        response = httpx.get(
            f"{NOTION_API_BASE}/databases/{database_id}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def query_database(
        self,
        database_id: str,
        filter_params: dict[str, Any] | None = None,
        sort_params: list[dict[str, Any]] | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        """Filter and search pages within a database."""
        payload: dict[str, Any] = {
            "page_size": min(limit, 100),
        }
        if filter_params:
            payload["filter"] = filter_params
        if sort_params:
            payload["sorts"] = sort_params

        response = httpx.post(
            f"{NOTION_API_BASE}/databases/{database_id}/query",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_page(
        self,
        parent_id: str,
        parent_type: str = "database_id",
        properties: dict[str, Any] | None = None,
        children: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a new page."""
        payload: dict[str, Any] = {
            "parent": {parent_type: parent_id},
            "properties": properties or {},
        }
        if children:
            payload["children"] = children

        response = httpx.post(
            f"{NOTION_API_BASE}/pages",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_page_properties(
        self,
        page_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Update properties of an existing page."""
        payload = {"properties": properties}
        response = httpx.patch(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_page(self, page_id: str) -> dict[str, Any]:
        """Retrieve a page's properties."""
        response = httpx.get(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_block_children(
        self,
        block_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Retrieve content of a page or block (children blocks)."""
        params = {"page_size": min(limit, 100)}
        response = httpx.get(
            f"{NOTION_API_BASE}/blocks/{block_id}/children",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Notion tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Notion token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("notion")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('notion'), got {type(token).__name__}"
                )
            return token
        return os.getenv("NOTION_TOKEN")

    def _get_client() -> _NotionClient | dict[str, str]:
        """Get a Notion client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "Notion credentials not configured",
                "help": (
                    "Set NOTION_TOKEN environment variable "
                    "or configure via credential store. "
                    "Get a token at https://www.notion.so/my-integrations"
                ),
            }
        return _NotionClient(token)

    @mcp.tool()
    def notion_search(
        query: str | None = None,
        filter_type: str | None = None,
        limit: int = 30,
    ) -> dict:
        """
        Search for pages, databases, or blocks in Notion.

        Args:
            query: The search text
            filter_type: Optional filter by object type ("page" or "database")
            limit: Maximum number of results to return (1-100, default 30)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.search(query=query, filter_type=filter_type, limit=limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def notion_get_database(database_id: str) -> dict:
        """
        Retrieve a database's schema and information.

        Args:
            database_id: The ID of the database to retrieve
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_database(database_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def notion_query_database(
        database_id: str,
        filter_params: dict | None = None,
        limit: int = 30,
    ) -> dict:
        """
        Query a database for specific pages based on filters.

        Args:
            database_id: The ID of the database to query
            filter_params: Notion filter object (optional)
            limit: Maximum number of results (1-100, default 30)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.query_database(database_id, filter_params=filter_params, limit=limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def notion_create_database_page(
        database_id: str,
        properties: dict,
        content: list[dict] | None = None,
    ) -> dict:
        """
        Create a new page in a Notion database.

        Args:
            database_id: The ID of the parent database
            properties: Properties for the new page (must match database schema)
            content: Optional blocks representing the page content
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_page(
                parent_id=database_id,
                parent_type="database_id",
                properties=properties,
                children=content,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def notion_get_page_content(page_id: str, limit: int = 50) -> dict:
        """
        Retrieve the content (blocks) of a Notion page.

        Args:
            page_id: The ID of the page to retrieve content from
            limit: Maximum number of blocks to return
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_block_children(page_id, limit=limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def notion_update_page(page_id: str, properties: dict) -> dict:
        """
        Update the properties of an existing Notion page.

        Args:
            page_id: The ID of the page to update
            properties: The new properties for the page
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_page_properties(page_id, properties)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}
