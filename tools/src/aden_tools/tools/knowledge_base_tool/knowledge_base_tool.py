"""
Knowledge Base Tool - Access external knowledge bases, wikis, and documentation portals.

Supports:
- Confluence: Search and retrieve content from Atlassian Confluence wikis
- Notion: Search and retrieve content from Notion workspaces
- Generic Documentation: Scrape and search documentation portals

All tools provide real-time access to external knowledge sources for agent reasoning.
"""

from __future__ import annotations

import os
import re
import time
from typing import TYPE_CHECKING, Literal
from urllib.parse import urljoin, urlparse

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register knowledge base tools with the MCP server."""

    def _get_credential(name: str) -> str | None:
        """Get a credential from the adapter or environment."""
        if credentials is not None:
            return credentials.get(name)
        spec_map = {
            "confluence": "CONFLUENCE_API_TOKEN",
            "notion": "NOTION_API_KEY",
        }
        return os.getenv(spec_map.get(name, name.upper() + "_API_KEY"))

    def _make_request(
        method: str,
        url: str,
        headers: dict,
        params: dict | None = None,
        json_data: dict | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> dict:
        """Make an HTTP request with retry logic."""
        for attempt in range(max_retries + 1):
            try:
                if method.upper() == "GET":
                    response = httpx.get(url, headers=headers, params=params, timeout=timeout)
                elif method.upper() == "POST":
                    response = httpx.post(url, headers=headers, json=json_data, timeout=timeout)
                else:
                    return {"error": f"Unsupported HTTP method: {method}"}

                if response.status_code == 429 and attempt < max_retries:
                    time.sleep(2**attempt)
                    continue

                if response.status_code == 401:
                    return {"error": "Authentication failed. Check your API credentials."}
                elif response.status_code == 403:
                    return {"error": "Access forbidden. Check permissions."}
                elif response.status_code == 404:
                    return {"error": "Resource not found."}
                elif response.status_code == 429:
                    return {"error": "Rate limit exceeded. Please try again later."}
                elif response.status_code >= 400:
                    return {"error": f"Request failed: HTTP {response.status_code}"}

                return {"status_code": response.status_code, "data": response.json()}

            except httpx.TimeoutException:
                if attempt < max_retries:
                    time.sleep(2**attempt)
                    continue
                return {"error": "Request timed out"}
            except httpx.RequestError as e:
                return {"error": f"Network error: {str(e)}"}
            except Exception as e:
                return {"error": f"Request failed: {str(e)}"}

        return {"error": "Max retries exceeded"}

    @mcp.tool()
    def confluence_search(
        query: str,
        confluence_url: str | None = None,
        limit: int = 10,
        space_key: str | None = None,
        content_type: Literal["page", "blogpost", "comment", "all"] = "all",
    ) -> dict:
        """
        Search Confluence wiki for pages, blog posts, and content.

        Uses Confluence's CQL (Confluence Query Language) for powerful searching.
        Requires CONFLUENCE_API_TOKEN and CONFLUENCE_URL environment variables.

        Args:
            query: Search query (1-500 chars). Supports CQL syntax.
            confluence_url: Base URL of Confluence instance (e.g., 'https://company.atlassian.net/wiki')
                           If not provided, uses CONFLUENCE_URL env var.
            limit: Maximum results to return (1-50)
            space_key: Limit search to a specific space
            content_type: Type of content to search

        Returns:
            Dict with search results including title, url, excerpt, and metadata
        """
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}

        limit = max(1, min(limit, 50))

        api_token = _get_credential("confluence")
        if not api_token:
            return {
                "error": "Confluence credentials not configured",
                "help": "Set CONFLUENCE_API_TOKEN and CONFLUENCE_URL environment variables",
                "setup": "Get API token from: https://id.atlassian.com/manage-profile/security/api-tokens",
            }

        base_url = confluence_url or os.getenv("CONFLUENCE_URL")
        if not base_url:
            return {
                "error": "Confluence URL not configured",
                "help": "Set CONFLUENCE_URL environment variable or provide confluence_url parameter",
            }

        base_url = base_url.rstrip("/")

        cql_parts = [f'text ~ "{query}"']
        if space_key:
            cql_parts.append(f"space = '{space_key}'")
        if content_type != "all":
            cql_parts.append(f"type = '{content_type}'")

        cql = " AND ".join(cql_parts)

        result = _make_request(
            "GET",
            f"{base_url}/rest/api/content/search",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
            },
            params={"cql": cql, "limit": limit, "expand": "body.view,space,version"},
        )

        if "error" in result:
            return result

        data = result.get("data", {})
        results = []
        for item in data.get("results", []):
            body = item.get("body", {}).get("view", {}).get("value", "")
            results.append(
                {
                    "id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "type": item.get("type", ""),
                    "url": f"{base_url}{item.get('_links', {}).get('webui', '')}",
                    "space": item.get("space", {}).get("key", ""),
                    "excerpt": body[:500] + "..." if len(body) > 500 else body,
                    "version": item.get("version", {}).get("number", 0),
                    "last_updated": item.get("version", {}).get("when", ""),
                    "author": item.get("version", {}).get("by", {}).get("displayName", ""),
                }
            )

        return {
            "query": query,
            "source": "confluence",
            "results": results,
            "total": len(results),
        }

    @mcp.tool()
    def confluence_get_page(
        page_id: str,
        confluence_url: str | None = None,
        include_attachments: bool = False,
    ) -> dict:
        """
        Retrieve a specific Confluence page by ID with full content.

        Args:
            page_id: The Confluence page ID
            confluence_url: Base URL of Confluence instance
            include_attachments: Whether to include attachment metadata

        Returns:
            Dict with page content, metadata, and optionally attachments
        """
        if not page_id:
            return {"error": "Page ID is required"}

        api_token = _get_credential("confluence")
        if not api_token:
            return {
                "error": "Confluence credentials not configured",
                "help": "Set CONFLUENCE_API_TOKEN environment variable",
            }

        base_url = confluence_url or os.getenv("CONFLUENCE_URL")
        if not base_url:
            return {"error": "Confluence URL not configured"}

        base_url = base_url.rstrip("/")
        expands = ["body.view", "version", "space", "ancestors"]
        if include_attachments:
            expands.append("attachments")

        result = _make_request(
            "GET",
            f"{base_url}/rest/api/content/{page_id}",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
            },
            params={"expand": ",".join(expands)},
        )

        if "error" in result:
            return result

        item = result.get("data", {})
        page_data = {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "type": item.get("type", ""),
            "url": f"{base_url}{item.get('_links', {}).get('webui', '')}",
            "space": item.get("space", {}).get("key", ""),
            "content": item.get("body", {}).get("view", {}).get("value", ""),
            "version": item.get("version", {}).get("number", 0),
            "last_updated": item.get("version", {}).get("when", ""),
            "author": item.get("version", {}).get("by", {}).get("displayName", ""),
        }

        ancestors = item.get("ancestors", [])
        if ancestors:
            page_data["path"] = " > ".join(
                [a.get("title", "") for a in ancestors] + [page_data["title"]]
            )

        if include_attachments:
            attachments = item.get("attachments", {}).get("results", [])
            page_data["attachments"] = [
                {
                    "id": a.get("id", ""),
                    "title": a.get("title", ""),
                    "size": a.get("extensions", {}).get("fileSize", 0),
                    "type": a.get("extensions", {}).get("mediaType", ""),
                }
                for a in attachments
            ]

        return page_data

    @mcp.tool()
    def notion_search(
        query: str,
        filter_type: Literal["page", "database", "all"] = "all",
        sort_direction: Literal["ascending", "descending"] = "descending",
        page_size: int = 10,
    ) -> dict:
        """
        Search Notion workspace for pages and databases.

        Uses Notion's search API to find content across the workspace.

        Args:
            query: Search query (1-200 chars). Empty query returns recent pages.
            filter_type: Type of content to search
            sort_direction: Sort results by last edited time
            page_size: Number of results per page (1-100)

        Returns:
            Dict with search results including title, url, and content preview
        """
        if query and len(query) > 200:
            return {"error": "Query must be 1-200 characters"}

        page_size = max(1, min(page_size, 100))

        api_key = _get_credential("notion")
        if not api_key:
            return {
                "error": "Notion credentials not configured",
                "help": "Set NOTION_API_KEY environment variable",
                "setup": "Create integration at: https://www.notion.so/my-integrations",
            }

        payload = {
            "query": query or "",
            "page_size": page_size,
            "sort": {
                "direction": sort_direction,
                "timestamp": "last_edited_time",
            },
        }

        if filter_type != "all":
            payload["filter"] = {
                "property": "object",
                "value": filter_type,
            }

        result = _make_request(
            "POST",
            "https://api.notion.com/v1/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json_data=payload,
        )

        if "error" in result:
            return result

        data = result.get("data", {})
        results = []
        for item in data.get("results", []):
            title = ""
            if "properties" in item:
                title_prop = item["properties"].get("title") or item["properties"].get("Name") or {}
                if title_prop.get("title"):
                    title = "".join([t.get("plain_text", "") for t in title_prop["title"]])
            elif "title" in item:
                title_items = item.get("title", [])
                title = (
                    "".join([t.get("plain_text", "") for t in title_items]) if title_items else ""
                )

            url = item.get("url", "")
            page_id = item.get("id", "").replace("-", "")

            results.append(
                {
                    "id": item.get("id", ""),
                    "title": title or "Untitled",
                    "type": item.get("object", ""),
                    "url": url or f"https://notion.so/{page_id}",
                    "last_edited": item.get("last_edited_time", ""),
                    "created": item.get("created_time", ""),
                    "parent_type": item.get("parent", {}).get("type", ""),
                }
            )

        return {
            "query": query or "",
            "source": "notion",
            "results": results,
            "total": len(results),
            "has_more": data.get("has_more", False),
            "next_cursor": data.get("next_cursor"),
        }

    @mcp.tool()
    def notion_get_page(
        page_id: str,
        include_content: bool = True,
        include_blocks: bool = False,
    ) -> dict:
        """
        Retrieve a specific Notion page with content.

        Args:
            page_id: The Notion page ID (with or without hyphens)
            include_content: Whether to include page properties
            include_blocks: Whether to include page block content

        Returns:
            Dict with page content, properties, and optionally blocks
        """
        if not page_id:
            return {"error": "Page ID is required"}

        page_id = page_id.replace("-", "")

        api_key = _get_credential("notion")
        if not api_key:
            return {
                "error": "Notion credentials not configured",
                "help": "Set NOTION_API_KEY environment variable",
            }

        result = _make_request(
            "GET",
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Notion-Version": "2022-06-28",
            },
        )

        if "error" in result:
            return result

        item = result.get("data", {})

        title = ""
        properties = {}
        if include_content and "properties" in item:
            for prop_name, prop_value in item["properties"].items():
                if prop_value.get("type") == "title":
                    title = "".join([t.get("plain_text", "") for t in prop_value.get("title", [])])
                elif prop_value.get("type") == "rich_text":
                    text = "".join(
                        [t.get("plain_text", "") for t in prop_value.get("rich_text", [])]
                    )
                    if text:
                        properties[prop_name] = text
                elif prop_value.get("type") in [
                    "number",
                    "date",
                    "select",
                    "multi_select",
                    "checkbox",
                ]:
                    properties[prop_name] = prop_value.get(prop_value["type"])

        page_data = {
            "id": item.get("id", ""),
            "title": title or "Untitled",
            "url": item.get("url", ""),
            "created": item.get("created_time", ""),
            "last_edited": item.get("last_edited_time", ""),
            "parent_type": item.get("parent", {}).get("type", ""),
            "parent_id": item.get("parent", {}).get("page_id")
            or item.get("parent", {}).get("database_id", ""),
        }

        if include_content:
            page_data["properties"] = properties

        if include_blocks:
            blocks_result = _make_request(
                "GET",
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Notion-Version": "2022-06-28",
                },
                params={"page_size": 100},
            )
            if "error" not in blocks_result:
                blocks = []
                for block in blocks_result.get("data", {}).get("results", []):
                    block_type = block.get("type", "")
                    if block_type and block.get(block_type):
                        text_content = ""
                        rich_text = block[block_type].get("rich_text", [])
                        text_content = "".join([t.get("plain_text", "") for t in rich_text])
                        blocks.append(
                            {
                                "type": block_type,
                                "text": text_content,
                            }
                        )
                page_data["blocks"] = blocks

        return page_data

    @mcp.tool()
    def docs_search(
        base_url: str,
        query: str,
        search_paths: list[str] | None = None,
        max_pages: int = 20,
    ) -> dict:
        """
        Search a documentation portal by crawling and indexing pages.

        Searches for content within a documentation website by crawling
        specified paths and matching query against page content.

        Args:
            base_url: Base URL of the documentation portal (e.g., 'https://docs.python.org/3/')
            query: Search query (1-200 chars)
            search_paths: URL paths to search (e.g., ['/tutorial/', '/reference/'])
                         If not provided, searches common doc paths
            max_pages: Maximum pages to crawl (1-50)

        Returns:
            Dict with matching pages including title, url, and matching excerpt
        """
        if not base_url:
            return {"error": "Base URL is required"}
        if not query or len(query) > 200:
            return {"error": "Query must be 1-200 characters"}

        max_pages = max(1, min(max_pages, 50))

        parsed_url = urlparse(base_url)
        if not parsed_url.scheme or not parsed_url.netloc:
            return {"error": "Invalid URL format. Include scheme (e.g., https://)"}

        if search_paths is None:
            search_paths = [
                "/",
                "/docs/",
                "/documentation/",
                "/guide/",
                "/api/",
                "/reference/",
                "/tutorial/",
            ]

        query_lower = query.lower()
        query_terms = re.findall(r"\w+", query_lower)

        results = []
        visited = set()
        to_visit = []

        for path in search_paths:
            full_url = urljoin(base_url, path)
            to_visit.append(full_url)

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                while to_visit and len(visited) < max_pages:
                    url = to_visit.pop(0)
                    if url in visited:
                        continue

                    try:
                        response = client.get(url)
                        if response.status_code != 200:
                            continue

                        visited.add(url)

                        content = response.text

                        title = ""
                        title_match = re.search(
                            r"<title[^>]*>([^<]+)</title>", content, re.IGNORECASE
                        )
                        if title_match:
                            title = title_match.group(1).strip()

                        text_content = re.sub(
                            r"<script[^>]*>.*?</script>",
                            "",
                            content,
                            flags=re.DOTALL | re.IGNORECASE,
                        )
                        text_content = re.sub(
                            r"<style[^>]*>.*?</style>",
                            "",
                            text_content,
                            flags=re.DOTALL | re.IGNORECASE,
                        )
                        text_content = re.sub(r"<[^>]+>", " ", text_content)
                        text_content = re.sub(r"\s+", " ", text_content).strip()

                        text_lower = text_content.lower()
                        score = 0
                        for term in query_terms:
                            score += text_lower.count(term)

                        if score > 0:
                            excerpt_start = 0
                            for term in query_terms:
                                pos = text_lower.find(term)
                                if pos != -1:
                                    excerpt_start = max(0, pos - 100)
                                    break

                            excerpt = text_content[excerpt_start : excerpt_start + 300]
                            if excerpt_start > 0:
                                excerpt = "..." + excerpt
                            if len(text_content) > excerpt_start + 300:
                                excerpt = excerpt + "..."

                            results.append(
                                {
                                    "title": title,
                                    "url": url,
                                    "excerpt": excerpt,
                                    "relevance_score": score,
                                }
                            )

                        if len(visited) < max_pages:
                            for match in re.finditer(r'href=["\']([^"\']+)["\']', content):
                                href = match.group(1)
                                if href.startswith("#") or href.startswith("javascript:"):
                                    continue
                                full_href = urljoin(url, href)
                                if (
                                    full_href.startswith(base_url)
                                    and full_href not in visited
                                    and full_href not in to_visit
                                ):
                                    to_visit.append(full_href)

                    except (httpx.RequestError, httpx.TimeoutException):
                        continue

        except Exception as e:
            return {"error": f"Failed to search documentation: {str(e)}"}

        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        results = results[:10]

        return {
            "query": query,
            "source": base_url,
            "source_type": "documentation_portal",
            "results": results,
            "total": len(results),
            "pages_crawled": len(visited),
        }

    @mcp.tool()
    def docs_get_page(
        url: str,
        extract_code_blocks: bool = False,
    ) -> dict:
        """
        Retrieve content from a documentation page.

        Args:
            url: URL of the documentation page
            extract_code_blocks: Whether to extract code blocks separately

        Returns:
            Dict with page title, content, and optionally code blocks
        """
        if not url:
            return {"error": "URL is required"}

        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            return {"error": "Invalid URL format"}

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                response = client.get(url)
                if response.status_code == 404:
                    return {"error": "Page not found"}
                elif response.status_code != 200:
                    return {"error": f"Failed to fetch page: HTTP {response.status_code}"}

                content = response.text

                title = ""
                title_match = re.search(r"<title[^>]*>([^<]+)</title>", content, re.IGNORECASE)
                if title_match:
                    title = title_match.group(1).strip()

                main_content = ""
                for selector in [
                    "main",
                    "article",
                    '[role="main"]',
                    ".content",
                    "#content",
                    ".documentation",
                ]:
                    match = re.search(
                        rf"<{selector}[^>]*>(.*?)</{selector}>", content, re.DOTALL | re.IGNORECASE
                    )
                    if match:
                        main_content = match.group(1)
                        break

                if not main_content:
                    main_content = content

                text_content = re.sub(
                    r"<script[^>]*>.*?</script>", "", main_content, flags=re.DOTALL | re.IGNORECASE
                )
                text_content = re.sub(
                    r"<style[^>]*>.*?</style>", "", text_content, flags=re.DOTALL | re.IGNORECASE
                )
                text_content = re.sub(r"<[^>]+>", " ", text_content)
                text_content = re.sub(r"\s+", " ", text_content).strip()

                if len(text_content) > 10000:
                    text_content = text_content[:10000] + "..."

                page_data = {
                    "title": title,
                    "url": url,
                    "content": text_content,
                }

                if extract_code_blocks:
                    code_blocks = []
                    for match in re.finditer(
                        r"<(?:pre|code)[^>]*>(.*?)</(?:pre|code)>",
                        content,
                        re.DOTALL | re.IGNORECASE,
                    ):
                        code = re.sub(r"<[^>]+>", "", match.group(1))
                        code = code.strip()
                        if code:
                            code_blocks.append(code)
                    page_data["code_blocks"] = code_blocks[:20]

                return page_data

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to fetch page: {str(e)}"}

    @mcp.tool()
    def knowledge_base_list_sources() -> dict:
        """
        List available knowledge base sources and their configuration status.

        Returns:
            Dict with available sources and whether they are configured
        """
        sources = [
            {
                "name": "confluence",
                "display_name": "Confluence",
                "type": "company_wiki",
                "description": "Atlassian Confluence wiki and documentation",
                "tools": ["confluence_search", "confluence_get_page"],
                "credentials_required": ["CONFLUENCE_API_TOKEN", "CONFLUENCE_URL"],
                "configured": bool(_get_credential("confluence") and os.getenv("CONFLUENCE_URL")),
                "setup_url": "https://id.atlassian.com/manage-profile/security/api-tokens",
            },
            {
                "name": "notion",
                "display_name": "Notion",
                "type": "workspace",
                "description": "Notion workspace with pages and databases",
                "tools": ["notion_search", "notion_get_page"],
                "credentials_required": ["NOTION_API_KEY"],
                "configured": bool(_get_credential("notion")),
                "setup_url": "https://www.notion.so/my-integrations",
            },
            {
                "name": "docs",
                "display_name": "Documentation Portal",
                "type": "web_docs",
                "description": "Generic documentation websites and portals",
                "tools": ["docs_search", "docs_get_page"],
                "credentials_required": [],
                "configured": True,
                "setup_url": None,
            },
        ]

        return {
            "sources": sources,
            "total": len(sources),
            "configured_count": sum(1 for s in sources if s["configured"]),
        }
