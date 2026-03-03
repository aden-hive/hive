"""
Tests for Reddit tool.

Covers:
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 18 MCP tool functions
- Error handling (API errors, validation)
- PRAW client initialization
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter
from aden_tools.tools.reddit_tool.reddit_tool import register_tools


@pytest.fixture
def mock_reddit_instance():
    """Create a mock PRAW Reddit instance."""
    with patch("aden_tools.tools.reddit_tool.reddit_tool.praw") as mock_praw:
        mock_reddit = MagicMock()
        mock_praw.Reddit.return_value = mock_reddit
        yield mock_reddit


@pytest.fixture
def mcp():
    """Create FastMCP instance with Reddit tools."""
    server = FastMCP("test")
    # Mock credentials
    creds = CredentialStoreAdapter.for_testing(
        {
            "reddit": {
                "client_id": "test_client_id",
                "client_secret": "test_client_secret",
                "refresh_token": "test_refresh_token",
                "user_agent": "TestBot/1.0",
            }
        }
    )
    register_tools(server, credentials=creds)
    return server


class TestRedditCredentials:
    """Test credential handling."""

    def test_credentials_from_adapter(self, mcp, mock_reddit_instance):
        """Test credentials are retrieved from CredentialStoreAdapter."""
        tool_fn = mcp._tool_manager._tools["reddit_search_posts"].fn
        tool_fn(query="test", limit=5)
        # Should not raise an error if credentials are properly passed

    @patch.dict(
        "os.environ",
        {
            "REDDIT_CREDENTIALS": (
                '{"client_id":"env_id","client_secret":"env_secret",'
                '"refresh_token":"env_token","user_agent":"EnvBot/1.0"}'
            )
        },
    )
    def test_credentials_from_env(self, mock_reddit_instance):
        """Test credentials fallback to environment variable."""
        server = FastMCP("test")
        register_tools(server, credentials=None)
        tool_fn = server._tool_manager._tools["reddit_search_posts"].fn
        tool_fn(query="test", limit=5)
        # Should not raise an error

    def test_missing_credentials(self):
        """Test error when credentials are missing."""
        server = FastMCP("test")
        register_tools(server, credentials=None)
        tool_fn = server._tool_manager._tools["reddit_search_posts"].fn

        with patch.dict("os.environ", {}, clear=True):
            result = tool_fn(query="test")
            assert "error" in result
            assert "REDDIT_CREDENTIALS not configured" in result["error"]

    def test_invalid_json_credentials(self):
        """Test error when env credentials are invalid JSON."""
        server = FastMCP("test")
        register_tools(server, credentials=None)
        tool_fn = server._tool_manager._tools["reddit_search_posts"].fn

        with patch.dict("os.environ", {"REDDIT_CREDENTIALS": "not valid json"}):
            result = tool_fn(query="test")
            assert "error" in result
            assert "Invalid REDDIT_CREDENTIALS format" in result["error"]

    def test_missing_credential_fields(self):
        """Test error when required credential fields are missing."""
        server = FastMCP("test")
        creds = CredentialStoreAdapter.for_testing(
            {
                "reddit": {"client_id": "test_id"}  # Missing other required fields
            }
        )
        register_tools(server, credentials=creds)
        tool_fn = server._tool_manager._tools["reddit_search_posts"].fn

        result = tool_fn(query="test")
        assert "error" in result
        assert "Missing required credential fields" in result["error"]


class TestRedditSearchMonitoring:
    """Test search and monitoring functions."""

    def test_reddit_search_posts(self, mcp, mock_reddit_instance):
        """Test searching for posts."""
        # Mock submission objects
        mock_sub = MagicMock()
        mock_post = MagicMock()
        mock_post.id = "abc123"
        mock_post.title = "Test Post"
        mock_post.author = MagicMock()
        mock_post.author.__str__ = MagicMock(return_value="testuser")
        mock_post.subreddit.__str__ = MagicMock(return_value="test")
        mock_post.score = 100
        mock_post.upvote_ratio = 0.95
        mock_post.num_comments = 50
        mock_post.created_utc = 1234567890
        mock_post.url = "https://reddit.com/test"
        mock_post.permalink = "/r/test/comments/abc123/test/"
        mock_post.selftext = "Test content"
        mock_post.is_self = True
        mock_post.link_flair_text = "Discussion"

        mock_sub.search.return_value = [mock_post]
        mock_reddit_instance.subreddit.return_value = mock_sub

        tool_fn = mcp._tool_manager._tools["reddit_search_posts"].fn
        result = tool_fn(query="test query", subreddit="test", limit=10)

        assert result["query"] == "test query"
        assert result["subreddit"] == "test"
        assert result["count"] == 1
        assert len(result["posts"]) == 1
        assert result["posts"][0]["title"] == "Test Post"

    def test_reddit_search_posts_validation(self, mcp):
        """Test input validation for search posts."""
        tool_fn = mcp._tool_manager._tools["reddit_search_posts"].fn

        # Empty query
        result = tool_fn(query="")
        assert "error" in result

        # Query too long
        result = tool_fn(query="x" * 513)
        assert "error" in result

    def test_reddit_get_subreddit_new(self, mcp, mock_reddit_instance):
        """Test getting new subreddit posts."""
        mock_sub = MagicMock()
        mock_post = MagicMock()
        mock_post.id = "xyz789"
        mock_post.title = "New Post"
        mock_post.author = MagicMock()
        mock_post.author.__str__ = MagicMock(return_value="user1")
        mock_post.subreddit.__str__ = MagicMock(return_value="python")
        mock_post.score = 200
        mock_post.upvote_ratio = 0.98
        mock_post.num_comments = 100
        mock_post.created_utc = 1234567890
        mock_post.url = "https://reddit.com/test"
        mock_post.permalink = "/r/python/comments/xyz789/new/"
        mock_post.selftext = ""
        mock_post.is_self = False
        mock_post.link_flair_text = None

        mock_sub.new.return_value = [mock_post]
        mock_reddit_instance.subreddit.return_value = mock_sub

        tool_fn = mcp._tool_manager._tools["reddit_get_subreddit_new"].fn
        result = tool_fn(subreddit="python", limit=25)

        assert result["subreddit"] == "python"
        assert result["feed_type"] == "new"
        assert result["count"] == 1
        assert result["posts"][0]["title"] == "New Post"

    def test_reddit_get_subreddit_hot(self, mcp, mock_reddit_instance):
        """Test getting hot subreddit posts."""
        mock_sub = MagicMock()
        mock_post = MagicMock()
        mock_post.id = "abc456"
        mock_post.title = "Hot Post"
        mock_post.author = MagicMock()
        mock_post.author.__str__ = MagicMock(return_value="user2")
        mock_post.subreddit.__str__ = MagicMock(return_value="python")
        mock_post.score = 500
        mock_post.upvote_ratio = 0.99
        mock_post.num_comments = 200
        mock_post.created_utc = 1234567890
        mock_post.url = "https://reddit.com/test"
        mock_post.permalink = "/r/python/comments/abc456/hot/"
        mock_post.selftext = ""
        mock_post.is_self = False
        mock_post.link_flair_text = None

        mock_sub.hot.return_value = [mock_post]
        mock_reddit_instance.subreddit.return_value = mock_sub

        tool_fn = mcp._tool_manager._tools["reddit_get_subreddit_hot"].fn
        result = tool_fn(subreddit="python", limit=25)

        assert result["subreddit"] == "python"
        assert result["feed_type"] == "hot"
        assert result["count"] == 1
        assert result["posts"][0]["title"] == "Hot Post"

    def test_reddit_get_post(self, mcp, mock_reddit_instance):
        """Test getting a specific post."""
        mock_submission = MagicMock()
        mock_submission.id = "test123"
        mock_submission.title = "Specific Post"
        mock_submission.author = MagicMock()
        mock_submission.author.__str__ = MagicMock(return_value="author1")
        mock_submission.subreddit.__str__ = MagicMock(return_value="test")
        mock_submission.score = 50
        mock_submission.upvote_ratio = 0.9
        mock_submission.num_comments = 10
        mock_submission.created_utc = 1234567890
        mock_submission.url = "https://reddit.com/test"
        mock_submission.permalink = "/r/test/comments/test123/"
        mock_submission.selftext = "Post body"
        mock_submission.is_self = True
        mock_submission.link_flair_text = None

        mock_reddit_instance.submission.return_value = mock_submission

        tool_fn = mcp._tool_manager._tools["reddit_get_post"].fn
        result = tool_fn(post_id="test123")

        assert result["success"] is True
        assert result["post"]["id"] == "test123"
        assert result["post"]["title"] == "Specific Post"

    def test_reddit_get_comments(self, mcp, mock_reddit_instance):
        """Test getting post comments."""
        mock_comment = MagicMock()
        mock_comment.id = "comment1"
        mock_comment.author = MagicMock()
        mock_comment.author.__str__ = MagicMock(return_value="commenter1")
        mock_comment.body = "Test comment"
        mock_comment.score = 10
        mock_comment.created_utc = 1234567890
        mock_comment.permalink = "/r/test/comments/post1/title/comment1/"
        mock_comment.parent_id = "t3_post1"
        mock_comment.submission = MagicMock()
        mock_comment.submission.id = "post1"

        mock_submission = MagicMock()
        mock_submission.comments.list.return_value = [mock_comment]
        mock_submission.comments.replace_more = MagicMock()
        mock_reddit_instance.submission.return_value = mock_submission

        tool_fn = mcp._tool_manager._tools["reddit_get_comments"].fn
        result = tool_fn(post_id="post1", sort="best", limit=50)

        assert result["post_id"] == "post1"
        assert result["count"] == 1
        assert result["comments"][0]["body"] == "Test comment"

class TestRedditContentCreation:
    """Test content creation functions."""

    def test_reddit_submit_post_text(self, mcp, mock_reddit_instance):
        """Test submitting a text post."""
        mock_submission = MagicMock()
        mock_submission.id = "new_post1"
        mock_submission.permalink = "/r/test/comments/new_post1/"
        mock_submission.title = "New Post"
        mock_submission.author = MagicMock()
        mock_submission.author.__str__ = MagicMock(return_value="bot")
        mock_submission.subreddit.__str__ = MagicMock(return_value="test")
        mock_submission.score = 1
        mock_submission.upvote_ratio = 1.0
        mock_submission.num_comments = 0
        mock_submission.created_utc = 1234567890
        mock_submission.url = "https://reddit.com/r/test/comments/new_post1/"
        mock_submission.selftext = "Post content"
        mock_submission.is_self = True
        mock_submission.link_flair_text = None

        mock_sub = MagicMock()
        mock_sub.submit.return_value = mock_submission
        mock_reddit_instance.subreddit.return_value = mock_sub

        tool_fn = mcp._tool_manager._tools["reddit_submit_post"].fn
        result = tool_fn(subreddit="test", title="New Post", content="Post content")

        assert result["success"] is True
        assert result["post_id"] == "new_post1"
        assert "permalink" in result

    def test_reddit_reply_to_post(self, mcp, mock_reddit_instance):
        """Test replying to a post."""
        mock_comment = MagicMock()
        mock_comment.id = "reply1"
        mock_comment.permalink = "/r/test/comments/post1/title/reply1/"

        mock_submission = MagicMock()
        mock_submission.reply.return_value = mock_comment
        mock_reddit_instance.submission.return_value = mock_submission

        tool_fn = mcp._tool_manager._tools["reddit_reply_to_post"].fn
        result = tool_fn(post_id="post1", text="This is a reply")

        assert result["success"] is True
        assert result["comment_id"] == "reply1"

    def test_reddit_reply_to_comment(self, mcp, mock_reddit_instance):
        """Test replying to a comment."""
        mock_reply = MagicMock()
        mock_reply.id = "reply2"
        mock_reply.permalink = "/r/test/comments/post1/title/comment1/reply2/"

        mock_comment = MagicMock()
        mock_comment.reply.return_value = mock_reply
        mock_reddit_instance.comment.return_value = mock_comment

        tool_fn = mcp._tool_manager._tools["reddit_reply_to_comment"].fn
        result = tool_fn(comment_id="comment1", text="Reply to comment")

        assert result["success"] is True
        assert result["comment_id"] == "reply2"

    def test_reddit_edit_comment(self, mcp, mock_reddit_instance):
        """Test editing a comment."""
        mock_comment = MagicMock()
        mock_comment.edit.return_value = None
        mock_reddit_instance.comment.return_value = mock_comment

        tool_fn = mcp._tool_manager._tools["reddit_edit_comment"].fn
        result = tool_fn(comment_id="comment1", new_text="Edited text")

        assert result["success"] is True
        assert "edited successfully" in result["message"]

    def test_reddit_delete_comment(self, mcp, mock_reddit_instance):
        """Test deleting a comment."""
        mock_comment = MagicMock()
        mock_comment.delete.return_value = None
        mock_reddit_instance.comment.return_value = mock_comment

        tool_fn = mcp._tool_manager._tools["reddit_delete_comment"].fn
        result = tool_fn(comment_id="comment1")

        assert result["success"] is True
        assert "deleted successfully" in result["message"]


class TestRedditUserEngagement:
    """Test user engagement functions."""

    def test_reddit_get_user_profile(self, mcp, mock_reddit_instance):
        """Test getting user profile."""
        mock_redditor = MagicMock()
        mock_redditor.name = "testuser"
        mock_redditor.id = "user123"
        mock_redditor.created_utc = 1234567890
        mock_redditor.link_karma = 1000
        mock_redditor.comment_karma = 5000
        mock_redditor.is_gold = False
        mock_redditor.is_mod = False
        mock_redditor.has_verified_email = True

        mock_reddit_instance.redditor.return_value = mock_redditor

        tool_fn = mcp._tool_manager._tools["reddit_get_user_profile"].fn
        result = tool_fn(username="testuser")

        assert result["success"] is True
        assert result["user"]["name"] == "testuser"
        assert result["user"]["link_karma"] == 1000

    def test_reddit_upvote(self, mcp, mock_reddit_instance):
        """Test upvoting content."""
        mock_submission = MagicMock()
        mock_submission.upvote.return_value = None
        mock_reddit_instance.submission.return_value = mock_submission

        tool_fn = mcp._tool_manager._tools["reddit_upvote"].fn
        result = tool_fn(item_id="post1")

        assert result["success"] is True
        assert "Upvoted successfully" in result["message"]

    def test_reddit_downvote(self, mcp, mock_reddit_instance):
        """Test downvoting content."""
        mock_submission = MagicMock()
        mock_submission.downvote.return_value = None
        mock_reddit_instance.submission.return_value = mock_submission

        tool_fn = mcp._tool_manager._tools["reddit_downvote"].fn
        result = tool_fn(item_id="post1")

        assert result["success"] is True
        assert "Downvoted successfully" in result["message"]

    def test_reddit_save_post(self, mcp, mock_reddit_instance):
        """Test saving a post."""
        mock_submission = MagicMock()
        mock_submission.save.return_value = None
        mock_reddit_instance.submission.return_value = mock_submission

        tool_fn = mcp._tool_manager._tools["reddit_save_post"].fn
        result = tool_fn(post_id="post1")

        assert result["success"] is True
        assert "saved successfully" in result["message"]


class TestRedditModeration:
    """Test moderation functions."""

    def test_reddit_remove_post(self, mcp, mock_reddit_instance):
        """Test removing a post."""
        mock_submission = MagicMock()
        mock_submission.mod.remove.return_value = None
        mock_reddit_instance.submission.return_value = mock_submission

        tool_fn = mcp._tool_manager._tools["reddit_remove_post"].fn
        result = tool_fn(post_id="post1", spam=False)

        assert result["success"] is True
        assert "removed successfully" in result["message"]

    def test_reddit_approve_post(self, mcp, mock_reddit_instance):
        """Test approving a post."""
        mock_submission = MagicMock()
        mock_submission.mod.approve.return_value = None
        mock_reddit_instance.submission.return_value = mock_submission

        tool_fn = mcp._tool_manager._tools["reddit_approve_post"].fn
        result = tool_fn(post_id="post1")

        assert result["success"] is True
        assert "approved successfully" in result["message"]

    def test_reddit_ban_user(self, mcp, mock_reddit_instance):
        """Test banning a user."""
        mock_sub = MagicMock()
        mock_sub.banned.add.return_value = None
        mock_reddit_instance.subreddit.return_value = mock_sub

        tool_fn = mcp._tool_manager._tools["reddit_ban_user"].fn
        result = tool_fn(subreddit="test", username="spammer", duration=7, reason="Spam")

        assert result["success"] is True
        assert "banned" in result["message"]


class TestRedditErrorHandling:
    """Test error handling."""

    def test_prawcore_exception(self, mcp, mock_reddit_instance):
        """Test handling of PRAW exceptions."""
        from prawcore.exceptions import PrawcoreException

        mock_reddit_instance.submission.side_effect = PrawcoreException("API Error")

        tool_fn = mcp._tool_manager._tools["reddit_get_post"].fn
        result = tool_fn(post_id="test123")

        assert "error" in result
        assert "Reddit API error" in result["error"]

    def test_validation_errors(self, mcp):
        """Test input validation."""
        # Test empty subreddit
        tool_fn = mcp._tool_manager._tools["reddit_get_subreddit_hot"].fn
        result = tool_fn(subreddit="")
        assert "error" in result

        # Test invalid post ID
        tool_fn = mcp._tool_manager._tools["reddit_get_post"].fn
        result = tool_fn(post_id="")
        assert "error" in result

        # Test invalid title length
        tool_fn = mcp._tool_manager._tools["reddit_submit_post"].fn
        result = tool_fn(subreddit="test", title="x" * 301, content="test")
        assert "error" in result
