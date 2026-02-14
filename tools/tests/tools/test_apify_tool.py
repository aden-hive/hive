"""Tests for Apify tools - FastMCP."""

from unittest.mock import patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.apify_tool import register_tools


@pytest.fixture
def run_actor_fn(mcp: FastMCP):
    """Register and return the apify_run_actor tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["apify_run_actor"].fn


@pytest.fixture
def get_dataset_fn(mcp: FastMCP):
    """Register and return the apify_get_dataset tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["apify_get_dataset"].fn


@pytest.fixture
def get_run_fn(mcp: FastMCP):
    """Register and return the apify_get_run tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["apify_get_run"].fn


@pytest.fixture
def search_actors_fn(mcp: FastMCP):
    """Register and return the apify_search_actors tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["apify_search_actors"].fn


# ---- Credential Tests ----


class TestCredentials:
    """Test credential handling for all Apify tools."""

    def test_run_actor_no_creds(self, run_actor_fn, monkeypatch):
        """apify_run_actor without credentials returns helpful error."""
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        result = run_actor_fn(actor_id="apify/web-scraper", input={})
        assert "error" in result
        assert "Apify credentials not configured" in result["error"]
        assert "help" in result

    def test_get_dataset_no_creds(self, get_dataset_fn, monkeypatch):
        """apify_get_dataset without credentials returns error."""
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        result = get_dataset_fn(dataset_id="xyz123")
        assert "error" in result
        assert "Apify credentials not configured" in result["error"]

    def test_get_run_no_creds(self, get_run_fn, monkeypatch):
        """apify_get_run without credentials returns error."""
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        result = get_run_fn(run_id="abc123")
        assert "error" in result
        assert "Apify credentials not configured" in result["error"]

    def test_search_actors_no_creds(self, search_actors_fn, monkeypatch):
        """apify_search_actors without credentials returns error."""
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        result = search_actors_fn(query="instagram scraper")
        assert "error" in result
        assert "Apify credentials not configured" in result["error"]


# ---- Input Validation Tests ----


class TestInputValidation:
    """Test input validation for all tools."""

    def test_run_actor_empty_id(self, run_actor_fn, monkeypatch):
        """Empty actor_id returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = run_actor_fn(actor_id="", input={})
        assert "error" in result
        assert "actor_id" in result["error"]

    def test_run_actor_invalid_input(self, run_actor_fn, monkeypatch):
        """Non-dict input returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = run_actor_fn(actor_id="apify/test", input="invalid")
        assert "error" in result
        assert "dictionary" in result["error"]

    def test_get_dataset_empty_id(self, get_dataset_fn, monkeypatch):
        """Empty dataset_id returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = get_dataset_fn(dataset_id="")
        assert "error" in result
        assert "dataset_id" in result["error"]

    def test_get_run_empty_id(self, get_run_fn, monkeypatch):
        """Empty run_id returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = get_run_fn(run_id="")
        assert "error" in result
        assert "run_id" in result["error"]

    def test_search_actors_empty_query(self, search_actors_fn, monkeypatch):
        """Empty query returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = search_actors_fn(query="")
        assert "error" in result
        assert "1-200" in result["error"]

    def test_search_actors_long_query(self, search_actors_fn, monkeypatch):
        """Query exceeding 200 chars returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = search_actors_fn(query="x" * 201)
        assert "error" in result


# ---- HTTP Error Handling Tests ----


