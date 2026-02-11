"""
SerpAPI Tool - Google Scholar & Google Patents search via SerpAPI.

Supports:
- Direct API key (SERPAPI_API_KEY)
- Credential store via CredentialStoreAdapter

API Reference: https://serpapi.com/search-api

Tools:
- scholar_search: Search Google Scholar for academic papers
- scholar_get_citations: Get citation formats for a specific paper
- scholar_get_author: Get author profile, h-index, articles
- patents_search: Search Google Patents
- patents_get_details: Get detailed patent information
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

SERPAPI_BASE = "https://serpapi.com/search.json"
SERPAPI_ACCOUNT = "https://serpapi.com/account.json"


class _SerpAPIClient:
    """Internal client wrapping SerpAPI HTTP calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        """Make a GET request to SerpAPI."""
        params["api_key"] = self._api_key
        response = httpx.get(SERPAPI_BASE, params=params, timeout=30.0)

        if response.status_code == 401:
            return {
                "error": "Invalid SerpAPI API key",
                "help": "Check your key at https://serpapi.com/manage-api-key",
            }
        if response.status_code == 429:
            return {"error": "SerpAPI rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", response.text)
            except Exception:
                detail = response.text
            return {"error": f"SerpAPI error (HTTP {response.status_code}): {detail}"}

        data = response.json()
        if "error" in data:
            return {"error": f"SerpAPI error: {data['error']}"}
        return data

    def scholar_search(
        self,
        query: str,
        num: int = 10,
        start: int = 0,
        year_low: int | None = None,
        year_high: int | None = None,
        sort_by_date: bool = False,
    ) -> dict[str, Any]:
        """Search Google Scholar."""
        params: dict[str, Any] = {
            "engine": "google_scholar",
            "q": query,
            "num": min(num, 20),
            "start": start,
        }
        if year_low is not None:
            params["as_ylo"] = year_low
        if year_high is not None:
            params["as_yhi"] = year_high
        if sort_by_date:
            params["scisbd"] = 1
        return self._request(params)

    def scholar_cite(self, result_id: str) -> dict[str, Any]:
        """Get citation formats for a scholar result."""
        return self._request({"engine": "google_scholar_cite", "q": result_id})

    def scholar_author(
        self,
        author_id: str,
        start: int = 0,
        num: int = 20,
        sort_by: str = "citedby",
    ) -> dict[str, Any]:
        """Get author profile and articles."""
        return self._request(
            {
                "engine": "google_scholar_author",
                "author_id": author_id,
                "start": start,
                "num": min(num, 100),
                "sort": sort_by,
            }
        )

    def patents_search(
        self,
        query: str,
        page: int = 1,
        country: str | None = None,
        status: str | None = None,
        before: str | None = None,
        after: str | None = None,
    ) -> dict[str, Any]:
        """Search Google Patents."""
        params: dict[str, Any] = {
            "engine": "google_patents",
            "q": query,
            "page": page,
        }
        if country:
            params["country"] = country
        if status:
            params["status"] = status
        if before:
            params["before"] = f"priority:{before}"
        if after:
            params["after"] = f"priority:{after}"
        return self._request(params)

    def patents_details(self, patent_id: str) -> dict[str, Any]:
        """Get details for a specific patent by searching its ID."""
        return self._request({"engine": "google_patents", "q": patent_id})


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register SerpAPI tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get SerpAPI API key from credential store or environment."""
        if credentials is not None:
            return credentials.get("serpapi")
        return os.getenv("SERPAPI_API_KEY")

    def _get_client() -> _SerpAPIClient | dict[str, str]:
        """Get a SerpAPI client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "SerpAPI credentials not configured",
                "help": (
                    "Set SERPAPI_API_KEY environment variable or configure "
                    "via credential store. Get a key at https://serpapi.com/manage-api-key"
                ),
            }
        return _SerpAPIClient(api_key)

    @mcp.tool()
    def scholar_search(
        query: str,
        num_results: int = 10,
        start: int = 0,
        year_low: int | None = None,
        year_high: int | None = None,
        sort_by_date: bool = False,
    ) -> dict:
        """
        Search Google Scholar for academic papers, articles, and citations.

        Returns structured results with titles, authors, citation counts,
        and links. Google Scholar has no official API — this is the only way
        to get structured paper metadata including citation counts and h-index.

        Args:
            query: Search query for academic papers (1-500 chars)
            num_results: Number of results to return (1-20, default 10)
            start: Pagination offset (0, 10, 20, etc.)
            year_low: Filter papers published after this year (e.g. 2020)
            year_high: Filter papers published before this year (e.g. 2024)
            sort_by_date: If True, sort by date instead of relevance

        Returns:
            Dict with organic_results containing paper metadata, or error dict
        """
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            data = client.scholar_search(
                query=query,
                num=num_results,
                start=start,
                year_low=year_low,
                year_high=year_high,
                sort_by_date=sort_by_date,
            )
            if "error" in data:
                return data

            results = []
            for item in data.get("organic_results", []):
                result = {
                    "title": item.get("title", ""),
                    "link": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "result_id": item.get("result_id", ""),
                    "publication_info": item.get("publication_info", {}).get("summary", ""),
                    "cited_by_count": (
                        item.get("inline_links", {}).get("cited_by", {}).get("total", 0)
                    ),
                    "cites_id": (
                        item.get("inline_links", {}).get("cited_by", {}).get("cites_id", "")
                    ),
                }
                authors = item.get("publication_info", {}).get("authors", [])
                if authors:
                    result["authors"] = [
                        {
                            "name": a.get("name", ""),
                            "author_id": a.get("author_id", ""),
                        }
                        for a in authors
                    ]
                resources = item.get("resources", [])
                if resources:
                    result["pdf_link"] = resources[0].get("link", "")
                results.append(result)

            return {
                "query": query,
                "total_results": (data.get("search_information", {}).get("total_results", 0)),
                "results": results,
                "count": len(results),
            }

        except httpx.TimeoutException:
            return {"error": "Search request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        except Exception as e:
            return {"error": f"Scholar search failed: {e}"}

    @mcp.tool()
    def scholar_get_citations(result_id: str) -> dict:
        """
        Get formatted citations for a Google Scholar paper.

        Returns citation text in MLA, APA, Chicago, Harvard, and Vancouver
        formats, plus download links for BibTeX, EndNote, RefMan, RefWorks.

        Args:
            result_id: The result_id from a scholar_search result

        Returns:
            Dict with citations list and download links, or error dict
        """
        if not result_id:
            return {"error": "result_id is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            data = client.scholar_cite(result_id)
            if "error" in data:
                return data

            return {
                "result_id": result_id,
                "citations": data.get("citations", []),
                "links": data.get("links", []),
            }

        except httpx.TimeoutException:
            return {"error": "Citation request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        except Exception as e:
            return {"error": f"Citation lookup failed: {e}"}

    @mcp.tool()
    def scholar_get_author(
        author_id: str,
        num_articles: int = 20,
        start: int = 0,
        sort_by: str = "citedby",
    ) -> dict:
        """
        Get a Google Scholar author profile with h-index, citations, and articles.

        Returns author name, affiliations, research interests, citation
        metrics (total citations, h-index, i10-index), and their articles.

        Args:
            author_id: Google Scholar author ID (e.g. 'WLN3QrAAAAAJ')
            num_articles: Number of articles to return (1-100, default 20)
            start: Pagination offset for articles (default 0)
            sort_by: Sort articles by 'citedby' (default) or 'pubdate'

        Returns:
            Dict with author profile, metrics, and articles, or error dict
        """
        if not author_id:
            return {"error": "author_id is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            data = client.scholar_author(
                author_id=author_id,
                start=start,
                num=num_articles,
                sort_by=sort_by,
            )
            if "error" in data:
                return data

            author = data.get("author", {})
            cited_by = data.get("cited_by", {})

            metrics = {}
            for entry in cited_by.get("table", []):
                for key, value in entry.items():
                    metrics[key] = value

            articles = []
            for article in data.get("articles", []):
                articles.append(
                    {
                        "title": article.get("title", ""),
                        "authors": article.get("authors", ""),
                        "publication": article.get("publication", ""),
                        "year": article.get("year", ""),
                        "cited_by_count": article.get("cited_by", {}).get("value", 0),
                        "citation_id": article.get("citation_id", ""),
                    }
                )

            return {
                "author_id": author_id,
                "name": author.get("name", ""),
                "affiliations": author.get("affiliations", ""),
                "email": author.get("email", ""),
                "interests": [i.get("title", "") for i in author.get("interests", [])],
                "thumbnail": author.get("thumbnail", ""),
                "metrics": metrics,
                "articles": articles,
                "article_count": len(articles),
            }

        except httpx.TimeoutException:
            return {"error": "Author lookup timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        except Exception as e:
            return {"error": f"Author lookup failed: {e}"}

    @mcp.tool()
    def patents_search(
        query: str,
        page: int = 1,
        country: str | None = None,
        status: str | None = None,
        before_date: str | None = None,
        after_date: str | None = None,
    ) -> dict:
        """
        Search Google Patents for patents and patent applications.

        Supports keyword search, inventor/assignee filtering via query operators,
        and date/country/status filters.

        Query operators (use in query string):
        - inassignee:Google — filter by assignee
        - ininventor:"John Smith" — filter by inventor
        - inclaims:neural network — search within claims
        - intitle:machine learning — search within title

        Args:
            query: Search query for patents (1-500 chars)
            page: Page number, 1-indexed (default 1)
            country: Filter by country code (e.g. 'US', 'EP', 'WO', 'CN')
            status: Patent status filter: 'GRANT' or 'APPLICATION'
            before_date: Patents filed before this date (YYYYMMDD)
            after_date: Patents filed after this date (YYYYMMDD)

        Returns:
            Dict with patent results, or error dict
        """
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            data = client.patents_search(
                query=query,
                page=page,
                country=country,
                status=status,
                before=before_date,
                after=after_date,
            )
            if "error" in data:
                return data

            results = []
            for item in data.get("organic_results", []):
                results.append(
                    {
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                        "link": item.get("link", ""),
                        "patent_id": item.get("patent_id", ""),
                        "publication_number": item.get("publication_number", ""),
                        "inventor": item.get("inventor", ""),
                        "assignee": item.get("assignee", ""),
                        "filing_date": item.get("filing_date", ""),
                        "grant_date": item.get("grant_date"),
                        "publication_date": item.get("publication_date", ""),
                        "priority_date": item.get("priority_date", ""),
                        "pdf": item.get("pdf", ""),
                    }
                )

            return {
                "query": query,
                "total_results": (data.get("search_information", {}).get("total_results", 0)),
                "results": results,
                "count": len(results),
                "page": page,
            }

        except httpx.TimeoutException:
            return {"error": "Patent search timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        except Exception as e:
            return {"error": f"Patent search failed: {e}"}

    @mcp.tool()
    def patents_get_details(patent_id: str) -> dict:
        """
        Get detailed information for a specific patent.

        Fetches a single patent by its publication number (e.g. 'US20210012345A1')
        and returns full metadata including title, abstract, inventors, assignee,
        dates, classifications, and PDF link.

        Args:
            patent_id: Patent publication number (e.g. 'US20210012345A1')

        Returns:
            Dict with patent details, or error dict
        """
        if not patent_id:
            return {"error": "patent_id is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            data = client.patents_details(patent_id)
            if "error" in data:
                return data

            results = data.get("organic_results", [])
            if not results:
                return {"error": f"No patent found for ID: {patent_id}"}

            patent = results[0]
            return {
                "patent_id": patent_id,
                "title": patent.get("title", ""),
                "snippet": patent.get("snippet", ""),
                "link": patent.get("link", ""),
                "publication_number": patent.get("publication_number", ""),
                "inventor": patent.get("inventor", ""),
                "assignee": patent.get("assignee", ""),
                "filing_date": patent.get("filing_date", ""),
                "grant_date": patent.get("grant_date"),
                "publication_date": patent.get("publication_date", ""),
                "priority_date": patent.get("priority_date", ""),
                "pdf": patent.get("pdf", ""),
                "classifications": patent.get("classifications", {}),
            }

        except httpx.TimeoutException:
            return {"error": "Patent detail request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        except Exception as e:
            return {"error": f"Patent detail lookup failed: {e}"}
