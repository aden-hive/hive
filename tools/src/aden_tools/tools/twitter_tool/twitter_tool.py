"""Twitter/X API v2 integration.

Provides tweet search, user lookup, and timeline access via the X API v2.
Requires X_BEARER_TOKEN for read-only access.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

BASE_URL = "https://api.x.com/2"

TWEET_FIELDS = "created_at,public_metrics,author_id,lang"
USER_FIELDS = "created_at,description,public_metrics,profile_image_url,verified"


def _get_headers() -> dict | None:
    """Return auth headers or None if credentials missing."""
    token = os.getenv("X_BEARER_TOKEN", "")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def _get(path: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _extract_tweet(t: dict) -> dict:
    """Extract key fields from a tweet."""
    metrics = t.get("public_metrics", {})
    return {
        "id": t.get("id"),
        "text": t.get("text"),
        "author_id": t.get("author_id"),
        "created_at": t.get("created_at"),
        "lang": t.get("lang"),
        "retweet_count": metrics.get("retweet_count", 0),
        "reply_count": metrics.get("reply_count", 0),
        "like_count": metrics.get("like_count", 0),
        "impression_count": metrics.get("impression_count", 0),
    }


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Twitter/X tools."""

    @mcp.tool()
    def twitter_search_tweets(
        query: str,
        max_results: int = 10,
        sort_order: str = "recency",
    ) -> dict:
        """Search recent tweets (last 7 days) on X/Twitter.

        Args:
            query: Search query. Supports operators like 'from:user', 'has:media', '-is:retweet'.
            max_results: Number of results (10-100, default 10).
            sort_order: Sort by 'recency' or 'relevancy'.
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "X_BEARER_TOKEN is required",
                "help": "Set X_BEARER_TOKEN environment variable",
            }
        if not query:
            return {"error": "query is required"}

        params: dict[str, Any] = {
            "query": query,
            "max_results": max(10, min(max_results, 100)),
            "sort_order": sort_order,
            "tweet.fields": TWEET_FIELDS,
            "expansions": "author_id",
            "user.fields": "name,username",
        }

        data = _get("/tweets/search/recent", headers, params)
        if "error" in data:
            return data

        tweets = data.get("data", [])
        # Build author lookup from includes
        users_map = {}
        for u in data.get("includes", {}).get("users", []):
            users_map[u["id"]] = {"name": u.get("name"), "username": u.get("username")}

        results = []
        for t in tweets:
            tweet = _extract_tweet(t)
            author = users_map.get(t.get("author_id"), {})
            tweet["author_name"] = author.get("name")
            tweet["author_username"] = author.get("username")
            results.append(tweet)

        meta = data.get("meta", {})
        return {
            "count": meta.get("result_count", len(results)),
            "tweets": results,
        }

    @mcp.tool()
    def twitter_get_user(username: str) -> dict:
        """Get a Twitter/X user profile by username.

        Args:
            username: Twitter username (without @).
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "X_BEARER_TOKEN is required",
                "help": "Set X_BEARER_TOKEN environment variable",
            }
        if not username:
            return {"error": "username is required"}

        params = {"user.fields": USER_FIELDS}
        data = _get(f"/users/by/username/{username}", headers, params)
        if "error" in data:
            return data

        user = data.get("data", {})
        metrics = user.get("public_metrics", {})
        return {
            "id": user.get("id"),
            "name": user.get("name"),
            "username": user.get("username"),
            "description": user.get("description"),
            "created_at": user.get("created_at"),
            "profile_image_url": user.get("profile_image_url"),
            "verified": user.get("verified"),
            "followers_count": metrics.get("followers_count", 0),
            "following_count": metrics.get("following_count", 0),
            "tweet_count": metrics.get("tweet_count", 0),
        }

    @mcp.tool()
    def twitter_get_user_tweets(
        user_id: str,
        max_results: int = 10,
        exclude_replies: bool = True,
        exclude_retweets: bool = True,
    ) -> dict:
        """Get recent tweets from a user's timeline.

        Args:
            user_id: Twitter user ID (numeric string). Get from twitter_get_user.
            max_results: Number of results (5-100, default 10).
            exclude_replies: If true, exclude reply tweets.
            exclude_retweets: If true, exclude retweets.
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "X_BEARER_TOKEN is required",
                "help": "Set X_BEARER_TOKEN environment variable",
            }
        if not user_id:
            return {"error": "user_id is required"}

        params: dict[str, Any] = {
            "max_results": max(5, min(max_results, 100)),
            "tweet.fields": TWEET_FIELDS,
        }
        excludes = []
        if exclude_replies:
            excludes.append("replies")
        if exclude_retweets:
            excludes.append("retweets")
        if excludes:
            params["exclude"] = ",".join(excludes)

        data = _get(f"/users/{user_id}/tweets", headers, params)
        if "error" in data:
            return data

        tweets = [_extract_tweet(t) for t in data.get("data", [])]
        return {"count": len(tweets), "tweets": tweets}

    @mcp.tool()
    def twitter_get_tweet(tweet_id: str) -> dict:
        """Get details of a specific tweet by ID.

        Args:
            tweet_id: Tweet ID (numeric string).
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "X_BEARER_TOKEN is required",
                "help": "Set X_BEARER_TOKEN environment variable",
            }
        if not tweet_id:
            return {"error": "tweet_id is required"}

        params = {
            "tweet.fields": TWEET_FIELDS,
            "expansions": "author_id",
            "user.fields": "name,username",
        }

        data = _get(f"/tweets/{tweet_id}", headers, params)
        if "error" in data:
            return data

        tweet = _extract_tweet(data.get("data", {}))
        users = data.get("includes", {}).get("users", [])
        if users:
            tweet["author_name"] = users[0].get("name")
            tweet["author_username"] = users[0].get("username")
        return tweet

    @mcp.tool()
    def twitter_get_user_followers(
        user_id: str,
        max_results: int = 25,
    ) -> dict:
        """Get followers of a Twitter/X user.

        Args:
            user_id: Twitter user ID (numeric string). Get from twitter_get_user.
            max_results: Number of results (1-100, default 25).
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "X_BEARER_TOKEN is required",
                "help": "Set X_BEARER_TOKEN environment variable",
            }
        if not user_id:
            return {"error": "user_id is required"}

        params: dict[str, Any] = {
            "max_results": max(1, min(max_results, 100)),
            "user.fields": USER_FIELDS,
        }

        data = _get(f"/users/{user_id}/followers", headers, params)
        if "error" in data:
            return data

        followers = []
        for u in data.get("data", []):
            metrics = u.get("public_metrics", {})
            followers.append(
                {
                    "id": u.get("id"),
                    "name": u.get("name"),
                    "username": u.get("username"),
                    "description": (u.get("description") or "")[:200],
                    "followers_count": metrics.get("followers_count", 0),
                    "following_count": metrics.get("following_count", 0),
                    "verified": u.get("verified"),
                }
            )
        return {"count": len(followers), "followers": followers}

    @mcp.tool()
    def twitter_get_tweet_replies(
        tweet_id: str,
        max_results: int = 10,
    ) -> dict:
        """Get replies to a specific tweet using search.

        Args:
            tweet_id: Tweet ID to get replies for (numeric string).
            max_results: Number of results (10-100, default 10).
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "X_BEARER_TOKEN is required",
                "help": "Set X_BEARER_TOKEN environment variable",
            }
        if not tweet_id:
            return {"error": "tweet_id is required"}

        params: dict[str, Any] = {
            "query": f"conversation_id:{tweet_id} is:reply",
            "max_results": max(10, min(max_results, 100)),
            "tweet.fields": TWEET_FIELDS,
            "expansions": "author_id",
            "user.fields": "name,username",
        }

        data = _get("/tweets/search/recent", headers, params)
        if "error" in data:
            return data

        users_map = {}
        for u in data.get("includes", {}).get("users", []):
            users_map[u["id"]] = {"name": u.get("name"), "username": u.get("username")}

        replies = []
        for t in data.get("data", []):
            reply = _extract_tweet(t)
            author = users_map.get(t.get("author_id"), {})
            reply["author_name"] = author.get("name")
            reply["author_username"] = author.get("username")
            replies.append(reply)

        return {"tweet_id": tweet_id, "count": len(replies), "replies": replies}

    @mcp.tool()
    def twitter_get_list_tweets(
        list_id: str,
        max_results: int = 10,
    ) -> dict:
        """Get recent tweets from a Twitter/X list.

        Args:
            list_id: Twitter list ID (numeric string).
            max_results: Number of results (1-100, default 10).
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "X_BEARER_TOKEN is required",
                "help": "Set X_BEARER_TOKEN environment variable",
            }
        if not list_id:
            return {"error": "list_id is required"}

        params: dict[str, Any] = {
            "max_results": max(1, min(max_results, 100)),
            "tweet.fields": TWEET_FIELDS,
            "expansions": "author_id",
            "user.fields": "name,username",
        }

        data = _get(f"/lists/{list_id}/tweets", headers, params)
        if "error" in data:
            return data

        users_map = {}
        for u in data.get("includes", {}).get("users", []):
            users_map[u["id"]] = {"name": u.get("name"), "username": u.get("username")}

        tweets = []
        for t in data.get("data", []):
            tweet = _extract_tweet(t)
            author = users_map.get(t.get("author_id"), {})
            tweet["author_name"] = author.get("name")
            tweet["author_username"] = author.get("username")
            tweets.append(tweet)

        return {"list_id": list_id, "count": len(tweets), "tweets": tweets}
