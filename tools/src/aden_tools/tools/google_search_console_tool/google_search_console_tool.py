"""
Google Search Console Tool - SEO Performance, Search Queries & Indexing.

API Reference: https://developers.google.com/webmaster-tools/v1/api_reference_index
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class _GSCClient:
    """Internal client wrapping Google Search Console API calls."""

    def __init__(self, credentials_path: str | None = None):
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
        except ImportError:
            raise ImportError(
                "google-api-python-client is required for GSC tools. "
                "Install it with: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            ) from None

        if credentials_path:
            self._creds = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
            )
        else:
            # Fallback to Application Default Credentials
            import google.auth
            self._creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
            )
        
        self._service = build("webmasters", "v3", credentials=self._creds, cache_discovery=False)

    def search_analytics(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
        query_filter: str | None = None,
        page_filter: str | None = None,
        row_limit: int = 100,
    ) -> dict[str, Any]:
        """Query search performance data."""
        request = {
            "startDate": start_date,
            "endDate": end_date,
            "rowLimit": min(row_limit, 25000),
        }
        if dimensions:
            request["dimensions"] = dimensions

        dimension_filters = []
        if query_filter:
            dimension_filters.append({
                "dimension": "query",
                "operator": "contains",
                "expression": query_filter
            })
        if page_filter:
            dimension_filters.append({
                "dimension": "page",
                "operator": "contains",
                "expression": page_filter
            })
        
        if dimension_filters:
            request["dimensionFilterGroups"] = [{"filters": dimension_filters}]

        return self._service.searchanalytics().query(siteUrl=site_url, body=request).execute()

    def list_sites(self) -> dict[str, Any]:
        """List verified sites."""
        return self._service.sites().list().execute()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Search Console tools with the MCP server."""

    def _get_credentials_path() -> str | None:
        """Get GSC credentials path."""
        if credentials is not None:
            return credentials.get("google_search_console")
        return os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    def _get_client() -> _GSCClient | dict[str, str]:
        """Get initialized GSC client or error."""
        try:
            path = _get_credentials_path()
            return _GSCClient(path)
        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependencies: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib",
            }
        except Exception as e:
            return {"error": f"Failed to initialize GSC client: {str(e)}"}

    @mcp.tool()
    def gsc_search_analytics(
        site_url: str,
        start_date: str = "28daysAgo",
        end_date: str = "today",
        dimensions: list[str] | None = None,
        query_filter: str | None = None,
        page_filter: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        Query Google Search Console search analytics data.

        Args:
            site_url: Site URL (e.g., "https://example.com" or "sc-domain:example.com")
            start_date: Start date (e.g., "2024-01-01" or "28daysAgo")
            end_date: End date (e.g., "today")
            dimensions: Dimensions to group by (e.g., ["query", "page", "country", "device"])
            query_filter: Filter to specific queries (substring match)
            page_filter: Filter to specific pages (URL contains)
            limit: Max rows to return (1-25000)

        Returns:
            Dict with search analytics rows or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.search_analytics(
                site_url=site_url,
                start_date=start_date,
                end_date=end_date,
                dimensions=dimensions,
                query_filter=query_filter,
                page_filter=page_filter,
                row_limit=limit,
            )
        except Exception as e:
            return {"error": f"GSC API error: {str(e)}"}

    @mcp.tool()
    def gsc_get_top_queries(
        site_url: str,
        start_date: str = "28daysAgo",
        end_date: str = "today",
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Get top search queries by clicks and impressions.

        Args:
            site_url: Site URL.
            start_date: Start date.
            end_date: End date.
            limit: Max queries to return.

        Returns:
            Dict with queries, clicks, impressions, CTR, and average position
        """
        return gsc_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=["query"],
            limit=limit,
        )

    @mcp.tool()
    def gsc_get_top_pages(
        site_url: str,
        start_date: str = "28daysAgo",
        end_date: str = "today",
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Get top pages by organic search performance.

        Args:
            site_url: Site URL.
            start_date: Start date.
            end_date: End date.
            limit: Max pages to return.

        Returns:
            Dict with pages, clicks, impressions, CTR, and average position
        """
        return gsc_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=["page"],
            limit=limit,
        )

    @mcp.tool()
    def gsc_list_sites() -> dict[str, Any]:
        """List Search Console properties accessible by the service account."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_sites()
        except Exception as e:
            return {"error": f"GSC API error: {str(e)}"}
