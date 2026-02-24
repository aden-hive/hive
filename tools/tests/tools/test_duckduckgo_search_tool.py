import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.duckduckgo_search_tool.duckduckgo_search_tool import register_tools


@pytest.fixture
def mcp():
    """Mock MCP server."""
    mcp_mock = MagicMock(spec=FastMCP)
    mcp_mock.tool.return_value = lambda f: f
    return mcp_mock


def test_register_tools(mcp):
    """Test register_tools function."""
    register_tools(mcp)
    assert mcp.tool.call_count == 2


@patch("duckduckgo_search.DDGS")
def test_ddg_search_web_success(mock_ddgs_class, mcp):
    """Test web search success."""
    # Setup mock
    mock_instance = MagicMock()
    mock_ddgs_class.return_value.__enter__.return_value = mock_instance
    
    mock_results = [{"title": "Result 1", "body": "Body 1", "href": "https://example.com"}]
    mock_instance.text.return_value = mock_results

    # Need to extract the function that was registered
    registered_funcs = []
    
    def tool_decorator():
        def wrapper(f):
            registered_funcs.append(f)
            return f
        return wrapper
        
    mcp.tool.side_effect = tool_decorator
    register_tools(mcp)
    
    ddg_search_web = [f for f in registered_funcs if f.__name__ == "ddg_search_web"][0]

    result = ddg_search_web("test query", max_results=1)

    assert "error" not in result
    assert result["query"] == "test query"
    assert "results" in result
    assert len(result["results"]) == 1
    assert result["provider"] == "duckduckgo"
    mock_instance.text.assert_called_once_with(
        "test query", max_results=1, backend="api", safesearch="moderate"
    )


@patch("duckduckgo_search.DDGS")
def test_ddg_search_web_failure(mock_ddgs_class, mcp):
    """Test web search failure."""
    mock_instance = MagicMock()
    mock_ddgs_class.return_value.__enter__.return_value = mock_instance
    mock_instance.text.side_effect = Exception("API Error")

    registered_funcs = []
    
    def tool_decorator():
        def wrapper(f):
            registered_funcs.append(f)
            return f
        return wrapper
        
    mcp.tool.side_effect = tool_decorator
    register_tools(mcp)
    
    ddg_search_web = [f for f in registered_funcs if f.__name__ == "ddg_search_web"][0]

    result = ddg_search_web("test query")

    assert "error" in result
    assert "DuckDuckGo search failed" in result["error"]


@patch("duckduckgo_search.DDGS")
def test_ddg_search_news_success(mock_ddgs_class, mcp):
    """Test news search success."""
    mock_instance = MagicMock()
    mock_ddgs_class.return_value.__enter__.return_value = mock_instance
    
    mock_results = [{"title": "News 1", "body": "News Body", "url": "https://news.com"}]
    mock_instance.news.return_value = mock_results

    registered_funcs = []
    
    def tool_decorator():
        def wrapper(f):
            registered_funcs.append(f)
            return f
        return wrapper
        
    mcp.tool.side_effect = tool_decorator
    register_tools(mcp)
    
    ddg_search_news = [f for f in registered_funcs if f.__name__ == "ddg_search_news"][0]

    result = ddg_search_news("test query", max_results=1)

    assert "error" not in result
    assert result["query"] == "test query"
    assert "results" in result
    assert len(result["results"]) == 1
    assert result["provider"] == "duckduckgo"
    mock_instance.news.assert_called_once_with(
        "test query", max_results=1, safesearch="moderate"
    )
