"""
Confluence Tool - Wiki & knowledge management via REST API v2.

Supports:
- Atlassian API token (Basic auth: email + token)
- Spaces, pages, content search (CQL)
- Confluence Cloud API v2

API Reference: https://developer.atlassian.com/cloud/confluence/rest/v2/intro/
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_credentials(credentials: CredentialStoreAdapter | None) -> tuple[str | None, str | None, str | None]:
    """Return (domain, email, api_token)."""
    if credentials is not None:
        domain = credentials.get("confluence_domain")
        email = credentials.get("confluence_email")
        token = credentials.get("confluence_token")
        return domain, email, token
    return (
        os.getenv("CONFLUENCE_DOMAIN"),
        os.getenv("CONFLUENCE_EMAIL"),
        os.getenv("CONFLUENCE_API_TOKEN"),
    )


def _base_url(domain: str) -> str:
    if domain.startswith("https://"):
        return domain.rstrip("/")
    return f"https://{domain}"


def _auth_header(email: str, token: str) -> str:
    encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
    return f"Basic {encoded}"


def _request(
    method: str, url: str, email: str, token: str, **kwargs: Any
) -> dict[str, Any]:
    """Make a request to the Confluence API."""
    headers = {
        "Authorization": _auth_header(email, token),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = getattr(httpx, method)(
            url,
            headers=headers,
            timeout=30.0,
            **kwargs,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your Confluence credentials."}
        if resp.status_code == 404:
            return {"error": "Not found"}
        if resp.status_code not in (200, 201, 204):
            return {"error": f"Confluence API error {resp.status_code}: {resp.text[:500]}"}
        if resp.status_code == 204 or not resp.content:
            return {"status": "ok"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Confluence timed out"}
    except Exception as e:
        return {"error": f"Confluence request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "CONFLUENCE_DOMAIN, CONFLUENCE_EMAIL, and CONFLUENCE_API_TOKEN not set",
        "help": "Generate an API token at https://id.atlassian.com/manage/api-tokens",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Confluence tools with the MCP server."""

    @mcp.tool()
    def confluence_list_spaces(limit: int = 25) -> dict[str, Any]:
        """
        List spaces in the Confluence instance.

        Args:
            limit: Max results (1-250, default 25)

        Returns:
            Dict with spaces list (id, key, name, type, status)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()

        url = f"{_base_url(domain)}/wiki/api/v2/spaces"
        data = _request("get", url, email, token, params={"limit": max(1, min(limit, 250))})
        if "error" in data:
            return data

        spaces = []
        for s in data.get("results", []):
            spaces.append({
                "id": s.get("id", ""),
                "key": s.get("key", ""),
                "name": s.get("name", ""),
                "type": s.get("type", ""),
                "status": s.get("status", ""),
            })
        return {"spaces": spaces, "count": len(spaces)}

    @mcp.tool()
    def confluence_list_pages(
        space_id: str = "",
        title: str = "",
        limit: int = 25,
    ) -> dict[str, Any]:
        """
        List pages, optionally filtered by space or title.

        Args:
            space_id: Filter by space ID (optional)
            title: Filter by exact page title (optional)
            limit: Max results (1-250, default 25)

        Returns:
            Dict with pages list (id, title, space_id, status, version)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()

        params: dict[str, Any] = {"limit": max(1, min(limit, 250))}
        if title:
            params["title"] = title

        if space_id:
            url = f"{_base_url(domain)}/wiki/api/v2/spaces/{space_id}/pages"
        else:
            url = f"{_base_url(domain)}/wiki/api/v2/pages"

        data = _request("get", url, email, token, params=params)
        if "error" in data:
            return data

        pages = []
        for p in data.get("results", []):
            ver = p.get("version") or {}
            pages.append({
                "id": p.get("id", ""),
                "title": p.get("title", ""),
                "space_id": p.get("spaceId", ""),
                "status": p.get("status", ""),
                "version": ver.get("number", 0),
                "created_at": p.get("createdAt", ""),
            })
        return {"pages": pages, "count": len(pages)}

    @mcp.tool()
    def confluence_get_page(
        page_id: str,
        body_format: str = "storage",
    ) -> dict[str, Any]:
        """
        Get a specific Confluence page by ID.

        Args:
            page_id: Page ID (required)
            body_format: Body format: storage, view, or atlas_doc_format (default storage)

        Returns:
            Dict with page details including body content
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not page_id:
            return {"error": "page_id is required"}

        url = f"{_base_url(domain)}/wiki/api/v2/pages/{page_id}"
        data = _request("get", url, email, token, params={"body-format": body_format})
        if "error" in data:
            return data

        ver = data.get("version") or {}
        body = data.get("body") or {}
        body_content = ""
        for fmt in (body_format, "storage", "view"):
            if fmt in body:
                body_content = body[fmt].get("value", "")
                break

        if len(body_content) > 5000:
            body_content = body_content[:5000] + "... (truncated)"

        return {
            "id": data.get("id", ""),
            "title": data.get("title", ""),
            "space_id": data.get("spaceId", ""),
            "status": data.get("status", ""),
            "version": ver.get("number", 0),
            "body": body_content,
            "created_at": data.get("createdAt", ""),
        }

    @mcp.tool()
    def confluence_create_page(
        space_id: str,
        title: str,
        body: str,
        parent_id: str = "",
    ) -> dict[str, Any]:
        """
        Create a new page in Confluence.

        Args:
            space_id: Space ID to create the page in (required)
            title: Page title (required)
            body: Page content in Confluence storage format (XHTML) (required)
            parent_id: Parent page ID for child pages (optional)

        Returns:
            Dict with created page id, title, and status
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not space_id or not title or not body:
            return {"error": "space_id, title, and body are required"}

        payload: dict[str, Any] = {
            "spaceId": space_id,
            "status": "current",
            "title": title,
            "body": {
                "representation": "storage",
                "value": body,
            },
        }
        if parent_id:
            payload["parentId"] = parent_id

        url = f"{_base_url(domain)}/wiki/api/v2/pages"
        data = _request("post", url, email, token, json=payload)
        if "error" in data:
            return data

        return {
            "id": data.get("id", ""),
            "title": data.get("title", ""),
            "status": "created",
        }

    @mcp.tool()
    def confluence_search(
        query: str,
        space_key: str = "",
        limit: int = 25,
    ) -> dict[str, Any]:
        """
        Search Confluence content using CQL (Confluence Query Language).

        Args:
            query: Search text (will be used in CQL text~ query)
            space_key: Filter by space key e.g. "DEV" (optional)
            limit: Max results (1-50, default 25)

        Returns:
            Dict with search results (title, excerpt, page_id, space)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not query:
            return {"error": "query is required"}

        cql_parts = [f'type = page AND text ~ "{query}"']
        if space_key:
            cql_parts.append(f'space = "{space_key}"')

        cql = " AND ".join(cql_parts) + " ORDER BY lastModified desc"

        url = f"{_base_url(domain)}/wiki/rest/api/search"
        data = _request("get", url, email, token, params={
            "cql": cql,
            "limit": max(1, min(limit, 50)),
        })
        if "error" in data:
            return data

        results = []
        for r in data.get("results", []):
            content = r.get("content") or {}
            space = content.get("space") or {}
            results.append({
                "title": r.get("title", ""),
                "excerpt": (r.get("excerpt", "") or "")[:300],
                "page_id": content.get("id", ""),
                "space_key": space.get("key", ""),
                "space_name": space.get("name", ""),
                "last_modified": r.get("lastModified", ""),
            })
        return {"results": results, "count": len(results)}
