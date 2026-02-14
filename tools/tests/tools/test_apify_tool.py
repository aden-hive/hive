"""Tests for Apify tools (Web Scraping & Automation Marketplace) - FastMCP."""

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
        result = run_actor_fn(actor_id="apify/instagram-scraper")
        assert "error" in result
        assert "Apify credentials not configured" in result["error"]
        assert "help" in result

    def test_get_dataset_no_creds(self, get_dataset_fn, monkeypatch):
        """apify_get_dataset without credentials returns error."""
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        result = get_dataset_fn(dataset_id="xyz789")
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
        result = search_actors_fn(query="instagram")
        assert "error" in result
        assert "Apify credentials not configured" in result["error"]


# ---- Input Validation Tests ----


class TestInputValidation:
    """Test input validation for all tools."""

    def test_empty_actor_id(self, run_actor_fn, monkeypatch):
        """Empty actor_id returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = run_actor_fn(actor_id="")
        assert "error" in result
        assert "Invalid actor_id" in result["error"]

    def test_invalid_actor_id_format(self, run_actor_fn, monkeypatch):
        """Invalid actor_id format returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        # Missing slash
        result = run_actor_fn(actor_id="instagram-scraper")
        assert "error" in result
        assert "Invalid actor_id" in result["error"]

    def test_valid_actor_id_formats(self, run_actor_fn, monkeypatch):
        """Valid actor_id formats pass validation."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        
        # These should pass validation (will fail at API call, but that's OK for this test)
        valid_ids = [
            "apify/instagram-scraper",
            "~username/custom-actor",
            "abc123def456",  # Actor ID
        ]
        
        for actor_id in valid_ids:
            with patch("httpx.request") as mock_request:
                mock_request.side_effect = httpx.RequestError("Test")
                result = run_actor_fn(actor_id=actor_id)
                # Should hit network error, not validation error
                assert "Network error" in result.get("error", "")

    def test_empty_dataset_id(self, get_dataset_fn, monkeypatch):
        """Empty dataset_id returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = get_dataset_fn(dataset_id="")
        assert "error" in result
        assert "dataset_id is required" in result["error"]

    def test_invalid_dataset_limit(self, get_dataset_fn, monkeypatch):
        """Invalid dataset limit returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = get_dataset_fn(dataset_id="xyz", limit=0)
        assert "error" in result
        assert "between 1 and 10000" in result["error"]
        
        result = get_dataset_fn(dataset_id="xyz", limit=20000)
        assert "error" in result
        assert "between 1 and 10000" in result["error"]

    def test_empty_run_id(self, get_run_fn, monkeypatch):
        """Empty run_id returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = get_run_fn(run_id="")
        assert "error" in result
        assert "run_id is required" in result["error"]

    def test_empty_search_query(self, search_actors_fn, monkeypatch):
        """Empty search query returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = search_actors_fn(query="")
        assert "error" in result
        assert "query is required" in result["error"]

    def test_invalid_search_limit(self, search_actors_fn, monkeypatch):
        """Invalid search limit returns error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        result = search_actors_fn(query="test", limit=0)
        assert "error" in result
        
        result = search_actors_fn(query="test", limit=200)
        assert "error" in result


# ---- HTTP Error Handling Tests ----


def _mock_response(status_code: int, json_data: dict | list | None = None, text: str = ""):
    """Create a mock httpx.Response."""
    from unittest.mock import Mock
    
    resp = Mock(spec=httpx.Response)
    resp.status_code = status_code
    
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.return_value = {}
    
    resp.text = text if text else "{}"
    
    return resp


class TestHTTPErrors:
    """Test HTTP error handling."""

    def test_401_returns_auth_error(self, run_actor_fn, monkeypatch):
        """HTTP 401 returns invalid API token error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "bad-token")
        with patch("httpx.request", return_value=_mock_response(401)):
            result = run_actor_fn(actor_id="apify/instagram-scraper")
        assert "error" in result
        assert "Invalid Apify API token" in result["error"]

    def test_404_returns_not_found(self, run_actor_fn, monkeypatch):
        """HTTP 404 returns resource not found error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(404)):
            result = run_actor_fn(actor_id="invalid/actor")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_429_returns_rate_limit(self, run_actor_fn, monkeypatch):
        """HTTP 429 returns rate limit error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(429)):
            result = run_actor_fn(actor_id="apify/instagram-scraper")
        assert "error" in result
        assert "rate limit" in result["error"].lower()

    def test_500_returns_server_error(self, run_actor_fn, monkeypatch):
        """HTTP 500 returns server error."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(500, text="Internal Error")):
            result = run_actor_fn(actor_id="apify/instagram-scraper")
        assert "error" in result
        assert "500" in result["error"]

    def test_timeout_returns_error(self, run_actor_fn, monkeypatch):
        """Timeout returns error dict."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", side_effect=httpx.TimeoutException("timed out")):
            result = run_actor_fn(actor_id="apify/instagram-scraper")
        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_network_error_returns_error(self, run_actor_fn, monkeypatch):
        """Network error returns error dict."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", side_effect=httpx.ConnectError("Connection refused")):
            result = run_actor_fn(actor_id="apify/instagram-scraper")
        assert "error" in result
        assert "error" in result["error"].lower()


