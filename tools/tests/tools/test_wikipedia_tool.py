from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.wikipedia_tool.wikipedia_tool import register_tools


@pytest.fixture
def mcp():
    return FastMCP("test-server")


@pytest.fixture
def tool_func(mcp):
    """Register the tool and return the callable function."""
    register_tools(mcp)
    # FastMCP stores tools in _tools dictionary usually, or we can just access
    # the decorated function if we extracted it. Since register_tools uses
    # @mcp.tool(), let's extract the function logic or call via mcp if possible.
    # For unit testing the logic, it's easier if we can access the underlying function.

    # But register_tools defines the function *inside* the scope.
    # So we'll need to rely on how FastMCP exposes tools or refactor slightly?
    # Actually, looking at other tests might help, but let's assume standard FastMCP behavior.
    # If FastMCP.tool() returns the function, we can capture it.
    # But here register_tools returns None.

    # Workaround: We can inspect mcp._tools (if it exists) or use a mock mcp
    # to capture the decorator.

    tools = {}
    mock_mcp = MagicMock()

    def mock_tool():
        def decorator(f):
            tools[f.__name__] = f
            return f

        return decorator

    mock_mcp.tool = mock_tool

    register_tools(mock_mcp)
    return tools["search_wikipedia"]


def test_search_wikipedia_success(tool_func):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "pages": [
            {
                "title": "Artificial Intelligence",
                "key": "Artificial_Intelligence",
                "description": "Intelligence demonstrated by machines",
                "excerpt": "<b>Artificial intelligence</b> (<b>AI</b>)...",
            },
            {
                "title": "AI Winter",
                "key": "AI_Winter",
                "description": "Period of reduced funding",
                "excerpt": "In the history of AI...",
            },
        ]
    }

    patch_target = "aden_tools.tools.wikipedia_tool.wikipedia_tool.httpx.get"
    with patch(patch_target, return_value=mock_response) as mock_get:
        result = tool_func(query="AI")

        assert result["query"] == "AI"
        assert result["count"] == 2
        assert result["results"][0]["title"] == "Artificial Intelligence"
        assert "Artificial_Intelligence" in result["results"][0]["url"]
        # Verify HTML stripping
        assert "<b>" not in result["results"][0]["snippet"]
        assert "Artificial intelligence (AI)..." in result["results"][0]["snippet"]

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert kwargs["params"]["q"] == "AI"


def test_search_wikipedia_empty_query(tool_func):
    result = tool_func(query="")
    assert "error" in result
    assert result["error"] == "Query cannot be empty"


def test_search_wikipedia_api_error(tool_func):
    mock_response = MagicMock()
    mock_response.status_code = 500

    patch_target = "aden_tools.tools.wikipedia_tool.wikipedia_tool.httpx.get"
    with patch(patch_target, return_value=mock_response):
        result = tool_func(query="Error")
        assert "error" in result
        assert "Wikipedia API error: 500" in result["error"]


def test_search_wikipedia_timeout(tool_func):
    import httpx

    patch_target = "aden_tools.tools.wikipedia_tool.wikipedia_tool.httpx.get"
    with patch(patch_target, side_effect=httpx.TimeoutException("Timeout")):
        result = tool_func(query="Timeout")
        assert "error" in result
        assert "Request timed out" in result["error"]
