"""
Wikipedia Search Tool - Search and retrieve summaries from Wikipedia.

Uses the Wikipedia Public API (REST) to find relevant articles and get their intros.
No external 'wikipedia' library required, uses standard `httpx`.
"""

from __future__ import annotations

import re

import httpx
from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register wikipedia tool with the MCP server."""

    def _strip_html(text: str) -> str:
        """Remove HTML tags from a string."""
        if not text:
            return ""
        return re.sub(r"<[^>]+>", "", text)

    @mcp.tool()
    def search_wikipedia(query: str, lang: str = "en", num_results: int = 3) -> dict:
        """
        Search Wikipedia for a given query and return summaries of top matching articles.

        Args:
            query: The search term (e.g. "Artificial Intelligence")
            lang: Language code (default: "en")
            num_results: Number of pages to retrieve (default: 3, max: 10)

        Returns:
            Dict containing query metadata and list of results (title, summary, url).
        """
        if not query:
            return {"error": "Query cannot be empty"}

        num_results = max(1, min(num_results, 10))
        base_url = f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page"

        try:
            # 1. Search for pages
            response = httpx.get(
                base_url,
                params={"q": query, "limit": num_results},
                timeout=10.0,
                headers={"User-Agent": "AdenAgentFramework/1.0 (https://adenhq.com)"},
            )

            if response.status_code != 200:
                return {"error": f"Wikipedia API error: {response.status_code}", "query": query}

            data = response.json()
            pages = data.get("pages", [])

            results = []
            for page in pages:
                # Basic info
                title = page.get("title", "")
                key = page.get("key", "")

                # Use description or excerpt for summary
                description = page.get("description") or "No description available."
                excerpt = page.get("excerpt") or ""

                # Clean up HTML from excerpt (e.g. <span class="searchmatch">)
                snippet = _strip_html(excerpt)

                results.append(
                    {
                        "title": title,
                        "url": f"https://{lang}.wikipedia.org/wiki/{key}",
                        "description": description,
                        "snippet": snippet,
                    }
                )

            return {"query": query, "lang": lang, "count": len(results), "results": results}

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}
