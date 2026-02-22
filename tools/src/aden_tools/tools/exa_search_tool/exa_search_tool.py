"""
Exa Search Tool - AI-powered web search using the Exa API.

Supports:
- Neural/keyword web search with filters (exa_search)
- Similar page discovery (exa_find_similar)
- Content extraction from URLs (exa_get_contents)
- Citation-backed answers (exa_answer)

All tools use the EXA_API_KEY credential for authentication.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Literal

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# Exa API base URL
EXA_API_BASE = "https://api.exa.ai"


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Exa search tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get the Exa API key from credentials or environment."""
        if credentials is not None:
            return credentials.get("exa_search")
        return os.getenv("EXA_API_KEY")

    def _make_request(
        endpoint: str,
        payload: dict,
        api_key: str,
    ) -> dict:
        """Make a POST request to the Exa API with retry on rate limit.

        Args:
            endpoint: API endpoint path (e.g., "/search")
            payload: JSON request body
            api_key: Exa API key

        Returns:
            Parsed JSON response dict, or error dict on failure
        """
        max_retries = 3
        for attempt in range(max_retries + 1):
            response = httpx.post(
                f"{EXA_API_BASE}{endpoint}",
                json=payload,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )

            if response.status_code == 429 and attempt < max_retries:
                time.sleep(2**attempt)
                continue

            if response.status_code == 401:
                return {"error": "Invalid Exa API key"}
            elif response.status_code == 429:
                return {"error": "Exa rate limit exceeded. Try again later."}
            elif response.status_code != 200:
                return {"error": f"Exa API request failed: HTTP {response.status_code}"}

            break

        return response.json()

    @mcp.tool()
    def exa_search(
        query: str,
        num_results: int = 10,
        search_type: Literal["auto", "neural", "keyword"] = "auto",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        start_published_date: str | None = None,
        end_published_date: str | None = None,
        include_text: bool = True,
        include_highlights: bool = False,
        category: str | None = None,
    ) -> dict:
        """
        Search the web using Exa's AI-powered search engine.

        Supports neural (semantic) and keyword search with domain and date filters.

        Args:
            query: The search query (1-500 chars)
            num_results: Number of results to return (1-20)
            search_type: Search mode - "auto", "neural" (semantic), or "keyword"
            include_domains: Only include results from these domains
            exclude_domains: Exclude results from these domains
            start_published_date: Filter by publish date start (ISO 8601, e.g. "2024-01-01")
            end_published_date: Filter results published before this date (ISO 8601)
            include_text: Include full page text in results
            include_highlights: Include relevant text highlights
            category: Content category filter (e.g. "research paper", "news", "company")

        Returns:
            Dict with search results including titles, URLs, and optionally text/highlights
        """
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}

        num_results = max(1, min(num_results, 20))

        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Exa credentials not configured",
                "help": "Set EXA_API_KEY environment variable",
            }

        payload: dict = {
            "query": query,
            "numResults": num_results,
            "contents": {},
        }

        if search_type != "auto":
            payload["type"] = search_type

        if include_domains:
            payload["includeDomains"] = include_domains
        if exclude_domains:
            payload["excludeDomains"] = exclude_domains
        if start_published_date:
            payload["startPublishedDate"] = start_published_date
        if end_published_date:
            payload["endPublishedDate"] = end_published_date
        if category:
            payload["category"] = category

        if include_text:
            payload["contents"]["text"] = True
        if include_highlights:
            payload["contents"]["highlights"] = True

        try:
            data = _make_request("/search", payload, api_key)

            if "error" in data:
                return data

            results = []
            for item in data.get("results", []):
                result = {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "published_date": item.get("publishedDate", ""),
                    "author": item.get("author", ""),
                }
                if include_text and "text" in item:
                    result["text"] = item["text"]
                if include_highlights and "highlights" in item:
                    result["highlights"] = item["highlights"]
                results.append(result)

            return {
                "query": query,
                "results": results,
                "total": len(results),
                "provider": "exa",
            }

        except httpx.TimeoutException:
            return {"error": "Exa search request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Exa search failed: {str(e)}"}

    @mcp.tool()
    def exa_find_similar(
        url: str,
        num_results: int = 10,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        include_text: bool = True,
    ) -> dict:
        """
        Find web pages similar to a given URL.

        Uses Exa's neural understanding to find semantically similar content.

        Args:
            url: The source URL to find similar pages for
            num_results: Number of similar results to return (1-20)
            include_domains: Only include results from these domains
            exclude_domains: Exclude results from these domains
            include_text: Include full page text in results

        Returns:
            Dict with similar pages including titles, URLs, and optionally text
        """
        if not url:
            return {"error": "URL is required"}

        num_results = max(1, min(num_results, 20))

        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Exa credentials not configured",
                "help": "Set EXA_API_KEY environment variable",
            }

        payload: dict = {
            "url": url,
            "numResults": num_results,
            "contents": {},
        }

        if include_domains:
            payload["includeDomains"] = include_domains
        if exclude_domains:
            payload["excludeDomains"] = exclude_domains

        if include_text:
            payload["contents"]["text"] = True

        try:
            data = _make_request("/findSimilar", payload, api_key)

            if "error" in data:
                return data

            results = []
            for item in data.get("results", []):
                result = {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "published_date": item.get("publishedDate", ""),
                }
                if include_text and "text" in item:
                    result["text"] = item["text"]
                results.append(result)

            return {
                "source_url": url,
                "results": results,
                "total": len(results),
                "provider": "exa",
            }

        except httpx.TimeoutException:
            return {"error": "Exa find similar request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Exa find similar failed: {str(e)}"}

    @mcp.tool()
    def exa_get_contents(
        urls: list[str],
        include_text: bool = True,
        include_highlights: bool = False,
    ) -> dict:
        """
        Extract content from one or more URLs using Exa's content extraction.

        Args:
            urls: List of URLs to extract content from (1-10 URLs)
            include_text: Include full page text
            include_highlights: Include relevant text highlights

        Returns:
            Dict with extracted content for each URL
        """
        if not urls:
            return {"error": "At least one URL is required"}
        if len(urls) > 10:
            return {"error": "Maximum 10 URLs per request"}

        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Exa credentials not configured",
                "help": "Set EXA_API_KEY environment variable",
            }

        payload: dict = {
            "ids": urls,
        }

        contents: dict = {}
        if include_text:
            contents["text"] = True
        if include_highlights:
            contents["highlights"] = True
        if contents:
            payload["contents"] = contents

        try:
            data = _make_request("/contents", payload, api_key)

            if "error" in data:
                return data

            results = []
            for item in data.get("results", []):
                result = {
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                }
                if include_text and "text" in item:
                    result["text"] = item["text"]
                if include_highlights and "highlights" in item:
                    result["highlights"] = item["highlights"]
                results.append(result)

            return {
                "results": results,
                "total": len(results),
                "provider": "exa",
            }

        except httpx.TimeoutException:
            return {"error": "Exa content extraction request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Exa content extraction failed: {str(e)}"}

    @mcp.tool()
    def exa_answer(
        query: str,
        include_citations: bool = True,
    ) -> dict:
        """
        Get an answer to a question with citations from web sources.

        Uses Exa to search the web and generate a citation-backed answer.

        Args:
            query: The question to answer (1-500 chars)
            include_citations: Include source citations in the response

        Returns:
            Dict with the answer text and optionally source citations
        """
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}

        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Exa credentials not configured",
                "help": "Set EXA_API_KEY environment variable",
            }

        payload: dict = {
            "query": query,
        }

        try:
            data = _make_request("/answer", payload, api_key)

            if "error" in data:
                return data

            result: dict = {
                "query": query,
                "answer": data.get("answer", ""),
                "provider": "exa",
            }

            if include_citations:
                citations = []
                for source in data.get("citations", []):
                    citations.append(
                        {
                            "title": source.get("title", ""),
                            "url": source.get("url", ""),
                            "published_date": source.get("publishedDate", ""),
                        }
                    )
                result["citations"] = citations

            return result

        except httpx.TimeoutException:
            return {"error": "Exa answer request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Exa answer failed: {str(e)}"}
