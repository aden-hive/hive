"""
Tests for DuckDuckGo Search tool.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from aden_tools.tools.duckduckgo_search_tool.duckduckgo_search_tool import register_tools


class TestDuckDuckGoSearchTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        register_tools(self.mcp)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.duckduckgo_search_tool.duckduckgo_search_tool.DDGS")
    def test_duckduckgo_search_success(self, mock_ddgs_class):
        mock_ddgs_instance = MagicMock()
        mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs_instance
        mock_ddgs_instance.text.return_value = [
            {"title": "Test", "href": "http://test.com", "body": "Body"}
        ]

        result = self._fn("duckduckgo_search")("Test", max_results=1)

        assert result["success"] is True
        mock_ddgs_instance.text.assert_called_once_with(
            "Test", max_results=1, backend="api", safesearch="moderate"
        )

    @patch("aden_tools.tools.duckduckgo_search_tool.duckduckgo_search_tool.DDGS")
    def test_duckduckgo_news_search_success(self, mock_ddgs_class):
        mock_ddgs_instance = MagicMock()
        mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs_instance
        mock_ddgs_instance.news.return_value = [
            {"title": "News", "url": "http://news.com", "body": "News Body"}
        ]

        result = self._fn("duckduckgo_news_search")("Test News", max_results=1)

        assert result["success"] is True
        mock_ddgs_instance.news.assert_called_once_with(
            "Test News", max_results=1, safesearch="moderate"
        )

    def test_duckduckgo_empty_query(self):
        result_web = self._fn("duckduckgo_search")("   ")
        result_news = self._fn("duckduckgo_news_search")("")
        assert "error" in result_web and "error" in result_news
