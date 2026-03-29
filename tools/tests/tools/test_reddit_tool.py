"""Tests for reddit_tool - Community content monitoring and search."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.reddit_tool.reddit_tool import register_tools

ENV = {
    "REDDIT_CLIENT_ID": "test-client-id",
    "REDDIT_CLIENT_SECRET": "test-client-secret",
}


def _mock_token_resp():
    """Create a mock token response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"access_token": "test-token"}
    return resp


def _mock_listing(children):
    """Create a mock Reddit Listing response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": {"children": children}}
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestRedditSearch:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["reddit_search"](query="python")
        assert "error" in result

    def test_missing_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["reddit_search"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        post = {
            "kind": "t3",
            "data": {
                "id": "abc123",
                "title": "Learn Python",
                "author": "testuser",
                "subreddit": "python",
                "score": 100,
                "num_comments": 25,
                "url": "https://reddit.com/r/python/abc123",
                "permalink": "/r/python/comments/abc123/learn_python/",
                "selftext": "Great resources",
                "created_utc": 1700000000,
                "is_self": True,
            },
        }
        token_resp = _mock_token_resp()
        listing_resp = _mock_listing([post])

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.reddit_tool.reddit_tool.httpx.post", return_value=token_resp),
            patch("aden_tools.tools.reddit_tool.reddit_tool.httpx.get", return_value=listing_resp),
        ):
            result = tool_fns["reddit_search"](query="python")

        assert result["count"] == 1
        assert result["posts"][0]["title"] == "Learn Python"


class TestRedditGetPosts:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["reddit_get_posts"](subreddit="python")
        assert "error" in result

    def test_missing_subreddit(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["reddit_get_posts"](subreddit="")
        assert "error" in result

    def test_successful_get_posts(self, tool_fns):
        post = {
            "kind": "t3",
            "data": {
                "id": "xyz789",
                "title": "Hot Post",
                "author": "poster",
                "subreddit": "python",
                "score": 500,
                "num_comments": 42,
                "url": "https://reddit.com/r/python/xyz789",
                "permalink": "/r/python/comments/xyz789/hot_post/",
                "selftext": "",
                "created_utc": 1700000000,
                "is_self": False,
            },
        }
        token_resp = _mock_token_resp()
        listing_resp = _mock_listing([post])

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.reddit_tool.reddit_tool.httpx.post", return_value=token_resp),
            patch("aden_tools.tools.reddit_tool.reddit_tool.httpx.get", return_value=listing_resp),
        ):
            result = tool_fns["reddit_get_posts"](subreddit="python")

        assert result["count"] == 1
        assert result["posts"][0]["id"] == "xyz789"


class TestRedditGetComments:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["reddit_get_comments"](post_id="abc123")
        assert "error" in result

    def test_missing_post_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["reddit_get_comments"](post_id="")
        assert "error" in result

    def test_successful_get_comments(self, tool_fns):
        post_listing = {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "abc123",
                            "title": "Test Post",
                            "author": "op",
                            "score": 50,
                            "selftext": "Post body",
                        },
                    }
                ]
            }
        }
        comment_listing = {
            "data": {
                "children": [
                    {
                        "kind": "t1",
                        "data": {
                            "id": "c1",
                            "author": "commenter",
                            "body": "Nice post!",
                            "score": 10,
                            "created_utc": 1700000000,
                        },
                    }
                ]
            }
        }
        token_resp = _mock_token_resp()
        comments_resp = MagicMock()
        comments_resp.status_code = 200
        comments_resp.json.return_value = [post_listing, comment_listing]

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.reddit_tool.reddit_tool.httpx.post", return_value=token_resp),
            patch("aden_tools.tools.reddit_tool.reddit_tool.httpx.get", return_value=comments_resp),
        ):
            result = tool_fns["reddit_get_comments"](post_id="abc123")

        assert result["comment_count"] == 1
        assert result["comments"][0]["body"] == "Nice post!"
        assert result["post"]["title"] == "Test Post"


class TestRedditGetUser:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["reddit_get_user"](username="testuser")
        assert "error" in result

    def test_missing_username(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["reddit_get_user"](username="")
        assert "error" in result

    def test_successful_get_user(self, tool_fns):
        token_resp = _mock_token_resp()
        user_resp = MagicMock()
        user_resp.status_code = 200
        user_resp.json.return_value = {
            "data": {
                "name": "testuser",
                "link_karma": 1000,
                "comment_karma": 5000,
                "total_karma": 6000,
                "created_utc": 1500000000,
                "is_gold": False,
            }
        }

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.reddit_tool.reddit_tool.httpx.post", return_value=token_resp),
            patch("aden_tools.tools.reddit_tool.reddit_tool.httpx.get", return_value=user_resp),
        ):
            result = tool_fns["reddit_get_user"](username="testuser")

        assert result["name"] == "testuser"
        assert result["total_karma"] == 6000
