"""Tests for google_search_console_tool - Search analytics, sitemaps, and URL inspection."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.google_search_console_tool.google_search_console_tool import register_tools

ENV = {"GOOGLE_SEARCH_CONSOLE_TOKEN": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestGscSearchAnalytics:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["gsc_search_analytics"](
                site_url="https://example.com", start_date="2024-01-01", end_date="2024-01-31"
            )
        assert "error" in result

    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["gsc_search_analytics"](site_url="", start_date="", end_date="")
        assert "error" in result

    def test_successful_query(self, tool_fns):
        mock_resp = {
            "rows": [
                {
                    "keys": ["best crm software"],
                    "clicks": 150,
                    "impressions": 5000,
                    "ctr": 0.03,
                    "position": 4.2,
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.google_search_console_tool.google_search_console_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["gsc_search_analytics"](
                site_url="https://example.com", start_date="2024-01-01", end_date="2024-01-31"
            )

        assert len(result["rows"]) == 1
        assert result["rows"][0]["clicks"] == 150


class TestGscListSites:
    def test_successful_list(self, tool_fns):
        mock_resp = {"siteEntry": [{"siteUrl": "https://example.com", "permissionLevel": "siteOwner"}]}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.google_search_console_tool.google_search_console_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["gsc_list_sites"]()

        assert len(result["sites"]) == 1
        assert result["sites"][0]["site_url"] == "https://example.com"


class TestGscListSitemaps:
    def test_missing_site(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["gsc_list_sitemaps"](site_url="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "sitemap": [
                {
                    "path": "https://example.com/sitemap.xml",
                    "lastSubmitted": "2024-01-01T00:00:00Z",
                    "isPending": False,
                    "isSitemapsIndex": True,
                    "warnings": 0,
                    "errors": 0,
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.google_search_console_tool.google_search_console_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["gsc_list_sitemaps"](site_url="https://example.com")

        assert len(result["sitemaps"]) == 1
        assert result["sitemaps"][0]["is_index"] is True


class TestGscInspectUrl:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["gsc_inspect_url"](site_url="", inspection_url="")
        assert "error" in result

    def test_successful_inspect(self, tool_fns):
        mock_resp = {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": "PASS",
                    "coverageState": "Submitted and indexed",
                    "indexingState": "INDEXING_ALLOWED",
                    "lastCrawlTime": "2024-01-15T10:00:00Z",
                    "crawledAs": "DESKTOP",
                    "pageFetchState": "SUCCESSFUL",
                    "robotsTxtState": "ALLOWED",
                },
                "mobileUsabilityResult": {"verdict": "PASS"},
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.google_search_console_tool.google_search_console_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["gsc_inspect_url"](
                site_url="https://example.com",
                inspection_url="https://example.com/page",
            )

        assert result["verdict"] == "PASS"
        assert result["indexing_state"] == "INDEXING_ALLOWED"


class TestGscSubmitSitemap:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["gsc_submit_sitemap"](site_url="", sitemap_url="")
        assert "error" in result

    def test_successful_submit(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.google_search_console_tool.google_search_console_tool.httpx.put") as mock_put,
        ):
            mock_put.return_value.status_code = 204
            result = tool_fns["gsc_submit_sitemap"](
                site_url="https://example.com",
                sitemap_url="https://example.com/sitemap.xml",
            )

        assert result["status"] == "submitted"
