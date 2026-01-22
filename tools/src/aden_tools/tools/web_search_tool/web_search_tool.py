"""
Web Search Tool - Search the web using Brave Search API.

Requires BRAVE_SEARCH_API_KEY environment variable.
Returns search results with titles, URLs, and snippets.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialManager


def register_tools(
    mcp: FastMCP,
    credentials: Optional["CredentialManager"] = None,
) -> None:
    """Register web search tools with the MCP server."""

    @mcp.tool()
    def web_search(
        query: str,
        num_results: int = 10,
        country: str = "us",
    ) -> dict:
        """
        Search the web for information using Brave Search API.

        Returns titles, URLs, and snippets. Use when you need current
        information, research, or to find websites.

        Requires BRAVE_SEARCH_API_KEY environment variable.

        Args:
            query: The search query (1-500 chars)
            num_results: Number of results to return (1-20)
            country: Country code for localized results (us, uk, de, etc.)

        Returns:
            Dict with search results or error dict
        """
        # Get API key - use CredentialManager if provided, fallback to direct env
        if credentials is not None:
            api_key = credentials.get("brave_search")
        else:
            # Backward compatibility: direct env access
            api_key = os.getenv("BRAVE_SEARCH_API_KEY")

        if not api_key:
            return {
                "error": "BRAVE_SEARCH_API_KEY environment variable not set",
                "help": "Get an API key at https://brave.com/search/api/",
            }

        # Validate inputs
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}
        if num_results < 1 or num_results > 20:
            num_results = max(1, min(20, num_results))

        try:
            # Make request to Brave Search API
            response = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={
                    "q": query,
                    "count": num_results,
                    "country": country,
                },
                headers={
                    "X-Subscription-Token": api_key,
                    "Accept": "application/json",
                },
                timeout=30.0,
            )

            if response.status_code == 401:
                return {"error": "Invalid API key"}
            elif response.status_code == 429:
                return {"error": "Rate limit exceeded. Try again later."}
            elif response.status_code != 200:
                return {"error": f"API request failed: HTTP {response.status_code}"}

            data = response.json()

            # Extract results
            results = []
            web_results = data.get("web", {}).get("results", [])

            for item in web_results[:num_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                })

            return {
                "query": query,
                "results": results,
                "total": len(results),
            }

        except httpx.TimeoutException:
            return {"error": "Search request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}
