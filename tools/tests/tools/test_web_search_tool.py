"""Tests for web_search tool with multi-provider support (FastMCP)."""

from types import SimpleNamespace

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.web_search_tool import register_tools, web_search_tool


@pytest.fixture
def web_search_fn(mcp: FastMCP, monkeypatch):
    """Register and return the web_search tool function."""
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(200, json={}))
    register_tools(mcp)
    return mcp._tool_manager._tools["web_search"].fn


class TestWebSearchTool:
    """Tests for web_search tool."""

    def test_no_credentials_returns_error(self, web_search_fn, monkeypatch):
        """Search without any credentials returns helpful error."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)

        result = web_search_fn(query="test query")

        assert "error" in result
        assert "No search credentials configured" in result["error"]
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


class TestBraveProvider:
    """Tests for Brave Search provider."""

    def test_brave_missing_api_key(self, web_search_fn, monkeypatch):
        """Brave provider without API key returns error."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        result = web_search_fn(query="test", provider="brave")

        assert "error" in result
        assert "Brave credentials not configured" in result["error"]

    def test_brave_explicit_provider(self, web_search_fn, monkeypatch):
        """Brave provider can be explicitly selected."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        result = web_search_fn(query="test", provider="brave")
        assert isinstance(result, dict)


class TestGoogleProvider:
    """Tests for Google Custom Search provider."""

    def test_google_missing_api_key(self, web_search_fn, monkeypatch):
        """Google provider without API key returns error."""
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)

        result = web_search_fn(query="test", provider="google")

        assert "error" in result
        assert "Google credentials not configured" in result["error"]

    def test_google_missing_cse_id(self, web_search_fn, monkeypatch):
        """Google provider with API key but missing CSE ID returns error."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)

        result = web_search_fn(query="test", provider="google")

        assert "error" in result
        assert "Google credentials not configured" in result["error"]

    def test_google_explicit_provider(self, web_search_fn, monkeypatch):
        """Google provider can be explicitly selected."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        monkeypatch.setenv("GOOGLE_CSE_ID", "test-cse-id")

        result = web_search_fn(query="test", provider="google")
        assert isinstance(result, dict)


class TestAutoProvider:
    """Tests for auto provider selection."""

    def test_auto_prefers_brave_for_backward_compatibility(self, web_search_fn, monkeypatch):
        """Auto mode uses Brave first for backward compatibility."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
        monkeypatch.setenv("GOOGLE_CSE_ID", "test-cse-id")
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-brave-key")

        result = web_search_fn(query="test", provider="auto")
        assert isinstance(result, dict)

    def test_auto_falls_back_to_google(self, web_search_fn, monkeypatch):
        """Auto mode falls back to Google when Brave not available."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
        monkeypatch.setenv("GOOGLE_CSE_ID", "test-cse-id")
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        result = web_search_fn(query="test", provider="auto")
        assert isinstance(result, dict)

    def test_default_provider_is_auto(self, web_search_fn, monkeypatch):
        """Default provider is auto."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        result = web_search_fn(query="test")
        assert isinstance(result, dict)


class TestParameters:
    """Tests for tool parameters."""

    @pytest.mark.parametrize(
        ("num_results", "message"),
        [
            (-1, "num_results must be at least 1"),
            (0, "num_results must be at least 1"),
            (21, "num_results cannot exceed 20"),
        ],
    )
    @pytest.mark.parametrize("provider", ["brave", "google", "auto"])
    @pytest.mark.parametrize("credential_source", ["environment", "store"])
    def test_invalid_num_results_skips_request(self, mcp, mock_credentials, monkeypatch, num_results, message, provider, credential_source):
        """Reject invalid counts before credential lookup or provider requests."""

        def unexpected_credentials(*args, **kwargs):
            pytest.fail("Invalid result counts must not read search credentials")

        monkeypatch.setattr(web_search_tool, "os", SimpleNamespace(getenv=unexpected_credentials))
        monkeypatch.setattr(mock_credentials, "get", unexpected_credentials)
        register_tools(mcp, credentials=mock_credentials if credential_source == "store" else None)
        web_search_fn = mcp._tool_manager._tools["web_search"].fn

        def unexpected_request(*args, **kwargs):
            pytest.fail("Invalid result counts must not reach a search provider")

        monkeypatch.setattr(httpx, "get", unexpected_request)
        assert web_search_fn("test", num_results=num_results, provider=provider) == {"error": message}

    @pytest.mark.parametrize("num_results", [1, 20])
    @pytest.mark.parametrize("provider", ["brave", "google"])
    def test_num_results_boundaries(self, web_search_fn, monkeypatch, num_results, provider):
        """Preserve each provider's result-count cap at both valid boundaries."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        monkeypatch.setenv("GOOGLE_CSE_ID", "test-cse")
        requests = []

        def search_response(url, **kwargs):
            requests.append((url, kwargs["params"]))
            return httpx.Response(200, json={"items": [], "web": {"results": []}})

        monkeypatch.setattr(httpx, "get", search_response)
        result = web_search_fn("test", num_results=num_results, provider=provider)
        assert result["query"] == "test"
        assert result["results"] == []
        assert result["total"] == 0
        assert result["provider"] == provider
        assert len(requests) == 1
        if provider == "brave":
            assert requests[0][1]["count"] == num_results
        else:
            assert requests[0][1]["num"] == min(num_results, 10)

    def test_custom_language_and_country(self, web_search_fn, monkeypatch):
        """Custom language and country parameters are accepted."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        result = web_search_fn(query="test", language="id", country="id")
        assert isinstance(result, dict)

    def test_num_results_parameter(self, web_search_fn, monkeypatch):
        """num_results parameter is accepted."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        result = web_search_fn(query="test", num_results=5)
        assert isinstance(result, dict)