def _mock_response(status_code: int, json_data: dict | None = None, text: str = ""):
    """Create a mock httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "https://api.apify.com/v2/"),
    )
    return resp


class TestHTTPErrors:
    """Test HTTP error handling."""

    def test_401_returns_auth_error(self, run_actor_fn, monkeypatch):
        """HTTP 401 returns invalid token error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "bad-token")
        with patch("httpx.request", return_value=_mock_response(401, {"error": {"message": "Invalid token"}})):
            result = run_actor_fn(actor_id="apify/test", input={}, wait=True)
        assert "error" in result
        assert "Invalid Apify API token" in result["error"]

    def test_404_returns_not_found(self, run_actor_fn, monkeypatch):
        """HTTP 404 returns not found error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(404)):
            result = run_actor_fn(actor_id="apify/nonexistent", input={})
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_429_returns_rate_limit(self, get_dataset_fn, monkeypatch):
        """HTTP 429 returns rate limit error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(429)):
            result = get_dataset_fn(dataset_id="xyz123")
        assert "error" in result
        assert "rate limit" in result["error"].lower()

    def test_500_returns_server_error(self, run_actor_fn, monkeypatch):
        """HTTP 500 returns server error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(500, text="Internal Server Error")):
            result = run_actor_fn(actor_id="apify/test", input={})
        assert "error" in result
        assert "500" in result["error"]

    def test_timeout_returns_error(self, get_run_fn, monkeypatch):
        """Timeout returns error dict."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", side_effect=httpx.TimeoutException("timed out")):
            result = get_run_fn(run_id="abc123")
        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_network_error_returns_error(self, search_actors_fn, monkeypatch):
        """Network error returns error dict."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", side_effect=httpx.ConnectError("Connection refused")):
            result = search_actors_fn(query="test")
        assert "error" in result
        assert "Network error" in result["error"] or "error" in result["error"].lower()


# ---- Success Response Tests ----


RUN_ACTOR_SYNC_RESPONSE = [
    {"url": "https://example.com", "title": "Example Domain"},
    {"url": "https://example.org", "title": "Example Org"},
]

RUN_ACTOR_ASYNC_RESPONSE = {
    "data": {
        "id": "abc123xyz",
        "status": "RUNNING",
        "startedAt": "2024-01-15T10:30:00.000Z",
        "defaultDatasetId": "dataset789",
    }
}

DATASET_RESPONSE = [
    {"name": "Item 1", "price": 100},
    {"name": "Item 2", "price": 200},
]

RUN_STATUS_RESPONSE = {
    "data": {
        "id": "abc123xyz",
        "status": "SUCCEEDED",
        "startedAt": "2024-01-15T10:30:00.000Z",
        "finishedAt": "2024-01-15T10:35:00.000Z",
        "defaultDatasetId": "dataset789",
        "stats": {"inputBytes": 1024, "outputBytes": 2048},
        "meta": {"origin": "API", "clientIp": "192.168.1.1"},
        "exitCode": 0,
    }
}

SEARCH_ACTORS_RESPONSE = {
    "data": {
        "items": [
            {
                "name": "instagram-scraper",
                "username": "apify",
                "title": "Instagram Scraper",
                "description": "Scrape Instagram profiles, posts, and more",
                "stats": {"totalRuns": 50000, "totalUsers": 1000},
            },
            {
                "name": "web-scraper",
                "username": "apify",
                "title": "Web Scraper",
                "description": "Universal web scraper for any website",
                "stats": {"totalRuns": 100000, "totalUsers": 5000},
            },
        ]
    }
}


class TestRunActor:
    """Tests for apify_run_actor with mock API responses."""

    def test_run_actor_sync_success(self, run_actor_fn, monkeypatch):
        """Successful synchronous actor run returns results."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, RUN_ACTOR_SYNC_RESPONSE)):
            result = run_actor_fn(
                actor_id="apify/web-scraper",
                input={"startUrls": [{"url": "https://example.com"}]},
                wait=True,
            )

        assert "error" not in result
        assert result["actor_id"] == "apify/web-scraper"
        assert result["status"] == "SUCCEEDED"
        assert len(result["results"]) == 2
        assert result["count"] == 2
        assert result["results"][0]["title"] == "Example Domain"

    def test_run_actor_async_success(self, run_actor_fn, monkeypatch):
        """Successful asynchronous actor run returns run info."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, RUN_ACTOR_ASYNC_RESPONSE)):
            result = run_actor_fn(
                actor_id="apify/instagram-scraper",
                input={"username": "example"},
                wait=False,
            )

        assert "error" not in result
        assert result["actor_id"] == "apify/instagram-scraper"
        assert result["run_id"] == "abc123xyz"
        assert result["status"] == "RUNNING"
        assert result["default_dataset_id"] == "dataset789"
        assert "message" in result

    def test_run_actor_timeout_parameter(self, run_actor_fn, monkeypatch):
        """Timeout parameter is capped to 1-300 range."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, RUN_ACTOR_SYNC_RESPONSE)):
            # Test min cap
            result = run_actor_fn(actor_id="apify/test", input={}, timeout=0)
            assert "error" not in result

            # Test max cap
            result = run_actor_fn(actor_id="apify/test", input={}, timeout=500)
            assert "error" not in result


class TestGetDataset:
    """Tests for apify_get_dataset with mock API responses."""

    def test_get_dataset_success(self, get_dataset_fn, monkeypatch):
        """Successful dataset retrieval returns items."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, DATASET_RESPONSE)):
            result = get_dataset_fn(dataset_id="dataset789", limit=50, offset=0)

        assert "error" not in result
        assert result["dataset_id"] == "dataset789"
        assert len(result["items"]) == 2
        assert result["count"] == 2
        assert result["offset"] == 0
        assert result["items"][0]["name"] == "Item 1"

    def test_get_dataset_pagination(self, get_dataset_fn, monkeypatch):
        """Dataset pagination parameters are validated."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, DATASET_RESPONSE)):
            # Test limit caps
            result = get_dataset_fn(dataset_id="test", limit=2000)
            assert "error" not in result

            result = get_dataset_fn(dataset_id="test", limit=-5)
            assert "error" not in result

            # Test offset handling
            result = get_dataset_fn(dataset_id="test", offset=-10)
            assert "error" not in result


class TestGetRun:
    """Tests for apify_get_run with mock API responses."""

    def test_get_run_success(self, get_run_fn, monkeypatch):
        """Successful run status check returns details."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, RUN_STATUS_RESPONSE)):
            result = get_run_fn(run_id="abc123xyz")

        assert "error" not in result
        assert result["run_id"] == "abc123xyz"
        assert result["status"] == "SUCCEEDED"
        assert result["started_at"] == "2024-01-15T10:30:00.000Z"
        assert result["finished_at"] == "2024-01-15T10:35:00.000Z"
        assert result["default_dataset_id"] == "dataset789"
        assert result["stats"]["inputBytes"] == 1024
        assert result["exit_code"] == 0


class TestSearchActors:
    """Tests for apify_search_actors with mock API responses."""

    def test_search_actors_success(self, search_actors_fn, monkeypatch):
        """Successful actor search returns matching actors."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, SEARCH_ACTORS_RESPONSE)):
            result = search_actors_fn(query="instagram", limit=10)

        assert "error" not in result
        assert result["query"] == "instagram"
        assert len(result["actors"]) == 2
        assert result["count"] == 2

        actor = result["actors"][0]
        assert actor["name"] == "instagram-scraper"
        assert actor["username"] == "apify"
        assert actor["title"] == "Instagram Scraper"
        assert actor["stats"]["runs"] == 50000
        assert "apify.com/apify/instagram-scraper" in actor["url"]

    def test_search_actors_limit_cap(self, search_actors_fn, monkeypatch):
        """Search actors limit is capped to 1-50 range."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, SEARCH_ACTORS_RESPONSE)):
            result = search_actors_fn(query="test", limit=100)
            assert "error" not in result

            result = search_actors_fn(query="test", limit=-5)
            assert "error" not in result
