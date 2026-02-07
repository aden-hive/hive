"""
Reddit Tool - Community Management & Content Monitoring.

Supports:
- OAuth 2.0 authentication via REDDIT_CREDENTIALS
- Search & Monitoring (5 functions)
- Content Creation (5 functions)
- User Engagement (3 functions)
- Moderation (3 functions)

Total: 18 tools

API Reference: https://www.reddit.com/dev/api/
PRAW Documentation: https://praw.readthedocs.io/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# PRAW imports - lazy loaded to avoid import errors if not installed
try:
    import praw
    from prawcore.exceptions import PrawcoreException

    PRAW_AVAILABLE = True
except ImportError:
    PRAW_AVAILABLE = False


def _get_reddit_client(
    credentials: CredentialStoreAdapter | None = None,
) -> praw.Reddit | dict[str, str]:
    """
    Initialize Reddit client with credentials.

    Returns:
        Authenticated PRAW Reddit instance or error dict
    """
    if not PRAW_AVAILABLE:
        return {
            "error": "PRAW library not installed",
            "help": "Install with: pip install praw>=7.7.1 prawcore>=2.4.0",
        }

    # Get credentials from adapter or environment
    if credentials is not None:
        creds = credentials.get("reddit")
    else:
        creds_str = os.getenv("REDDIT_CREDENTIALS")
        if creds_str:
            import json

            try:
                creds = json.loads(creds_str)
            except json.JSONDecodeError:
                return {
                    "error": "Invalid REDDIT_CREDENTIALS format",
                    "help": (
                        "Must be valid JSON with client_id, client_secret, "
                        "refresh_token, user_agent"
                    ),
                }
        else:
            creds = None

    if not creds:
        return {
            "error": "REDDIT_CREDENTIALS not configured",
            "help": "Get credentials at https://www.reddit.com/prefs/apps",
        }

    # Validate required fields
    required_fields = ["client_id", "client_secret", "refresh_token", "user_agent"]
    missing = [f for f in required_fields if f not in creds]
    if missing:
        return {
            "error": f"Missing required credential fields: {', '.join(missing)}",
            "help": (
                "REDDIT_CREDENTIALS must include: client_id, client_secret, "
                "refresh_token, user_agent"
            ),
        }

    try:
        reddit = praw.Reddit(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            refresh_token=creds["refresh_token"],
            user_agent=creds["user_agent"],
        )
        return reddit
    except Exception as e:
        return {"error": f"Failed to authenticate with Reddit: {str(e)}"}


def _serialize_submission(submission: Any) -> dict[str, Any]:
    """Serialize a Reddit submission to a dictionary."""
    return {
        "id": submission.id,
        "title": submission.title,
        "author": str(submission.author) if submission.author else "[deleted]",
        "subreddit": str(submission.subreddit),
        "score": submission.score,
        "upvote_ratio": submission.upvote_ratio,
        "num_comments": submission.num_comments,
        "created_utc": submission.created_utc,
        "url": submission.url,
        "permalink": f"https://reddit.com{submission.permalink}",
        "selftext": submission.selftext[:500] if submission.selftext else "",
        "is_self": submission.is_self,
        "link_flair_text": submission.link_flair_text,
    }


def _serialize_comment(comment: Any) -> dict[str, Any]:
    """Serialize a Reddit comment to a dictionary."""
    return {
        "id": comment.id,
        "author": str(comment.author) if comment.author else "[deleted]",
        "body": comment.body[:500] if comment.body else "",
        "score": comment.score,
        "created_utc": comment.created_utc,
        "permalink": f"https://reddit.com{comment.permalink}",
        "parent_id": comment.parent_id,
        "submission_id": comment.submission.id if hasattr(comment, "submission") else None,
    }


def _serialize_redditor(redditor: Any) -> dict[str, Any]:
    """Serialize a Reddit user profile to a dictionary."""
    return {
        "name": redditor.name,
        "id": redditor.id,
        "created_utc": redditor.created_utc,
        "link_karma": redditor.link_karma,
        "comment_karma": redditor.comment_karma,
        "is_gold": redditor.is_gold,
        "is_mod": redditor.is_mod,
        "has_verified_email": redditor.has_verified_email,
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Reddit tools with the MCP server."""

    # ==================== Search & Monitoring (5 functions) ====================

    @mcp.tool()
    def reddit_search_posts(
        query: str,
        subreddit: str = "all",
        time_filter: str = "all",
        sort: str = "relevance",
        limit: int = 10,
    ) -> dict:
        """
        Search for Reddit posts matching a query.

        Use this to find posts about specific topics, brands, or keywords across Reddit.

        Args:
            query: Search query (1-512 characters)
            subreddit: Subreddit name or "all" for site-wide search
            time_filter: Time period - "hour", "day", "week", "month", "year", "all"
            sort: Sort method - "relevance", "hot", "top", "new", "comments"
            limit: Maximum number of posts to return (1-100)

        Returns:
            Dict with search results or error dict
        """
        if not query or len(query) > 512:
            return {"error": "Query must be 1-512 characters"}

        limit = max(1, min(100, limit))

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            sub = reddit.subreddit(subreddit)
            posts = sub.search(query, time_filter=time_filter, sort=sort, limit=limit)
            results = [_serialize_submission(post) for post in posts]

            return {
                "query": query,
                "subreddit": subreddit,
                "count": len(results),
                "posts": results,
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}

    @mcp.tool()
    def reddit_search_comments(
        query: str,
        subreddit: str = "all",
        time_filter: str = "all",
        sort: str = "relevance",
        limit: int = 10,
    ) -> dict:
        """
        Search for Reddit comments matching a query.

        Use this to monitor brand mentions or discussions in comments.

        Args:
            query: Search query (1-512 characters)
            subreddit: Subreddit name or "all" for site-wide search
            time_filter: Time period - "hour", "day", "week", "month", "year", "all"
            sort: Sort method - "relevance", "new", "top"
            limit: Maximum number of comments to return (1-100)

        Returns:
            Dict with search results or error dict
        """
        if not query or len(query) > 512:
            return {"error": "Query must be 1-512 characters"}

        limit = max(1, min(100, limit))

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            # PRAW's search returns submissions, not comments directly
            # To get comments, use reddit_search_posts and then reddit_get_comments
            return {
                "error": "Comment search not directly supported by PRAW",
                "help": (
                    "Use reddit_search_posts and then reddit_get_comments for specific posts"
                ),
            }
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}

    @mcp.tool()
    def reddit_get_subreddit_new(
        subreddit: str,
        limit: int = 25,
    ) -> dict:
        """
        Get new posts from a subreddit.

        Use this to monitor latest community activity.

        Args:
            subreddit: Subreddit name (e.g., "python", "programming")
            limit: Maximum number of posts to return (1-100)

        Returns:
            Dict with posts or error dict
        """
        if not subreddit or len(subreddit) > 50:
            return {"error": "Subreddit name must be 1-50 characters"}

        limit = max(1, min(100, limit))

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            sub = reddit.subreddit(subreddit)
            posts = sub.new(limit=limit)
            results = [_serialize_submission(post) for post in posts]

            return {
                "subreddit": subreddit,
                "feed_type": "new",
                "count": len(results),
                "posts": results,
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to get posts: {str(e)}"}

    @mcp.tool()
    def reddit_get_subreddit_hot(
        subreddit: str,
        limit: int = 25,
    ) -> dict:
        """
        Get hot posts from a subreddit.

        Use this to monitor trending community content.

        Args:
            subreddit: Subreddit name (e.g., "python", "programming")
            limit: Maximum number of posts to return (1-100)

        Returns:
            Dict with posts or error dict
        """
        if not subreddit or len(subreddit) > 50:
            return {"error": "Subreddit name must be 1-50 characters"}

        limit = max(1, min(100, limit))

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            sub = reddit.subreddit(subreddit)
            posts = sub.hot(limit=limit)
            results = [_serialize_submission(post) for post in posts]

            return {
                "subreddit": subreddit,
                "feed_type": "hot",
                "count": len(results),
                "posts": results,
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to get posts: {str(e)}"}

    @mcp.tool()
    def reddit_get_post(post_id: str) -> dict:
        """
        Get a specific Reddit post by ID.

        Use this to retrieve full details of a post.

        Args:
            post_id: Reddit post ID (e.g., "abc123")

        Returns:
            Dict with post details or error dict
        """
        if not post_id or len(post_id) > 20:
            return {"error": "Post ID must be 1-20 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            submission = reddit.submission(id=post_id)
            return {
                "success": True,
                "post": _serialize_submission(submission),
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to get post: {str(e)}"}

    @mcp.tool()
    def reddit_get_comments(
        post_id: str,
        sort: str = "best",
        limit: int = 50,
    ) -> dict:
        """
        Get comments from a Reddit post.

        Use this to retrieve discussions from a specific post.

        Args:
            post_id: Reddit post ID
            sort: Sort method - "best", "top", "new", "controversial", "old", "qa"
            limit: Maximum number of comments to return (1-500)

        Returns:
            Dict with comments or error dict
        """
        if not post_id or len(post_id) > 20:
            return {"error": "Post ID must be 1-20 characters"}

        limit = max(1, min(500, limit))

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            submission = reddit.submission(id=post_id)
            submission.comment_sort = sort
            submission.comment_limit = limit
            submission.comments.replace_more(limit=0)  # Don't fetch "load more" comments

            comments = [_serialize_comment(comment) for comment in submission.comments.list()]

            return {
                "post_id": post_id,
                "count": len(comments),
                "comments": comments,
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to get comments: {str(e)}"}

    # ==================== Content Creation (5 functions) ====================

    @mcp.tool()
    def reddit_submit_post(
        subreddit: str,
        title: str,
        content: str = "",
        url: str = "",
        flair_id: str = "",
    ) -> dict:
        """
        Submit a new post to a subreddit.

        Use this to create content or automate posting.
        Provide either content (text post) or url (link post).

        Args:
            subreddit: Subreddit name to post to
            title: Post title (1-300 characters)
            content: Post body text (for self posts)
            url: Link URL (for link posts)
            flair_id: Optional flair ID to apply

        Returns:
            Dict with submission details or error dict
        """
        if not subreddit or len(subreddit) > 50:
            return {"error": "Subreddit name must be 1-50 characters"}

        if not title or len(title) > 300:
            return {"error": "Title must be 1-300 characters"}

        if not content and not url:
            return {"error": "Must provide either content (text post) or url (link post)"}

        if content and url:
            return {"error": "Cannot provide both content and url - choose one"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            sub = reddit.subreddit(subreddit)

            if url:
                submission = sub.submit(
                    title=title, url=url, flair_id=flair_id if flair_id else None
                )
            else:
                submission = sub.submit(
                    title=title,
                    selftext=content,
                    flair_id=flair_id if flair_id else None,
                )

            return {
                "success": True,
                "post_id": submission.id,
                "permalink": f"https://reddit.com{submission.permalink}",
                "post": _serialize_submission(submission),
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to submit post: {str(e)}"}

    @mcp.tool()
    def reddit_reply_to_post(post_id: str, text: str) -> dict:
        """
        Reply to a Reddit post.

        Use this to engage with community posts.

        Args:
            post_id: Reddit post ID to reply to
            text: Reply text (1-10000 characters)

        Returns:
            Dict with comment details or error dict
        """
        if not post_id or len(post_id) > 20:
            return {"error": "Post ID must be 1-20 characters"}

        if not text or len(text) > 10000:
            return {"error": "Reply text must be 1-10000 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            submission = reddit.submission(id=post_id)
            comment = submission.reply(text)

            return {
                "success": True,
                "comment_id": comment.id,
                "permalink": f"https://reddit.com{comment.permalink}",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to reply: {str(e)}"}

    @mcp.tool()
    def reddit_reply_to_comment(comment_id: str, text: str) -> dict:
        """
        Reply to a Reddit comment.

        Use this to respond to discussions and engage with users.

        Args:
            comment_id: Reddit comment ID to reply to
            text: Reply text (1-10000 characters)

        Returns:
            Dict with new comment details or error dict
        """
        if not comment_id or len(comment_id) > 20:
            return {"error": "Comment ID must be 1-20 characters"}

        if not text or len(text) > 10000:
            return {"error": "Reply text must be 1-10000 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            comment = reddit.comment(id=comment_id)
            reply = comment.reply(text)

            return {
                "success": True,
                "comment_id": reply.id,
                "permalink": f"https://reddit.com{reply.permalink}",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to reply: {str(e)}"}

    @mcp.tool()
    def reddit_edit_comment(comment_id: str, new_text: str) -> dict:
        """
        Edit an existing comment.

        Use this to update or correct your comments.

        Args:
            comment_id: Reddit comment ID to edit
            new_text: New comment text (1-10000 characters)

        Returns:
            Dict with success status or error dict
        """
        if not comment_id or len(comment_id) > 20:
            return {"error": "Comment ID must be 1-20 characters"}

        if not new_text or len(new_text) > 10000:
            return {"error": "Comment text must be 1-10000 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            comment = reddit.comment(id=comment_id)
            comment.edit(new_text)

            return {
                "success": True,
                "comment_id": comment_id,
                "message": "Comment edited successfully",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to edit comment: {str(e)}"}

    @mcp.tool()
    def reddit_delete_comment(comment_id: str) -> dict:
        """
        Delete a comment.

        Use this to remove your comments.

        Args:
            comment_id: Reddit comment ID to delete

        Returns:
            Dict with success status or error dict
        """
        if not comment_id or len(comment_id) > 20:
            return {"error": "Comment ID must be 1-20 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            comment = reddit.comment(id=comment_id)
            comment.delete()

            return {
                "success": True,
                "comment_id": comment_id,
                "message": "Comment deleted successfully",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to delete comment: {str(e)}"}

    # ==================== User Engagement (3 functions) ====================

    @mcp.tool()
    def reddit_get_user_profile(username: str) -> dict:
        """
        Get a Reddit user's profile information.

        Use this to view public user data and statistics.

        Args:
            username: Reddit username (without u/ prefix)

        Returns:
            Dict with user profile or error dict
        """
        if not username or len(username) > 50:
            return {"error": "Username must be 1-50 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            redditor = reddit.redditor(username)
            return {
                "success": True,
                "user": _serialize_redditor(redditor),
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to get user profile: {str(e)}"}

    @mcp.tool()
    def reddit_upvote(item_id: str) -> dict:
        """
        Upvote a post or comment.

        Use this to upvote content you like.

        Args:
            item_id: Reddit post or comment ID

        Returns:
            Dict with success status or error dict
        """
        if not item_id or len(item_id) > 20:
            return {"error": "Item ID must be 1-20 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            # Try as submission first, then comment
            try:
                item = reddit.submission(id=item_id)
            except Exception:
                item = reddit.comment(id=item_id)

            item.upvote()

            return {
                "success": True,
                "item_id": item_id,
                "message": "Upvoted successfully",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to upvote: {str(e)}"}

    @mcp.tool()
    def reddit_downvote(item_id: str) -> dict:
        """
        Downvote a post or comment.

        Use this to downvote content you dislike.

        Args:
            item_id: Reddit post or comment ID

        Returns:
            Dict with success status or error dict
        """
        if not item_id or len(item_id) > 20:
            return {"error": "Item ID must be 1-20 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            # Try as submission first, then comment
            try:
                item = reddit.submission(id=item_id)
            except Exception:
                item = reddit.comment(id=item_id)

            item.downvote()

            return {
                "success": True,
                "item_id": item_id,
                "message": "Downvoted successfully",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to downvote: {str(e)}"}

    @mcp.tool()
    def reddit_save_post(post_id: str) -> dict:
        """
        Save a Reddit post.

        Use this to bookmark posts for later.

        Args:
            post_id: Reddit post ID to save

        Returns:
            Dict with success status or error dict
        """
        if not post_id or len(post_id) > 20:
            return {"error": "Post ID must be 1-20 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            submission = reddit.submission(id=post_id)
            submission.save()

            return {
                "success": True,
                "post_id": post_id,
                "message": "Post saved successfully",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to save post: {str(e)}"}

    # ==================== Moderation (3 functions - optional) ====================

    @mcp.tool()
    def reddit_remove_post(post_id: str, spam: bool = False) -> dict:
        """
        Remove a post (requires moderator permissions).

        Use this to moderate subreddit content.

        Args:
            post_id: Reddit post ID to remove
            spam: Mark as spam (True) or regular removal (False)

        Returns:
            Dict with success status or error dict
        """
        if not post_id or len(post_id) > 20:
            return {"error": "Post ID must be 1-20 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            submission = reddit.submission(id=post_id)
            submission.mod.remove(spam=spam)

            return {
                "success": True,
                "post_id": post_id,
                "message": f"Post {'marked as spam and ' if spam else ''}removed successfully",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error (check moderator permissions): {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to remove post: {str(e)}"}

    @mcp.tool()
    def reddit_approve_post(post_id: str) -> dict:
        """
        Approve a post (requires moderator permissions).

        Use this to approve posts from moderation queue.

        Args:
            post_id: Reddit post ID to approve

        Returns:
            Dict with success status or error dict
        """
        if not post_id or len(post_id) > 20:
            return {"error": "Post ID must be 1-20 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            submission = reddit.submission(id=post_id)
            submission.mod.approve()

            return {
                "success": True,
                "post_id": post_id,
                "message": "Post approved successfully",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error (check moderator permissions): {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to approve post: {str(e)}"}

    @mcp.tool()
    def reddit_ban_user(
        subreddit: str,
        username: str,
        duration: int = 0,
        reason: str = "",
        note: str = "",
    ) -> dict:
        """
        Ban a user from a subreddit (requires moderator permissions).

        Use this for subreddit moderation.

        Args:
            subreddit: Subreddit name
            username: Reddit username to ban
            duration: Ban duration in days (0 = permanent)
            reason: Ban reason shown to user
            note: Internal mod note

        Returns:
            Dict with success status or error dict
        """
        if not subreddit or len(subreddit) > 50:
            return {"error": "Subreddit name must be 1-50 characters"}

        if not username or len(username) > 50:
            return {"error": "Username must be 1-50 characters"}

        reddit = _get_reddit_client(credentials)
        if isinstance(reddit, dict):
            return reddit

        try:
            sub = reddit.subreddit(subreddit)
            sub.banned.add(
                username,
                duration=duration if duration > 0 else None,
                ban_reason=reason,
                note=note,
            )

            ban_type = "permanently" if duration == 0 else f"for {duration} days"
            return {
                "success": True,
                "username": username,
                "subreddit": subreddit,
                "message": f"User {username} banned {ban_type} from r/{subreddit}",
            }
        except PrawcoreException as e:
            return {"error": f"Reddit API error (check moderator permissions): {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to ban user: {str(e)}"}
