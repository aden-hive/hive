"""
Google Search Tool - Search the web using Google Custom Search API.

Requires GOOGLE_API_KEY and GOOGLE_CSE_ID environment variables.
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
    """Register Google search tools with the MCP server."""

    @mcp.tool()
    def google_search(
        query: str,
        num_results: int = 10,
        language: str = "id",
        country: str = "id",
    ) -> dict:
        """
        Search the web for information using Google Custom Search API.

        Returns titles, URLs, and snippets. Use when you need current
        information, research, or to find websites.

        Requires GOOGLE_API_KEY and GOOGLE_CSE_ID environment variables.

        Args:
            query: The search query (1-500 chars)
            num_results: Number of results to return (1-10)
            language: Language code for results (id=Indonesian, en=English)
            country: Country code for localized results (id=Indonesia, us=USA)

        Returns:
            Dict with search results or error dict
        """
        # Get API key and CSE ID
        if credentials is not None:
            api_key = credentials.get("google_search")
            cse_id = credentials.get("google_cse")
        else:
            api_key = os.getenv("GOOGLE_API_KEY")
            cse_id = os.getenv("GOOGLE_CSE_ID")

        if not api_key:
            return {
                "error": "GOOGLE_API_KEY environment variable not set",
                "help": "Get an API key at https://console.cloud.google.com/",
            }

        if not cse_id:
            return {
                "error": "GOOGLE_CSE_ID environment variable not set",
                "help": "Create a search engine at https://programmablesearchengine.google.com/",
            }

        # Validate inputs
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}
        if num_results < 1 or num_results > 10:
            num_results = max(1, min(10, num_results))

        try:
            # Make request to Google Custom Search API
            response = httpx.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": query,
                    "num": num_results,
                    "lr": f"lang_{language}",
                    "gl": country,
                },
                timeout=30.0,
            )

            if response.status_code == 401:
                return {"error": "Invalid API key"}
            elif response.status_code == 403:
                return {"error": "API key not authorized or quota exceeded"}
            elif response.status_code == 429:
                return {"error": "Rate limit exceeded. Try again later."}
            elif response.status_code != 200:
                return {"error": f"API request failed: HTTP {response.status_code}"}

            data = response.json()

            # Extract results
            results = []
            items = data.get("items", [])

            for item in items[:num_results]:
                results.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    }
                )

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
