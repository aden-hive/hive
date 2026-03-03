"""Tests for the X (Twitter) tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.x_tool.x_tool import (
    X_API_BASE,
    _XClient,
    _XOAuthClient,
    register_tools,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_with_x(monkeypatch):
    """MCP server with all X credentials set."""
    monkeypatch.setenv("X_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("X_API_KEY", "test-api-key")
    monkeypatch.setenv("X_API_SECRET", "test-api-secret")
    monkeypatch.setenv("X_ACCESS_TOKEN", "test-access-token")
    monkeypatch.setenv("X_ACCESS_TOKEN_SECRET", "test-access-secret")

    mcp = FastMCP("test-x")
    register_tools(mcp)
    return mcp


@pytest.fixture
def mcp_bearer_only(monkeypatch):
    """MCP server with only Bearer token set (no OAuth)."""
    monkeypatch.setenv("X_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.delenv("X_API_KEY", raising=False)
    monkeypatch.delenv("X_API_SECRET", raising=False)
    monkeypatch.delenv("X_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("X_ACCESS_TOKEN_SECRET", raising=False)

    mcp = FastMCP("test-x-bearer-only")
    register_tools(mcp)
    return mcp


@pytest.fixture
def mcp_no_creds(monkeypatch):
    """MCP server with no X credentials set."""
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("X_API_KEY", raising=False)
    monkeypatch.delenv("X_API_SECRET", raising=False)
    monkeypatch.delenv("X_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("X_ACCESS_TOKEN_SECRET", raising=False)

    mcp = FastMCP("test-x-no-creds")
    register_tools(mcp)
    return mcp


def _get_tool_fn(mcp, tool_name):
    """Get a tool function from the MCP server."""
    return mcp._tool_manager._tools[tool_name].fn


def _make_response(status_code=200, json_data=None):
    """Create a mock httpx response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {}
    mock_resp.text = "{}"
    return mock_resp


# ---------------------------------------------------------------------------
# TestXClient (Bearer token client)
# ---------------------------------------------------------------------------


