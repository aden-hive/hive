"""
Hacker News Tool - Search and fetch stories from Hacker News.

Uses the Algolia HN Search API (no key required).
Enables agents to find tech news, discussions, and trending topics.
"""

from __future__ import annotations

import httpx
from fastmcp import FastMCP

_BASE_URL = "https://hn.algolia.com/api/v1"
_USER_AGENT = "AdenHive/1.0 (https://github.com/adenhq/hive)"


def register_tools(mcp: FastMCP) -> None:
    """Register Hacker News tools with the MCP server."""

    @mcp.tool()
    def hacker_news_search(
        query: str,
        max_results: int = 10,
        sort_by: str = "relevance",
        tags: str = "",
    ) -> dict:
        """
        Search Hacker News for stories and discussions.

        Use when you need tech news, product launches, or community discussions.
        Returns story titles, URLs, points, comment counts, and authors.

        Args:
            query: Search query (e.g. "AI agents", "rust async")
            max_results: Max results to return (1-20, default 10)
            sort_by: relevance or date (default: relevance)
            tags: Filter by tag - story, comment, ask_hn, show_hn, front_page (optional)

        Returns:
            Dict with query, count, and results (title, url, points, num_comments, author)
        """
        if not query or not query.strip():
            return {"error": "Query cannot be empty"}

        max_results = max(1, min(max_results, 20))
        endpoint = "search_by_date" if sort_by == "date" else "search"
        hits_per_page = max_results

        params: dict = {
            "query": query.strip()[:200],
            "hitsPerPage": hits_per_page,
        }
        if tags:
            params["tags"] = tags

        try:
            response = httpx.get(
                f"{_BASE_URL}/{endpoint}",
                params=params,
                timeout=15.0,
                headers={"User-Agent": _USER_AGENT},
            )

            if response.status_code != 200:
                return {
                    "error": f"Hacker News API error: {response.status_code}",
                    "query": query,
                }

            data = response.json()
            hits = data.get("hits", [])

            results = []
            for h in hits:
                results.append(
                    {
                        "object_id": h.get("objectID"),
                        "title": h.get("title", ""),
                        "url": h.get("url", ""),
                        "story_url": h.get("story_url", ""),
                        "author": h.get("author", ""),
                        "points": h.get("points", 0),
                        "num_comments": h.get("num_comments", 0),
                        "created_at": h.get("created_at", ""),
                        "tags": h.get("_tags", []),
                    }
                )

            return {
                "query": query,
                "count": len(results),
                "results": results,
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out", "query": query}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}", "query": query}
        except Exception as e:
            return {"error": f"Search failed: {str(e)}", "query": query}

    @mcp.tool()
    def hacker_news_front_page(max_results: int = 10) -> dict:
        """
        Get the current Hacker News front page stories.

        Use when you need trending tech news or popular discussions.
        Returns top stories by points.

        Args:
            max_results: Max stories to return (1-20, default 10)

        Returns:
            Dict with count and results (title, url, points, num_comments, author)
        """
        max_results = max(1, min(max_results, 20))

        try:
            response = httpx.get(
                f"{_BASE_URL}/search",
                params={
                    "tags": "front_page",
                    "hitsPerPage": max_results,
                },
                timeout=15.0,
                headers={"User-Agent": _USER_AGENT},
            )

            if response.status_code != 200:
                return {"error": f"Hacker News API error: {response.status_code}"}

            data = response.json()
            hits = data.get("hits", [])

            results = []
            for h in hits:
                results.append(
                    {
                        "object_id": h.get("objectID"),
                        "title": h.get("title", ""),
                        "url": h.get("url", ""),
                        "story_url": h.get("story_url", ""),
                        "author": h.get("author", ""),
                        "points": h.get("points", 0),
                        "num_comments": h.get("num_comments", 0),
                        "created_at": h.get("created_at", ""),
                    }
                )

            return {"count": len(results), "results": results}

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to fetch front page: {str(e)}"}
