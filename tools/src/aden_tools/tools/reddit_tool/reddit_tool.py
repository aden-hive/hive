"""
Reddit Tool - Community content monitoring and search via OAuth2 API.

Supports:
- Reddit OAuth2 (client_credentials grant for app-only access)
- Subreddit browsing, post search, comments, user info

API Reference: https://www.reddit.com/dev/api/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
USER_AGENT = "HiveAgent/1.0"


def _get_credentials(credentials: CredentialStoreAdapter | None) -> tuple[str | None, str | None]:
    """Return (client_id, client_secret)."""
    if credentials is not None:
        cid = credentials.get("reddit_client_id")
        secret = credentials.get("reddit_secret")
        return cid, secret
    return os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")


def _get_token(client_id: str, client_secret: str) -> str | None:
    """Acquire an OAuth2 app-only access token."""
    try:
        resp = httpx.post(
            TOKEN_URL,
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        return None
    except Exception:
        return None


def _get(path: str, token: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list:
    """Make an authenticated GET to the Reddit OAuth API."""
    try:
        resp = httpx.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"bearer {token}", "User-Agent": USER_AGENT},
            params=params or {},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Reddit token may be expired."}
        if resp.status_code == 403:
            return {"error": "Forbidden. Check Reddit app permissions."}
        if resp.status_code != 200:
            return {"error": f"Reddit API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Reddit timed out"}
    except Exception as e:
        return {"error": f"Reddit request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET not set",
        "help": "Create an app at https://www.reddit.com/prefs/apps",
    }


def _extract_posts(listing: dict) -> list[dict[str, Any]]:
    """Extract posts from a Reddit Listing response."""
    children = (listing.get("data") or {}).get("children", [])
    posts = []
    for child in children:
        if child.get("kind") != "t3":
            continue
        d = child.get("data", {})
        posts.append(
            {
                "id": d.get("id", ""),
                "title": d.get("title", ""),
                "author": d.get("author", ""),
                "subreddit": d.get("subreddit", ""),
                "score": d.get("score", 0),
                "num_comments": d.get("num_comments", 0),
                "url": d.get("url", ""),
                "permalink": d.get("permalink", ""),
                "selftext": (d.get("selftext", "") or "")[:500],
                "created_utc": d.get("created_utc", 0),
                "is_self": d.get("is_self", False),
            }
        )
    return posts


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Reddit tools with the MCP server."""

    @mcp.tool()
    def reddit_search(
        query: str,
        subreddit: str = "",
        sort: str = "relevance",
        time: str = "all",
        limit: int = 25,
    ) -> dict[str, Any]:
        """
        Search Reddit posts.

        Args:
            query: Search query text (required)
            subreddit: Restrict search to this subreddit (optional)
            sort: Sort: relevance, hot, top, new, comments (default relevance)
            time: Time filter: hour, day, week, month, year, all (default all)
            limit: Max results (1-100, default 25)

        Returns:
            Dict with matching posts (title, author, score, url, etc.)
        """
        client_id, client_secret = _get_credentials(credentials)
        if not client_id or not client_secret:
            return _auth_error()
        if not query:
            return {"error": "query is required"}

        token = _get_token(client_id, client_secret)
        if not token:
            return {"error": "Failed to acquire Reddit access token"}

        path = f"/r/{subreddit}/search" if subreddit else "/search"
        params: dict[str, Any] = {
            "q": query,
            "sort": sort,
            "t": time,
            "limit": max(1, min(limit, 100)),
            "restrict_sr": "true" if subreddit else "false",
        }

        data = _get(path, token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        listing = data if isinstance(data, dict) else {}
        posts = _extract_posts(listing)
        return {"query": query, "posts": posts, "count": len(posts)}

    @mcp.tool()
    def reddit_get_posts(
        subreddit: str,
        sort: str = "hot",
        time: str = "day",
        limit: int = 25,
    ) -> dict[str, Any]:
        """
        Get posts from a subreddit.

        Args:
            subreddit: Subreddit name without r/ prefix (required)
            sort: Sort: hot, new, top, rising, controversial (default hot)
            time: Time filter for top/controversial: hour, day, week, month, year, all
            limit: Max results (1-100, default 25)

        Returns:
            Dict with posts list
        """
        client_id, client_secret = _get_credentials(credentials)
        if not client_id or not client_secret:
            return _auth_error()
        if not subreddit:
            return {"error": "subreddit is required"}

        token = _get_token(client_id, client_secret)
        if not token:
            return {"error": "Failed to acquire Reddit access token"}

        params: dict[str, Any] = {
            "limit": max(1, min(limit, 100)),
            "t": time,
        }
        data = _get(f"/r/{subreddit}/{sort}", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        listing = data if isinstance(data, dict) else {}
        posts = _extract_posts(listing)
        return {"subreddit": subreddit, "posts": posts, "count": len(posts)}

    @mcp.tool()
    def reddit_get_comments(
        post_id: str,
        subreddit: str = "",
        sort: str = "confidence",
        limit: int = 25,
    ) -> dict[str, Any]:
        """
        Get comments on a Reddit post.

        Args:
            post_id: Post ID (e.g. "abc123", without t3_ prefix) (required)
            subreddit: Subreddit name (optional, improves routing)
            sort: Sort: confidence (best), top, new, controversial, old
            limit: Max comments (default 25)

        Returns:
            Dict with post info and top-level comments
        """
        client_id, client_secret = _get_credentials(credentials)
        if not client_id or not client_secret:
            return _auth_error()
        if not post_id:
            return {"error": "post_id is required"}

        token = _get_token(client_id, client_secret)
        if not token:
            return {"error": "Failed to acquire Reddit access token"}

        path = f"/r/{subreddit}/comments/{post_id}" if subreddit else f"/comments/{post_id}"
        params = {"sort": sort, "limit": max(1, min(limit, 100))}

        data = _get(path, token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        # Response is [post_listing, comment_listing]
        if not isinstance(data, list) or len(data) < 2:
            return {"error": "Unexpected response format"}

        # Extract post
        post_listing = data[0]
        post_children = (post_listing.get("data") or {}).get("children", [])
        post = {}
        if post_children and post_children[0].get("kind") == "t3":
            pd = post_children[0].get("data", {})
            post = {
                "id": pd.get("id", ""),
                "title": pd.get("title", ""),
                "author": pd.get("author", ""),
                "score": pd.get("score", 0),
                "selftext": (pd.get("selftext", "") or "")[:500],
            }

        # Extract comments
        comment_listing = data[1]
        comment_children = (comment_listing.get("data") or {}).get("children", [])
        comments = []
        for child in comment_children:
            if child.get("kind") != "t1":
                continue
            cd = child.get("data", {})
            comments.append(
                {
                    "id": cd.get("id", ""),
                    "author": cd.get("author", ""),
                    "body": (cd.get("body", "") or "")[:500],
                    "score": cd.get("score", 0),
                    "created_utc": cd.get("created_utc", 0),
                }
            )

        return {"post": post, "comments": comments, "comment_count": len(comments)}

    @mcp.tool()
    def reddit_get_user(username: str) -> dict[str, Any]:
        """
        Get public info about a Reddit user.

        Args:
            username: Reddit username (required)

        Returns:
            Dict with user info (name, karma, created_utc)
        """
        client_id, client_secret = _get_credentials(credentials)
        if not client_id or not client_secret:
            return _auth_error()
        if not username:
            return {"error": "username is required"}

        token = _get_token(client_id, client_secret)
        if not token:
            return {"error": "Failed to acquire Reddit access token"}

        data = _get(f"/user/{username}/about", token)
        if isinstance(data, dict) and "error" in data:
            return data

        d = (data if isinstance(data, dict) else {}).get("data", {})
        return {
            "name": d.get("name", ""),
            "link_karma": d.get("link_karma", 0),
            "comment_karma": d.get("comment_karma", 0),
            "total_karma": d.get("total_karma", 0),
            "created_utc": d.get("created_utc", 0),
            "is_gold": d.get("is_gold", False),
        }

    @mcp.tool()
    def reddit_get_subreddit_info(subreddit: str) -> dict[str, Any]:
        """
        Get information about a subreddit.

        Args:
            subreddit: Subreddit name without r/ prefix (required)

        Returns:
            Dict with subreddit details (subscribers, description, rules, etc.)
        """
        client_id, client_secret = _get_credentials(credentials)
        if not client_id or not client_secret:
            return _auth_error()
        if not subreddit:
            return {"error": "subreddit is required"}

        token = _get_token(client_id, client_secret)
        if not token:
            return {"error": "Failed to acquire Reddit access token"}

        data = _get(f"/r/{subreddit}/about", token)
        if isinstance(data, dict) and "error" in data:
            return data

        d = (data if isinstance(data, dict) else {}).get("data", {})
        return {
            "name": d.get("display_name", ""),
            "title": d.get("title", ""),
            "description": (d.get("public_description", "") or "")[:500],
            "subscribers": d.get("subscribers", 0),
            "active_users": d.get("accounts_active", 0),
            "created_utc": d.get("created_utc", 0),
            "over18": d.get("over18", False),
            "subreddit_type": d.get("subreddit_type", ""),
            "submission_type": d.get("submission_type", ""),
        }

    @mcp.tool()
    def reddit_get_post_detail(post_id: str) -> dict[str, Any]:
        """
        Get full details for a single Reddit post by ID.

        Args:
            post_id: Post ID (e.g. "abc123", without t3_ prefix) (required)

        Returns:
            Dict with full post details including selftext, flair, awards
        """
        client_id, client_secret = _get_credentials(credentials)
        if not client_id or not client_secret:
            return _auth_error()
        if not post_id:
            return {"error": "post_id is required"}

        token = _get_token(client_id, client_secret)
        if not token:
            return {"error": "Failed to acquire Reddit access token"}

        data = _get(f"/by_id/t3_{post_id}", token)
        if isinstance(data, dict) and "error" in data:
            return data

        listing = data if isinstance(data, dict) else {}
        children = (listing.get("data") or {}).get("children", [])
        if not children or children[0].get("kind") != "t3":
            return {"error": "Post not found"}

        d = children[0].get("data", {})
        return {
            "id": d.get("id", ""),
            "title": d.get("title", ""),
            "author": d.get("author", ""),
            "subreddit": d.get("subreddit", ""),
            "score": d.get("score", 0),
            "upvote_ratio": d.get("upvote_ratio", 0),
            "num_comments": d.get("num_comments", 0),
            "url": d.get("url", ""),
            "permalink": d.get("permalink", ""),
            "selftext": (d.get("selftext", "") or "")[:2000],
            "link_flair_text": d.get("link_flair_text", ""),
            "created_utc": d.get("created_utc", 0),
            "is_self": d.get("is_self", False),
            "over_18": d.get("over_18", False),
            "locked": d.get("locked", False),
            "archived": d.get("archived", False),
        }

    @mcp.tool()
    def reddit_get_user_posts(
        username: str,
        sort: str = "new",
        time: str = "all",
        limit: int = 25,
    ) -> dict[str, Any]:
        """
        Get recent posts submitted by a Reddit user.

        Args:
            username: Reddit username (required)
            sort: Sort: hot, new, top, controversial (default new)
            time: Time filter for top/controversial: hour, day, week, month, year, all
            limit: Max results (1-100, default 25)

        Returns:
            Dict with user's submitted posts
        """
        client_id, client_secret = _get_credentials(credentials)
        if not client_id or not client_secret:
            return _auth_error()
        if not username:
            return {"error": "username is required"}

        token = _get_token(client_id, client_secret)
        if not token:
            return {"error": "Failed to acquire Reddit access token"}

        params: dict[str, Any] = {
            "sort": sort,
            "t": time,
            "limit": max(1, min(limit, 100)),
        }
        data = _get(f"/user/{username}/submitted", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        listing = data if isinstance(data, dict) else {}
        posts = _extract_posts(listing)
        return {"username": username, "posts": posts, "count": len(posts)}
