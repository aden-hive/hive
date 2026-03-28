"""
Tests for the HackerNews tool.
"""

from unittest.mock import patch, MagicMock

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.hackernews_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test")


@pytest.fixture
def top_stories_tool(mcp):
    """Register and return get_top_hn_stories tool."""
    register_tools(mcp)
    for tool in mcp._tool_manager._tools.values():
        if tool.name == "get_top_hn_stories":
            return tool.fn
    raise RuntimeError("get_top_hn_stories tool not found")


@pytest.fixture
def story_details_tool(mcp):
    """Register and return get_hn_story_details tool."""
    register_tools(mcp)
    for tool in mcp._tool_manager._tools.values():
        if tool.name == "get_hn_story_details":
            return tool.fn
    raise RuntimeError("get_hn_story_details tool not found")


class TestHackerNewsTool:
    """Tests for hackernews tools."""

    @patch("httpx.Client.get")
    def test_get_top_stories_success(self, mock_get, top_stories_tool):
        """Test fetching top stories successfully."""
        # Setup mocks
        mock_response_ids = MagicMock()
        mock_response_ids.status_code = 200
        mock_response_ids.json.return_value = [101]

        mock_response_story = MagicMock()
        mock_response_story.status_code = 200
        mock_response_story.json.return_value = {
            "id": 101, "type": "story", "title": "Test Story",
            "score": 100, "by": "user", "time": 123456789, "descendants": 5
        }

        mock_get.side_effect = [mock_response_ids, mock_response_story]

        result = top_stories_tool(limit=1)

        assert "stories" in result
        assert len(result["stories"]) == 1
        assert result["stories"][0]["id"] == 101
        assert result["stories"][0]["title"] == "Test Story"

    @patch("httpx.Client.get")
    def test_get_top_stories_timeout(self, mock_get, top_stories_tool):
        """Test handling of timeout when fetching top stories."""
        mock_get.side_effect = httpx.TimeoutException("Timeout")

        result = top_stories_tool()

        assert "error" in result
        assert "timed out" in result["error"]

    @patch("httpx.Client.get")
    def test_get_story_details_success(self, mock_get, story_details_tool):
        """Test fetching story details successfully."""
        mock_response_story = MagicMock()
        mock_response_story.status_code = 200
        mock_response_story.json.return_value = {
            "id": 101, "type": "story", "title": "Test Story",
            "score": 100, "by": "user", "time": 123456789,
            "kids": [201]
        }

        mock_response_comment = MagicMock()
        mock_response_comment.status_code = 200
        mock_response_comment.json.return_value = {
            "id": 201, "type": "comment", "text": "Test Comment",
            "by": "commenter", "time": 123456790
        }

        mock_get.side_effect = [mock_response_story, mock_response_comment]

        result = story_details_tool(story_id=101, include_comments=True)

        assert "story" in result
        assert result["story"]["id"] == 101
        assert "comments" in result
        assert len(result["comments"]) == 1
        assert result["comments"][0]["id"] == 201

    @patch("httpx.Client.get")
    def test_get_story_details_not_found(self, mock_get, story_details_tool):
        """Test handling when a story is not found or not a story type."""
        mock_response_story = MagicMock()
        mock_response_story.status_code = 200
        mock_response_story.json.return_value = {
            "id": 101, "type": "comment" # Not a story
        }
        
        mock_get.return_value = mock_response_story

        result = story_details_tool(story_id=101)

        assert "error" in result
        assert "not found or is not a story" in result["error"]
