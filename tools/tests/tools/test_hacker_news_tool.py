"""Tests for Hacker News tool."""

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.hacker_news_tool.hacker_news_tool import register_tools


@pytest.fixture
def tools():
    """Register tools and return dict of tool name -> function."""
    tools_dict = {}
    mock_mcp = MagicMock()

    def mock_tool():
        def decorator(f):
            tools_dict[f.__name__] = f
            return f

        return decorator

    mock_mcp.tool = mock_tool
    register_tools(mock_mcp)
    return tools_dict


def test_hacker_news_search_success(tools):
    search_fn = tools["hacker_news_search"]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "hits": [
            {
                "objectID": "12345",
                "title": "Show HN: My AI Project",
                "url": "https://example.com",
                "author": "johndoe",
                "points": 42,
                "num_comments": 10,
                "created_at": "2024-01-15T12:00:00Z",
                "_tags": ["story", "front_page"],
            },
        ],
    }

    patch_target = "aden_tools.tools.hacker_news_tool.hacker_news_tool.httpx.get"
    with patch(patch_target, return_value=mock_response):
        result = search_fn(query="AI agents", max_results=5)

    assert result["query"] == "AI agents"
    assert result["count"] == 1
    assert result["results"][0]["title"] == "Show HN: My AI Project"
    assert result["results"][0]["points"] == 42
    assert result["results"][0]["author"] == "johndoe"


def test_hacker_news_search_empty_query(tools):
    search_fn = tools["hacker_news_search"]
    result = search_fn(query="")
    assert "error" in result
    assert "empty" in result["error"].lower()


def test_hacker_news_search_api_error(tools):
    search_fn = tools["hacker_news_search"]
    mock_response = MagicMock()
    mock_response.status_code = 500

    patch_target = "aden_tools.tools.hacker_news_tool.hacker_news_tool.httpx.get"
    with patch(patch_target, return_value=mock_response):
        result = search_fn(query="test")

    assert "error" in result
    assert "500" in result["error"]


def test_hacker_news_front_page_success(tools):
    front_fn = tools["hacker_news_front_page"]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "hits": [
            {
                "objectID": "111",
                "title": "Top Story",
                "url": "https://example.com/1",
                "author": "alice",
                "points": 500,
                "num_comments": 100,
            },
        ],
    }

    patch_target = "aden_tools.tools.hacker_news_tool.hacker_news_tool.httpx.get"
    with patch(patch_target, return_value=mock_response):
        result = front_fn(max_results=10)

    assert result["count"] == 1
    assert result["results"][0]["title"] == "Top Story"
    assert result["results"][0]["points"] == 500


def test_hacker_news_front_page_api_error(tools):
    front_fn = tools["hacker_news_front_page"]
    mock_response = MagicMock()
    mock_response.status_code = 503

    patch_target = "aden_tools.tools.hacker_news_tool.hacker_news_tool.httpx.get"
    with patch(patch_target, return_value=mock_response):
        result = front_fn()

    assert "error" in result
    assert "503" in result["error"]
