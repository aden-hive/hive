"""
SimilarWeb Tool - Traffic and competitor insights for FastMCP.

Provides website analytics, demographic data, and competitor intelligence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from aden_tools.credentials import CredentialStoreAdapter


def _get_api_key(credentials: CredentialStoreAdapter | None = None) -> str | dict[str, str]:
    """Get the SimilarWeb API key from credentials or environment."""
    if credentials:
        key = credentials.get("similarweb")
        if key:
            return key

    import os

    env_key = os.environ.get("SIMILARWEB_API_KEY")
    if env_key:
        return env_key

    return {
        "error": "SimilarWeb credentials not configured",
        "help": (
            "Set SIMILARWEB_API_KEY environment variable or configure "
            "via credential store. Get a key at https://developer.similarweb.com/"
        ),
    }


def _make_request(
    endpoint: str,
    api_key: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper method to make requests to the SimilarWeb API."""
    if params is None:
        params = {}

    # SimilarWeb official API v5 uses the api key as a header
    headers = {"api-key": api_key}

    params["format"] = "json"

    # Defaults according to official v5 API structure
    if "start_date" not in params:
        # Some default/dummy dates or required by specific endpoints
        pass

    url = f"https://api.similarweb.com/v5/{endpoint}"

    try:
        response = httpx.get(url, params=params, headers=headers, timeout=30.0)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            # Enforce returning dict
            return {"data": result}
        return result
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP error {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}


