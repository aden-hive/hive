"""Tests for youtube_tool - YouTube Data API v3 integration."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.youtube_tool.youtube_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    """Register and return all YouTube tool functions."""
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestYoutubeSearchVideos:
    """Tests for youtube_search_videos."""

    def test_missing_api_key(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["youtube_search_videos"](query="python tutorial")
        assert "error" in result
        assert "YOUTUBE_API_KEY" in result["error"]

    def test_empty_query(self, tool_fns):
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}):
            result = tool_fns["youtube_search_videos"](query="")
        assert "error" in result
        assert "query" in result["error"]

    def test_successful_search(self, tool_fns):
        mock_response = {
            "pageInfo": {"totalResults": 1},
            "items": [
                {
                    "id": {"videoId": "abc123"},
                    "snippet": {
                        "title": "Python Tutorial",
                        "channelTitle": "Dev Channel",
                        "channelId": "UC123",
                        "publishedAt": "2024-01-01T00:00:00Z",
                        "description": "Learn Python",
                        "thumbnails": {"medium": {"url": "https://img.youtube.com/thumb.jpg"}},
                    },
                }
            ],
        }
        with (
            patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}),
            patch("aden_tools.tools.youtube_tool.youtube_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response
            result = tool_fns["youtube_search_videos"](query="python tutorial")

        assert result["query"] == "python tutorial"
        assert len(result["results"]) == 1
        assert result["results"][0]["videoId"] == "abc123"
        assert result["results"][0]["title"] == "Python Tutorial"

    def test_max_results_clamped(self, tool_fns):
        with (
            patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}),
            patch("aden_tools.tools.youtube_tool.youtube_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"pageInfo": {"totalResults": 0}, "items": []}
            tool_fns["youtube_search_videos"](query="test", max_results=100)
            call_params = mock_get.call_args[1]["params"]
            assert call_params["maxResults"] == 50


class TestYoutubeGetVideoDetails:
    """Tests for youtube_get_video_details."""

    def test_missing_video_ids(self, tool_fns):
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}):
            result = tool_fns["youtube_get_video_details"](video_ids="")
        assert "error" in result

    def test_successful_details(self, tool_fns):
        mock_response = {
            "items": [
                {
                    "id": "abc123",
                    "snippet": {
                        "title": "Test Video",
                        "description": "A test",
                        "channelTitle": "Test Channel",
                        "channelId": "UC123",
                        "publishedAt": "2024-01-01T00:00:00Z",
                        "tags": ["python", "tutorial"],
                        "categoryId": "27",
                        "thumbnails": {"high": {"url": "https://img.youtube.com/high.jpg"}},
                    },
                    "statistics": {
                        "viewCount": "1000",
                        "likeCount": "50",
                        "commentCount": "10",
                    },
                    "contentDetails": {"duration": "PT1H2M3S"},
                }
            ],
        }
        with (
            patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}),
            patch("aden_tools.tools.youtube_tool.youtube_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response
            result = tool_fns["youtube_get_video_details"](video_ids="abc123")

        assert len(result["videos"]) == 1
        video = result["videos"][0]
        assert video["title"] == "Test Video"
        assert video["viewCount"] == 1000
        assert video["duration"] == "1h2m3s"


class TestYoutubeGetChannel:
    """Tests for youtube_get_channel."""

    def test_no_identifier(self, tool_fns):
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}):
            result = tool_fns["youtube_get_channel"]()
        assert "error" in result
        assert "Provide one of" in result["error"]

    def test_channel_not_found(self, tool_fns):
        with (
            patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}),
            patch("aden_tools.tools.youtube_tool.youtube_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"items": []}
            result = tool_fns["youtube_get_channel"](channel_id="UC_nonexistent")
        assert "error" in result
        assert "not found" in result["error"]

    def test_successful_channel(self, tool_fns):
        mock_response = {
            "items": [
                {
                    "id": "UC123",
                    "snippet": {
                        "title": "Dev Channel",
                        "description": "A dev channel",
                        "customUrl": "@devchannel",
                        "publishedAt": "2020-01-01T00:00:00Z",
                        "thumbnails": {"high": {"url": "https://img.youtube.com/ch.jpg"}},
                    },
                    "statistics": {
                        "subscriberCount": "50000",
                        "videoCount": "200",
                        "viewCount": "1000000",
                    },
                    "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}},
                }
            ],
        }
        with (
            patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}),
            patch("aden_tools.tools.youtube_tool.youtube_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response
            result = tool_fns["youtube_get_channel"](handle="devchannel")

        assert result["channelId"] == "UC123"
        assert result["subscriberCount"] == 50000
        assert result["uploadsPlaylistId"] == "UU123"


class TestYoutubeGetPlaylist:
    """Tests for youtube_get_playlist."""

    def test_missing_playlist_id(self, tool_fns):
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}):
            result = tool_fns["youtube_get_playlist"](playlist_id="")
        assert "error" in result

    def test_playlist_not_found(self, tool_fns):
        with (
            patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}),
            patch("aden_tools.tools.youtube_tool.youtube_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"items": []}
            result = tool_fns["youtube_get_playlist"](playlist_id="PL_nonexistent")
        assert "error" in result


class TestYoutubeGetVideoComments:
    """Tests for youtube_get_video_comments."""

    def test_missing_video_id(self, tool_fns):
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}):
            result = tool_fns["youtube_get_video_comments"](video_id="")
        assert "error" in result

    def test_successful_comments(self, tool_fns):
        mock_response = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "authorDisplayName": "User1",
                                "textDisplay": "Great video!",
                                "likeCount": 5,
                                "publishedAt": "2024-06-01T00:00:00Z",
                            }
                        },
                        "totalReplyCount": 2,
                    }
                }
            ],
        }
        with (
            patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}),
            patch("aden_tools.tools.youtube_tool.youtube_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response
            result = tool_fns["youtube_get_video_comments"](video_id="abc123")

        assert result["video_id"] == "abc123"
        assert len(result["comments"]) == 1
        assert result["comments"][0]["author"] == "User1"
        assert result["comments"][0]["replyCount"] == 2


class TestParseDuration:
    """Tests for _parse_duration helper."""

    def test_hours_minutes_seconds(self):
        from aden_tools.tools.youtube_tool.youtube_tool import _parse_duration

        assert _parse_duration("PT1H2M3S") == "1h2m3s"

    def test_minutes_only(self):
        from aden_tools.tools.youtube_tool.youtube_tool import _parse_duration

        assert _parse_duration("PT5M") == "5m"

    def test_seconds_only(self):
        from aden_tools.tools.youtube_tool.youtube_tool import _parse_duration

        assert _parse_duration("PT30S") == "30s"

    def test_empty_string(self):
        from aden_tools.tools.youtube_tool.youtube_tool import _parse_duration

        assert _parse_duration("") == ""
