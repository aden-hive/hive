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
    """Helper method to make requests to the SimilarWeb API V5."""
    if params is None:
        params = {}

    # SimilarWeb API v5 uses api-key in the header
    headers = {"api-key": api_key, "Accept": "application/json"}

    url = f"https://api.similarweb.com/v5/{endpoint}"

    try:
        response = httpx.get(url, params=params, headers=headers, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP error {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}


def register_tools(mcp: FastMCP, credentials: CredentialStoreAdapter | None = None) -> None:
    """Register SimilarWeb V5 tools with the MCP server."""

    @mcp.tool()
    def similarweb_v5_traffic_and_engagement(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
        granularity: str = "monthly",
    ) -> dict[str, Any]:
        """
        Get traffic and engagement metrics for a website using V5 API.

        Args:
            domain: The website domain (e.g., 'amazon.com')
            start_date: Start date (YYYY-MM or YYYY-MM-DD)
            end_date: End date (YYYY-MM or YYYY-MM-DD)
            country: 2-letter country code or 'world'
            granularity: 'daily', 'weekly', or 'monthly'
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {
            "metrics": "visits,bounce_rate,avg_visit_duration,pages_per_visit,total_page_views",
            "country": country,
            "granularity": granularity,
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        params["web_source"] = "desktop"
        return _make_request("website-analysis/websites/traffic-and-engagement", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_website_rank(
        domain: str,
    ) -> dict[str, Any]:
        """Get global, country, and category ranks for a website."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request("website-analysis/websites/website-rank", api_key_res, {"domain": domain})

    @mcp.tool()
    def similarweb_v5_traffic_sources(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get marketing channels (traffic sources) breakdown for a website."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/websites/traffic-sources", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_geography(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get traffic distribution by geography for a website."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/websites/traffic-geography", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_demographics(
        domain: str,
    ) -> dict[str, Any]:
        """Get audience demographics (age and gender) for a website."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request("website-analysis/websites/demographics/aggregated", api_key_res, {"domain": domain})

    @mcp.tool()
    def similarweb_v5_company_info(
        domain: str,
    ) -> dict[str, Any]:
        """Get company information (HQ, industry, etc.) for a website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request("website-analysis/websites/company-info/company-info", api_key_res, {"domain": domain})

    @mcp.tool()
    def similarweb_v5_top_sites_by_category(
        category: str,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get top sites in a specific category (e.g., 'Games', 'Lifestyle')."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"category": category, "country": country}
        return _make_request("website-analysis/websites/top-sites-by-category/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_referrals(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get detailed referral traffic sources for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/websites/referrals/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_ppc_spend(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get estimated PPC spend for a website domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/websites/ppc-spend", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_geography_details(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get detailed traffic distribution by country (aggregated)."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/websites/geography/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_similar_sites(
        domain: str,
    ) -> dict[str, Any]:
        """Get a list of websites similar to the given domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request("website-analysis/websites/similar-sites/aggregated", api_key_res, {"domain": domain})

    @mcp.tool()
    def similarweb_v5_ad_networks(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get performance data across different ad networks for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/ad-networks/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_demographics_traffic(
        domain: str,
    ) -> dict[str, Any]:
        """Get traffic breakdown by audience demographic segments."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request(
            "website-analysis/websites/traffic-by-demographics/aggregated", api_key_res, {"domain": domain}
        )

    @mcp.tool()
    def similarweb_v5_deduplicated_audience(
        domains: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """
        Get unique visitor count across multiple domains (comma-separated).

        Args:
            domains: Comma-separated domains (e.g. 'amazon.com,ebay.com')
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"domains": domains, "country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        return _make_request("website-analysis/websites/deduplicated-audience", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_audience_interests(
        domain: str,
    ) -> dict[str, Any]:
        """Get interests and categories relevant to the website's audience."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request("website-analysis/websites/audience-interests/aggregated", api_key_res, {"domain": domain})

    @mcp.tool()
    def similarweb_v5_audience_overlap(
        domain: str,
        compare_to: str,
    ) -> dict[str, Any]:
        """
        Get shared audience between the main domain and a comparison domain.

        Args:
            domain: The main domain
            compare_to: Domain to compare overlap with
        """
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"domain": domain, "compare_to": compare_to}
        return _make_request("website-analysis/websites/audience-overlap/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_technologies(
        domain: str,
    ) -> dict[str, Any]:
        """Get technologies used on the website (CMS, Ads, Analytics, etc.)."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request("website-analysis/websites/technologies/aggregated", api_key_res, {"domain": domain})

    @mcp.tool()
    def similarweb_v5_leading_folders(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get top sub-folders by traffic for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/websites/pages/leading-folders/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_popular_pages(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get most visited pages on the given domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-content/pages/popular-pages/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_subdomains(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get traffic breakdown by subdomain for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-content/subdomains/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_keyword_competitors(
        domain: str,
    ) -> dict[str, Any]:
        """Get organic and paid keyword competitors for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request(
            "website-analysis/websites/keywords-competitors/aggregated", api_key_res, {"domain": domain}
        )

    @mcp.tool()
    def similarweb_v5_keyword_opportunities(
        domain: str,
    ) -> dict[str, Any]:
        """Get keyword gap analysis and opportunities for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request(
            "website-analysis/websites/keywords-opportunities/aggregated", api_key_res, {"domain": domain}
        )

    @mcp.tool()
    def similarweb_v5_serp_features(
        domain: str,
    ) -> dict[str, Any]:
        """Get SERP features analysis for the domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request("website-analysis/websites/keywords/serp-features", api_key_res, {"domain": domain})

    @mcp.tool()
    def similarweb_v5_organic_keywords(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get detailed organic keyword performance for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/websites/keywords/organic/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_paid_keywords(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get detailed paid keyword performance for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/websites/keywords/paid/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_serp_players(
        domain: str,
    ) -> dict[str, Any]:
        """Get top websites driving search traffic for keywords (SERP players)."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request(
            "website-analysis/websites/keywords/serp-players/aggregated", api_key_res, {"domain": domain}
        )

    @mcp.tool()
    def similarweb_v5_social_referrals(
        domain: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get traffic distribution from social networks for a domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["domain"] = domain
        return _make_request("website-analysis/websites/social-referrals/aggregated", api_key_res, params)

    @mcp.tool()
    def similarweb_v5_segments_list(
        domain: str,
    ) -> dict[str, Any]:
        """List custom segments available for the domain."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        return _make_request("segment-analysis/segments/describe", api_key_res, {"domain": domain})

    @mcp.tool()
    def similarweb_v5_segment_analysis(
        segment_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str = "world",
    ) -> dict[str, Any]:
        """Get traffic and engagement for a specific segment ID."""
        api_key_res = _get_api_key(credentials)
        if isinstance(api_key_res, dict):
            return api_key_res

        params = {"country": country}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        params["segment"] = segment_id
        return _make_request("segment-analysis/segments/traffic-and-engagement", api_key_res, params)
