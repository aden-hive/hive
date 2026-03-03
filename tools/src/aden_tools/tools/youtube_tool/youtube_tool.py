"""
YouTube Data API Tool - Search and retrieve video/channel information.

Supports:
- API key authentication (YOUTUBE_API_KEY)

Use Cases:
- Search for videos by query
- Get detailed video information (title, description, views, likes)
- Get channel information and statistics
- List videos from a specific channel
- Get playlist items
- Search for channels

API Reference: https://developers.google.com/youtube/v3/docs
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

logger = logging.getLogger(__name__)

# YouTube Data API base URL
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class _YouTubeClient:
    """Internal client for YouTube Data API v3 calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = httpx.Client(timeout=30.0)

    def _request(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Make a request to the YouTube Data API.

        Args:
            endpoint: API endpoint (e.g., "search", "videos")
            params: Query parameters

        Returns:
            JSON response as dict
        """
        # Add API key to params
        params["key"] = self._api_key

        url = f"{YOUTUBE_API_BASE}/{endpoint}"

        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_data = {}
            try:
                error_data = e.response.json()
            except Exception:
                pass
            return {
                "error": f"YouTube API error: {e.response.status_code}",
                "details": error_data,
            }
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}

    def search_videos(
        self,
        query: str,
        max_results: int = 10,
        order: str = "relevance",
    ) -> dict[str, Any]:
        """Search for videos.

        Args:
            query: Search query
            max_results: Number of results (1-50)
            order: Sort order (date, rating, relevance, title, viewCount)

        Returns:
            Dict with video search results
        """
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(max(max_results, 1), 50),
            "order": order,
        }
        return self._request("search", params)

    def get_video_details(self, video_id: str) -> dict[str, Any]:
        """Get detailed information about a video.

        Args:
            video_id: YouTube video ID

        Returns:
            Dict with video details (snippet, statistics, contentDetails)
        """
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
        }
        return self._request("videos", params)

    def get_channel_info(self, channel_id: str) -> dict[str, Any]:
        """Get channel information and statistics.

        Args:
            channel_id: YouTube channel ID

        Returns:
            Dict with channel details
        """
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": channel_id,
        }
        return self._request("channels", params)

    def list_channel_videos(
        self,
        channel_id: str,
        max_results: int = 10,
        order: str = "date",
    ) -> dict[str, Any]:
        """List videos from a channel.

        Args:
            channel_id: YouTube channel ID
            max_results: Number of results (1-50)
            order: Sort order (date, rating, relevance, title, viewCount)

        Returns:
            Dict with video list
        """
        params = {
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "maxResults": min(max(max_results, 1), 50),
            "order": order,
        }
        return self._request("search", params)

    def get_playlist_items(
        self,
        playlist_id: str,
        max_results: int = 10,
    ) -> dict[str, Any]:
        """Get videos from a playlist.

        Args:
            playlist_id: YouTube playlist ID
            max_results: Number of results (1-50)

        Returns:
            Dict with playlist items
        """
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": min(max(max_results, 1), 50),
        }
        return self._request("playlistItems", params)

    def search_channels(
        self,
        query: str,
        max_results: int = 10,
    ) -> dict[str, Any]:
        """Search for channels.

        Args:
            query: Search query
            max_results: Number of results (1-50)

        Returns:
            Dict with channel search results
        """
        params = {
            "part": "snippet",
            "q": query,
            "type": "channel",
            "maxResults": min(max(max_results, 1), 50),
        }
        return self._request("search", params)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register YouTube Data API tools with the MCP server."""

    def _get_api_key() -> str | dict[str, str]:
        """Get YouTube API key from credential manager or environment."""
        if credentials is not None:
            api_key = credentials.get("youtube")
            if api_key and isinstance(api_key, str):
                return api_key

        import os

        api_key = os.getenv("YOUTUBE_API_KEY")
        if api_key:
            return api_key

        return {
            "error": "YouTube API key not configured",
            "help": (
                "Set YOUTUBE_API_KEY environment variable. "
                "Get your API key at https://console.cloud.google.com/apis/credentials"
            ),
        }

    def _get_client() -> _YouTubeClient | dict[str, str]:
        """Get a YouTube client, or return an error dict if no API key."""
        key = _get_api_key()
        if isinstance(key, dict):
            return key
        return _YouTubeClient(key)

    @mcp.tool()
    def youtube_search_videos(
        query: str,
        max_results: int = 10,
        order: str = "relevance",
    ) -> dict:
        """
        Search for YouTube videos.

        Args:
            query: Search query string
            max_results: Number of results to return (1-50, default: 10)
            order: Sort order - one of: date, rating, relevance, title, viewCount
                (default: relevance)

        Returns:
            Dict with search results including video ID, title, description,
                channel info, and thumbnails

        Example:
            youtube_search_videos(query="Python tutorial", max_results=5, order="viewCount")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not query or not query.strip():
            return {"error": "Query parameter is required and cannot be empty"}

        try:
            return client.search_videos(query, max_results, order)
        finally:
            client.close()

    @mcp.tool()
    def youtube_get_video_details(video_id: str) -> dict:
        """
        Get detailed information about a specific YouTube video.

        Args:
            video_id: YouTube video ID (e.g., "dQw4w9WgXcQ")

        Returns:
            Dict with video details including title, description, view count,
                like count, duration, and more

        Example:
            youtube_get_video_details(video_id="dQw4w9WgXcQ")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not video_id or not video_id.strip():
            return {"error": "video_id parameter is required and cannot be empty"}

        try:
            return client.get_video_details(video_id)
        finally:
            client.close()

    @mcp.tool()
    def youtube_get_channel_info(channel_id: str) -> dict:
        """
        Get information and statistics about a YouTube channel.

        Args:
            channel_id: YouTube channel ID (e.g., "UCuAXFkgsw1L7xaCfnd5JJOw")

        Returns:
            Dict with channel details including title, description,
                subscriber count, video count, and view count

        Example:
            youtube_get_channel_info(channel_id="UCuAXFkgsw1L7xaCfnd5JJOw")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not channel_id or not channel_id.strip():
            return {"error": "channel_id parameter is required and cannot be empty"}

        try:
            return client.get_channel_info(channel_id)
        finally:
            client.close()

    @mcp.tool()
    def youtube_list_channel_videos(
        channel_id: str,
        max_results: int = 10,
        order: str = "date",
    ) -> dict:
        """
        List videos from a specific YouTube channel.

        Args:
            channel_id: YouTube channel ID
            max_results: Number of results to return (1-50, default: 10)
            order: Sort order - one of: date, rating, relevance, title, viewCount (default: date)

        Returns:
            Dict with list of videos from the channel

        Example:
            youtube_list_channel_videos(
                channel_id="UCuAXFkgsw1L7xaCfnd5JJOw",
                max_results=20,
                order="viewCount"
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not channel_id or not channel_id.strip():
            return {"error": "channel_id parameter is required and cannot be empty"}

        try:
            return client.list_channel_videos(channel_id, max_results, order)
        finally:
            client.close()

    @mcp.tool()
    def youtube_get_playlist_items(
        playlist_id: str,
        max_results: int = 10,
    ) -> dict:
        """
        Get videos from a YouTube playlist.

        Args:
            playlist_id: YouTube playlist ID
            max_results: Number of results to return (1-50, default: 10)

        Returns:
            Dict with playlist items including video details

        Example:
            youtube_get_playlist_items(
                playlist_id="PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
                max_results=25
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not playlist_id or not playlist_id.strip():
            return {"error": "playlist_id parameter is required and cannot be empty"}

        try:
            return client.get_playlist_items(playlist_id, max_results)
        finally:
            client.close()

    @mcp.tool()
    def youtube_search_channels(
        query: str,
        max_results: int = 10,
    ) -> dict:
        """
        Search for YouTube channels.

        Args:
            query: Search query string
            max_results: Number of results to return (1-50, default: 10)

        Returns:
            Dict with channel search results including channel ID, title,
                description, and thumbnails

        Example:
            youtube_search_channels(query="Python programming", max_results=5)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not query or not query.strip():
            return {"error": "Query parameter is required and cannot be empty"}

        try:
            return client.search_channels(query, max_results)
        finally:
            client.close()
