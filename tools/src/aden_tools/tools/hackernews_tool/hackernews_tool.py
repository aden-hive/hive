"""
HackerNews Tool - Fetch top stories and details from Hacker News.

Provides agents with access to Hacker News data including stories,
metadata, and comments without requiring authentication.
"""

from __future__ import annotations

import httpx
from fastmcp import FastMCP

# Define Firebase API Base URL
HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

def register_tools(mcp: FastMCP) -> None:
    """Register HackerNews tools with the MCP server."""

    @mcp.tool()
    def get_top_hn_stories(limit: int = 10) -> dict:
        """
        Fetch the top stories from Hacker News.

        Use this tool when you need to get the latest trending news,
        discussions, and show/ask HN posts.

        Args:
            limit: Maximum number of stories to fetch (capped at 50).

        Returns:
            Dictionary with a list of stories:
            - id: Story ID
            - title: Story Title
            - url: Link to the article (if any)
            - by: Author username
            - score: Upvotes
            - time: Unix timestamp of creation
            - descendants: Number of comments
        """
        limit = min(max(1, limit), 50)  # Cap between 1 and 50

        try:
            with httpx.Client(timeout=10.0) as client:
                # Get top story IDs
                resp = client.get(f"{HN_API_BASE}/topstories.json")
                resp.raise_for_status()
                story_ids = resp.json()[:limit]

                stories = []
                for sid in story_ids:
                    s_resp = client.get(f"{HN_API_BASE}/item/{sid}.json")
                    if s_resp.status_code == 200:
                        data = s_resp.json()
                        if data and data.get("type") == "story":
                            stories.append({
                                "id": data.get("id"),
                                "title": data.get("title"),
                                "url": data.get("url"),
                                "by": data.get("by"),
                                "score": data.get("score"),
                                "time": data.get("time"),
                                "descendants": data.get("descendants", 0),
                            })
                
                return {"stories": stories}

        except httpx.TimeoutException:
            return {"error": "Request to HackerNews API timed out."}
        except Exception as e:
            return {"error": f"Failed to fetch HackerNews stories: {str(e)}"}

    @mcp.tool()
    def get_hn_story_details(story_id: int, include_comments: bool = True, comment_limit: int = 10) -> dict:
        """
        Fetch details and top-level comments for a specific Hacker News story.

        Use this tool to read the discussion on a specific post.

        Args:
            story_id: The ID of the Hacker News story.
            include_comments: Whether to fetch top-level comments.
            comment_limit: Maximum number of top-level comments to fetch (capped at 20).

        Returns:
            Dictionary with story details and top-level comments.
        """
        comment_limit = min(max(1, comment_limit), 20)

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{HN_API_BASE}/item/{story_id}.json")
                resp.raise_for_status()
                data = resp.json()

                if not data or data.get("type") != "story":
                    return {"error": f"Story {story_id} not found or is not a story type."}

                story = {
                    "id": data.get("id"),
                    "title": data.get("title"),
                    "url": data.get("url"),
                    "by": data.get("by"),
                    "text": data.get("text"),
                    "score": data.get("score"),
                    "time": data.get("time"),
                    "descendants": data.get("descendants", 0),
                }

                comments = []
                if include_comments and "kids" in data:
                    kid_ids = data["kids"][:comment_limit]
                    for kid_id in kid_ids:
                        c_resp = client.get(f"{HN_API_BASE}/item/{kid_id}.json")
                        if c_resp.status_code == 200:
                            c_data = c_resp.json()
                            if c_data and c_data.get("type") == "comment" and not c_data.get("deleted"):
                                comments.append({
                                    "id": c_data.get("id"),
                                    "by": c_data.get("by"),
                                    "text": c_data.get("text"),
                                    "time": c_data.get("time")
                                })

                return {
                    "story": story,
                    "comments": comments
                }

        except httpx.TimeoutException:
            return {"error": "Request to HackerNews API timed out."}
        except Exception as e:
            return {"error": f"Failed to fetch detailed story info: {str(e)}"}
