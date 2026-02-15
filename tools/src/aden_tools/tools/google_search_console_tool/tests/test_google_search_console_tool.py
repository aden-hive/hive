"""Tests for Google Search Console tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.google_search_console_tool.google_search_console_tool import (
    _GSCClient,
    register_tools,
)


class TestGSCClient:
    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.service_account.Credentials.from_service_account_file")
    def test_init_with_path(self, mock_from_file, mock_build):
        mock_from_file.return_value = MagicMock()
        client = _GSCClient("test-creds.json")
        
        mock_from_file.assert_called_once_with(
            "test-creds.json",
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
        )
        mock_build.assert_called_once()

    @patch("googleapiclient.discovery.build")
    def test_search_analytics(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Setup the mock chain: self._service.searchanalytics().query().execute()
        mock_query = MagicMock()
        mock_service.searchanalytics.return_value.query.return_value = mock_query
        mock_query.execute.return_value = {"rows": [{"keys": ["query1"], "clicks": 10}]}

        with patch("google.auth.default", return_value=(MagicMock(), "project")):
            client = _GSCClient(None)
        
        result = client.search_analytics(
            site_url="https://example.com",
            start_date="2024-01-01",
            end_date="2024-01-07",
            dimensions=["query"],
            query_filter="test"
        )

        mock_service.searchanalytics.return_value.query.assert_called_once()
        args, kwargs = mock_service.searchanalytics.return_value.query.call_args
        assert kwargs["siteUrl"] == "https://example.com"
        assert kwargs["body"]["startDate"] == "2024-01-01"
        assert kwargs["body"]["dimensions"] == ["query"]
        assert kwargs["body"]["dimensionFilterGroups"][0]["filters"][0]["expression"] == "test"
        assert result["rows"][0]["clicks"] == 10

    @patch("googleapiclient.discovery.build")
    def test_list_sites(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.sites.return_value.list.return_value.execute.return_value = {"siteEntry": []}

        with patch("google.auth.default", return_value=(MagicMock(), "project")):
            client = _GSCClient(None)
        
        result = client.list_sites()
        assert "siteEntry" in result


class TestToolRegistration:
    def test_register_tools_registers_all(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 4

    @patch("aden_tools.tools.google_search_console_tool.google_search_console_tool._GSCClient")
    def test_tool_calls_client(self, mock_client_class):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp)
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.search_analytics.return_value = {"success": True}

        # Find gsc_search_analytics in registered_fns
        query_fn = next(fn for fn in registered_fns if fn.__name__ == "gsc_search_analytics")
        
        with patch.dict("os.environ", {"GOOGLE_APPLICATION_CREDENTIALS": "test.json"}):
            result = query_fn(site_url="https://test.com")
        
        assert result == {"success": True}
        mock_client.search_analytics.assert_called_once()
