"""Tests for duckduckgo_tool - DuckDuckGo web, news, and image search."""

from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.duckduckgo_tool.duckduckgo_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _mock_ddgs():
    """Create a mock duckduckgo_search module."""
    mock_mod = ModuleType("duckduckgo_search")
    mock_mod.DDGS = MagicMock
    return mock_mod


class TestDuckDuckGoSearch:
    def test_empty_query(self, tool_fns):
        result = tool_fns["duckduckgo_search"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_mod = _mock_ddgs()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = [
            {"title": "Python.org", "href": "https://python.org", "body": "Official Python site"},
            {"title": "Python Tutorial", "href": "https://docs.python.org", "body": "Learn Python"},
        ]
        mock_mod.DDGS = MagicMock(return_value=mock_ddgs_instance)

        with patch.dict("sys.modules", {"duckduckgo_search": mock_mod}):
            result = tool_fns["duckduckgo_search"](query="python programming")

        assert result["count"] == 2
        assert result["results"][0]["title"] == "Python.org"


class TestDuckDuckGoNews:
    def test_empty_query(self, tool_fns):
        result = tool_fns["duckduckgo_news"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_mod = _mock_ddgs()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.news.return_value = [
            {
                "title": "Tech News",
                "url": "https://news.com/tech",
                "source": "TechCrunch",
                "date": "2024-06-01",
                "body": "Latest tech news",
            }
        ]
        mock_mod.DDGS = MagicMock(return_value=mock_ddgs_instance)

        with patch.dict("sys.modules", {"duckduckgo_search": mock_mod}):
            result = tool_fns["duckduckgo_news"](query="technology")

        assert result["count"] == 1
        assert result["results"][0]["source"] == "TechCrunch"


class TestDuckDuckGoImages:
    def test_empty_query(self, tool_fns):
        result = tool_fns["duckduckgo_images"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_mod = _mock_ddgs()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.images.return_value = [
            {
                "title": "Sunset Photo",
                "image": "https://example.com/sunset.jpg",
                "thumbnail": "https://example.com/sunset_thumb.jpg",
                "source": "Unsplash",
                "width": 1920,
                "height": 1080,
            }
        ]
        mock_mod.DDGS = MagicMock(return_value=mock_ddgs_instance)

        with patch.dict("sys.modules", {"duckduckgo_search": mock_mod}):
            result = tool_fns["duckduckgo_images"](query="sunset")

        assert result["count"] == 1
        assert result["results"][0]["width"] == 1920
