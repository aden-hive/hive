"""Tests for twitter_tool - Tweet search and user lookup."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.twitter_tool.twitter_tool import register_tools

ENV = {"X_BEARER_TOKEN": "test-bearer-token"}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestTwitterSearchTweets:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["twitter_search_tweets"](query="python")
        assert "error" in result

    def test_missing_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["twitter_search_tweets"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        data = {
            "data": [
                {
                    "id": "123",
                    "text": "Hello world",
                    "author_id": "456",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "lang": "en",
                    "public_metrics": {
                        "retweet_count": 5,
                        "reply_count": 2,
                        "like_count": 10,
                        "impression_count": 100,
                    },
                }
            ],
            "includes": {"users": [{"id": "456", "name": "Test User", "username": "testuser"}]},
            "meta": {"result_count": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.twitter_tool.twitter_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["twitter_search_tweets"](query="hello")

        assert result["count"] == 1
        assert result["tweets"][0]["text"] == "Hello world"
        assert result["tweets"][0]["author_username"] == "testuser"
        assert result["tweets"][0]["like_count"] == 10


class TestTwitterGetUser:
    def test_missing_username(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["twitter_get_user"](username="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "data": {
                "id": "456",
                "name": "Test User",
                "username": "testuser",
                "description": "A test account",
                "created_at": "2020-01-01T00:00:00.000Z",
                "profile_image_url": "https://pbs.twimg.com/test.jpg",
                "verified": False,
                "public_metrics": {
                    "followers_count": 1000,
                    "following_count": 500,
                    "tweet_count": 5000,
                },
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.twitter_tool.twitter_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["twitter_get_user"](username="testuser")

        assert result["username"] == "testuser"
        assert result["followers_count"] == 1000


class TestTwitterGetUserTweets:
    def test_missing_user_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["twitter_get_user_tweets"](user_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "data": [
                {
                    "id": "789",
                    "text": "My latest tweet",
                    "author_id": "456",
                    "created_at": "2024-01-15T12:00:00.000Z",
                    "public_metrics": {
                        "retweet_count": 1,
                        "reply_count": 0,
                        "like_count": 5,
                        "impression_count": 50,
                    },
                }
            ],
            "meta": {"result_count": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.twitter_tool.twitter_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["twitter_get_user_tweets"](user_id="456")

        assert result["count"] == 1
        assert result["tweets"][0]["text"] == "My latest tweet"


class TestTwitterGetTweet:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["twitter_get_tweet"](tweet_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "data": {
                "id": "123",
                "text": "Specific tweet",
                "author_id": "456",
                "created_at": "2024-01-01T12:00:00.000Z",
                "lang": "en",
                "public_metrics": {
                    "retweet_count": 0,
                    "reply_count": 0,
                    "like_count": 3,
                    "impression_count": 20,
                },
            },
            "includes": {"users": [{"name": "Author", "username": "author"}]},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.twitter_tool.twitter_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["twitter_get_tweet"](tweet_id="123")

        assert result["text"] == "Specific tweet"
        assert result["author_username"] == "author"
