"""
Tests for YouTube Data API tool.

Covers:
- All 6 YouTube API tools
- Error handling (missing API key, empty params, HTTP errors)
- Credential retrieval (CredentialStoreAdapter vs env var)
- Input validation (empty query/IDs, max_results clamping)
- HTTP response mocking
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.youtube_tool.youtube_tool import register_tools


@pytest.fixture
def youtube_tools(mcp: FastMCP):
    """Register YouTube tools and return dict of tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {
        "search_videos": tools["youtube_search_videos"].fn,
        "get_video_details": tools["youtube_get_video_details"].fn,
        "get_channel_info": tools["youtube_get_channel_info"].fn,
        "list_channel_videos": tools["youtube_list_channel_videos"].fn,
        "get_playlist_items": tools["youtube_get_playlist_items"].fn,
        "search_channels": tools["youtube_search_channels"].fn,
    }


# ---------------------------------------------------------------------------
# Credential Tests
# ---------------------------------------------------------------------------


class TestCredentials:
    """Test credential retrieval logic."""

    def test_no_credentials_returns_error(self, youtube_tools, monkeypatch):
        """All tools should return error when no API key is configured."""
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

        result = youtube_tools["search_videos"](query="test")

        assert "error" in result
        assert "YouTube API key not configured" in result["error"]
        assert "help" in result
        assert "YOUTUBE_API_KEY" in result["help"]

    def test_env_var_credential(self, youtube_tools, monkeypatch):
        """Tools should work with YOUTUBE_API_KEY environment variable."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-api-key")

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"items": []}
            mock_response.raise_for_status.return_value = None
            mock_client.return_value.get.return_value = mock_response

            result = youtube_tools["search_videos"](query="test")

            assert "error" not in result


# ---------------------------------------------------------------------------
# Search Videos Tests
# ---------------------------------------------------------------------------


class TestSearchVideos:
    """Test youtube_search_videos tool."""

    def test_empty_query_returns_error(self, youtube_tools, monkeypatch):
        """Empty query should return error."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        result = youtube_tools["search_videos"](query="")

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_whitespace_query_returns_error(self, youtube_tools, monkeypatch):
        """Whitespace-only query should return error."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        result = youtube_tools["search_videos"](query="   ")

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_search_success(self, youtube_tools, monkeypatch):
        """Successful search returns video results."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "items": [
                    {
                        "id": {"videoId": "video123"},
                        "snippet": {
                            "title": "Test Video",
                            "description": "Test description",
                            "channelTitle": "Test Channel",
                        },
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_client.return_value.get.return_value = mock_response

            result = youtube_tools["search_videos"](
                query="Python tutorial", max_results=5, order="viewCount"
            )

            assert "items" in result
            assert len(result["items"]) == 1
            assert result["items"][0]["id"]["videoId"] == "video123"

    def test_http_error_handling(self, youtube_tools, monkeypatch):
        """HTTP errors should be caught and returned as error dict."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        with patch("httpx.Client") as mock_client:
            import httpx

            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.json.return_value = {
                "error": {"message": "API key invalid"}
            }
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "403 Forbidden", request=MagicMock(), response=mock_response
            )
            mock_client.return_value.get.return_value = mock_response

            result = youtube_tools["search_videos"](query="test")

            assert "error" in result
            assert "403" in result["error"]


# ---------------------------------------------------------------------------
# Get Video Details Tests
# ---------------------------------------------------------------------------


class TestGetVideoDetails:
    """Test youtube_get_video_details tool."""

    def test_empty_video_id_returns_error(self, youtube_tools, monkeypatch):
        """Empty video_id should return error."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        result = youtube_tools["get_video_details"](video_id="")

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_get_video_details_success(self, youtube_tools, monkeypatch):
        """Successful video details fetch returns video data."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "items": [
                    {
                        "id": "video123",
                        "snippet": {
                            "title": "Test Video",
                            "description": "Test description",
                        },
                        "statistics": {
                            "viewCount": "1000",
                            "likeCount": "100",
                        },
                        "contentDetails": {"duration": "PT5M30S"},
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_client.return_value.get.return_value = mock_response

            result = youtube_tools["get_video_details"](video_id="video123")

            assert "items" in result
            assert result["items"][0]["id"] == "video123"
            assert "statistics" in result["items"][0]
            assert result["items"][0]["statistics"]["viewCount"] == "1000"


# ---------------------------------------------------------------------------
# Get Channel Info Tests
# ---------------------------------------------------------------------------


class TestGetChannelInfo:
    """Test youtube_get_channel_info tool."""

    def test_empty_channel_id_returns_error(self, youtube_tools, monkeypatch):
        """Empty channel_id should return error."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        result = youtube_tools["get_channel_info"](channel_id="")

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_get_channel_info_success(self, youtube_tools, monkeypatch):
        """Successful channel info fetch returns channel data."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "items": [
                    {
                        "id": "channel123",
                        "snippet": {
                            "title": "Test Channel",
                            "description": "Channel description",
                        },
                        "statistics": {
                            "subscriberCount": "10000",
                            "videoCount": "50",
                            "viewCount": "100000",
                        },
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_client.return_value.get.return_value = mock_response

            result = youtube_tools["get_channel_info"](channel_id="channel123")

            assert "items" in result
            assert result["items"][0]["id"] == "channel123"
            assert result["items"][0]["statistics"]["subscriberCount"] == "10000"


# ---------------------------------------------------------------------------
# List Channel Videos Tests
# ---------------------------------------------------------------------------


class TestListChannelVideos:
    """Test youtube_list_channel_videos tool."""

    def test_empty_channel_id_returns_error(self, youtube_tools, monkeypatch):
        """Empty channel_id should return error."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        result = youtube_tools["list_channel_videos"](channel_id="")

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_list_channel_videos_success(self, youtube_tools, monkeypatch):
        """Successful channel videos list returns video data."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "items": [
                    {
                        "id": {"videoId": "video1"},
                        "snippet": {"title": "Video 1", "publishedAt": "2024-01-01"},
                    },
                    {
                        "id": {"videoId": "video2"},
                        "snippet": {"title": "Video 2", "publishedAt": "2024-01-02"},
                    },
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_client.return_value.get.return_value = mock_response

            result = youtube_tools["list_channel_videos"](
                channel_id="channel123", max_results=20, order="viewCount"
            )

            assert "items" in result
            assert len(result["items"]) == 2


# ---------------------------------------------------------------------------
# Get Playlist Items Tests
# ---------------------------------------------------------------------------


class TestGetPlaylistItems:
    """Test youtube_get_playlist_items tool."""

    def test_empty_playlist_id_returns_error(self, youtube_tools, monkeypatch):
        """Empty playlist_id should return error."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        result = youtube_tools["get_playlist_items"](playlist_id="")

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_get_playlist_items_success(self, youtube_tools, monkeypatch):
        """Successful playlist items fetch returns video data."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "items": [
                    {
                        "snippet": {
                            "title": "Playlist Video 1",
                            "resourceId": {"videoId": "plvideo1"},
                        },
                        "contentDetails": {"videoId": "plvideo1"},
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_client.return_value.get.return_value = mock_response

            result = youtube_tools["get_playlist_items"](
                playlist_id="playlist123", max_results=25
            )

            assert "items" in result
            assert len(result["items"]) == 1


# ---------------------------------------------------------------------------
# Search Channels Tests
# ---------------------------------------------------------------------------


class TestSearchChannels:
    """Test youtube_search_channels tool."""

    def test_empty_query_returns_error(self, youtube_tools, monkeypatch):
        """Empty query should return error."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        result = youtube_tools["search_channels"](query="")

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_search_channels_success(self, youtube_tools, monkeypatch):
        """Successful channel search returns channel results."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "items": [
                    {
                        "id": {"channelId": "channel123"},
                        "snippet": {
                            "title": "Test Channel",
                            "description": "Channel about Python",
                        },
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_client.return_value.get.return_value = mock_response

            result = youtube_tools["search_channels"](
                query="Python programming", max_results=5
            )

            assert "items" in result
            assert len(result["items"]) == 1
            assert result["items"][0]["id"]["channelId"] == "channel123"


# ---------------------------------------------------------------------------
# Client Lifecycle Tests
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    """Test that HTTP client is properly closed after each call."""

    def test_client_close_on_success(self, youtube_tools, monkeypatch):
        """Client should be closed even on successful calls."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"items": []}
            mock_response.raise_for_status.return_value = None
            mock_instance.get.return_value = mock_response
            mock_client.return_value = mock_instance

            youtube_tools["search_videos"](query="test")

            # Verify close was called
            mock_instance.close.assert_called_once()

    def test_client_close_on_error(self, youtube_tools, monkeypatch):
        """Client should be closed even when HTTP errors occur."""
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

        with patch("httpx.Client") as mock_client:
            import httpx

            mock_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.json.return_value = {}
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500 Internal Server Error",
                request=MagicMock(),
                response=mock_response,
            )
            mock_instance.get.return_value = mock_response
            mock_client.return_value = mock_instance

            result = youtube_tools["search_videos"](query="test")

            # Verify close was called even after error
            mock_instance.close.assert_called_once()
            assert "error" in result
