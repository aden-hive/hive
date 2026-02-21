"""Tests for Twitter tool with FastMCP."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.twitter_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def twitter_create_tweet_fn(mcp: FastMCP):
    """Register and return the twitter_create_tweet tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["twitter_create_tweet"].fn


@pytest.fixture
def twitter_get_user_fn(mcp: FastMCP):
    """Register and return the twitter_get_user tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["twitter_get_user"].fn


@pytest.fixture
def twitter_search_tweets_fn(mcp: FastMCP):
    """Register and return the twitter_search_tweets tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["twitter_search_tweets"].fn


@pytest.fixture
def twitter_get_me_fn(mcp: FastMCP):
    """Register and return the twitter_get_me tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["twitter_get_me"].fn


class TestTwitterCredentials:
    """Tests for Twitter credential handling."""

    def test_no_credentials_returns_error(self, twitter_create_tweet_fn, monkeypatch):
        """Send without credentials returns helpful error."""
        monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)

        result = twitter_create_tweet_fn(text="Hello world")

        assert "error" in result
        assert "Twitter credentials not configured" in result["error"]
        assert "help" in result


class TestTwitterCreateTweet:
    """Tests for twitter_create_tweet tool."""

    def test_create_tweet_success(self, twitter_create_tweet_fn, monkeypatch):
        """Successful tweet creation returns tweet ID."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"data": {"id": "1234567890", "text": "Hello world"}}
            mock_post.return_value = mock_response

            result = twitter_create_tweet_fn(text="Hello world")

        assert result["success"] is True
        assert result["tweet_id"] == "1234567890"
        assert result["text"] == "Hello world"

    def test_create_tweet_empty_text(self, twitter_create_tweet_fn, monkeypatch):
        """Empty tweet text returns error."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        result = twitter_create_tweet_fn(text="")

        assert "error" in result
        assert "cannot be empty" in result["error"]

    def test_create_tweet_too_long(self, twitter_create_tweet_fn, monkeypatch):
        """Tweet over 280 characters returns error."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        long_text = "a" * 281
        result = twitter_create_tweet_fn(text=long_text)

        assert "error" in result
        assert "280 characters" in result["error"]

    def test_create_tweet_with_reply(self, twitter_create_tweet_fn, monkeypatch):
        """Tweet with reply includes in_reply_to_tweet_id."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"data": {"id": "1234567891", "text": "Great point!"}}
            mock_post.return_value = mock_response

            result = twitter_create_tweet_fn(text="Great point!", reply_to_tweet_id="1234567890")

        assert result["success"] is True
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["reply"] == {"in_reply_to_tweet_id": "1234567890"}


class TestTwitterGetUser:
    """Tests for twitter_get_user tool."""

    def test_get_user_success(self, twitter_get_user_fn, monkeypatch):
        """Get user returns user details."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "id": "1234567890",
                    "username": "elonmusk",
                    "name": "Elon Musk",
                    "public_metrics": {
                        "followers_count": 1000000,
                        "following_count": 100,
                    },
                }
            }
            mock_get.return_value = mock_response

            result = twitter_get_user_fn(username="elonmusk")

        assert result["success"] is True
        assert result["user"]["username"] == "elonmusk"
        assert result["user"]["name"] == "Elon Musk"

    def test_get_user_not_found(self, twitter_get_user_fn, monkeypatch):
        """User not found returns error."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {"title": "Not Found", "detail": "User not found"}
            mock_get.return_value = mock_response

            result = twitter_get_user_fn(username="nonexistentuser123")

        assert "error" in result

    def test_get_user_empty_username(self, twitter_get_user_fn, monkeypatch):
        """Empty username returns error."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        result = twitter_get_user_fn(username="")

        assert "error" in result
        assert "required" in result["error"]


