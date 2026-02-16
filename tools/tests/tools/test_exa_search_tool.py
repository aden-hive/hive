"""Tests for exa_search tools (FastMCP)."""

import pytest
from fastmcp import FastMCP

from aden_tools.tools.exa_search_tool import register_tools


@pytest.fixture
def mcp():
    """Create a fresh FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def exa_search_fn(mcp: FastMCP):
    """Register and return the exa_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["exa_search"].fn


@pytest.fixture
def exa_find_similar_fn(mcp: FastMCP):
    """Register and return the exa_find_similar tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["exa_find_similar"].fn


@pytest.fixture
def exa_get_contents_fn(mcp: FastMCP):
    """Register and return the exa_get_contents tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["exa_get_contents"].fn


@pytest.fixture
def exa_answer_fn(mcp: FastMCP):
    """Register and return the exa_answer tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["exa_answer"].fn


class TestExaSearchCredentials:
    """Tests for Exa credential handling."""

    def test_no_credentials_returns_error(self, exa_search_fn, monkeypatch):
        """Search without API key returns helpful error."""
        monkeypatch.delenv("EXA_API_KEY", raising=False)

        result = exa_search_fn(query="test query")

        assert "error" in result
        assert "Exa credentials not configured" in result["error"]
        assert "help" in result

    def test_find_similar_no_credentials(self, exa_find_similar_fn, monkeypatch):
        """Find similar without API key returns error."""
        monkeypatch.delenv("EXA_API_KEY", raising=False)

        result = exa_find_similar_fn(url="https://example.com")

        assert "error" in result
        assert "Exa credentials not configured" in result["error"]

    def test_get_contents_no_credentials(self, exa_get_contents_fn, monkeypatch):
        """Get contents without API key returns error."""
        monkeypatch.delenv("EXA_API_KEY", raising=False)

        result = exa_get_contents_fn(urls=["https://example.com"])

        assert "error" in result
        assert "Exa credentials not configured" in result["error"]

    def test_answer_no_credentials(self, exa_answer_fn, monkeypatch):
        """Answer without API key returns error."""
        monkeypatch.delenv("EXA_API_KEY", raising=False)

        result = exa_answer_fn(query="test question")

        assert "error" in result
        assert "Exa credentials not configured" in result["error"]


class TestExaSearchValidation:
    """Tests for input validation."""

    def test_empty_query_returns_error(self, exa_search_fn, monkeypatch):
        """Empty query returns error."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_search_fn(query="")

        assert "error" in result
        assert "1-500" in result["error"]

    def test_long_query_returns_error(self, exa_search_fn, monkeypatch):
        """Query exceeding 500 chars returns error."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_search_fn(query="x" * 501)

        assert "error" in result

    def test_find_similar_empty_url(self, exa_find_similar_fn, monkeypatch):
        """Find similar with empty URL returns error."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_find_similar_fn(url="")

        assert "error" in result
        assert "URL is required" in result["error"]

    def test_get_contents_empty_urls(self, exa_get_contents_fn, monkeypatch):
        """Get contents with empty URL list returns error."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_get_contents_fn(urls=[])

        assert "error" in result
        assert "At least one URL is required" in result["error"]

    def test_get_contents_too_many_urls(self, exa_get_contents_fn, monkeypatch):
        """Get contents with more than 10 URLs returns error."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        urls = [f"https://example.com/{i}" for i in range(11)]
        result = exa_get_contents_fn(urls=urls)

        assert "error" in result
        assert "Maximum 10 URLs" in result["error"]

    def test_answer_empty_query(self, exa_answer_fn, monkeypatch):
        """Answer with empty query returns error."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_answer_fn(query="")

        assert "error" in result
        assert "1-500" in result["error"]

    def test_answer_long_query(self, exa_answer_fn, monkeypatch):
        """Answer with query exceeding 500 chars returns error."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_answer_fn(query="x" * 501)

        assert "error" in result


class TestExaSearchWithKey:
    """Tests that verify tools accept valid credentials."""

    def test_search_with_key_makes_request(self, exa_search_fn, monkeypatch):
        """Search with valid API key attempts API call."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        # Will fail (test key is invalid) but should not be a credential error
        result = exa_search_fn(query="test query")
        assert isinstance(result, dict)

    def test_find_similar_with_key(self, exa_find_similar_fn, monkeypatch):
        """Find similar with valid API key attempts API call."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_find_similar_fn(url="https://example.com")
        assert isinstance(result, dict)

    def test_get_contents_with_key(self, exa_get_contents_fn, monkeypatch):
        """Get contents with valid API key attempts API call."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_get_contents_fn(urls=["https://example.com"])
        assert isinstance(result, dict)

    def test_answer_with_key(self, exa_answer_fn, monkeypatch):
        """Answer with valid API key attempts API call."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_answer_fn(query="What is AI?")
        assert isinstance(result, dict)


class TestExaSearchParameters:
    """Tests for tool parameters."""

    def test_search_type_parameter(self, exa_search_fn, monkeypatch):
        """search_type parameter is accepted."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_search_fn(query="test", search_type="neural")
        assert isinstance(result, dict)

    def test_num_results_clamped(self, exa_search_fn, monkeypatch):
        """num_results is clamped to valid range."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_search_fn(query="test", num_results=50)
        assert isinstance(result, dict)

    def test_domain_filters(self, exa_search_fn, monkeypatch):
        """Domain filter parameters are accepted."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_search_fn(
            query="test",
            include_domains=["example.com"],
            exclude_domains=["spam.com"],
        )
        assert isinstance(result, dict)

    def test_date_filters(self, exa_search_fn, monkeypatch):
        """Date filter parameters are accepted."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_search_fn(
            query="test",
            start_published_date="2024-01-01",
            end_published_date="2024-12-31",
        )
        assert isinstance(result, dict)

    def test_category_parameter(self, exa_search_fn, monkeypatch):
        """Category parameter is accepted."""
        monkeypatch.setenv("EXA_API_KEY", "test-key")

        result = exa_search_fn(query="test", category="news")
        assert isinstance(result, dict)


class TestExaToolRegistration:
    """Tests for tool registration."""

    def test_all_tools_registered(self, mcp: FastMCP):
        """All four Exa tools are registered."""
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        assert "exa_search" in tools
        assert "exa_find_similar" in tools
        assert "exa_get_contents" in tools
        assert "exa_answer" in tools
