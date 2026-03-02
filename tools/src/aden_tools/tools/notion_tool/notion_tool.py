"""
Notion Tool - Read, write, search and manage Notion pages and databases.

Uses the official Notion API (v1) via httpx.
Credentials: NOTION_API_KEY (Integration Token from notion.so/my-integrations)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class _NotionClient:
    def __init__(self, api_key: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict:
        if response.status_code == 200:
            return response.json()
        if response.status_code == 401:
            return {"error": "Invalid Notion API key. Check your integration token."}
        if response.status_code == 403:
            return {"error": "Notion integration lacks permission to access this resource."}
        if response.status_code == 404:
            return {"error": "Notion resource not found. Ensure the integration is added to the page/database."}
        if response.status_code == 429:
            return {"error": "Notion rate limit exceeded. Try again in a few seconds."}
        try:
            detail = response.json().get("message", "")
        except Exception:
            detail = ""
        return {"error": f"Notion API error {response.status_code}: {detail}"}

    def search(self, query: str, filter_type: str | None = None, page_size: int = 10) -> dict:
        payload: dict[str, Any] = {"query": query, "page_size": min(page_size, 100)}
        if filter_type in ("page", "database"):
            payload["filter"] = {"value": filter_type, "property": "object"}
        try:
            r = httpx.post(f"{NOTION_API_BASE}/search", headers=self._headers, json=payload, timeout=30.0)
            return self._handle_response(r)
        except httpx.TimeoutException:
            return {"error": "Notion request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    def get_page(self, page_id: str) -> dict:
        try:
            r = httpx.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=self._headers, timeout=30.0)
            return self._handle_response(r)
        except httpx.TimeoutException:
            return {"error": "Notion request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    def get_block_children(self, block_id: str, page_size: int = 100) -> dict:
        try:
            r = httpx.get(
                f"{NOTION_API_BASE}/blocks/{block_id}/children",
                headers=self._headers,
                params={"page_size": min(page_size, 100)},
                timeout=30.0,
            )
            return self._handle_response(r)
        except httpx.TimeoutException:
            return {"error": "Notion request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    def append_blocks(self, block_id: str, children: list[dict]) -> dict:
        try:
            r = httpx.patch(
                f"{NOTION_API_BASE}/blocks/{block_id}/children",
                headers=self._headers,
                json={"children": children},
                timeout=30.0,
            )
            return self._handle_response(r)
        except httpx.TimeoutException:
            return {"error": "Notion request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    def create_page(self, parent: dict, properties: dict, children: list[dict]) -> dict:
        try:
            r = httpx.post(
                f"{NOTION_API_BASE}/pages",
                headers=self._headers,
                json={"parent": parent, "properties": properties, "children": children},
                timeout=30.0,
            )
            return self._handle_response(r)
        except httpx.TimeoutException:
            return {"error": "Notion request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    def query_database(self, database_id: str, filter_payload: dict | None = None,
                       sorts: list[dict] | None = None, page_size: int = 10) -> dict:
        payload: dict[str, Any] = {"page_size": min(page_size, 100)}
        if filter_payload:
            payload["filter"] = filter_payload
        if sorts:
            payload["sorts"] = sorts
        try:
            r = httpx.post(
                f"{NOTION_API_BASE}/databases/{database_id}/query",
                headers=self._headers,
                json=payload,
                timeout=30.0,
            )
            return self._handle_response(r)
        except httpx.TimeoutException:
            return {"error": "Notion request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}


def _rich_text(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _build_block(block_type: str, content: str, checked: bool = False) -> dict:
    if block_type == "to_do":
        return {"object": "block", "type": "to_do",
                "to_do": {"rich_text": _rich_text(content), "checked": checked}}
    return {"object": "block", "type": block_type, block_type: {"rich_text": _rich_text(content)}}


def _blocks_to_text(blocks: list[dict]) -> str:
    lines: list[str] = []
    for block in blocks:
        btype = block.get("type", "")
        data = block.get(btype, {})
        rich = data.get("rich_text", [])
        text = "".join(t.get("plain_text", "") for t in rich)
        if btype == "heading_1":
            lines.append(f"# {text}")
        elif btype == "heading_2":
            lines.append(f"## {text}")
        elif btype == "heading_3":
            lines.append(f"### {text}")
        elif btype == "bulleted_list_item":
            lines.append(f"• {text}")
        elif btype == "numbered_list_item":
            lines.append(f"1. {text}")
        elif btype == "to_do":
            tick = "☑" if data.get("checked") else "☐"
            lines.append(f"{tick} {text}")
        elif btype == "code":
            lang = data.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")
        elif btype == "divider":
            lines.append("---")
        elif text:
            lines.append(text)
    return "\n".join(lines)


def _extract_page_title(page: dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            return "".join(p.get("plain_text", "") for p in parts)
    return page.get("id", "Untitled")


def register_tools(mcp: FastMCP, credentials=None) -> None:
    """Register Notion tools with the MCP server."""

    def _get_api_key() -> str | None:
        if credentials is not None:
            return credentials.get("notion")
        return os.getenv("NOTION_API_KEY")

    @mcp.tool()
    def notion_search(
        query: str,
        filter_type: Literal["page", "database", "all"] = "all",
        max_results: int = 10,
    ) -> dict:
        """
        Search Notion for pages or databases by title/content.

        Use when you need to find a specific Notion page, note, doc, or database
        by name or keyword. Returns titles, IDs, and URLs.

        Args:
            query: Text to search for (page/database titles and content)
            filter_type: Filter results to "page", "database", or "all"
            max_results: Maximum number of results to return (1-20)

        Returns:
            Dict with list of matching results (id, title, type, url, last_edited)
        """
        api_key = _get_api_key()
        if not api_key:
            return {"error": "Notion API key not configured. Set NOTION_API_KEY environment variable."}
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}
        client = _NotionClient(api_key)
        ftype = filter_type if filter_type != "all" else None
        raw = client.search(query, filter_type=ftype, page_size=min(max_results, 20))
        if "error" in raw:
            return raw
        results = []
        for item in raw.get("results", []):
            if item.get("object") == "page":
                title = _extract_page_title(item)
            else:
                title_list = item.get("title", [])
                title = title_list[0].get("plain_text", "Untitled") if title_list else "Untitled"
            results.append({
                "id": item.get("id"),
                "type": item.get("object"),
                "title": title,
                "url": item.get("url"),
                "last_edited": item.get("last_edited_time"),
            })
        return {"results": results, "total": len(results)}

    @mcp.tool()
    def notion_read_page(page_id: str) -> dict:
        """
        Read the full content of a Notion page as plain text.

        Use when you need to read the text content of a specific Notion page.
        Fetches all blocks and converts them to readable text.

        Args:
            page_id: The Notion page ID (UUID with or without dashes)

        Returns:
            Dict with page title, url, and full text content
        """
        api_key = _get_api_key()
        if not api_key:
            return {"error": "Notion API key not configured."}
        if not page_id:
            return {"error": "page_id is required"}
        client = _NotionClient(api_key)
        page = client.get_page(page_id)
        if "error" in page:
            return page
        blocks_raw = client.get_block_children(page_id)
        if "error" in blocks_raw:
            return blocks_raw
        blocks = blocks_raw.get("results", [])
        content = _blocks_to_text(blocks)
        title = _extract_page_title(page)
        return {
            "id": page.get("id"),
            "title": title,
            "url": page.get("url"),
            "content": content,
            "block_count": len(blocks),
        }

    @mcp.tool()
    def notion_create_page(
        parent_id: str,
        title: str,
        content: str = "",
        parent_type: Literal["database", "page"] = "page",
    ) -> dict:
        """
        Create a new Notion page inside a parent page or database.

        Use when you need to create a new note, document, or entry in Notion.
        The content is added as paragraph blocks under the title.

        Args:
            parent_id: ID of the parent page or database
            title: Title for the new page
            content: Optional initial text content for the page body
            parent_type: Whether the parent is a "page" or "database"

        Returns:
            Dict with the new page id, title, and url
        """
        api_key = _get_api_key()
        if not api_key:
            return {"error": "Notion API key not configured."}
        if not title:
            return {"error": "title is required"}
        if len(title) > 2000:
            return {"error": "title must be under 2000 characters"}
        client = _NotionClient(api_key)
        if parent_type == "database":
            parent = {"type": "database_id", "database_id": parent_id}
        else:
            parent = {"type": "page_id", "page_id": parent_id}
        properties = {"title": {"title": _rich_text(title)}}
        children: list[dict] = []
        if content:
            for chunk in [content[i:i+2000] for i in range(0, len(content), 2000)]:
                children.append(_build_block("paragraph", chunk))
        result = client.create_page(parent, properties, children)
        if "error" in result:
            return result
        return {"id": result.get("id"), "title": title, "url": result.get("url"), "created": True}

    @mcp.tool()
    def notion_append_to_page(
        page_id: str,
        content: str,
        block_type: Literal["paragraph", "heading_1", "heading_2", "heading_3",
                            "to_do", "bulleted_list_item"] = "paragraph",
        checked: bool = False,
    ) -> dict:
        """
        Append new content blocks to the end of an existing Notion page.

        Use when you need to add text, headings, to-do items, or bullet points
        to an existing Notion page without replacing existing content.

        Args:
            page_id: The Notion page ID to append content to
            content: Text content to append
            block_type: Type of block — paragraph, heading_1/2/3, to_do, bulleted_list_item
            checked: For to_do blocks, whether the checkbox is pre-checked

        Returns:
            Dict confirming the append with block count added
        """
        api_key = _get_api_key()
        if not api_key:
            return {"error": "Notion API key not configured."}
        if not content:
            return {"error": "content is required"}
        client = _NotionClient(api_key)
        chunks = [content[i:i+2000] for i in range(0, len(content), 2000)]
        children = [_build_block(block_type, chunk, checked=checked) for chunk in chunks]
        result = client.append_blocks(page_id, children)
        if "error" in result:
            return result
        return {"page_id": page_id, "blocks_added": len(children), "block_type": block_type, "success": True}

    @mcp.tool()
    def notion_query_database(database_id: str, max_results: int = 10) -> dict:
        """
        Query all entries (rows) from a Notion database.

        Use when you need to list items, tasks, or records stored in a Notion
        database. Returns page titles, IDs, URLs and last-edited timestamps.

        Args:
            database_id: The Notion database ID to query
            max_results: Maximum number of entries to return (1-50)

        Returns:
            Dict with list of database entries (id, title, url, last_edited)
        """
        api_key = _get_api_key()
        if not api_key:
            return {"error": "Notion API key not configured."}
        if not database_id:
            return {"error": "database_id is required"}
        client = _NotionClient(api_key)
        raw = client.query_database(database_id, page_size=min(max_results, 50))
        if "error" in raw:
            return raw
        entries = []
        for item in raw.get("results", []):
            entries.append({
                "id": item.get("id"),
                "title": _extract_page_title(item),
                "url": item.get("url"),
                "last_edited": item.get("last_edited_time"),
                "created": item.get("created_time"),
            })
        return {
            "database_id": database_id,
            "entries": entries,
            "total": len(entries),
            "has_more": raw.get("has_more", False),
        }
