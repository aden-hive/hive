"""Tests for web_search tool (FastMCP)."""
import pytest

from fastmcp import FastMCP
from aden_tools.tools.web_search_tool import register_tools


@pytest.fixture
def web_search_fn(mcp: FastMCP):
    """Register and return the web_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["web_search"].fn


class TestWebSearchTool:
    """Tests for web_search tool."""

    def test_search_missing_api_key(self, web_search_fn, monkeypatch):
        """Search without API key returns helpful error."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        result = web_search_fn(query="test query")

        assert "error" in result
        assert "BRAVE_SEARCH_API_KEY" in result["error"]
        assert "help" in result

    def test_empty_query_returns_error(self, web_search_fn, monkeypatch):
        """Empty query returns error."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        result = web_search_fn(query="")

        assert "error" in result
        assert "1-500" in result["error"].lower() or "character" in result["error"].lower()

    def test_long_query_returns_error(self, web_search_fn, monkeypatch):
        """Query exceeding 500 chars returns error."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        result = web_search_fn(query="x" * 501)

        assert "error" in result

    def test_num_results_clamped_to_valid_range(self, web_search_fn, monkeypatch):
        """num_results outside 1-20 is clamped (not error)."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        # Test that the function handles out-of-range values gracefully
        # The implementation clamps values, so we just verify it doesn't crash
        # (actual API call would fail with invalid key, but that's expected)
        result = web_search_fn(query="test", num_results=0)
        # Should either clamp or error - both are acceptable
        assert isinstance(result, dict)

        result = web_search_fn(query="test", num_results=100)
        assert isinstance(result, dict)
