"""
Notion Tool - Workspace management via the Notion API.

Supports:
- API key authentication (NOTION_API_KEY)

Use Cases:
- Create, read, update, and archive pages
- Query and manage databases
- Append and manage block content
- Search across the workspace
- List users and manage comments

API Reference: https://developers.notion.com/reference
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

_BASE_URL = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


class _NotionClient:
    """Internal client wrapping Notion API calls via httpx."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = httpx.Client(
            base_url=_BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Notion-Version": _NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an API request and return the JSON response or error dict."""
        response = self._client.request(method, path, json=json, params=params)
        data = response.json()
        if response.status_code >= 400:
            msg = data.get("message", response.text)
            code = data.get("code", "unknown")
            return {"error": f"Notion API error ({code}): {msg}"}
        return data

    # --- Pages ---

    def create_page(
        self,
        parent: dict[str, Any],
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
        icon: dict[str, Any] | None = None,
        cover: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            body["children"] = children
        if icon:
            body["icon"] = icon
        if cover:
            body["cover"] = cover
        result = self._request("POST", "/pages", json=body)
        if "error" in result:
            return result
        return self._format_page(result)

    def get_page(self, page_id: str) -> dict[str, Any]:
        result = self._request("GET", f"/pages/{page_id}")
        if "error" in result:
            return result
        return self._format_page(result)

    def update_page(
        self,
        page_id: str,
        properties: dict[str, Any] | None = None,
        archived: bool | None = None,
        icon: dict[str, Any] | None = None,
        cover: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if properties is not None:
            body["properties"] = properties
        if archived is not None:
            body["archived"] = archived
        if icon is not None:
            body["icon"] = icon
        if cover is not None:
            body["cover"] = cover
        result = self._request("PATCH", f"/pages/{page_id}", json=body)
        if "error" in result:
            return result
        return self._format_page(result)

    def archive_page(self, page_id: str) -> dict[str, Any]:
        return self.update_page(page_id, archived=True)

    @staticmethod
    def _format_page(page: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": page.get("id"),
            "object": page.get("object"),
            "created_time": page.get("created_time"),
            "last_edited_time": page.get("last_edited_time"),
            "archived": page.get("archived"),
            "url": page.get("url"),
            "properties": page.get("properties", {}),
            "parent": page.get("parent"),
            "icon": page.get("icon"),
            "cover": page.get("cover"),
        }

    # --- Databases ---

    def query_database(
        self,
        database_id: str,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if filter:
            body["filter"] = filter
        if sorts:
            body["sorts"] = sorts
        if start_cursor:
            body["start_cursor"] = start_cursor
        body["page_size"] = min(page_size, 100)
        result = self._request("POST", f"/databases/{database_id}/query", json=body)
        if "error" in result:
            return result
        return {
            "results": [self._format_page(p) for p in result.get("results", [])],
            "has_more": result.get("has_more", False),
            "next_cursor": result.get("next_cursor"),
        }

    def get_database(self, database_id: str) -> dict[str, Any]:
        result = self._request("GET", f"/databases/{database_id}")
        if "error" in result:
            return result
        return self._format_database(result)

    def create_database(
        self,
        parent: dict[str, Any],
        title: list[dict[str, Any]],
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "parent": parent,
            "title": title,
            "properties": properties,
        }
        result = self._request("POST", "/databases", json=body)
        if "error" in result:
            return result
        return self._format_database(result)

    def update_database(
        self,
        database_id: str,
        title: list[dict[str, Any]] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if properties is not None:
            body["properties"] = properties
        result = self._request("PATCH", f"/databases/{database_id}", json=body)
        if "error" in result:
            return result
        return self._format_database(result)

    @staticmethod
    def _format_database(db: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": db.get("id"),
            "object": db.get("object"),
            "created_time": db.get("created_time"),
            "last_edited_time": db.get("last_edited_time"),
            "title": db.get("title"),
            "url": db.get("url"),
            "properties": db.get("properties", {}),
            "parent": db.get("parent"),
            "archived": db.get("archived"),
        }

    # --- Blocks ---

    def get_block(self, block_id: str) -> dict[str, Any]:
        result = self._request("GET", f"/blocks/{block_id}")
        if "error" in result:
            return result
        return self._format_block(result)

    def get_block_children(
        self,
        block_id: str,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": min(page_size, 100)}
        if start_cursor:
            params["start_cursor"] = start_cursor
        result = self._request("GET", f"/blocks/{block_id}/children", params=params)
        if "error" in result:
            return result
        return {
            "results": [self._format_block(b) for b in result.get("results", [])],
            "has_more": result.get("has_more", False),
            "next_cursor": result.get("next_cursor"),
        }

    def append_block_children(
        self,
        block_id: str,
        children: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result = self._request(
            "PATCH",
            f"/blocks/{block_id}/children",
            json={"children": children},
        )
        if "error" in result:
            return result
        return {
            "results": [self._format_block(b) for b in result.get("results", [])],
        }

    def delete_block(self, block_id: str) -> dict[str, Any]:
        result = self._request("DELETE", f"/blocks/{block_id}")
        if "error" in result:
            return result
        return self._format_block(result)

    @staticmethod
    def _format_block(block: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": block.get("id"),
            "object": block.get("object"),
            "type": block.get("type"),
            "created_time": block.get("created_time"),
            "last_edited_time": block.get("last_edited_time"),
            "has_children": block.get("has_children"),
            "archived": block.get("archived"),
            block.get("type", "_"): block.get(block.get("type", "_")),
        }

    # --- Search ---

    def search(
        self,
        query: str = "",
        filter_object: str | None = None,
        sort_direction: str = "descending",
        sort_timestamp: str = "last_edited_time",
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"page_size": min(page_size, 100)}
        if query:
            body["query"] = query
        if filter_object:
            body["filter"] = {"value": filter_object, "property": "object"}
        body["sort"] = {"direction": sort_direction, "timestamp": sort_timestamp}
        if start_cursor:
            body["start_cursor"] = start_cursor
        result = self._request("POST", "/search", json=body)
        if "error" in result:
            return result
        formatted = []
        for item in result.get("results", []):
            if item.get("object") == "page":
                formatted.append(self._format_page(item))
            elif item.get("object") == "database":
                formatted.append(self._format_database(item))
            else:
                formatted.append(item)
        return {
            "results": formatted,
            "has_more": result.get("has_more", False),
            "next_cursor": result.get("next_cursor"),
        }

    # --- Users ---

    def list_users(
        self,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": min(page_size, 100)}
        if start_cursor:
            params["start_cursor"] = start_cursor
        result = self._request("GET", "/users", params=params)
        if "error" in result:
            return result
        return {
            "users": [self._format_user(u) for u in result.get("results", [])],
            "has_more": result.get("has_more", False),
            "next_cursor": result.get("next_cursor"),
        }

    def get_user(self, user_id: str) -> dict[str, Any]:
        result = self._request("GET", f"/users/{user_id}")
        if "error" in result:
            return result
        return self._format_user(result)

    @staticmethod
    def _format_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user.get("id"),
            "object": user.get("object"),
            "type": user.get("type"),
            "name": user.get("name"),
            "avatar_url": user.get("avatar_url"),
            "person": user.get("person"),
            "bot": user.get("bot"),
        }

    # --- Comments ---

    def create_comment(
        self,
        parent: dict[str, Any],
        rich_text: list[dict[str, Any]],
        discussion_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"rich_text": rich_text}
        if discussion_id:
            body["discussion_id"] = discussion_id
        else:
            body["parent"] = parent
        result = self._request("POST", "/comments", json=body)
        if "error" in result:
            return result
        return self._format_comment(result)

    def list_comments(
        self,
        block_id: str,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "block_id": block_id,
            "page_size": min(page_size, 100),
        }
        if start_cursor:
            params["start_cursor"] = start_cursor
        result = self._request("GET", "/comments", params=params)
        if "error" in result:
            return result
        return {
            "comments": [self._format_comment(c) for c in result.get("results", [])],
            "has_more": result.get("has_more", False),
            "next_cursor": result.get("next_cursor"),
        }

    @staticmethod
    def _format_comment(comment: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": comment.get("id"),
            "object": comment.get("object"),
            "parent": comment.get("parent"),
            "discussion_id": comment.get("discussion_id"),
            "rich_text": comment.get("rich_text"),
            "created_time": comment.get("created_time"),
            "created_by": comment.get("created_by"),
        }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_UUID_MIN_LEN = 32  # UUIDs without dashes


def _is_valid_id(value: str) -> bool:
    """Check if a value looks like a valid Notion UUID (with or without dashes)."""
    if not value:
        return False
    stripped = value.replace("-", "")
    return len(stripped) >= _UUID_MIN_LEN and all(c in "0123456789abcdef" for c in stripped)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Notion workspace tools with the MCP server."""

    def _get_api_key() -> str | dict[str, str]:
        """Get Notion API key from credential manager or environment."""
        if credentials is not None:
            api_key = credentials.get("notion")
            if api_key and isinstance(api_key, str):
                return api_key
        else:
            api_key = os.getenv("NOTION_API_KEY")
            if api_key:
                return api_key

        return {
            "error": "Notion credentials not configured",
            "help": (
                "Set NOTION_API_KEY environment variable. "
                "Create an integration at https://www.notion.so/my-integrations"
            ),
        }

    def _get_client() -> _NotionClient | dict[str, str]:
        """Get a Notion client, or return an error dict if no credentials."""
        key = _get_api_key()
        if isinstance(key, dict):
            return key
        return _NotionClient(key)

    def _api_error(e: httpx.HTTPError) -> dict[str, Any]:
        return {"error": str(e)}

    # --- Page Tools ---

    @mcp.tool()
    def notion_create_page(
        parent_type: str,
        parent_id: str,
        properties: dict,
        children: list[dict] | None = None,
        icon: dict | None = None,
        cover: dict | None = None,
    ) -> dict:
        """
        Create a new Notion page.

        Args:
            parent_type: Parent type - "database_id" or "page_id"
            parent_id: ID of the parent database or page
            properties: Page properties (title, etc.) as Notion property objects
            children: Optional list of block objects for page content
            icon: Optional icon object (emoji or external URL)
            cover: Optional cover image object (external URL)

        Returns:
            Dict with page details or error

        Example:
            notion_create_page(
                parent_type="database_id",
                parent_id="abc123...",
                properties={"Name": {"title": [{"text": {"content": "My Page"}}]}}
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if parent_type not in ("database_id", "page_id"):
            return {"error": "parent_type must be 'database_id' or 'page_id'"}
        if not _is_valid_id(parent_id):
            return {"error": f"Invalid {parent_type}. Must be a valid Notion UUID."}
        try:
            return client.create_page(
                parent={parent_type: parent_id},
                properties=properties,
                children=children,
                icon=icon,
                cover=cover,
            )
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_get_page(page_id: str) -> dict:
        """
        Retrieve a Notion page by ID.

        Args:
            page_id: Notion page ID (UUID format)

        Returns:
            Dict with page details or error

        Example:
            notion_get_page("abc123def456...")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(page_id):
            return {"error": "Invalid page_id. Must be a valid Notion UUID."}
        try:
            return client.get_page(page_id)
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_update_page(
        page_id: str,
        properties: dict | None = None,
        archived: bool | None = None,
        icon: dict | None = None,
        cover: dict | None = None,
    ) -> dict:
        """
        Update a Notion page's properties, icon, cover, or archive status.

        Args:
            page_id: Notion page ID (UUID format)
            properties: Properties to update as Notion property objects
            archived: Set to True to archive, False to un-archive
            icon: Icon object (emoji or external URL), or None to skip
            cover: Cover image object (external URL), or None to skip

        Returns:
            Dict with updated page details or error

        Example:
            notion_update_page(
                "abc123...",
                properties={"Status": {"select": {"name": "Done"}}}
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(page_id):
            return {"error": "Invalid page_id. Must be a valid Notion UUID."}
        try:
            return client.update_page(page_id, properties, archived, icon, cover)
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_archive_page(page_id: str) -> dict:
        """
        Archive (soft-delete) a Notion page.

        Args:
            page_id: Notion page ID (UUID format)

        Returns:
            Dict with archived page details or error

        Example:
            notion_archive_page("abc123def456...")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(page_id):
            return {"error": "Invalid page_id. Must be a valid Notion UUID."}
        try:
            return client.archive_page(page_id)
        except httpx.HTTPError as e:
            return _api_error(e)

    # --- Database Tools ---

    @mcp.tool()
    def notion_query_database(
        database_id: str,
        filter: dict | None = None,
        sorts: list[dict] | None = None,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict:
        """
        Query a Notion database with optional filters and sorting.

        Args:
            database_id: Notion database ID (UUID format)
            filter: Notion filter object for narrowing results
            sorts: List of sort objects (property name + direction)
            start_cursor: Cursor for pagination from a previous response
            page_size: Number of results per page (max 100)

        Returns:
            Dict with results list, has_more flag, and next_cursor

        Example:
            notion_query_database(
                "abc123...",
                filter={"property": "Status", "select": {"equals": "Active"}}
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(database_id):
            return {"error": "Invalid database_id. Must be a valid Notion UUID."}
        if page_size < 1:
            return {"error": "page_size must be at least 1"}
        try:
            return client.query_database(database_id, filter, sorts, start_cursor, page_size)
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_get_database(database_id: str) -> dict:
        """
        Retrieve a Notion database schema and metadata.

        Args:
            database_id: Notion database ID (UUID format)

        Returns:
            Dict with database details including properties schema

        Example:
            notion_get_database("abc123def456...")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(database_id):
            return {"error": "Invalid database_id. Must be a valid Notion UUID."}
        try:
            return client.get_database(database_id)
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_create_database(
        parent_id: str,
        title: str,
        properties: dict,
    ) -> dict:
        """
        Create a new Notion database as a child of an existing page.

        Args:
            parent_id: Parent page ID (UUID format)
            title: Database title text
            properties: Database property schema as Notion property config objects

        Returns:
            Dict with new database details or error

        Example:
            notion_create_database(
                parent_id="abc123...",
                title="Project Tracker",
                properties={
                    "Name": {"title": {}},
                    "Status": {"select": {"options": [
                        {"name": "To Do", "color": "red"},
                        {"name": "Done", "color": "green"}
                    ]}}
                }
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(parent_id):
            return {"error": "Invalid parent_id. Must be a valid Notion UUID."}
        if not title:
            return {"error": "title is required and cannot be empty"}
        try:
            return client.create_database(
                parent={"type": "page_id", "page_id": parent_id},
                title=[{"type": "text", "text": {"content": title}}],
                properties=properties,
            )
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_update_database(
        database_id: str,
        title: str | None = None,
        properties: dict | None = None,
    ) -> dict:
        """
        Update a Notion database's title or property schema.

        Args:
            database_id: Notion database ID (UUID format)
            title: New title text, or None to skip
            properties: Updated property schema config, or None to skip

        Returns:
            Dict with updated database details or error

        Example:
            notion_update_database("abc123...", title="Updated Tracker")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(database_id):
            return {"error": "Invalid database_id. Must be a valid Notion UUID."}
        title_obj = None
        if title is not None:
            title_obj = [{"type": "text", "text": {"content": title}}]
        try:
            return client.update_database(database_id, title_obj, properties)
        except httpx.HTTPError as e:
            return _api_error(e)

    # --- Block Tools ---

    @mcp.tool()
    def notion_get_block(block_id: str) -> dict:
        """
        Retrieve a single Notion block by ID.

        Args:
            block_id: Notion block ID (UUID format)

        Returns:
            Dict with block details or error

        Example:
            notion_get_block("abc123def456...")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(block_id):
            return {"error": "Invalid block_id. Must be a valid Notion UUID."}
        try:
            return client.get_block(block_id)
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_get_block_children(
        block_id: str,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict:
        """
        Retrieve the content blocks (children) of a page or block.

        Args:
            block_id: Parent block or page ID (UUID format)
            start_cursor: Cursor for pagination
            page_size: Number of blocks per page (max 100)

        Returns:
            Dict with results list, has_more flag, and next_cursor

        Example:
            notion_get_block_children("abc123def456...")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(block_id):
            return {"error": "Invalid block_id. Must be a valid Notion UUID."}
        if page_size < 1:
            return {"error": "page_size must be at least 1"}
        try:
            return client.get_block_children(block_id, start_cursor, page_size)
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_append_block_children(
        block_id: str,
        children: list[dict],
    ) -> dict:
        """
        Append content blocks to a page or existing block.

        Args:
            block_id: Parent block or page ID (UUID format)
            children: List of Notion block objects to append

        Returns:
            Dict with the appended block results or error

        Example:
            notion_append_block_children(
                "abc123...",
                children=[{
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": "Hello!"}}]
                    }
                }]
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(block_id):
            return {"error": "Invalid block_id. Must be a valid Notion UUID."}
        if not children:
            return {"error": "children list cannot be empty"}
        try:
            return client.append_block_children(block_id, children)
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_delete_block(block_id: str) -> dict:
        """
        Delete (archive) a Notion block.

        Args:
            block_id: Notion block ID (UUID format)

        Returns:
            Dict with the deleted block details or error

        Example:
            notion_delete_block("abc123def456...")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(block_id):
            return {"error": "Invalid block_id. Must be a valid Notion UUID."}
        try:
            return client.delete_block(block_id)
        except httpx.HTTPError as e:
            return _api_error(e)

    # --- Search ---

    @mcp.tool()
    def notion_search(
        query: str = "",
        filter_object: str | None = None,
        sort_direction: str = "descending",
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict:
        """
        Search across all pages and databases in the workspace.

        Args:
            query: Text to search for (empty string returns all)
            filter_object: Filter by object type - "page" or "database"
            sort_direction: Sort order - "ascending" or "descending"
            start_cursor: Cursor for pagination
            page_size: Number of results per page (max 100)

        Returns:
            Dict with results list, has_more flag, and next_cursor

        Example:
            notion_search(query="Meeting Notes", filter_object="page")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if filter_object and filter_object not in ("page", "database"):
            return {"error": "filter_object must be 'page' or 'database'"}
        if sort_direction not in ("ascending", "descending"):
            return {"error": "sort_direction must be 'ascending' or 'descending'"}
        if page_size < 1:
            return {"error": "page_size must be at least 1"}
        try:
            return client.search(query, filter_object, sort_direction, "last_edited_time",
                                 start_cursor, page_size)
        except httpx.HTTPError as e:
            return _api_error(e)

    # --- User Tools ---

    @mcp.tool()
    def notion_list_users(
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict:
        """
        List all users in the Notion workspace.

        Args:
            start_cursor: Cursor for pagination
            page_size: Number of users per page (max 100)

        Returns:
            Dict with users list, has_more flag, and next_cursor

        Example:
            notion_list_users()
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if page_size < 1:
            return {"error": "page_size must be at least 1"}
        try:
            return client.list_users(start_cursor, page_size)
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_get_user(user_id: str) -> dict:
        """
        Retrieve a Notion user by ID.

        Args:
            user_id: Notion user ID (UUID format)

        Returns:
            Dict with user details or error

        Example:
            notion_get_user("abc123def456...")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(user_id):
            return {"error": "Invalid user_id. Must be a valid Notion UUID."}
        try:
            return client.get_user(user_id)
        except httpx.HTTPError as e:
            return _api_error(e)

    # --- Comment Tools ---

    @mcp.tool()
    def notion_create_comment(
        page_id: str,
        text: str,
        discussion_id: str | None = None,
    ) -> dict:
        """
        Add a comment to a Notion page or reply to a discussion thread.

        Args:
            page_id: Page ID to comment on (UUID format)
            text: Comment text content
            discussion_id: Optional discussion thread ID to reply to

        Returns:
            Dict with comment details or error

        Example:
            notion_create_comment("abc123...", text="Looks good!")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(page_id):
            return {"error": "Invalid page_id. Must be a valid Notion UUID."}
        if not text:
            return {"error": "text cannot be empty"}
        rich_text = [{"type": "text", "text": {"content": text}}]
        try:
            return client.create_comment(
                parent={"page_id": page_id},
                rich_text=rich_text,
                discussion_id=discussion_id,
            )
        except httpx.HTTPError as e:
            return _api_error(e)

    @mcp.tool()
    def notion_list_comments(
        block_id: str,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict:
        """
        List comments on a Notion page or block.

        Args:
            block_id: Page or block ID to list comments for (UUID format)
            start_cursor: Cursor for pagination
            page_size: Number of comments per page (max 100)

        Returns:
            Dict with comments list, has_more flag, and next_cursor

        Example:
            notion_list_comments("abc123def456...")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not _is_valid_id(block_id):
            return {"error": "Invalid block_id. Must be a valid Notion UUID."}
        if page_size < 1:
            return {"error": "page_size must be at least 1"}
        try:
            return client.list_comments(block_id, start_cursor, page_size)
        except httpx.HTTPError as e:
            return _api_error(e)
