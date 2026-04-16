"""Tests for similarweb_tool - Website traffic and competitor analytics."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.similarweb_tool.similarweb_tool import register_tools


class MockCredentials:
    def get(self, key):
        if key in ("similarweb", "similarweb_api_key"):
            return "test_api_key_123"
        return None


@pytest.fixture
def credentials():
    return MockCredentials()


@pytest.fixture
def mcp_with_tools(mcp: FastMCP, credentials):
    register_tools(mcp, credentials=credentials)
    return mcp


class TestSimilarWebTool:
    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_website_overview_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_website_overview"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_pages_per_visit_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_pages_per_visit"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_average_visit_duration_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        tool = mcp_with_tools._tool_manager._tools["similarweb_get_average_visit_duration"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_bounce_rate_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_bounce_rate"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_page_views_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_page_views"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_vs_mobile_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_vs_mobile"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_deduplicated_audience_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_deduplicated_audience"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_global_rank_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_global_rank"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_country_rank_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_country_rank"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_industry_rank_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_industry_rank"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_geography_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_geography"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_similar_competitors_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_similar_competitors"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_traffic_sources_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_traffic_sources"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_top_keywords_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_top_keywords"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_geography_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_geography"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_app_overview_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_app_overview"]
        _ = tool.fn(app_id="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_interests_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_interests"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_top_outgoing_links_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_top_outgoing_links"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_device_split_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_device_split"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_category_leaders_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_category_leaders"]
        _ = tool.fn(category="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_technologies_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_technologies"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_social_media_traffic_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_social_media_traffic"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_referring_websites_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_referring_websites"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_subdomain_traffic_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_subdomain_traffic"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_top_pages_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_top_pages"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_app_ranking_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_app_ranking"]
        _ = tool.fn(app_id="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_app_engagement_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_app_engagement"]
        _ = tool.fn(app_id="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_display_ads_publishers_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_display_ads_publishers"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_paid_search_competitors_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_paid_search_competitors"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_ad_creatives_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_ad_creatives"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_cross_browsing_behavior_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_cross_browsing_behavior"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_company_info_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_company_info"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_visits_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_visits"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_pages_per_visit_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_pages_per_visit"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_average_visit_duration_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_average_visit_duration"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_bounce_rate_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_bounce_rate"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_pageviews_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_pageviews"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_unique_visitors_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_unique_visitors"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_geography_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_geography"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_visits_by_channel_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_visits_by_channel"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_pages_per_visit_by_channel_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_desktop_pages_per_visit_by_channel"
        ]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_average_visit_duration_by_channel_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_desktop_average_visit_duration_by_channel"
        ]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_bounce_rate_by_channel_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_bounce_rate_by_channel"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_referrals_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_referrals"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_social_referrals_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_social_referrals"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_ad_networks_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_ad_networks"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_display_publishers_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_display_publishers"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_publishers_per_ad_network_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_desktop_publishers_per_ad_network"
        ]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_organic_keyword_competitors_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_desktop_organic_keyword_competitors"
        ]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_paid_keyword_competitors_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_desktop_paid_keyword_competitors"
        ]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_organic_outgoing_links_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_organic_outgoing_links"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_outgoing_ads_networks_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_outgoing_ads_networks"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_outgoing_ads_advertisers_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_desktop_outgoing_ads_advertisers"
        ]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_traffic_sources_by_channel_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_desktop_traffic_sources_by_channel"
        ]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_desktop_ppc_spend_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_desktop_ppc_spend"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_mobile_traffic_sources_by_channel_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_mobile_traffic_sources_by_channel"
        ]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_mobile_referrals_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_mobile_referrals"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_mobile_outgoing_referrals_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_mobile_outgoing_referrals"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_mobile_organic_keyword_competitors_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_mobile_organic_keyword_competitors"
        ]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_mobile_paid_keyword_competitors_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_mobile_paid_keyword_competitors"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_all_traffic_ppc_spend_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_all_traffic_ppc_spend"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_demographics_groups_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_demographics_groups"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_demographics_age_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_demographics_age"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_demographics_gender_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_demographics_gender"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_interests_all_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_interests_all"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_interests_desktop_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_interests_desktop"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_interests_mobile_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_interests_mobile"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_overlap_desktop_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_overlap_desktop"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_audience_new_vs_returning_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_audience_new_vs_returning"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_subdomains_desktop_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_subdomains_desktop"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_subdomains_mobile_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_subdomains_mobile"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_folders_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_folders"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_popular_pages_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_popular_pages"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_custom_segments_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_custom_segments"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_predefined_segments_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_predefined_segments"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_segment_traffic_total_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_segment_traffic_total"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_segment_traffic_desktop_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_segment_traffic_desktop"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_segment_marketing_channels_desktop_success(
        self, mock_get, mcp_with_tools
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools[
            "similarweb_get_segment_marketing_channels_desktop"
        ]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_segment_marketing_channels_all_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_segment_marketing_channels_all"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_conversion_segments_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_conversion_segments"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_conversion_analysis_desktop_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_conversion_analysis_desktop"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_api_lite_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_api_lite"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_website_description_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_website_description"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_top_similar_rank_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_top_similar_rank"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_top_sites_total_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_top_sites_total"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_top_sites_desktop_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_top_sites_desktop"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_top_sites_mobile_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_top_sites_mobile"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_rank_tracking_campaigns_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_rank_tracking_campaigns"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_rank_tracking_position_trend_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_rank_tracking_position_trend"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_rank_tracking_snapshot_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_rank_tracking_snapshot"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_rank_tracker_describe_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_rank_tracker_describe"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_list_companies_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_list_companies"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_company_analysis_total_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_company_analysis_total"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_company_analysis_desktop_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_company_analysis_desktop"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_company_analysis_mobile_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_company_analysis_mobile"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_website_technologies_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_website_technologies"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_batch_describe_tables_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_batch_describe_tables"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_test_webhooks_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_test_webhooks"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_remaining_credits_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_remaining_credits"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_remaining_user_credits_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_remaining_user_credits"]
        _ = tool.fn()

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_keyword_analysis_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_keyword_analysis"]
        _ = tool.fn(keyword="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_keyword_competitors_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_keyword_competitors"]
        _ = tool.fn(keyword="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_app_dau_mau_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_app_dau_mau"]
        _ = tool.fn(app_id="example_value", store="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_app_retention_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_app_retention"]
        _ = tool.fn(app_id="example_value", store="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_app_session_details_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_app_session_details"]
        _ = tool.fn(app_id="example_value", store="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_similarweb_get_conversion_rate_success(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "success"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        tool = mcp_with_tools._tool_manager._tools["similarweb_get_conversion_rate"]
        _ = tool.fn(domain="example_value")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"]["api-key"] == "test_api_key_123"
        assert mock_get.call_args[1]["params"].get("format") == "json"

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_all_api_http_error_handling(self, mock_get, mcp_with_tools):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        # Have httpx.get raise HTTPStatusError
        mock_get.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=mock_response
        )

        for name, tool in mcp_with_tools._tool_manager._tools.items():
            if not name.startswith("similarweb_get_"):
                continue

            # Determine what argument the tool needs (domain, app_id, or category)
            import inspect

            sig = inspect.signature(tool.fn)
            kwargs = {}
            if "domain" in sig.parameters:
                kwargs["domain"] = "example.com"
            if "app_id" in sig.parameters:
                kwargs["app_id"] = "example_app"
            if "category" in sig.parameters:
                kwargs["category"] = "Arts_and_Entertainment"
            if "keyword" in sig.parameters:
                kwargs["keyword"] = "example_keyword"
            if "store" in sig.parameters:
                kwargs["store"] = "google"

            # Execute the tool
            result = tool.fn(**kwargs)

            # Assert that the error is gracefully caught and returned
            assert "error" in result, f"Tool {name} did not return 'error' key"
            assert "HTTP error 404" in result["error"], (
                f"Tool {name} had wrong error message: {result['error']}"
            )

    @patch("aden_tools.tools.similarweb_tool.similarweb_tool.httpx.get")
    def test_all_api_network_error_handling(self, mock_get, mcp_with_tools):
        # Simulate a network/Request error (like timeout or connection refused)
        mock_get.side_effect = httpx.RequestError("Connection timeout")

        for name, tool in mcp_with_tools._tool_manager._tools.items():
            if not name.startswith("similarweb_get_"):
                continue

            import inspect

            sig = inspect.signature(tool.fn)
            kwargs = {}
            if "domain" in sig.parameters:
                kwargs["domain"] = "example.com"
            if "app_id" in sig.parameters:
                kwargs["app_id"] = "example_app"
            if "category" in sig.parameters:
                kwargs["category"] = "Arts_and_Entertainment"
            if "keyword" in sig.parameters:
                kwargs["keyword"] = "example_keyword"
            if "store" in sig.parameters:
                kwargs["store"] = "google"

            result = tool.fn(**kwargs)

            assert "error" in result, f"Tool {name} did not return 'error' key"
            assert "Request failed: Connection timeout" in result["error"]

    def test_missing_credentials_error(self, mcp):
        # Setup MCP without credentials
        register_tools(mcp, credentials=None)

        tool = mcp._tool_manager._tools["similarweb_get_website_overview"]

        # Temporarily clear environment variable if it exists
        import os

        original_key = os.environ.pop("SIMILARWEB_API_KEY", None)

        try:
            result = tool.fn(domain="example.com")

            assert "error" in result
            assert "credentials not configured" in result["error"]
        finally:
            if original_key is not None:
                os.environ["SIMILARWEB_API_KEY"] = original_key
