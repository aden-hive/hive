"""
Notion Tool - Pages, databases, and search via Notion API.

Supports:
- Notion internal integration token (Bearer auth)
- Search, page CRUD, database queries

API Reference: https://developers.notion.com/reference
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class BlockType(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"
    BULLETED_LIST_ITEM = "bulleted_list_item"
    NUMBERED_LIST_ITEM = "numbered_list_item"
    TO_DO = "to_do"
    QUOTE = "quote"
    CALLOUT = "callout"


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
        title: str,
        parent_database_id: str = "",
        parent_page_id: str = "",
        title_property: str = "",
        properties_json: str = "",
        content: str = "",
    ) -> dict[str, Any]:
        """
        Create a new page in a Notion database or as a child of another page.

        Provide exactly one of parent_database_id or parent_page_id.

        Args:
            title: Page title (required)
            parent_database_id: ID of the parent database (optional)
            parent_page_id: ID of the parent page (optional)
            title_property: Name of the title column in the database
                (required when using parent_database_id). Use
                notion_get_database to find the correct property name.
                Ignored when parent_page_id is used.
            properties_json: Additional properties as JSON string
                e.g. '{"Status": {"select": {"name": "Done"}}}'
                Ignored when parent_page_id is used. (optional)
            content: Plain text content for the page body (optional)

        Returns:
            Dict with created page (id, url)
        """
        import json as json_mod

        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not title:
            return {"error": "title is required"}
        if not parent_database_id and not parent_page_id:
            return {"error": "Provide parent_database_id or parent_page_id"}
        if parent_database_id and parent_page_id:
            return {"error": "Provide only one of parent_database_id or parent_page_id, not both"}

        body: dict[str, Any] = {}

        match (bool(parent_database_id), bool(parent_page_id)):
            case (True, False):
                if not title_property:
                    return {
                        "error": "title_property is required when using parent_database_id. "
                        "Use notion_get_database to find the title column name.",
                    }
                body["parent"] = {"database_id": parent_database_id}
                body["properties"] = {
                    title_property: {"title": [{"text": {"content": title}}]},
                }
                if properties_json:
                    try:
                        extra = json_mod.loads(properties_json)
                        body["properties"].update(extra)
                    except json_mod.JSONDecodeError:
                        return {"error": "properties_json is not valid JSON"}
            case (False, True):
                body["parent"] = {"page_id": parent_page_id}
                body["properties"] = {
                    "title": {"title": [{"text": {"content": title}}]},
                }

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
        sorts_json: str = "",
        start_cursor: str = "",
        page_size: int = 50,
    ) -> dict[str, Any]:
        """
        Query rows/pages from a Notion database.

        Args:
            database_id: Notion database ID (required)
            filter_json: Notion filter object as JSON string (optional)
                e.g. '{"property": "Status", "select": {"equals": "Done"}}'
            sorts_json: Sort order as JSON array string (optional)
                e.g. '[{"property": "Created", "direction": "descending"}]'
                or '[{"timestamp": "last_edited_time", "direction": "ascending"}]'
            start_cursor: Pagination cursor from a previous response's
                next_cursor field (optional)
            page_size: Max results (1-100, default 50)

        Returns:
            Dict with matching pages, count, has_more, and next_cursor
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

        if sorts_json:
            try:
                body["sorts"] = json_mod.loads(sorts_json)
            except json_mod.JSONDecodeError:
                return {"error": "sorts_json is not valid JSON"}

        if start_cursor:
            body["start_cursor"] = start_cursor

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
        return {
            "pages": pages,
            "count": len(pages),
            "has_more": data.get("has_more", False),
            "next_cursor": data.get("next_cursor"),
        }

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

    @mcp.tool()
    def notion_create_database(
        parent_page_id: str,
        title: str,
        properties_json: str = "",
    ) -> dict[str, Any]:
        """
        Create a new database as a child of an existing page.

        Args:
            parent_page_id: ID of the parent page (required)
            title: Database title (required)
            properties_json: Property definitions as JSON string (optional).
                If omitted, creates a database with a single "Name" title
                column. Example with extra columns:
                '{"Status": {"select": {"options": [{"name": "To Do"},
                {"name": "Done"}]}}, "Priority": {"number": {}}}'

        Returns:
            Dict with created database (id, url)
        """
        import json as json_mod

        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not parent_page_id or not title:
            return {"error": "parent_page_id and title are required"}

        properties: dict[str, Any] = {
            "Name": {"title": {}},
        }

        if properties_json:
            try:
                extra = json_mod.loads(properties_json)
                properties.update(extra)
            except json_mod.JSONDecodeError:
                return {"error": "properties_json is not valid JSON"}

        body: dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        }

        data = _request("post", "/databases", token, json=body)
        if "error" in data:
            return data

        return {
            "id": data.get("id", ""),
            "url": data.get("url", ""),
            "status": "created",
        }

    @mcp.tool()
    def notion_update_database(
        database_id: str,
        title: str = "",
        properties_json: str = "",
        archived: bool | None = None,
    ) -> dict[str, Any]:
        """
        Update a database's title, properties, or archive it.

        Args:
            database_id: Notion database ID (required)
            title: New database title (optional)
            properties_json: Property schema changes as JSON string (optional).
                Add new columns, rename, or change types.
                e.g. '{"Priority": {"number": {}}}'
            archived: Set to true to archive (delete), false to restore
                (optional)

        Returns:
            Dict with updated database (id, url, status)
        """
        import json as json_mod

        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not database_id:
            return {"error": "database_id is required"}

        body: dict[str, Any] = {}

        if title:
            body["title"] = [{"type": "text", "text": {"content": title}}]

        if properties_json:
            try:
                body["properties"] = json_mod.loads(properties_json)
            except json_mod.JSONDecodeError:
                return {"error": "properties_json is not valid JSON"}

        if archived is not None:
            body["archived"] = archived

        if not body:
            return {"error": "No updates provided. Set title, properties_json, or archived."}

        data = _request("patch", f"/databases/{database_id}", token, json=body)
        if "error" in data:
            return data

        return {
            "id": data.get("id", ""),
            "url": data.get("url", ""),
            "status": "updated",
        }

    @mcp.tool()
    def notion_update_page(
        page_id: str,
        properties_json: str = "",
        archived: bool | None = None,
    ) -> dict[str, Any]:
        """
        Update a Notion page's properties.

        Args:
            page_id: Notion page ID (required)
            properties_json: Properties to update as JSON string
                e.g. '{"Status": {"select": {"name": "Done"}}}'
                (optional)
            archived: Set to true to archive, false to unarchive (optional)

        Returns:
            Dict with updated page (id, url, status)
        """
        import json as json_mod

        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not page_id:
            return {"error": "page_id is required"}

        body: dict[str, Any] = {}

        if properties_json:
            try:
                body["properties"] = json_mod.loads(properties_json)
            except json_mod.JSONDecodeError:
                return {"error": "properties_json is not valid JSON"}

        if archived is not None:
            body["archived"] = archived

        if not body:
            return {"error": "No updates provided. Set properties_json or archived."}

        data = _request("patch", f"/pages/{page_id}", token, json=body)
        if "error" in data:
            return data

        return {
            "id": data.get("id", ""),
            "url": data.get("url", ""),
            "status": "updated",
        }

    @mcp.tool()
    def notion_get_block_children(
        block_id: str,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """
        Get child blocks (content) of a page or block.

        Args:
            block_id: Page ID or block ID (required)
            page_size: Max results (1-100, default 50)

        Returns:
            Dict with block content (type, text, children indicator)
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not block_id:
            return {"error": "block_id is required"}

        params = {"page_size": max(1, min(page_size, 100))}
        data = _request("get", f"/blocks/{block_id}/children", token, params=params)
        if "error" in data:
            return data

        blocks = []
        for item in data.get("results", []):
            block_type = item.get("type", "")
            block_data: dict[str, Any] = {
                "id": item.get("id", ""),
                "type": block_type,
                "has_children": item.get("has_children", False),
            }

            # Extract text content from common block types
            type_data = item.get(block_type, {})
            rich_text = type_data.get("rich_text", [])
            if rich_text:
                block_data["text"] = "".join(
                    p.get("text", {}).get("content", "") for p in rich_text
                )

            blocks.append(block_data)

        return {
            "blocks": blocks,
            "count": len(blocks),
            "has_more": data.get("has_more", False),
        }

    @mcp.tool()
    def notion_get_block(block_id: str) -> dict[str, Any]:
        """
        Retrieve a single block by ID.

        Args:
            block_id: Notion block ID (required)

        Returns:
            Dict with block details (id, type, text, has_children)
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not block_id:
            return {"error": "block_id is required"}

        data = _request("get", f"/blocks/{block_id}", token)
        if "error" in data:
            return data

        block_type = data.get("type", "")
        result: dict[str, Any] = {
            "id": data.get("id", ""),
            "type": block_type,
            "has_children": data.get("has_children", False),
            "archived": data.get("archived", False),
            "created_time": data.get("created_time", ""),
            "last_edited_time": data.get("last_edited_time", ""),
        }

        type_data = data.get(block_type, {})
        rich_text = type_data.get("rich_text", [])
        if rich_text:
            result["text"] = "".join(p.get("text", {}).get("content", "") for p in rich_text)

        return result

    @mcp.tool()
    def notion_update_block(
        block_id: str,
        content: str = "",
        block_type: str = "",
        archived: bool | None = None,
    ) -> dict[str, Any]:
        """
        Update a block's content or archive it.

        Args:
            block_id: Notion block ID (required)
            content: New text content for the block (optional).
                Only works for text-based blocks (paragraph, heading, etc.)
            block_type: The block's current type (required when setting content).
                Use notion_get_block to find the type first.
            archived: Set to true to archive (soft-delete), false to restore
                (optional)

        Returns:
            Dict with updated block info (id, type, status)
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not block_id:
            return {"error": "block_id is required"}

        body: dict[str, Any] = {}

        if content:
            if not block_type:
                return {
                    "error": "block_type is required when setting content. "
                    "Use notion_get_block to find the type.",
                }
            try:
                validated = BlockType(block_type)
            except ValueError:
                return {
                    "error": f"Invalid block_type: {block_type!r}",
                    "help": f"Must be one of: {', '.join(sorted(BlockType))}",
                }
            body[validated] = {
                "rich_text": [{"type": "text", "text": {"content": content}}],
            }

        if archived is not None:
            body["archived"] = archived

        if not body:
            return {"error": "No updates provided. Set content or archived."}

        data = _request("patch", f"/blocks/{block_id}", token, json=body)
        if "error" in data:
            return data

        return {
            "id": data.get("id", ""),
            "type": data.get("type", ""),
            "status": "updated",
        }

    @mcp.tool()
    def notion_delete_block(block_id: str) -> dict[str, Any]:
        """
        Delete a block (moves to trash).

        Args:
            block_id: Notion block ID to delete (required)

        Returns:
            Dict with deleted block info (id, status)
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not block_id:
            return {"error": "block_id is required"}

        data = _request("delete", f"/blocks/{block_id}", token)
        if "error" in data:
            return data

        return {
            "id": data.get("id", ""),
            "status": "deleted",
        }

    @mcp.tool()
    def notion_append_blocks(
        block_id: str,
        content: str,
        block_type: str = "paragraph",
    ) -> dict[str, Any]:
        """
        Append content blocks to a page or block.

        Args:
            block_id: Page ID or parent block ID to append to (required)
            content: Text content to append (required). For multiple blocks,
                separate with newlines. Max 100 blocks per request.
            block_type: Block type to create: "paragraph", "heading_1",
                "heading_2", "heading_3", "bulleted_list_item",
                "numbered_list_item", "to_do", "quote", "callout"
                (default "paragraph")

        Returns:
            Dict with appended block info or error
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not block_id or not content:
            return {"error": "block_id and content are required"}

        try:
            validated = BlockType(block_type)
        except ValueError:
            return {
                "error": f"Invalid block_type: {block_type!r}",
                "help": f"Must be one of: {', '.join(sorted(BlockType))}",
            }

        lines = [line for line in content.split("\n") if line.strip()]
        if not lines:
            return {"error": "content is empty after stripping blank lines"}
        if len(lines) > 100:
            return {"error": "Too many blocks. Notion API allows max 100 per request."}

        children = []
        for line in lines:
            block: dict[str, Any] = {
                "object": "block",
                "type": validated,
                validated: {
                    "rich_text": [{"type": "text", "text": {"content": line}}],
                },
            }
            match validated:
                case BlockType.TO_DO:
                    block[validated]["checked"] = False
            children.append(block)

        data = _request(
            "patch",
            f"/blocks/{block_id}/children",
            token,
            json={"children": children},
        )
        if "error" in data:
            return data

        return {
            "block_id": block_id,
            "blocks_added": len(children),
            "status": "appended",
        }
