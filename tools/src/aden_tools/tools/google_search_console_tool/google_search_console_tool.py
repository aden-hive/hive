"""
Google Search Console Tool - Search analytics, sitemaps, and URL inspection.

Supports:
- Google OAuth2 access token (GOOGLE_SEARCH_CONSOLE_TOKEN)
- Search Analytics queries (clicks, impressions, CTR, position)
- Sitemap management
- URL inspection

API Reference: https://developers.google.com/webmaster-tools/v1/api_reference_index
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

GSC_API = "https://www.googleapis.com/webmasters/v3"
INSPECTION_API = "https://searchconsole.googleapis.com/v1"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("google_search_console")
    return os.getenv("GOOGLE_SEARCH_CONSOLE_TOKEN")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(endpoint: str, token: str, base: str = GSC_API) -> dict[str, Any]:
    try:
        resp = httpx.get(f"{base}/{endpoint}", headers=_headers(token), timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your GOOGLE_SEARCH_CONSOLE_TOKEN."}
        if resp.status_code == 403:
            return {"error": f"Forbidden: {resp.text[:300]}"}
        if resp.status_code != 200:
            return {"error": f"Google API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Google Search Console timed out"}
    except Exception as e:
        return {"error": f"Request failed: {e!s}"}


def _post(endpoint: str, token: str, body: dict | None = None, base: str = GSC_API) -> dict[str, Any]:
    try:
        resp = httpx.post(f"{base}/{endpoint}", headers=_headers(token), json=body or {}, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your GOOGLE_SEARCH_CONSOLE_TOKEN."}
        if resp.status_code == 403:
            return {"error": f"Forbidden: {resp.text[:300]}"}
        if resp.status_code not in (200, 201):
            return {"error": f"Google API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Google Search Console timed out"}
    except Exception as e:
        return {"error": f"Request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "GOOGLE_SEARCH_CONSOLE_TOKEN not set",
        "help": "Generate an OAuth2 access token with webmasters.readonly scope",
    }


def _encode_site(site_url: str) -> str:
    """URL-encode the site URL for API paths."""
    import urllib.parse

    return urllib.parse.quote(site_url, safe="")


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Search Console tools with the MCP server."""

    @mcp.tool()
    def gsc_search_analytics(
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: str = "query",
        row_limit: int = 100,
        search_type: str = "web",
    ) -> dict[str, Any]:
        """
        Query search analytics data from Google Search Console.

        Args:
            site_url: Site URL (e.g. "https://example.com" or "sc-domain:example.com")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            dimensions: Comma-separated: query, page, country, device, date (default: query)
            row_limit: Number of rows (1-25000, default 100)
            search_type: Search type: web, image, video, news, discover, googleNews (default: web)

        Returns:
            Dict with rows (keys, clicks, impressions, ctr, position)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not site_url or not start_date or not end_date:
            return {"error": "site_url, start_date, and end_date are required"}

        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": [d.strip() for d in dimensions.split(",") if d.strip()],
            "rowLimit": max(1, min(row_limit, 25000)),
            "type": search_type,
        }

        encoded = _encode_site(site_url)
        data = _post(f"sites/{encoded}/searchAnalytics/query", token, body)
        if "error" in data:
            return data

        rows = []
        for r in data.get("rows", []):
            rows.append(
                {
                    "keys": r.get("keys", []),
                    "clicks": r.get("clicks", 0),
                    "impressions": r.get("impressions", 0),
                    "ctr": round(r.get("ctr", 0), 4),
                    "position": round(r.get("position", 0), 1),
                }
            )
        return {"site_url": site_url, "rows": rows, "count": len(rows)}

    @mcp.tool()
    def gsc_list_sites() -> dict[str, Any]:
        """
        List all sites in the Google Search Console account.

        Returns:
            Dict with sites list (siteUrl, permissionLevel)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _get("sites", token)
        if "error" in data:
            return data

        sites = []
        for s in data.get("siteEntry", []):
            sites.append(
                {
                    "site_url": s.get("siteUrl", ""),
                    "permission_level": s.get("permissionLevel", ""),
                }
            )
        return {"sites": sites}

    @mcp.tool()
    def gsc_list_sitemaps(site_url: str) -> dict[str, Any]:
        """
        List sitemaps for a site in Google Search Console.

        Args:
            site_url: Site URL (e.g. "https://example.com")

        Returns:
            Dict with sitemaps list
                (path, lastSubmitted, isPending, isSitemapsIndex, warnings, errors)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not site_url:
            return {"error": "site_url is required"}

        encoded = _encode_site(site_url)
        data = _get(f"sites/{encoded}/sitemaps", token)
        if "error" in data:
            return data

        sitemaps = []
        for s in data.get("sitemap", []):
            sitemaps.append(
                {
                    "path": s.get("path", ""),
                    "last_submitted": s.get("lastSubmitted", ""),
                    "is_pending": s.get("isPending", False),
                    "is_index": s.get("isSitemapsIndex", False),
                    "warnings": s.get("warnings", 0),
                    "errors": s.get("errors", 0),
                }
            )
        return {"site_url": site_url, "sitemaps": sitemaps}

    @mcp.tool()
    def gsc_inspect_url(
        site_url: str,
        inspection_url: str,
    ) -> dict[str, Any]:
        """
        Inspect a URL's indexing status in Google Search Console.

        Args:
            site_url: Site URL property (e.g. "https://example.com")
            inspection_url: Full URL to inspect

        Returns:
            Dict with indexing status, coverage state, crawl info, and mobile usability
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not site_url or not inspection_url:
            return {"error": "site_url and inspection_url are required"}

        body = {
            "inspectionUrl": inspection_url,
            "siteUrl": site_url,
        }
        data = _post("urlInspection/index:inspect", token, body, base=INSPECTION_API)
        if "error" in data:
            return data

        result = data.get("inspectionResult", {})
        index_status = result.get("indexStatusResult", {})
        mobile = result.get("mobileUsabilityResult", {})
        return {
            "inspection_url": inspection_url,
            "verdict": index_status.get("verdict", ""),
            "coverage_state": index_status.get("coverageState", ""),
            "indexing_state": index_status.get("indexingState", ""),
            "last_crawl_time": index_status.get("lastCrawlTime", ""),
            "crawled_as": index_status.get("crawledAs", ""),
            "page_fetch_state": index_status.get("pageFetchState", ""),
            "robots_txt_state": index_status.get("robotsTxtState", ""),
            "mobile_verdict": mobile.get("verdict", ""),
        }

    @mcp.tool()
    def gsc_submit_sitemap(
        site_url: str,
        sitemap_url: str,
    ) -> dict[str, Any]:
        """
        Submit a sitemap to Google Search Console.

        Args:
            site_url: Site URL property (e.g. "https://example.com")
            sitemap_url: Full sitemap URL (e.g. "https://example.com/sitemap.xml")

        Returns:
            Dict with submission status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not site_url or not sitemap_url:
            return {"error": "site_url and sitemap_url are required"}

        encoded_site = _encode_site(site_url)
        encoded_sitemap = _encode_site(sitemap_url)
        try:
            resp = httpx.put(
                f"{GSC_API}/sites/{encoded_site}/sitemaps/{encoded_sitemap}",
                headers=_headers(token),
                timeout=30.0,
            )
            if resp.status_code == 401:
                return {"error": "Unauthorized. Check your GOOGLE_SEARCH_CONSOLE_TOKEN."}
            if resp.status_code not in (200, 204):
                return {"error": f"Google API error {resp.status_code}: {resp.text[:500]}"}
            return {"sitemap_url": sitemap_url, "status": "submitted"}
        except Exception as e:
            return {"error": f"Request failed: {e!s}"}

    @mcp.tool()
    def gsc_top_queries(
        site_url: str,
        start_date: str,
        end_date: str,
        row_limit: int = 25,
        search_type: str = "web",
    ) -> dict[str, Any]:
        """
        Get the top search queries for a site sorted by clicks.

        Convenience wrapper around gsc_search_analytics with the 'query'
        dimension pre-selected and results sorted by clicks descending.

        Args:
            site_url: Site URL (e.g. "https://example.com")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            row_limit: Number of top queries (1-25000, default 25)
            search_type: Search type: web, image, video, news (default: web)

        Returns:
            Dict with top queries ranked by clicks
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not site_url or not start_date or not end_date:
            return {"error": "site_url, start_date, and end_date are required"}

        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["query"],
            "rowLimit": max(1, min(row_limit, 25000)),
            "type": search_type,
        }

        encoded = _encode_site(site_url)
        data = _post(f"sites/{encoded}/searchAnalytics/query", token, body)
        if "error" in data:
            return data

        rows = []
        for r in data.get("rows", []):
            rows.append(
                {
                    "query": r.get("keys", [""])[0],
                    "clicks": r.get("clicks", 0),
                    "impressions": r.get("impressions", 0),
                    "ctr": round(r.get("ctr", 0), 4),
                    "position": round(r.get("position", 0), 1),
                }
            )
        # Sort by clicks descending
        rows.sort(key=lambda x: x["clicks"], reverse=True)
        return {"site_url": site_url, "queries": rows, "count": len(rows)}

    @mcp.tool()
    def gsc_top_pages(
        site_url: str,
        start_date: str,
        end_date: str,
        row_limit: int = 25,
        search_type: str = "web",
    ) -> dict[str, Any]:
        """
        Get the top-performing pages for a site sorted by clicks.

        Convenience wrapper around gsc_search_analytics with the 'page'
        dimension pre-selected and results sorted by clicks descending.

        Args:
            site_url: Site URL (e.g. "https://example.com")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            row_limit: Number of top pages (1-25000, default 25)
            search_type: Search type: web, image, video, news (default: web)

        Returns:
            Dict with top pages ranked by clicks
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not site_url or not start_date or not end_date:
            return {"error": "site_url, start_date, and end_date are required"}

        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["page"],
            "rowLimit": max(1, min(row_limit, 25000)),
            "type": search_type,
        }

        encoded = _encode_site(site_url)
        data = _post(f"sites/{encoded}/searchAnalytics/query", token, body)
        if "error" in data:
            return data

        rows = []
        for r in data.get("rows", []):
            rows.append(
                {
                    "page": r.get("keys", [""])[0],
                    "clicks": r.get("clicks", 0),
                    "impressions": r.get("impressions", 0),
                    "ctr": round(r.get("ctr", 0), 4),
                    "position": round(r.get("position", 0), 1),
                }
            )
        rows.sort(key=lambda x: x["clicks"], reverse=True)
        return {"site_url": site_url, "pages": rows, "count": len(rows)}

    @mcp.tool()
    def gsc_delete_sitemap(
        site_url: str,
        sitemap_url: str,
    ) -> dict[str, Any]:
        """
        Delete a sitemap from Google Search Console.

        Args:
            site_url: Site URL property (e.g. "https://example.com")
            sitemap_url: Full sitemap URL to remove

        Returns:
            Dict with deletion status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not site_url or not sitemap_url:
            return {"error": "site_url and sitemap_url are required"}

        encoded_site = _encode_site(site_url)
        encoded_sitemap = _encode_site(sitemap_url)
        try:
            resp = httpx.delete(
                f"{GSC_API}/sites/{encoded_site}/sitemaps/{encoded_sitemap}",
                headers=_headers(token),
                timeout=30.0,
            )
            if resp.status_code == 401:
                return {"error": "Unauthorized. Check your GOOGLE_SEARCH_CONSOLE_TOKEN."}
            if resp.status_code not in (200, 204):
                return {"error": f"Google API error {resp.status_code}: {resp.text[:500]}"}
            return {"sitemap_url": sitemap_url, "status": "deleted"}
        except Exception as e:
            return {"error": f"Request failed: {e!s}"}
