"""
Notion Tool - Interact with Notion pages and databases.

Supports:
- Integration Token (NOTION_API_KEY)

API Reference: https://developers.notion.com/reference
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

try:
    from notion_client import APIResponseError, Client
except ImportError:
    Client = None
    APIResponseError = None

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _sanitize_error_message(error: Exception) -> str:
    """Sanitize error messages."""
    error_str = str(error)
    if "Authorization" in error_str or "Bearer" in error_str:
        return "Authentication error"
    return f"Notion API error: {error_str}"


class _NotionClient:
    """Internal client wrapping Notion SDK."""

    def __init__(self, token: str):
        if Client is None:
            raise ImportError(
                "notion-client is not installed. "
                "Please install it with `pip install notion-client`."
            )
        self.client = Client(auth=token)

    def search(
        self,
        query: str,
        filter_type: str | None = None,
        sort_direction: str = "descending",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search pages or databases."""
        kwargs: dict[str, Any] = {
            "query": query,
            "page_size": min(limit, 100),
            "sort": {
                "direction": sort_direction,
                "timestamp": "last_edited_time",
            },
        }
        if filter_type:
            kwargs["filter"] = {
                "value": filter_type,
                "property": "object",
            }

        try:
            return self.client.search(**kwargs)
        except Exception as e:
            return {"error": _sanitize_error_message(e)}

    def get_page(self, page_id: str) -> dict[str, Any]:
        """Retrieve a page."""
        try:
            return self.client.pages.retrieve(page_id=page_id)
        except Exception as e:
            return {"error": _sanitize_error_message(e)}

    def get_block_children(self, block_id: str, limit: int = 100) -> dict[str, Any]:
        """Retrieve block children (page content)."""
        try:
            return self.client.blocks.children.list(block_id=block_id, page_size=limit)
        except Exception as e:
            return {"error": _sanitize_error_message(e)}

    def create_page(
        self,
        parent_id: str,
        title: str,
        body: str | None = None,
        parent_type: str = "page_id",
    ) -> dict[str, Any]:
        """Create a new page."""
        parent = {parent_type: parent_id}

        properties: dict[str, Any] = {}

        # Structure depends on parent type
        if parent_type == "database_id":
            # Common default for new databases: Name as title
            properties = {"Name": {"title": [{"text": {"content": title}}]}}
        else:
            # Page parent
            properties = {
                "title": [
                    {
                        "text": {
                            "content": title,
                        }
                    }
                ]
            }

        children = []
        if body:
            # Simple paragraph block
            children.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": body}}]},
                }
            )

        try:
            return self.client.pages.create(
                parent=parent, properties=properties, children=children if children else None
            )
        except Exception as e:
            return {"error": _sanitize_error_message(e)}

    def append_block(self, block_id: str, content: str) -> dict[str, Any]:
        """Append a paragraph block to a parent block/page."""
        children = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
            }
        ]
        try:
            return self.client.blocks.children.append(block_id=block_id, children=children)
        except Exception as e:
            return {"error": _sanitize_error_message(e)}


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
                return None
            return token
        return os.getenv("NOTION_API_KEY")

    def _get_client_setup() -> _NotionClient | dict[str, str]:
        """Get a Notion client."""
        token = _get_token()
        if not token:
            return {
                "error": "Notion credentials not configured",
                "help": "Set NOTION_API_KEY environment variable.",
            }
        try:
            return _NotionClient(token)
        except ImportError as e:
            return {"error": str(e)}

    @mcp.tool()
    def notion_search(
        query: str,
        filter_type: str | None = None,
        limit: int = 10,
    ) -> dict:
        """
        Search for pages or databases in Notion.

        Args:
            query: Text to search for.
            filter_type: Optional filter ("page" or "database").
            limit: Max results (default 10).

        Returns:
            Dict with search results or error.
        """
        client = _get_client_setup()
        if isinstance(client, dict):
            return client
        return client.search(query, filter_type=filter_type, limit=limit)

    @mcp.tool()
    def notion_get_page(
        page_id: str,
    ) -> dict:
        """
        Get metadata and content of a Notion page.

        Args:
            page_id: The UUID of the page.

        Returns:
            Dict with page info and content (children blocks).
        """
        client = _get_client_setup()
        if isinstance(client, dict):
            return client

        page = client.get_page(page_id)
        if "error" in page:
            return page

        # Also fetch content (first 100 blocks)
        content = client.get_block_children(page_id)
        if "error" in content:
            return {"page": page, "content_error": content["error"]}

        return {"page": page, "content": content}

    @mcp.tool()
    def notion_create_page(
        parent_id: str,
        title: str,
        body: str | None = None,
        parent_type: str = "page_id",
    ) -> dict:
        """
        Create a new page in Notion.

        Args:
            parent_id: UUID of the parent page or database.
            title: Title of the new page.
            body: Optional text content (added as a paragraph block).
            parent_type: "page_id" (default) or "database_id".

        Returns:
            Dict with created page info or error.
        """
        client = _get_client_setup()
        if isinstance(client, dict):
            return client
        return client.create_page(parent_id, title, body, parent_type)

    @mcp.tool()
    def notion_append_text(
        page_id: str,
        text: str,
    ) -> dict:
        """
        Append a text paragraph to the end of a page.

        Args:
            page_id: UUID of the page/block to append to.
            text: Content of the paragraph.

        Returns:
            Dict with appended block info or error.
        """
        client = _get_client_setup()
        if isinstance(client, dict):
            return client
        return client.append_block(page_id, text)