# ---- Success Response Tests ----


SYNC_RUN_RESPONSE = [
    {"username": "instagram", "fullName": "Instagram", "followersCount": 500000000},
    {"username": "google", "fullName": "Google", "followersCount": 20000000},
]

ASYNC_RUN_RESPONSE = {
    "data": {
        "id": "run123abc",
        "status": "RUNNING",
        "startedAt": "2024-01-15T10:00:00.000Z",
        "defaultDatasetId": "dataset456xyz",
    }
}

DATASET_RESPONSE = [
    {"title": "Example Page 1", "url": "https://example.com/1"},
    {"title": "Example Page 2", "url": "https://example.com/2"},
]

RUN_STATUS_RESPONSE = {
    "data": {
        "id": "run123abc",
        "status": "SUCCEEDED",
        "startedAt": "2024-01-15T10:00:00.000Z",
        "finishedAt": "2024-01-15T10:05:00.000Z",
        "defaultDatasetId": "dataset456xyz",
        "stats": {"inputBytes": 100, "outputBytes": 5000},
    }
}

SEARCH_RESPONSE = {
    "data": {
        "total": 24,
        "items": [
            {
                "id": "actor1",
                "name": "instagram-profile-scraper",
                "username": "apify",
                "title": "Instagram Profile Scraper",
                "description": "Scrape Instagram profiles, posts, and stories",
                "stats": {"totalRuns": 50000},
            },
            {
                "id": "actor2",
                "name": "instagram-hashtag-scraper",
                "username": "apify",
                "title": "Instagram Hashtag Scraper",
                "description": "Scrape posts by hashtag",
                "stats": {"totalRuns": 30000},
            },
        ],
    }
}


class TestRunActor:
    """Tests for apify_run_actor with mock API responses."""

    def test_synchronous_run(self, run_actor_fn, monkeypatch):
        """Synchronous run (wait=True) returns results immediately."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, SYNC_RUN_RESPONSE)):
            result = run_actor_fn(
                actor_id="apify/instagram-scraper",
                input={"usernames": ["instagram"]},
                wait=True,
            )

        assert "error" not in result
        assert result["status"] == "SUCCEEDED"
        assert result["count"] == 2
        assert len(result["items"]) == 2
        assert result["items"][0]["username"] == "instagram"

    def test_asynchronous_run(self, run_actor_fn, monkeypatch):
        """Asynchronous run (wait=False) returns run_id."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, ASYNC_RUN_RESPONSE)):
            result = run_actor_fn(
                actor_id="apify/web-scraper",
                input={"startUrls": [{"url": "https://example.com"}]},
                wait=False,
            )

        assert "error" not in result
        assert result["run_id"] == "run123abc"
        assert result["status"] == "RUNNING"
        assert result["default_dataset_id"] == "dataset456xyz"

    def test_default_empty_input(self, run_actor_fn, monkeypatch):
        """Default input is empty dict when not provided."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, SYNC_RUN_RESPONSE)) as mock:
            run_actor_fn(actor_id="apify/test-actor")
            # Verify empty dict was sent
            call_kwargs = mock.call_args[1]
            assert call_kwargs["json"] == {}


class TestGetDataset:
    """Tests for apify_get_dataset with mock API responses."""

    def test_successful_retrieval(self, get_dataset_fn, monkeypatch):
        """Successful dataset retrieval returns items."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, DATASET_RESPONSE)):
            result = get_dataset_fn(dataset_id="dataset456xyz")

        assert "error" not in result
        assert result["count"] == 2
        assert len(result["items"]) == 2
        assert result["items"][0]["title"] == "Example Page 1"

    def test_custom_limit(self, get_dataset_fn, monkeypatch):
        """Custom limit parameter works."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, DATASET_RESPONSE)) as mock:
            get_dataset_fn(dataset_id="xyz", limit=50)
            params = mock.call_args[1]["params"]
            assert params["limit"] == 50


class TestGetRun:
    """Tests for apify_get_run with mock API responses."""

    def test_successful_status_check(self, get_run_fn, monkeypatch):
        """Successful run status check returns details."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, RUN_STATUS_RESPONSE)):
            result = get_run_fn(run_id="run123abc")

        assert "error" not in result
        assert result["run_id"] == "run123abc"
        assert result["status"] == "SUCCEEDED"
        assert result["default_dataset_id"] == "dataset456xyz"
        assert "stats" in result


class TestSearchActors:
    """Tests for apify_search_actors with mock API responses."""

    def test_successful_search(self, search_actors_fn, monkeypatch):
        """Successful actor search returns results."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, SEARCH_RESPONSE)):
            result = search_actors_fn(query="instagram")

        assert "error" not in result
        assert result["total"] == 24
        assert result["count"] == 2
        assert len(result["items"]) == 2
        assert result["items"][0]["name"] == "instagram-profile-scraper"
        assert result["items"][0]["username"] == "apify"

    def test_custom_limit(self, search_actors_fn, monkeypatch):
        """Custom limit parameter works."""
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        with patch("httpx.request", return_value=_mock_response(200, SEARCH_RESPONSE)) as mock:
            search_actors_fn(query="test", limit=5)
            params = mock.call_args[1]["params"]
            assert params["limit"] == 5
