"""Tests for similarweb_tool - Website traffic and competitor analytics (V5 API)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.similarweb_tool.similarweb_tool import register_tools


class MockCredentials:
    def get(self, key: str) -> str | None:
        if key == "similarweb":
            return "test_api_key_123"
        return None


@pytest.fixture
def credentials() -> MockCredentials:
    return MockCredentials()


@pytest.fixture
def mcp_with_tools(credentials: MockCredentials) -> FastMCP:
    mcp = FastMCP("SimilarWebTest")
    register_tools(mcp, credentials=credentials)
    return mcp


class TestSimilarWebToolV5:
    def _mock_response(self, mock_get: MagicMock, json_data: dict) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = json_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

    def _assert_v5_request(
        self,
        mock_get: MagicMock,
        expected_full_endpoint: str,
        expected_params: dict | None = None,
    ) -> None:
        mock_get.assert_called_once()
        actual_url = mock_get.call_args[0][0]
        expected_url = f"https://api.similarweb.com/v5/{expected_full_endpoint}"
        assert actual_url == expected_url

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["api-key"] == "test_api_key_123"
        assert call_kwargs["headers"]["Accept"] == "application/json"

        if expected_params:
            for k, v in expected_params.items():
                assert call_kwargs["params"][k] == v

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_traffic_and_engagement_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {
            "meta": {"request": {"domain": "amazon.com"}},
            "visits": [{"date": "2023-01-01", "visits": 1000}],
        }
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_traffic_and_engagement"]
        result = tool.fn(domain="amazon.com", country="us", granularity="daily")

        self._assert_v5_request(
            mock_get,
            "website-analysis/websites/traffic-and-engagement",
            {
                "domain": "amazon.com",
                "country": "us",
                "granularity": "daily",
                "metrics": "visits,bounce_rate,avg_visit_duration,pages_per_visit,total_page_views",
                "web_source": "desktop",
            },
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_website_rank_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"global_rank": 10, "country_rank": 5}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_website_rank"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(mock_get, "website-analysis/websites/website-rank", {"domain": "amazon.com"})
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_traffic_sources_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"search": 0.4, "direct": 0.3}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_traffic_sources"]
        result = tool.fn(domain="amazon.com", country="world")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/traffic-sources", {"domain": "amazon.com", "country": "world"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_geography_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"top_countries": [{"country": "US", "share": 0.5}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_geography"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(mock_get, "website-analysis/websites/traffic-geography", {"domain": "amazon.com"})
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_demographics_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"age_distribution": {"18-24": 0.2}}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_demographics"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(mock_get, "website-analysis/websites/demographics/aggregated", {"domain": "amazon.com"})
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_company_info_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"company_name": "Amazon", "headquarters": "Seattle, WA"}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_company_info"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/company-info/company-info", {"domain": "amazon.com"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_top_sites_by_category_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"top_sites": [{"domain": "google.com", "rank": 1}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_top_sites_by_category"]
        result = tool.fn(category="Search Engines")

        self._assert_v5_request(
            mock_get,
            "website-analysis/websites/top-sites-by-category/aggregated",
            {"category": "Search Engines", "country": "world"},
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_keyword_competitors_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"competitors": [{"domain": "competitor.com", "overlap": 0.8}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_keyword_competitors"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/keywords-competitors/aggregated", {"domain": "amazon.com"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_technologies_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"technologies": [{"name": "React", "category": "Frontend Framework"}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_technologies"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(mock_get, "website-analysis/websites/technologies/aggregated", {"domain": "amazon.com"})
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_deduplicated_audience_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"total_unique_visitors": 1000000}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_deduplicated_audience"]
        result = tool.fn(domains="amazon.com,ebay.com")

        self._assert_v5_request(
            mock_get,
            "website-analysis/websites/deduplicated-audience",
            {"domains": "amazon.com,ebay.com", "country": "world"},
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_referrals_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"referrals": [{"domain": "google.com", "share": 0.5}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_referrals"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/referrals/aggregated", {"domain": "amazon.com", "country": "world"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_ppc_spend_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"ppc_spend": 5000}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_ppc_spend"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/ppc-spend", {"domain": "amazon.com", "country": "world"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_geography_details_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"top_countries": [{"country": "US", "share": 0.5}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_geography_details"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(mock_get, "website-analysis/websites/geography/aggregated", {"domain": "amazon.com"})
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_similar_sites_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"similar_sites": [{"domain": "ebay.com"}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_similar_sites"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/similar-sites/aggregated", {"domain": "amazon.com"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_ad_networks_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"ad_networks": [{"name": "Google Ads", "share": 0.5}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_ad_networks"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/ad-networks/aggregated", {"domain": "amazon.com", "country": "world"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_demographics_traffic_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"demographics": {"male": 0.5, "female": 0.5}}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_demographics_traffic"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/traffic-by-demographics/aggregated", {"domain": "amazon.com"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_audience_interests_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"interests": ["shopping", "tech"]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_audience_interests"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/audience-interests/aggregated", {"domain": "amazon.com"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_audience_overlap_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"overlap": 0.3}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_audience_overlap"]
        result = tool.fn(domain="amazon.com", compare_to="ebay.com")

        self._assert_v5_request(
            mock_get,
            "website-analysis/websites/audience-overlap/aggregated",
            {"domain": "amazon.com", "compare_to": "ebay.com"},
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_leading_folders_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"folders": [{"name": "/products/", "share": 0.4}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_leading_folders"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get,
            "website-analysis/websites/pages/leading-folders/aggregated",
            {"domain": "amazon.com", "country": "world"},
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_popular_pages_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"pages": [{"url": "amazon.com/best-sellers", "share": 0.1}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_popular_pages"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-content/pages/popular-pages/aggregated", {"domain": "amazon.com", "country": "world"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_subdomains_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"subdomains": [{"name": "aws.amazon.com", "share": 0.2}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_subdomains"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-content/subdomains/aggregated", {"domain": "amazon.com", "country": "world"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_keyword_opportunities_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"opportunities": [{"keyword": "buy electronics", "score": 90}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_keyword_opportunities"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/keywords-opportunities/aggregated", {"domain": "amazon.com"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_serp_features_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"serp_features": {"featured_snippets": 10}}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_serp_features"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(mock_get, "website-analysis/websites/keywords/serp-features", {"domain": "amazon.com"})
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_organic_keywords_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"keywords": [{"phrase": "shopping", "visits": 1000}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_organic_keywords"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get,
            "website-analysis/websites/keywords/organic/aggregated",
            {"domain": "amazon.com", "country": "world"},
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_paid_keywords_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"keywords": [{"phrase": "buy books", "visits": 500}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_paid_keywords"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/keywords/paid/aggregated", {"domain": "amazon.com", "country": "world"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_serp_players_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"players": [{"domain": "walmart.com", "share": 0.1}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_serp_players"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get, "website-analysis/websites/keywords/serp-players/aggregated", {"domain": "amazon.com"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_social_referrals_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"social": [{"name": "Facebook", "share": 0.5}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_social_referrals"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(
            mock_get,
            "website-analysis/websites/social-referrals/aggregated",
            {"domain": "amazon.com", "country": "world"},
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_segments_list_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"segments": [{"id": "seg1", "name": "Segment 1"}]}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_segments_list"]
        result = tool.fn(domain="amazon.com")

        self._assert_v5_request(mock_get, "segment-analysis/segments/describe", {"domain": "amazon.com"})
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_v5_segment_analysis_success(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        response_data = {"metrics": {"visits": 1000}}
        self._mock_response(mock_get, response_data)

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_segment_analysis"]
        result = tool.fn(segment_id="seg1")

        self._assert_v5_request(
            mock_get, "segment-analysis/segments/traffic-and-engagement", {"segment": "seg1", "country": "world"}
        )
        assert result == response_data

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_make_request_error_handling(
        self,
        mock_get: MagicMock,
        mcp_with_tools: FastMCP,
    ) -> None:
        # Mock a 403 error
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403 Forbidden", request=MagicMock(), response=mock_response
        )
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_v5_website_rank"]
        result = tool.fn(domain="forbidden.com")

        assert "error" in result
        assert "403" in result["error"]
        assert "Forbidden" in result["error"]