class TestTwitterSearchTweets:
    """Tests for twitter_search_tweets tool."""

    def test_search_tweets_success(self, twitter_search_tweets_fn, monkeypatch):
        """Search tweets returns matching tweets."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [
                    {"id": "1", "text": "Tweet about AI"},
                    {"id": "2", "text": "Another tweet about AI"},
                ]
            }
            mock_get.return_value = mock_response

            result = twitter_search_tweets_fn(query="AI", max_results=10)

        assert result["success"] is True
        assert result["count"] == 2
        assert "AI" in result["tweets"][0]["text"]

    def test_search_tweets_empty_query(self, twitter_search_tweets_fn, monkeypatch):
        """Empty search query returns error."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        result = twitter_search_tweets_fn(query="")

        assert "error" in result
        assert "query is required" in result["error"]

    def test_search_tweets_rate_limit(self, twitter_search_tweets_fn, monkeypatch):
        """Rate limit returns appropriate error."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.json.return_value = {"title": "Too Many Requests"}
            mock_get.return_value = mock_response

            result = twitter_search_tweets_fn(query="test")

        assert "error" in result
        assert "rate limit" in result["error"].lower()


class TestTwitterGetMe:
    """Tests for twitter_get_me tool."""

    def test_get_me_success(self, twitter_get_me_fn, monkeypatch):
        """Get authenticated user returns profile."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "id": "1234567890",
                    "username": "testuser",
                    "name": "Test User",
                }
            }
            mock_get.return_value = mock_response

            result = twitter_get_me_fn()

        assert result["success"] is True
        assert result["user"]["username"] == "testuser"

    def test_get_me_invalid_token(self, twitter_get_me_fn, monkeypatch):
        """Invalid token returns error."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "invalid-token")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"title": "Unauthorized"}
            mock_get.return_value = mock_response

            result = twitter_get_me_fn()

        assert "error" in result
        assert "Invalid" in result["error"]


# ============================================================================
# Additional Tool Tests
# ============================================================================


@pytest.fixture
def get_tool_fn(mcp: FastMCP):
    """Factory fixture to get any tool function by name."""
    register_tools(mcp)

    def _get(name: str):
        return mcp._tool_manager._tools[name].fn

    return _get


class TestTwitterGetTweet:
    """Tests for twitter_get_tweet tool."""

    def test_get_tweet_success(self, get_tool_fn, monkeypatch):
        """Get tweet returns tweet details."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
        fn = get_tool_fn("twitter_get_tweet")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "id": "1234567890",
                    "text": "Hello world",
                    "public_metrics": {"retweet_count": 10, "like_count": 100},
                }
            }
            mock_get.return_value = mock_response

            result = fn(tweet_id="1234567890")

        assert result["success"] is True
        assert result["tweet"]["text"] == "Hello world"

    def test_get_tweet_empty_id(self, get_tool_fn, monkeypatch):
        """Empty tweet ID returns error."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
        fn = get_tool_fn("twitter_get_tweet")

        result = fn(tweet_id="")

        assert "error" in result
        assert "required" in result["error"]


class TestTwitterDeleteTweet:
    """Tests for twitter_delete_tweet tool."""

    def test_delete_tweet_success(self, get_tool_fn, monkeypatch):
        """Delete tweet returns success."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
        fn = get_tool_fn("twitter_delete_tweet")

        with patch("httpx.delete") as mock_delete:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_delete.return_value = mock_response

            result = fn(tweet_id="1234567890")

        assert result["success"] is True
        assert result["deleted_tweet_id"] == "1234567890"


class TestTwitterLikeTweet:
    """Tests for twitter_like_tweet tool."""

    def test_like_tweet_success(self, get_tool_fn, monkeypatch):
        """Like tweet returns success."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
        fn = get_tool_fn("twitter_like_tweet")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            result = fn(tweet_id="1234567890")

        assert result["success"] is True
        assert result["liked_tweet_id"] == "1234567890"


class TestTwitterRetweet:
    """Tests for twitter_retweet tool."""

    def test_retweet_success(self, get_tool_fn, monkeypatch):
        """Retweet returns success."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
        fn = get_tool_fn("twitter_retweet")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            result = fn(tweet_id="1234567890")

        assert result["success"] is True
        assert result["retweeted_tweet_id"] == "1234567890"


class TestTwitterFollowUser:
    """Tests for twitter_follow_user tool."""

    def test_follow_user_success(self, get_tool_fn, monkeypatch):
        """Follow user returns success."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
        fn = get_tool_fn("twitter_follow_user")

        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            # First call: get user ID
            user_response = MagicMock()
            user_response.status_code = 200
            user_response.json.return_value = {"data": {"id": "1234567890", "username": "testuser"}}
            mock_get.return_value = user_response

            # Second call: follow user
            follow_response = MagicMock()
            follow_response.status_code = 200
            mock_post.return_value = follow_response

            result = fn(username="testuser")

        assert result["success"] is True
        assert result["followed_user_id"] == "1234567890"


class TestTwitterBookmarkTweet:
    """Tests for twitter_bookmark_tweet tool."""

    def test_bookmark_tweet_success(self, get_tool_fn, monkeypatch):
        """Bookmark tweet returns success."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
        fn = get_tool_fn("twitter_bookmark_tweet")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            result = fn(tweet_id="1234567890")

        assert result["success"] is True
        assert result["bookmarked_tweet_id"] == "1234567890"


class TestTwitterGetFollowers:
    """Tests for twitter_get_followers tool."""

    def test_get_followers_success(self, get_tool_fn, monkeypatch):
        """Get followers returns follower list."""
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
        fn = get_tool_fn("twitter_get_followers")

        # Create two different mock responses for the two API calls
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"data": {"id": "12345", "username": "testuser"}}

        followers_response = MagicMock()
        followers_response.status_code = 200
        followers_response.json.return_value = {
            "data": [
                {"id": "1", "username": "follower1", "name": "Follower One"},
                {"id": "2", "username": "follower2", "name": "Follower Two"},
            ]
        }

        with patch("httpx.get") as mock_get:
            mock_get.side_effect = [user_response, followers_response]

            result = fn(username="testuser", max_results=10)

        assert result["success"] is True
        assert result["count"] == 2
        assert result["followers"][0]["username"] == "follower1"
