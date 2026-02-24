"""
DuckDuckGo Search Tool - Free, No-Key, Safe Web Search.

Supports:
- Web search (ddg_search_web)
- News search (ddg_search_news)

DuckDuckGo is anonymous and requires no authentication.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

logger = logging.getLogger(__name__)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register DuckDuckGo search tools with the MCP server."""

    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning(
            "duckduckgo-search is not installed. DuckDuckGo tools will fail if called."
        )
        DDGS = None  # type: ignore

    @mcp.tool()
    def ddg_search_web(
        query: str,
        max_results: int = 5,
    ) -> dict:
        """
        Performs a web search using DuckDuckGo with SafeSearch enabled by default.
        No API key required.

        Args:
            query: The search query.
            max_results: Number of results to return (1-20).

        Returns:
            Dict containing the query and the search results.
        """
        if DDGS is None:
            return {
                "error": "duckduckgo-search is not installed",
                "help": "pip install duckduckgo-search",
            }

        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}

        max_results = max(1, min(max_results, 20))

        try:
            with DDGS() as ddgs:
                results = list(
                    ddgs.text(
                        query,
                        max_results=max_results,
                        backend="api",
                        safesearch="moderate",
                    )
                )

            return {
                "query": query,
                "results": results,
                "total": len(results),
                "provider": "duckduckgo",
            }
        except Exception as e:
            return {"error": f"DuckDuckGo search failed: {str(e)}"}

    @mcp.tool()
    def ddg_search_news(
        query: str,
        max_results: int = 5,
    ) -> dict:
        """
        Search for news articles using DuckDuckGo.
        No API key required.

        Args:
            query: The news search query.
            max_results: Number of results to return (1-20).

        Returns:
            Dict containing the query and the news search results.
        """
        if DDGS is None:
            return {
                "error": "duckduckgo-search is not installed",
                "help": "pip install duckduckgo-search",
            }

        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}

        max_results = max(1, min(max_results, 20))

        try:
            with DDGS() as ddgs:
                results = list(
                    ddgs.news(
                        query,
                        max_results=max_results,
                        safesearch="moderate",
                    )
                )

            return {
                "query": query,
                "results": results,
                "total": len(results),
                "provider": "duckduckgo",
            }
        except Exception as e:
            return {"error": f"DuckDuckGo news search failed: {str(e)}"}