class TestXClient:
    """Test the Bearer token client."""

    def setup_method(self):
        self.client = _XClient("test-bearer")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Authorization"] == "Bearer test-bearer"
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "invalid or expired"),
            (403, "insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    def test_handle_response_errors(self, status_code, expected_substring):
        response = _make_response(status_code)
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"].lower()

    def test_handle_response_success(self):
        response = _make_response(200, {"data": [{"id": "1"}]})
        result = self.client._handle_response(response)
        assert result == {"data": [{"id": "1"}]}

    @patch("aden_tools.tools.x_tool.x_tool.httpx.get")
    def test_get_request(self, mock_get):
        mock_get.return_value = _make_response(200, {"data": []})
        result = self.client.get("/tweets/search/recent", params={"query": "test"})

        mock_get.assert_called_once_with(
            f"{X_API_BASE}/tweets/search/recent",
            headers=self.client._headers,
            params={"query": "test"},
            timeout=30.0,
        )
        assert result == {"data": []}

    def test_handle_generic_4xx_error(self):
        response = _make_response(400, {"detail": "Bad request"})
        result = self.client._handle_response(response)
        assert "error" in result
        assert "400" in result["error"]


# ---------------------------------------------------------------------------
# TestXOAuthClient
# ---------------------------------------------------------------------------


class TestXOAuthClient:
    """Test the OAuth 1.0a client."""

    def setup_method(self):
        self.client = _XOAuthClient(
            api_key="test-key",
            api_secret="test-secret",
            access_token="test-access",
            access_token_secret="test-access-secret",
        )

    def test_oauth_signature_generation(self):
        oauth_params = {
            "oauth_consumer_key": "test-key",
            "oauth_nonce": "testnonce",
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": "1234567890",
            "oauth_token": "test-access",
            "oauth_version": "1.0",
        }
        sig = self.client._generate_oauth_signature(
            "POST", "https://api.x.com/2/tweets", oauth_params
        )
        # Should be a non-empty base64 string
        assert sig
        assert len(sig) > 10

    def test_build_auth_header(self):
        header = self.client._build_auth_header("POST", "https://api.x.com/2/tweets")
        assert header.startswith("OAuth ")
        assert "oauth_consumer_key" in header
        assert "oauth_signature" in header
        assert "oauth_token" in header

    @patch("aden_tools.tools.x_tool.x_tool.httpx.post")
    def test_post_request(self, mock_post):
        mock_post.return_value = _make_response(200, {"data": {"id": "123", "text": "hi"}})
        result = self.client.post("/tweets", json_body={"text": "hi"})

        assert mock_post.called
        assert result == {"data": {"id": "123", "text": "hi"}}

    @patch("aden_tools.tools.x_tool.x_tool.httpx.delete")
    def test_delete_request(self, mock_delete):
        mock_delete.return_value = _make_response(200, {"data": {"deleted": True}})
        result = self.client.delete("/tweets/123")

        assert mock_delete.called
        assert result == {"data": {"deleted": True}}

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "oauth 1.0a authentication failed"),
            (403, "insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    def test_handle_response_errors(self, status_code, expected_substring):
        response = _make_response(status_code)
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"].lower()


# ---------------------------------------------------------------------------
# TestCredentials
# ---------------------------------------------------------------------------


class TestCredentials:
    """Test credential validation for all tools."""

    @pytest.mark.parametrize(
        "tool_name",
        ["x_search_tweets", "x_get_mentions"],
    )
    def test_bearer_tools_missing_creds(self, mcp_no_creds, tool_name):
        fn = _get_tool_fn(mcp_no_creds, tool_name)
        if tool_name == "x_search_tweets":
            result = fn(query="test")
        else:
            result = fn(user_id="123")
        assert "error" in result
        assert "bearer" in result["error"].lower()
        assert "help" in result

    @pytest.mark.parametrize(
        "tool_name",
        ["x_post_tweet", "x_reply_tweet", "x_delete_tweet", "x_send_dm"],
    )
    def test_oauth_tools_missing_creds(self, mcp_bearer_only, tool_name):
        """Write tools should fail when OAuth creds are missing (even with bearer)."""
        fn = _get_tool_fn(mcp_bearer_only, tool_name)
        if tool_name == "x_post_tweet":
            result = fn(text="test")
        elif tool_name == "x_reply_tweet":
            result = fn(tweet_id="1", text="test")
        elif tool_name == "x_delete_tweet":
            result = fn(tweet_id="1")
        elif tool_name == "x_send_dm":
            result = fn(participant_id="1", text="test")
        assert "error" in result
        assert "oauth" in result["error"].lower()
        assert "help" in result


# ---------------------------------------------------------------------------
# TestSearchTweets
# ---------------------------------------------------------------------------


class TestSearchTweets:
    """Test x_search_tweets tool."""

    @patch("aden_tools.tools.x_tool.x_tool.httpx.get")
    def test_search_success(self, mock_get, mcp_with_x):
        mock_get.return_value = _make_response(
            200,
            {
                "data": [{"id": "1", "text": "AI is cool"}],
                "meta": {"result_count": 1},
            },
        )

        fn = _get_tool_fn(mcp_with_x, "x_search_tweets")
        result = fn(query="AI agents", max_results=5)

        assert "data" in result
        call_params = mock_get.call_args.kwargs["params"]
        assert call_params["query"] == "AI agents"
        assert call_params["max_results"] == 5

    @patch("aden_tools.tools.x_tool.x_tool.httpx.get")
    def test_search_max_results_capped(self, mock_get, mcp_with_x):
        mock_get.return_value = _make_response(200, {"data": []})

        fn = _get_tool_fn(mcp_with_x, "x_search_tweets")
        fn(query="test", max_results=999)

        call_params = mock_get.call_args.kwargs["params"]
        assert call_params["max_results"] == 100

    @patch("aden_tools.tools.x_tool.x_tool.httpx.get")
    def test_search_timeout(self, mock_get, mcp_with_x):
        mock_get.side_effect = httpx.TimeoutException("timeout")

        fn = _get_tool_fn(mcp_with_x, "x_search_tweets")
        result = fn(query="test")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.x_tool.x_tool.httpx.get")
    def test_search_network_error(self, mock_get, mcp_with_x):
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        fn = _get_tool_fn(mcp_with_x, "x_search_tweets")
        result = fn(query="test")

        assert "error" in result
        assert "network error" in result["error"].lower()


# ---------------------------------------------------------------------------
# TestGetMentions
# ---------------------------------------------------------------------------


class TestGetMentions:
    """Test x_get_mentions tool."""

    @patch("aden_tools.tools.x_tool.x_tool.httpx.get")
    def test_mentions_success(self, mock_get, mcp_with_x):
        mock_get.return_value = _make_response(
            200,
            {
                "data": [{"id": "1", "text": "@user hello"}],
            },
        )

        fn = _get_tool_fn(mcp_with_x, "x_get_mentions")
        result = fn(user_id="12345", max_results=5)

        assert "data" in result
        assert mock_get.call_args.kwargs["params"]["max_results"] == 5

    @patch("aden_tools.tools.x_tool.x_tool.httpx.get")
    def test_mentions_min_clamped(self, mock_get, mcp_with_x):
        mock_get.return_value = _make_response(200, {"data": []})

        fn = _get_tool_fn(mcp_with_x, "x_get_mentions")
        fn(user_id="12345", max_results=-5)

        assert mock_get.call_args.kwargs["params"]["max_results"] == 1


# ---------------------------------------------------------------------------
# TestPostTweet
# ---------------------------------------------------------------------------


class TestPostTweet:
    """Test x_post_tweet tool."""

    @patch("aden_tools.tools.x_tool.x_tool.httpx.post")
    def test_post_success(self, mock_post, mcp_with_x):
        mock_post.return_value = _make_response(
            200,
            {
                "data": {"id": "111", "text": "Hello world"},
            },
        )

        fn = _get_tool_fn(mcp_with_x, "x_post_tweet")
        result = fn(text="Hello world")

        assert "data" in result
        assert result["data"]["id"] == "111"

    def test_post_empty_text(self, mcp_with_x):
        fn = _get_tool_fn(mcp_with_x, "x_post_tweet")
        result = fn(text="")
        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_post_too_long(self, mcp_with_x):
        fn = _get_tool_fn(mcp_with_x, "x_post_tweet")
        result = fn(text="a" * 281)
        assert "error" in result
        assert "280" in result["error"]

    @patch("aden_tools.tools.x_tool.x_tool.httpx.post")
    def test_post_timeout(self, mock_post, mcp_with_x):
        mock_post.side_effect = httpx.TimeoutException("timeout")

        fn = _get_tool_fn(mcp_with_x, "x_post_tweet")
        result = fn(text="Hello")

        assert "error" in result
        assert "timed out" in result["error"].lower()


# ---------------------------------------------------------------------------
# TestReplyTweet
# ---------------------------------------------------------------------------


class TestReplyTweet:
    """Test x_reply_tweet tool."""

    @patch("aden_tools.tools.x_tool.x_tool.httpx.post")
    def test_reply_success(self, mock_post, mcp_with_x):
        mock_post.return_value = _make_response(
            200,
            {
                "data": {"id": "222", "text": "Great point!"},
            },
        )

        fn = _get_tool_fn(mcp_with_x, "x_reply_tweet")
        result = fn(tweet_id="111", text="Great point!")

        assert "data" in result

    def test_reply_empty_text(self, mcp_with_x):
        fn = _get_tool_fn(mcp_with_x, "x_reply_tweet")
        result = fn(tweet_id="111", text="")
        assert "error" in result

    def test_reply_too_long(self, mcp_with_x):
        fn = _get_tool_fn(mcp_with_x, "x_reply_tweet")
        result = fn(tweet_id="111", text="b" * 281)
        assert "error" in result
        assert "280" in result["error"]


# ---------------------------------------------------------------------------
# TestDeleteTweet
# ---------------------------------------------------------------------------


class TestDeleteTweet:
    """Test x_delete_tweet tool."""

    @patch("aden_tools.tools.x_tool.x_tool.httpx.delete")
    def test_delete_success(self, mock_delete, mcp_with_x):
        mock_delete.return_value = _make_response(
            200,
            {
                "data": {"deleted": True},
            },
        )

        fn = _get_tool_fn(mcp_with_x, "x_delete_tweet")
        result = fn(tweet_id="111")

        assert result["data"]["deleted"] is True

    @patch("aden_tools.tools.x_tool.x_tool.httpx.delete")
    def test_delete_not_found(self, mock_delete, mcp_with_x):
        mock_delete.return_value = _make_response(404)

        fn = _get_tool_fn(mcp_with_x, "x_delete_tweet")
        result = fn(tweet_id="999")

        assert "error" in result
        assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# TestSendDM
# ---------------------------------------------------------------------------


class TestSendDM:
    """Test x_send_dm tool."""

    @patch("aden_tools.tools.x_tool.x_tool.httpx.post")
    def test_dm_success(self, mock_post, mcp_with_x):
        mock_post.return_value = _make_response(
            200,
            {
                "data": {"dm_event_id": "999", "text": "Hey there!"},
            },
        )

        fn = _get_tool_fn(mcp_with_x, "x_send_dm")
        result = fn(participant_id="12345", text="Hey there!")

        assert "data" in result
        assert result["data"]["dm_event_id"] == "999"

        # Verify correct v2 1:1 endpoint usage
        call_args = mock_post.call_args
        assert call_args[0][0] == f"{X_API_BASE}/dm_conversations/with/12345/messages"
        assert call_args[1]["json"] == {"text": "Hey there!"}

    def test_dm_empty_text(self, mcp_with_x):
        fn = _get_tool_fn(mcp_with_x, "x_send_dm")
        result = fn(participant_id="12345", text="")
        assert "error" in result
        assert "empty" in result["error"].lower()

    @patch("aden_tools.tools.x_tool.x_tool.httpx.post")
    def test_dm_network_error(self, mock_post, mcp_with_x):
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        fn = _get_tool_fn(mcp_with_x, "x_send_dm")
        result = fn(participant_id="12345", text="Hello")

        assert "error" in result
        assert "network error" in result["error"].lower()

    def test_dm_missing_oauth_creds(self, mcp_bearer_only):
        fn = _get_tool_fn(mcp_bearer_only, "x_send_dm")
        result = fn(participant_id="12345", text="Hello")
        assert "error" in result
        assert "oauth" in result["error"].lower()


# ---------------------------------------------------------------------------
# TestAPIErrorHandling
# ---------------------------------------------------------------------------


class TestAPIErrorHandling:
    """Test HTTP error code handling across tools."""

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "invalid or expired"),
            (403, "insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    @patch("aden_tools.tools.x_tool.x_tool.httpx.get")
    def test_bearer_error_codes(self, mock_get, status_code, expected_substring, mcp_with_x):
        mock_get.return_value = _make_response(status_code)

        fn = _get_tool_fn(mcp_with_x, "x_search_tweets")
        result = fn(query="test")

        assert "error" in result
        assert expected_substring in result["error"].lower()

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "oauth 1.0a authentication failed"),
            (403, "insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    @patch("aden_tools.tools.x_tool.x_tool.httpx.post")
    def test_oauth_error_codes(self, mock_post, status_code, expected_substring, mcp_with_x):
        mock_post.return_value = _make_response(status_code)

        fn = _get_tool_fn(mcp_with_x, "x_post_tweet")
        result = fn(text="test")

        assert "error" in result
        assert expected_substring in result["error"].lower()


# ---------------------------------------------------------------------------
# TestToolRegistration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Test that all tools are properly registered."""

    def test_all_tools_registered(self, mcp_with_x):
        tools = mcp_with_x._tool_manager._tools
        expected = [
            "x_search_tweets",
            "x_get_mentions",
            "x_post_tweet",
            "x_reply_tweet",
            "x_delete_tweet",
            "x_send_dm",
        ]
        for name in expected:
            assert name in tools, f"Tool '{name}' not registered"

    def test_tool_count(self, mcp_with_x):
        tools = mcp_with_x._tool_manager._tools
        x_tools = [name for name in tools if name.startswith("x_")]
        assert len(x_tools) == 6


# ---------------------------------------------------------------------------
# TestCredentialSpecs
# ---------------------------------------------------------------------------


class TestCredentialSpecs:
    """Test credential spec definitions."""

    def test_x_credential_specs_exist(self):
        from aden_tools.credentials.x import X_CREDENTIALS

        expected_keys = [
            "x_bearer_token",
            "x_api_key",
            "x_api_secret",
            "x_access_token",
            "x_access_token_secret",
        ]
        for key in expected_keys:
            assert key in X_CREDENTIALS, f"Missing credential spec: {key}"

    def test_bearer_token_spec(self):
        from aden_tools.credentials.x import X_CREDENTIALS

        spec = X_CREDENTIALS["x_bearer_token"]
        assert spec.env_var == "X_BEARER_TOKEN"
        assert "x_search_tweets" in spec.tools
        assert "x_post_tweet" in spec.tools
        assert "x_send_dm" in spec.tools
        assert spec.credential_group == "x"

    def test_oauth_specs_are_optional(self):
        from aden_tools.credentials.x import X_CREDENTIALS

        for key in ["x_api_key", "x_api_secret", "x_access_token", "x_access_token_secret"]:
            assert X_CREDENTIALS[key].required is False

    def test_specs_in_merged_registry(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "x_bearer_token" in CREDENTIAL_SPECS
        assert "x_api_key" in CREDENTIAL_SPECS
