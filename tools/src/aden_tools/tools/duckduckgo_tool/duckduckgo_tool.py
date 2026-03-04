"""
DuckDuckGo Search Tool - Web, news, and image search without API keys.

Uses the duckduckgo_search Python library (no credentials needed).
Supports:
- Text/web search
- News search
- Image search

Reference: https://pypi.org/project/duckduckgo-search/
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register DuckDuckGo search tools with the MCP server (no credentials needed)."""

    @mcp.tool()
    def duckduckgo_search(
        query: str,
        max_results: int = 10,
        region: str = "us-en",
        safesearch: str = "moderate",
        timelimit: str = "",
    ) -> dict[str, Any]:
        """
        Search the web using DuckDuckGo.

        Args:
            query: Search query
            max_results: Number of results (1-50, default 10)
            region: Region code (us-en, uk-en, de-de, etc., default us-en)
            safesearch: Safety filter: on, moderate, off (default moderate)
            timelimit: Time filter: d (day), w (week), m (month), y (year), "" (any)

        Returns:
            Dict with search results (title, href, body)
        """
        if not query:
            return {"error": "query is required"}

        try:
            from duckduckgo_search import DDGS

            ddgs = DDGS()
            kwargs: dict[str, Any] = {
                "keywords": query,
                "max_results": max(1, min(max_results, 50)),
                "region": region,
                "safesearch": safesearch,
            }
            if timelimit:
                kwargs["timelimit"] = timelimit

            results = list(ddgs.text(**kwargs))
            items = []
            for r in results:
                items.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                )
            return {"query": query, "results": items, "count": len(items)}
        except Exception as e:
            return {"error": f"DuckDuckGo search failed: {e!s}"}

    @mcp.tool()
    def duckduckgo_news(
        query: str,
        max_results: int = 10,
        region: str = "us-en",
        timelimit: str = "",
    ) -> dict[str, Any]:
        """
        Search news using DuckDuckGo.

        Args:
            query: News search query
            max_results: Number of results (1-50, default 10)
            region: Region code (default us-en)
            timelimit: Time filter: d (day), w (week), m (month), "" (any)

        Returns:
            Dict with news results (title, url, source, date, snippet)
        """
        if not query:
            return {"error": "query is required"}

        try:
            from duckduckgo_search import DDGS

            ddgs = DDGS()
            kwargs: dict[str, Any] = {
                "keywords": query,
                "max_results": max(1, min(max_results, 50)),
                "region": region,
            }
            if timelimit:
                kwargs["timelimit"] = timelimit

            results = list(ddgs.news(**kwargs))
            items = []
            for r in results:
                items.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "source": r.get("source", ""),
                        "date": r.get("date", ""),
                        "snippet": r.get("body", ""),
                    }
                )
            return {"query": query, "results": items, "count": len(items)}
        except Exception as e:
            return {"error": f"DuckDuckGo news search failed: {e!s}"}

    @mcp.tool()
    def duckduckgo_images(
        query: str,
        max_results: int = 10,
        region: str = "us-en",
        safesearch: str = "moderate",
        size: str = "",
    ) -> dict[str, Any]:
        """
        Search images using DuckDuckGo.

        Args:
            query: Image search query
            max_results: Number of results (1-50, default 10)
            region: Region code (default us-en)
            safesearch: Safety filter: on, moderate, off (default moderate)
            size: Size filter: Small, Medium, Large, Wallpaper, "" (any)

        Returns:
            Dict with image results (title, image_url, thumbnail_url, source, width, height)
        """
        if not query:
            return {"error": "query is required"}

        try:
            from duckduckgo_search import DDGS

            ddgs = DDGS()
            kwargs: dict[str, Any] = {
                "keywords": query,
                "max_results": max(1, min(max_results, 50)),
                "region": region,
                "safesearch": safesearch,
            }
            if size:
                kwargs["size"] = size

            results = list(ddgs.images(**kwargs))
            items = []
            for r in results:
                items.append(
                    {
                        "title": r.get("title", ""),
                        "image_url": r.get("image", ""),
                        "thumbnail_url": r.get("thumbnail", ""),
                        "source": r.get("source", ""),
                        "width": r.get("width", 0),
                        "height": r.get("height", 0),
                    }
                )
            return {"query": query, "results": items, "count": len(items)}
        except Exception as e:
            return {"error": f"DuckDuckGo image search failed: {e!s}"}
