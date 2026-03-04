"""
Notion Tool - Pages, databases, and search via Notion API.

Supports:
- Notion internal integration token (Bearer auth)
- Search, page CRUD, database queries

API Reference: https://developers.notion.com/reference
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _get_credentials(credentials: CredentialStoreAdapter | None) -> str | None:
    """Return the Notion integration token."""
    if credentials is not None:
        return credentials.get("notion_token")
    return os.getenv("NOTION_API_TOKEN")


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, token: str, **kwargs: Any) -> dict[str, Any]:
    """Make a request to the Notion API."""
    try:
        resp = getattr(httpx, method)(
            f"{API_BASE}{path}",
            headers=_headers(token),
            timeout=30.0,
            **kwargs,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your Notion integration token."}
        if resp.status_code == 403:
            return {"error": "Forbidden. Ensure the page/database is shared with the integration."}
        if resp.status_code == 404:
            return {"error": "Not found. The page or database may not exist or not be shared."}
        if resp.status_code == 429:
            return {"error": "Rate limited. Try again shortly."}
        if resp.status_code not in (200, 201):
            return {"error": f"Notion API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Notion timed out"}
    except Exception as e:
        return {"error": f"Notion request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "NOTION_API_TOKEN not set",
        "help": "Create an integration at https://www.notion.so/my-integrations",
    }


def _extract_title(properties: dict) -> str:
    """Extract title text from Notion properties."""
    for prop in properties.values():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            return "".join(p.get("text", {}).get("content", "") for p in parts)
    return ""


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Notion tools with the MCP server."""

    @mcp.tool()
    def notion_search(
        query: str = "",
        filter_type: str = "",
        page_size: int = 20,
    ) -> dict[str, Any]:
        """
        Search Notion pages and databases.

        Args:
            query: Search text to match against titles (optional, empty = all)
            filter_type: Filter by object type: page or database (optional)
            page_size: Max results (1-100, default 20)

        Returns:
            Dict with matching pages/databases (id, title, type, url)
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()

        body: dict[str, Any] = {
            "page_size": max(1, min(page_size, 100)),
        }
        if query:
            body["query"] = query
        if filter_type in ("page", "database"):
            body["filter"] = {"property": "object", "value": filter_type}

        data = _request("post", "/search", token, json=body)
        if "error" in data:
            return data

        results = []
        for item in data.get("results", []):
            obj_type = item.get("object", "")
            title = ""
            if obj_type == "page":
                title = _extract_title(item.get("properties", {}))
            elif obj_type == "database":
                title_parts = item.get("title", [])
                title = "".join(p.get("text", {}).get("content", "") for p in title_parts)
            results.append(
                {
                    "id": item.get("id", ""),
                    "object": obj_type,
                    "title": title,
                    "url": item.get("url", ""),
                    "created_time": item.get("created_time", ""),
                    "last_edited_time": item.get("last_edited_time", ""),
                }
            )
        return {"results": results, "count": len(results), "has_more": data.get("has_more", False)}

    @mcp.tool()
    def notion_get_page(page_id: str) -> dict[str, Any]:
        """
        Get a Notion page by ID.

        Args:
            page_id: Notion page ID (required)

        Returns:
            Dict with page details (id, title, properties, url)
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not page_id:
            return {"error": "page_id is required"}

        data = _request("get", f"/pages/{page_id}", token)
        if "error" in data:
            return data

        properties = data.get("properties", {})
        title = _extract_title(properties)

        # Simplify properties for output
        simple_props = {}
        for name, prop in properties.items():
            ptype = prop.get("type", "")
            if ptype == "title":
                simple_props[name] = title
            elif ptype == "rich_text":
                parts = prop.get("rich_text", [])
                simple_props[name] = "".join(p.get("text", {}).get("content", "") for p in parts)
            elif ptype == "select":
                sel = prop.get("select")
                simple_props[name] = sel.get("name", "") if sel else ""
            elif ptype == "multi_select":
                simple_props[name] = [s.get("name", "") for s in prop.get("multi_select", [])]
            elif ptype == "number":
                simple_props[name] = prop.get("number")
            elif ptype == "checkbox":
                simple_props[name] = prop.get("checkbox", False)
            elif ptype == "date":
                dt = prop.get("date")
                simple_props[name] = dt.get("start", "") if dt else ""
            elif ptype == "status":
                st = prop.get("status")
                simple_props[name] = st.get("name", "") if st else ""

        return {
            "id": data.get("id", ""),
            "title": title,
            "url": data.get("url", ""),
            "archived": data.get("archived", False),
            "properties": simple_props,
            "created_time": data.get("created_time", ""),
            "last_edited_time": data.get("last_edited_time", ""),
        }

    @mcp.tool()
    def notion_create_page(
        parent_database_id: str,
        title: str,
        properties_json: str = "",
        content: str = "",
    ) -> dict[str, Any]:
        """
        Create a new page in a Notion database.

        Args:
            parent_database_id: ID of the parent database (required)
            title: Page title (required)
            properties_json: Additional properties as JSON string
                e.g. '{"Status": {"select": {"name": "Done"}}}'
                (optional)
            content: Plain text content for the page body (optional)

        Returns:
            Dict with created page (id, url)
        """
        import json as json_mod

        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not parent_database_id or not title:
            return {"error": "parent_database_id and title are required"}

        body: dict[str, Any] = {
            "parent": {"database_id": parent_database_id},
            "properties": {
                "Name": {"title": [{"text": {"content": title}}]},
            },
        }

        if properties_json:
            try:
                extra = json_mod.loads(properties_json)
                body["properties"].update(extra)
            except json_mod.JSONDecodeError:
                return {"error": "properties_json is not valid JSON"}

        if content:
            body["children"] = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
                }
            ]

        data = _request("post", "/pages", token, json=body)
        if "error" in data:
            return data

        return {
            "id": data.get("id", ""),
            "url": data.get("url", ""),
            "status": "created",
        }

    @mcp.tool()
    def notion_query_database(
        database_id: str,
        filter_json: str = "",
        page_size: int = 50,
    ) -> dict[str, Any]:
        """
        Query rows/pages from a Notion database.

        Args:
            database_id: Notion database ID (required)
            filter_json: Notion filter object as JSON string (optional)
            page_size: Max results (1-100, default 50)

        Returns:
            Dict with matching pages and their properties
        """
        import json as json_mod

        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not database_id:
            return {"error": "database_id is required"}

        body: dict[str, Any] = {
            "page_size": max(1, min(page_size, 100)),
        }

        if filter_json:
            try:
                body["filter"] = json_mod.loads(filter_json)
            except json_mod.JSONDecodeError:
                return {"error": "filter_json is not valid JSON"}

        data = _request("post", f"/databases/{database_id}/query", token, json=body)
        if "error" in data:
            return data

        pages = []
        for item in data.get("results", []):
            title = _extract_title(item.get("properties", {}))
            pages.append(
                {
                    "id": item.get("id", ""),
                    "title": title,
                    "url": item.get("url", ""),
                    "created_time": item.get("created_time", ""),
                    "last_edited_time": item.get("last_edited_time", ""),
                }
            )
        return {"pages": pages, "count": len(pages), "has_more": data.get("has_more", False)}

    @mcp.tool()
    def notion_get_database(database_id: str) -> dict[str, Any]:
        """
        Get a Notion database schema.

        Args:
            database_id: Notion database ID (required)

        Returns:
            Dict with database info and property definitions
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not database_id:
            return {"error": "database_id is required"}

        data = _request("get", f"/databases/{database_id}", token)
        if "error" in data:
            return data

        title_parts = data.get("title", [])
        title = "".join(p.get("text", {}).get("content", "") for p in title_parts)

        props = {}
        for name, prop in data.get("properties", {}).items():
            props[name] = {"type": prop.get("type", ""), "id": prop.get("id", "")}

        return {
            "id": data.get("id", ""),
            "title": title,
            "url": data.get("url", ""),
            "properties": props,
            "created_time": data.get("created_time", ""),
            "last_edited_time": data.get("last_edited_time", ""),
        }
