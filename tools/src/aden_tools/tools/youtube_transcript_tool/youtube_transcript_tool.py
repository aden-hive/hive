"""
YouTube Transcript Tool - Retrieve video transcripts/captions.

Supports:
- Fetching transcripts by video ID
- Listing available transcript languages
- No API key required (uses youtube-transcript-api library)

Library: https://github.com/jdepoix/youtube-transcript-api
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


def register_tools(
    mcp: FastMCP,
) -> None:
    """Register YouTube Transcript tools with the MCP server."""

    @mcp.tool()
    def youtube_get_transcript(
        video_id: str,
        language: str = "en",
        preserve_formatting: bool = False,
    ) -> dict[str, Any]:
        """
        Get the transcript/captions for a YouTube video.

        Args:
            video_id: YouTube video ID e.g. "dQw4w9WgXcQ" (required)
            language: Language code e.g. "en", "de", "es" (default "en")
            preserve_formatting: Keep HTML formatting tags (default False)

        Returns:
            Dict with transcript snippets (text, start, duration) and metadata
        """
        if not video_id:
            return {"error": "video_id is required"}

        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            return {"error": ("youtube-transcript-api package not installed. Run: pip install youtube-transcript-api")}

        try:
            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(
                video_id,
                languages=[language],
                preserve_formatting=preserve_formatting,
            )
            snippets = transcript.to_raw_data()
            return {
                "video_id": video_id,
                "language": transcript.language,
                "language_code": transcript.language_code,
                "is_generated": transcript.is_generated,
                "snippets": snippets[:500],
                "snippet_count": len(snippets),
            }
        except Exception as e:
            error_type = type(e).__name__
            return {"error": f"{error_type}: {e!s}"}

    @mcp.tool()
    def youtube_list_transcripts(
        video_id: str,
    ) -> dict[str, Any]:
        """
        List available transcripts/caption tracks for a YouTube video.

        Args:
            video_id: YouTube video ID e.g. "dQw4w9WgXcQ" (required)

        Returns:
            Dict with available transcripts (language, language_code, is_generated)
        """
        if not video_id:
            return {"error": "video_id is required"}

        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            return {"error": ("youtube-transcript-api package not installed. Run: pip install youtube-transcript-api")}

        try:
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)
            transcripts = []
            for t in transcript_list:
                transcripts.append(
                    {
                        "language": t.language,
                        "language_code": t.language_code,
                        "is_generated": t.is_generated,
                        "is_translatable": t.is_translatable,
                    }
                )
            return {
                "video_id": video_id,
                "transcripts": transcripts,
                "count": len(transcripts),
            }
        except Exception as e:
            error_type = type(e).__name__
            return {"error": f"{error_type}: {e!s}"}