def register_tools(mcp: FastMCP, credentials: CredentialStoreAdapter | None = None) -> None:
    """Register SimilarWeb tools with the MCP server."""

    @mcp.tool()
    def similarweb_get_website_overview(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """
        Get total traffic and engagement overview for a specific website domain.

        Args:
            domain: The website domain to analyze (e.g., 'amazon.com')
            start_date: Format YYYY-MM (e.g., '2024-01'). Optional.
            end_date: Format YYYY-MM (e.g., '2024-01'). Optional.
            country: 2-letter ISO country code or 'world' (default).

        Returns:
            Dict containing total visits, bounce rate, pages per visit, etc.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}

        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-and-engagement/visits"
        return _make_request(endpoint, api_key, params)

    @mcp.tool()
    def similarweb_get_pages_per_visit(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get pages per visit for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-and-engagement/pages-per-visit"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_average_visit_duration(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get average visit duration for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-and-engagement/average-visit-duration"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_bounce_rate(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get bounce rate for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-and-engagement/bounce-rate"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_page_views(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get page views for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-and-engagement/page-views"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_vs_mobile(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get desktop vs mobile split for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-and-engagement/desktop-vs-mobile"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_deduplicated_audience(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get deduplicated audience for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-and-engagement/deduplicated-audience"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_global_rank(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get global rank for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/global-rank/global-rank"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_country_rank(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get country rank for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/country-rank/country-rank"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_industry_rank(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get industry rank for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/industry-rank/industry-rank"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_geography(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get geography data for a specific website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/geography/active-users"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_similar_competitors(domain: str, limit: int = 10) -> dict[str, Any]:
        """
        Find a list of similar websites or competitors for a given domain.

        Args:
            domain: The base website domain (e.g., 'netflix.com')
            limit: Number of similar sites to return (default 10)

        Returns:
            Dict containing a list of similar domains with similarity scores.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res

        params = {"limit": limit}

        params["domain"] = domain
        endpoint = "website-analysis/websites/similar-sites/similarsites"
        return _make_request(endpoint, api_key, params)

    @mcp.tool()
    def similarweb_get_traffic_sources(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """
        Get the distribution of traffic sources (direct, search, social, referrals) for a domain.

        Args:
            domain: The website domain (e.g., 'nytimes.com')
            start_date: Format YYYY-MM. Optional.
            end_date: Format YYYY-MM. Optional.
            country: 2-letter ISO country code or 'world'.

        Returns:
            Dict containing percentage breakdown of incoming traffic channels.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-sources/overview"
        return _make_request(endpoint, api_key, params)

    @mcp.tool()
    def similarweb_get_top_keywords(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
        limit: int = 25,
    ) -> dict[str, Any]:
        """
        Identify top search keywords driving organic or paid traffic to a domain.

        Args:
            domain: The website domain.
            start_date: Format YYYY-MM. Optional.
            end_date: Format YYYY-MM. Optional.
            country: 2-letter ISO country code or 'world'.
            limit: Maximum number of keywords (default 25).

        Returns:
            Dict containing top keywords and their respective traffic share.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res

        params: dict[str, Any] = {"country": country, "limit": limit}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/keywords/organic-search"
        return _make_request(endpoint, api_key, params)

    @mcp.tool()
    def similarweb_get_audience_geography(
        domain: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Get website traffic distribution by country (where visitors are located).

        Args:
            domain: The website domain.
            start_date: Format YYYY-MM. Optional.
            end_date: Format YYYY-MM. Optional.

        Returns:
            Dict containing a list of top countries and their traffic share.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/geography/audience-geography"
        return _make_request(endpoint, api_key, params)

    @mcp.tool()
    def similarweb_get_app_overview(
        app_id: str,
        store: str = "google",
        country: str = "us",
    ) -> dict[str, Any]:
        """
        Get an overview of mobile app performance (downloads, rank, usage).

        Args:
            app_id: The app identifier (e.g., 'com.whatsapp' or '310633997').
            store: 'google' for Play Store or 'apple' for App Store.
            country: 2-letter ISO country code (e.g., 'us').

        Returns:
            Dict containing app analytics like global rank, downloads, and usage patterns.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res

        params: dict[str, Any] = {"country": country, "store": store}
        params["app_id"] = app_id
        endpoint = f"app-analysis/{store}/apps/performance/overview"
        return _make_request(endpoint, api_key, params)

    @mcp.tool()
    def similarweb_get_audience_interests(
        domain: str,
    ) -> dict[str, Any]:
        """
        Identify the browsing interests and other visited categories of a website's audience.

        Args:
            domain: The website domain.

        Returns:
            Dict containing affinity scores for categories and other websites.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res



        endpoint = "website-analysis/websites/audience-interests/also-visited"
        return _make_request(endpoint, api_key, {"domain": domain})

    @mcp.tool()
    def similarweb_get_top_outgoing_links(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Identify the top destination websites traffic flows to from this domain.

        Args:
            domain: The website domain.
            start_date: Format YYYY-MM. Optional.
            end_date: Format YYYY-MM. Optional.

        Returns:
            Dict containing top outgoing links and their traffic share.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-sources/outgoing-links"
        return _make_request(endpoint, api_key, params)

    @mcp.tool()
    def similarweb_get_device_split(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """
        Get the split of traffic between Desktop and Mobile web for a domain.

        Args:
            domain: The website domain.
            start_date: Format YYYY-MM. Optional.
            end_date: Format YYYY-MM. Optional.
            country: 2-letter ISO country code or 'world'.

        Returns:
            Dict showing the desktop vs mobile traffic percentage breakdown.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res

        params: dict[str, Any] = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-and-engagement/desktop-vs-mobile"
        return _make_request(endpoint, api_key, params)

    @mcp.tool()
    def similarweb_get_category_leaders(
        category: str,
        country: str = "world",
        device: str = "Desktop_and_MobileWeb",
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        Get the top websites in a specific industry/category based on traffic.

        Args:
            category: Industry category slug (e.g., 'E-commerce_and_Shopping').
            country: 2-letter ISO country code or 'world'.
            device: 'Desktop', 'MobileWeb', or 'Desktop_and_MobileWeb'.
            limit: Number of leaders to return (default 100).

        Returns:
            Dict listing the category leaders ranked by traffic volume.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res

        params = {"country": country, "device": device, "limit": limit}
        endpoint = f"industry/{category}/top-websites"
        return _make_request(endpoint, api_key, params)

    @mcp.tool()
    def similarweb_get_technologies(
        domain: str,
    ) -> dict[str, Any]:
        """
        Get the software technologies, frameworks, and tracking codes used by a domain.

        Args:
            domain: The website domain.

        Returns:
            Dict listing the technologies grouped by category (e.g., 'Analytics', 'CMS').
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res
        api_key = api_key_res



        endpoint = "website-analysis/websites/technologies/technologies-used"
        return _make_request(endpoint, api_key, {"domain": domain})

    @mcp.tool()
    def similarweb_get_social_media_traffic(
        domain: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Breaks down traffic from different social platforms.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-sources/social"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_referring_websites(
        domain: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Identifies incoming traffic domains (referrals).
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-sources/referrals"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_subdomain_traffic(
        domain: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Analyzes traffic distribution across subdomains.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-and-engagement/subdomains"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_top_pages(
        domain: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Finds the most popular pages/sections of a domain.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/popular-pages/popular-pages"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_app_ranking(
        app_id: str, store: str = "google", country: str = "us"
    ) -> dict[str, Any]:
        """
        Gets App Store/Google Play rankings.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "store": store}
        params["app_id"] = app_id
        endpoint = f"app-analysis/{store}/apps/ranking/category-rank"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_app_engagement(
        app_id: str, store: str = "google", country: str = "us"
    ) -> dict[str, Any]:
        """
        Fetches DAU, MAU, and retention metrics.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "store": store}
        params["app_id"] = app_id
        endpoint = f"app-analysis/{store}/apps/engagement/usage-metrics"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_display_ads_publishers(
        domain: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Identifies ad networks and publishers used.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-sources/display-publishers"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_paid_search_competitors(
        domain: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Identifies PPC/Google Ads competitors.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-sources/paid-search-competitors"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_ad_creatives(
        domain: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Retrieves active ad creatives for a domain.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/traffic-sources/ad-creatives"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_cross_browsing_behavior(
        domain: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Analyzes audience overlap between two domains.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date



        params["domain"] = domain
        endpoint = "website-analysis/websites/audience-interests/cross-browsing"
        return _make_request(endpoint, api_key_res, params)

    @mcp.tool()
    def similarweb_get_company_info(domain: str) -> dict[str, Any]:
        """
        Gets estimated revenue, employee size, HQ location.
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res



        endpoint = "website-analysis/websites/company-info/company-info"
        return _make_request(endpoint, api_key_res, {"domain": domain})

    @mcp.tool()
    def similarweb_get_desktop_visits(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_visits."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/total-traffic-and-engagement/visits-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_pages_per_visit(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_pages_per_visit."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/total-traffic-and-engagement/pages-per-visit-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_average_visit_duration(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_average_visit_duration."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/total-traffic-and-engagement/average-visit-duration-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_bounce_rate(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_bounce_rate."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/total-traffic-and-engagement/bounce-rate-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_pageviews(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_pageviews."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/total-traffic-and-engagement/page-views-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_unique_visitors(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_unique_visitors."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/total-traffic-and-engagement/unique-visitors-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_geography(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_geography."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/geography/desktop-active-users"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_visits_by_channel(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_visits_by_channel."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/desktop-visits-by-channel"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_pages_per_visit_by_channel(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_pages_per_visit_by_channel."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/desktop-pages-per-visit-by-channel"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_average_visit_duration_by_channel(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated tool for similarweb_get_desktop_average_visit_duration_by_channel."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/desktop-average-visit-duration-by-channel"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_bounce_rate_by_channel(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_bounce_rate_by_channel."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/desktop-bounce-rate-by-channel"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_referrals(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_referrals."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/referrals-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_social_referrals(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_social_referrals."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/social-referrals-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_ad_networks(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_ad_networks."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/ad-networks-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_display_publishers(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_display_publishers."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/display-publishers-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_publishers_per_ad_network(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_publishers_per_ad_network."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/publishers-per-ad-network-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_organic_keyword_competitors(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_organic_keyword_competitors."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/keywords/organic-competitors-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_paid_keyword_competitors(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_paid_keyword_competitors."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/keywords/paid-competitors-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_organic_outgoing_links(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_organic_outgoing_links."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/outgoing-links/organic-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_outgoing_ads_networks(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_outgoing_ads_networks."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/outgoing-links/ad-networks-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_outgoing_ads_advertisers(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_outgoing_ads_advertisers."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/outgoing-links/advertisers-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_traffic_sources_by_channel(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_traffic_sources_by_channel."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/overview-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_desktop_ppc_spend(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_desktop_ppc_spend."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/ppc-spend-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_mobile_traffic_sources_by_channel(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_mobile_traffic_sources_by_channel."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/overview-mobile"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_mobile_referrals(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_mobile_referrals."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/referrals-mobile"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_mobile_outgoing_referrals(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_mobile_outgoing_referrals."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/outgoing-links/referrals-mobile"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_mobile_organic_keyword_competitors(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_mobile_organic_keyword_competitors."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/keywords/organic-competitors-mobile"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_mobile_paid_keyword_competitors(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_mobile_paid_keyword_competitors."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/keywords/paid-competitors-mobile"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_all_traffic_ppc_spend(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_all_traffic_ppc_spend."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/traffic-sources/ppc-spend-total"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_audience_demographics_groups(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_audience_demographics_groups."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/audience/demographics-groups"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_audience_demographics_age(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_audience_demographics_age."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/audience/demographics-age"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_audience_demographics_gender(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_audience_demographics_gender."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/audience/demographics-gender"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_audience_interests_all(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_audience_interests_all."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/audience/interests-total"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_audience_interests_desktop(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_audience_interests_desktop."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/audience/interests-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_audience_interests_mobile(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_audience_interests_mobile."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/audience/interests-mobile"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_audience_overlap_desktop(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_audience_overlap_desktop."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/audience/overlap-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_audience_new_vs_returning(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_audience_new_vs_returning."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/audience/new-vs-returning"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_subdomains_desktop(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_subdomains_desktop."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/structure/subdomains-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_subdomains_mobile(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_subdomains_mobile."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/structure/subdomains-mobile"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_folders(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_folders."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/structure/folders"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_popular_pages(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_popular_pages."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/structure/popular-pages"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_custom_segments(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_custom_segments."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "segments/custom/list"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_predefined_segments(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_predefined_segments."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "segments/predefined/list"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_segment_traffic_total(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_segment_traffic_total."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "segments/traffic/total"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_segment_traffic_desktop(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_segment_traffic_desktop."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "segments/traffic/desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_segment_marketing_channels_desktop(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_segment_marketing_channels_desktop."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "segments/marketing-channels/desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_segment_marketing_channels_all(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_segment_marketing_channels_all."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "segments/marketing-channels/total"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_conversion_segments(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_conversion_segments."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "conversions/segments"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_conversion_analysis_desktop(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_conversion_analysis_desktop."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "conversions/analysis-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_api_lite(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_api_lite."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/api-lite"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_website_description(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_website_description."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/description"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_top_similar_rank(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_top_similar_rank."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/similar-ranking"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_top_sites_total(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_top_sites_total."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "top-sites/total"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_top_sites_desktop(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_top_sites_desktop."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "top-sites/desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_top_sites_mobile(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_top_sites_mobile."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "top-sites/mobile"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_rank_tracking_campaigns(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_rank_tracking_campaigns."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "rank-tracking/campaigns"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_rank_tracking_position_trend(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_rank_tracking_position_trend."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "rank-tracking/position-trend"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_rank_tracking_snapshot(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_rank_tracking_snapshot."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "rank-tracking/snapshot"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_rank_tracker_describe(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_rank_tracker_describe."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "rank-tracking/describe"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_list_companies(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_list_companies."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "companies/list"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_company_analysis_total(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_company_analysis_total."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"companies/{domain}/analysis-total"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_company_analysis_desktop(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_company_analysis_desktop."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"companies/{domain}/analysis-desktop"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_company_analysis_mobile(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_company_analysis_mobile."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"companies/{domain}/analysis-mobile"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_website_technologies(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_website_technologies."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/technologies"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_batch_describe_tables(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_batch_describe_tables."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "batch/describe"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_test_webhooks(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_test_webhooks."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "webhooks/test"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_remaining_credits(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_remaining_credits."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "account/remaining-credits"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_remaining_user_credits(
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """A generated SimilarWeb tool for similarweb_get_remaining_user_credits."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "granularity": "monthly"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = "account/user-remaining-credits"
        return _make_request(ep, api_key_res, params)


    @mcp.tool()
    def similarweb_get_keyword_analysis(
        keyword: str,
        country: str = "us",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get keyword analysis metrics like Search Volume, CPC, and Keyword Difficulty."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"keywords/{keyword}/analysis"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_keyword_competitors(
        keyword: str,
        country: str = "us",
        limit: int = 100,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Find domains dominating a specific keyword in organic and paid search results."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country, "limit": limit}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"keywords/{keyword}/competitors"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_app_dau_mau(
        app_id: str,
        store: str,
        country: str = "us",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get Daily Active Users (DAU) and Monthly Active Users (MAU) for a mobile app."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"app/{store}/{app_id}/engagement/dau-mau"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_app_retention(
        app_id: str,
        store: str,
        country: str = "us",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get app retention rate metrics mapping how long users use it after install."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"app/{store}/{app_id}/engagement/retention"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_app_session_details(
        app_id: str,
        store: str,
        country: str = "us",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get details on how much time uses spend using an app per session."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"app/{store}/{app_id}/engagement/session-details"
        return _make_request(ep, api_key_res, params)

    @mcp.tool()
    def similarweb_get_conversion_rate(
        domain: str,
        country: str = "us",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get e-commerce conversion rate (users who made a purchase) for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params: dict[str, Any] = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        ep = f"website/{domain}/conversion-rate"
        return _make_request(ep, api_key_res, params)
