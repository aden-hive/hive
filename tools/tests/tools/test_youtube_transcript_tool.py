"""Tests for youtube_transcript_tool - Video transcript retrieval."""

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.youtube_transcript_tool.youtube_transcript_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _make_mock_module(mock_api_class):
    """Create a mock youtube_transcript_api module."""
    mock_mod = MagicMock()
    mock_mod.YouTubeTranscriptApi = mock_api_class
    return mock_mod


class TestYoutubeGetTranscript:
    def test_missing_video_id(self, tool_fns):
        result = tool_fns["youtube_get_transcript"](video_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_transcript = MagicMock()
        mock_transcript.language = "English"
        mock_transcript.language_code = "en"
        mock_transcript.is_generated = True
        mock_transcript.to_raw_data.return_value = [
            {"text": "Hello world", "start": 0.0, "duration": 1.5},
            {"text": "How are you", "start": 1.5, "duration": 2.0},
        ]

        mock_api_instance = MagicMock()
        mock_api_instance.fetch.return_value = mock_transcript
        mock_api_class = MagicMock(return_value=mock_api_instance)

        mock_mod = _make_mock_module(mock_api_class)
        with patch.dict(sys.modules, {"youtube_transcript_api": mock_mod}):
            result = tool_fns["youtube_get_transcript"](video_id="dQw4w9WgXcQ")

        assert result["video_id"] == "dQw4w9WgXcQ"
        assert result["language"] == "English"
        assert result["snippet_count"] == 2
        assert result["snippets"][0]["text"] == "Hello world"

    def test_video_not_found(self, tool_fns):
        mock_api_instance = MagicMock()
        mock_api_instance.fetch.side_effect = Exception("VideoUnavailable")
        mock_api_class = MagicMock(return_value=mock_api_instance)

        mock_mod = _make_mock_module(mock_api_class)
        with patch.dict(sys.modules, {"youtube_transcript_api": mock_mod}):
            result = tool_fns["youtube_get_transcript"](video_id="nonexistent")

        assert "error" in result


class TestYoutubeListTranscripts:
    def test_missing_video_id(self, tool_fns):
        result = tool_fns["youtube_list_transcripts"](video_id="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_t1 = MagicMock()
        mock_t1.language = "English"
        mock_t1.language_code = "en"
        mock_t1.is_generated = True
        mock_t1.is_translatable = True

        mock_t2 = MagicMock()
        mock_t2.language = "Spanish"
        mock_t2.language_code = "es"
        mock_t2.is_generated = False
        mock_t2.is_translatable = True

        mock_list = MagicMock()
        mock_list.__iter__ = MagicMock(return_value=iter([mock_t1, mock_t2]))

        mock_api_instance = MagicMock()
        mock_api_instance.list.return_value = mock_list
        mock_api_class = MagicMock(return_value=mock_api_instance)

        mock_mod = _make_mock_module(mock_api_class)
        with patch.dict(sys.modules, {"youtube_transcript_api": mock_mod}):
            result = tool_fns["youtube_list_transcripts"](video_id="dQw4w9WgXcQ")

        assert result["count"] == 2
        assert result["transcripts"][0]["language_code"] == "en"
        assert result["transcripts"][1]["is_generated"] is False
