"""
YouTube Data API Tool - Search videos, get video/channel details, and browse playlists.

Supports:
- YouTube Data API v3 with API Key authentication

API Reference: https://developers.google.com/youtube/v3/docs
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
MAX_RESULTS_LIMIT = 50  # YouTube API max per page


def _get_api_key(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("youtube")
    return os.getenv("YOUTUBE_API_KEY")


def _request(
    endpoint: str,
    params: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    """Make a GET request to the YouTube Data API."""
    params["key"] = api_key
    url = f"{YOUTUBE_API_BASE}/{endpoint}"
    try:
        resp = httpx.get(url, params=params, timeout=30.0)
        if resp.status_code == 403:
            data = resp.json()
            reason = ""
            errors = data.get("error", {}).get("errors", [])
            if errors:
                reason = errors[0].get("reason", "")
            if reason == "quotaExceeded":
                return {
                    "error": (
                        "YouTube API quota exceeded."
                        " Try again tomorrow or"
                        " request a quota increase."
                    )
                }
            return {"error": f"Forbidden: {reason or resp.text}"}
        if resp.status_code != 200:
            return {"error": f"YouTube API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to YouTube API timed out"}
    except Exception as e:
        return {"error": f"YouTube API request failed: {e!s}"}


def _parse_duration(duration: str) -> str:
    """Convert ISO 8601 duration (PT1H2M3S) to human-readable string."""
    if not duration or not duration.startswith("PT"):
        return duration
    d = duration[2:]
    hours = minutes = seconds = 0
    for unit, setter in [("H", "hours"), ("M", "minutes"), ("S", "seconds")]:
        if unit in d:
            val, d = d.split(unit, 1)
            if setter == "hours":
                hours = int(val)
            elif setter == "minutes":
                minutes = int(val)
            elif setter == "seconds":
                seconds = int(val)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return "".join(parts)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register YouTube Data API tools with the MCP server."""

    @mcp.tool()
    def youtube_search_videos(
        query: str,
        max_results: int = 10,
        order: str = "relevance",
        published_after: str = "",
        region_code: str = "",
        video_duration: str = "",
        video_type: str = "",
    ) -> dict[str, Any]:
        """
        Search for YouTube videos by keyword.

        Args:
            query: Search query string
            max_results: Number of results to return (1-50, default 10)
            order: Sort order - relevance, date, viewCount, rating (default relevance)
            published_after: Filter by publish date (RFC 3339 format, e.g. 2024-01-01T00:00:00Z)
            region_code: ISO 3166-1 alpha-2 country code (e.g. US, GB, JP)
            video_duration: Filter by duration - short (<4min), medium (4-20min), long (>20min)
            video_type: Filter by type - episode, movie, or empty for any

        Returns:
            Dict with query, results list (title, videoId,
                channelTitle, publishedAt, description,
                thumbnail), and total_results count
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return {
                "error": "YOUTUBE_API_KEY not set",
                "help": "Get an API key at https://console.cloud.google.com/apis/credentials",
            }
        if not query:
            return {"error": "query is required"}
        max_results = max(1, min(max_results, MAX_RESULTS_LIMIT))

        params: dict[str, Any] = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "order": order,
        }
        if published_after:
            params["publishedAfter"] = published_after
        if region_code:
            params["regionCode"] = region_code
        if video_duration:
            params["videoDuration"] = video_duration
        if video_type:
            params["videoType"] = video_type

        data = _request("search", params, api_key)
        if "error" in data:
            return data

        results = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            results.append(
                {
                    "videoId": item.get("id", {}).get("videoId", ""),
                    "title": snippet.get("title", ""),
                    "channelTitle": snippet.get("channelTitle", ""),
                    "channelId": snippet.get("channelId", ""),
                    "publishedAt": snippet.get("publishedAt", ""),
                    "description": snippet.get("description", ""),
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                }
            )
        return {
            "query": query,
            "results": results,
            "total_results": data.get("pageInfo", {}).get("totalResults", 0),
        }

    @mcp.tool()
    def youtube_get_video_details(
        video_ids: str,
    ) -> dict[str, Any]:
        """
        Get detailed information for one or more YouTube videos.

        Args:
            video_ids: Comma-separated video IDs (max 50, e.g. "dQw4w9WgXcQ,jNQXAC9IVRw")

        Returns:
            Dict with videos list containing title, description, channelTitle, publishedAt,
            viewCount, likeCount, commentCount, duration, tags, categoryId, and thumbnail
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return {
                "error": "YOUTUBE_API_KEY not set",
                "help": "Get an API key at https://console.cloud.google.com/apis/credentials",
            }
        if not video_ids:
            return {"error": "video_ids is required"}

        data = _request(
            "videos",
            {
                "part": "snippet,contentDetails,statistics",
                "id": video_ids,
            },
            api_key,
        )
        if "error" in data:
            return data

        videos = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            videos.append(
                {
                    "videoId": item.get("id", ""),
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "channelTitle": snippet.get("channelTitle", ""),
                    "channelId": snippet.get("channelId", ""),
                    "publishedAt": snippet.get("publishedAt", ""),
                    "tags": snippet.get("tags", []),
                    "categoryId": snippet.get("categoryId", ""),
                    "duration": _parse_duration(content.get("duration", "")),
                    "duration_raw": content.get("duration", ""),
                    "viewCount": int(stats.get("viewCount", 0)),
                    "likeCount": int(stats.get("likeCount", 0)),
                    "commentCount": int(stats.get("commentCount", 0)),
                    "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                }
            )
        return {"videos": videos}

    @mcp.tool()
    def youtube_get_channel(
        channel_id: str = "",
        username: str = "",
        handle: str = "",
    ) -> dict[str, Any]:
        """
        Get YouTube channel information by channel ID, username, or handle.

        Args:
            channel_id: YouTube channel ID (e.g. UCxxxxxx)
            username: Legacy YouTube username
            handle: YouTube handle without @ (e.g. "GoogleDevelopers")

        Returns:
            Dict with channel details: title, description, subscriberCount, videoCount,
            viewCount, publishedAt, thumbnail, and customUrl
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return {
                "error": "YOUTUBE_API_KEY not set",
                "help": "Get an API key at https://console.cloud.google.com/apis/credentials",
            }

        params: dict[str, Any] = {"part": "snippet,statistics,contentDetails"}
        if channel_id:
            params["id"] = channel_id
        elif username:
            params["forUsername"] = username
        elif handle:
            params["forHandle"] = handle
        else:
            return {"error": "Provide one of: channel_id, username, or handle"}

        data = _request("channels", params, api_key)
        if "error" in data:
            return data

        items = data.get("items", [])
        if not items:
            return {"error": "Channel not found"}

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        return {
            "channelId": item.get("id", ""),
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "customUrl": snippet.get("customUrl", ""),
            "publishedAt": snippet.get("publishedAt", ""),
            "subscriberCount": int(stats.get("subscriberCount", 0)),
            "videoCount": int(stats.get("videoCount", 0)),
            "viewCount": int(stats.get("viewCount", 0)),
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
            "uploadsPlaylistId": item.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads", ""),
        }

    @mcp.tool()
    def youtube_list_channel_videos(
        channel_id: str,
        max_results: int = 20,
        order: str = "date",
    ) -> dict[str, Any]:
        """
        List recent videos from a YouTube channel.

        Args:
            channel_id: YouTube channel ID (e.g. UCxxxxxx)
            max_results: Number of results (1-50, default 20)
            order: Sort order - date, viewCount, rating, relevance (default date)

        Returns:
            Dict with channel_id and videos list (videoId, title,
                publishedAt, description, thumbnail)
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return {
                "error": "YOUTUBE_API_KEY not set",
                "help": "Get an API key at https://console.cloud.google.com/apis/credentials",
            }
        if not channel_id:
            return {"error": "channel_id is required"}
        max_results = max(1, min(max_results, MAX_RESULTS_LIMIT))

        data = _request(
            "search",
            {
                "part": "snippet",
                "channelId": channel_id,
                "type": "video",
                "maxResults": max_results,
                "order": order,
            },
            api_key,
        )
        if "error" in data:
            return data

        videos = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            videos.append(
                {
                    "videoId": item.get("id", {}).get("videoId", ""),
                    "title": snippet.get("title", ""),
                    "publishedAt": snippet.get("publishedAt", ""),
                    "description": snippet.get("description", ""),
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                }
            )
        return {"channel_id": channel_id, "videos": videos}

    @mcp.tool()
    def youtube_get_playlist(
        playlist_id: str,
        max_results: int = 20,
    ) -> dict[str, Any]:
        """
        Get playlist details and its video items.

        Args:
            playlist_id: YouTube playlist ID (e.g. PLxxxxxx)
            max_results: Number of items to return (1-50, default 20)

        Returns:
            Dict with playlist info (title, description, itemCount, channelTitle) and
            items list (videoId, title, position, channelTitle, thumbnail)
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return {
                "error": "YOUTUBE_API_KEY not set",
                "help": "Get an API key at https://console.cloud.google.com/apis/credentials",
            }
        if not playlist_id:
            return {"error": "playlist_id is required"}
        max_results = max(1, min(max_results, MAX_RESULTS_LIMIT))

        # Get playlist metadata
        pl_data = _request(
            "playlists",
            {"part": "snippet,contentDetails", "id": playlist_id},
            api_key,
        )
        if "error" in pl_data:
            return pl_data

        pl_items = pl_data.get("items", [])
        if not pl_items:
            return {"error": "Playlist not found"}

        pl = pl_items[0]
        pl_snippet = pl.get("snippet", {})

        # Get playlist items
        items_data = _request(
            "playlistItems",
            {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": max_results,
            },
            api_key,
        )
        if "error" in items_data:
            return items_data

        items = []
        for item in items_data.get("items", []):
            snippet = item.get("snippet", {})
            items.append(
                {
                    "videoId": snippet.get("resourceId", {}).get("videoId", ""),
                    "title": snippet.get("title", ""),
                    "position": snippet.get("position", 0),
                    "channelTitle": snippet.get("videoOwnerChannelTitle", ""),
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                }
            )

        return {
            "playlistId": playlist_id,
            "title": pl_snippet.get("title", ""),
            "description": pl_snippet.get("description", ""),
            "channelTitle": pl_snippet.get("channelTitle", ""),
            "itemCount": pl.get("contentDetails", {}).get("itemCount", 0),
            "items": items,
        }

    @mcp.tool()
    def youtube_search_channels(
        query: str,
        max_results: int = 10,
        order: str = "relevance",
    ) -> dict[str, Any]:
        """
        Search for YouTube channels by keyword.

        Args:
            query: Search query string
            max_results: Number of results to return (1-50, default 10)
            order: Sort order - relevance, date, viewCount, rating (default relevance)

        Returns:
            Dict with query and results list (channelId, title, description, thumbnail)
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return {
                "error": "YOUTUBE_API_KEY not set",
                "help": "Get an API key at https://console.cloud.google.com/apis/credentials",
            }
        if not query:
            return {"error": "query is required"}
        max_results = max(1, min(max_results, MAX_RESULTS_LIMIT))

        data = _request(
            "search",
            {
                "part": "snippet",
                "q": query,
                "type": "channel",
                "maxResults": max_results,
                "order": order,
            },
            api_key,
        )
        if "error" in data:
            return data

        results = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            results.append(
                {
                    "channelId": item.get("id", {}).get("channelId", ""),
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                }
            )
        return {"query": query, "results": results}

    @mcp.tool()
    def youtube_get_video_comments(
        video_id: str,
        max_results: int = 20,
        order: str = "relevance",
    ) -> dict[str, Any]:
        """
        Get top-level comments on a YouTube video.

        Args:
            video_id: YouTube video ID
            max_results: Number of comments to return (1-100, default 20)
            order: Sort order - relevance or time (default relevance)

        Returns:
            Dict with video_id and comments list (author, text, likeCount, publishedAt, replyCount)
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return {
                "error": "YOUTUBE_API_KEY not set",
                "help": "Get an API key at https://console.cloud.google.com/apis/credentials",
            }
        if not video_id:
            return {"error": "video_id is required"}
        max_results = max(1, min(max_results, 100))

        data = _request(
            "commentThreads",
            {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": max_results,
                "order": order,
                "textFormat": "plainText",
            },
            api_key,
        )
        if "error" in data:
            return data

        comments = []
        for item in data.get("items", []):
            top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            comments.append(
                {
                    "author": top.get("authorDisplayName", ""),
                    "text": top.get("textDisplay", ""),
                    "likeCount": top.get("likeCount", 0),
                    "publishedAt": top.get("publishedAt", ""),
                    "replyCount": item.get("snippet", {}).get("totalReplyCount", 0),
                }
            )
        return {"video_id": video_id, "comments": comments}

    @mcp.tool()
    def youtube_get_video_categories(
        region_code: str = "US",
    ) -> dict[str, Any]:
        """
        Get available YouTube video categories for a region.

        Args:
            region_code: ISO 3166-1 alpha-2 country code (default US)

        Returns:
            Dict with region_code and categories list (id, title)
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return {
                "error": "YOUTUBE_API_KEY not set",
                "help": "Get an API key at https://console.cloud.google.com/apis/credentials",
            }

        data = _request(
            "videoCategories",
            {"part": "snippet", "regionCode": region_code},
            api_key,
        )
        if "error" in data:
            return data

        categories = []
        for item in data.get("items", []):
            categories.append(
                {
                    "id": item.get("id", ""),
                    "title": item.get("snippet", {}).get("title", ""),
                }
            )
        return {"region_code": region_code, "categories": categories}
