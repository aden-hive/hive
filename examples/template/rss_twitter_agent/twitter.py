"""Twitter/X posting for RSS-to-Twitter Agent (draft vs live mode)."""

from __future__ import annotations

import json
from typing import Any

from framework.llm.provider import Tool

# Type for config that has twitter_post_mode and credential fields
TwitterConfig = Any


def get_twitter_config(config: TwitterConfig) -> dict[str, Any]:
    """Extract Twitter post mode and credentials from RuntimeConfig."""
    return {
        "post_mode": getattr(config, "twitter_post_mode", "draft") or "draft",
        "bearer_token": getattr(config, "twitter_bearer_token", None),
        "api_key": getattr(config, "twitter_api_key", None),
        "api_secret": getattr(config, "twitter_api_secret", None),
        "access_token": getattr(config, "twitter_access_token", None),
        "access_secret": getattr(config, "twitter_access_secret", None),
    }


def _has_live_credentials(c: dict[str, Any]) -> bool:
    """Return True if OAuth 1.0a credentials are present for posting."""
    return bool(
        c.get("api_key")
        and c.get("api_secret")
        and c.get("access_token")
        and c.get("access_secret")
    )


def post_threads_impl(threads_json: str, config: TwitterConfig) -> str | dict[str, Any]:
    """
    Post threads to Twitter/X or return draft/fallback message.

    In draft mode or when live credentials are missing, returns a message.
    In live mode with credentials, posts each thread via tweepy (OAuth 1.0a) and returns a summary.
    """
    c = get_twitter_config(config)
    mode = c["post_mode"]

    if mode != "live":
        return "Draft mode: threads are ready for review. No post to Twitter/X was made."

    if not _has_live_credentials(c):
        return (
            "Live mode was requested but Twitter credentials are missing. "
            "Set TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, and "
            "TWITTER_ACCESS_SECRET (see https://developer.twitter.com). "
            "Falling back to draft — no post was made."
        )

    try:
        threads = json.loads(threads_json)
    except (json.JSONDecodeError, TypeError) as e:
        return f"Invalid threads_json: {e!s}"

    if not isinstance(threads, list):
        return "threads_json must be a JSON array of thread objects."

    import tweepy

    client = tweepy.Client(
        consumer_key=c["api_key"],
        consumer_secret=c["api_secret"],
        access_token=c["access_token"],
        access_token_secret=c["access_secret"],
    )

    results: list[dict[str, Any]] = []
    for item in threads:
        if not isinstance(item, dict):
            continue
        thread_tweets = item.get("thread") or item.get("tweets") or []
        if not thread_tweets:
            continue
        tweet_ids: list[str] = []
        in_reply_to: str | None = None
        for text in thread_tweets:
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                resp = client.create_tweet(
                    text=text.strip(),
                    in_reply_to_tweet_id=in_reply_to,
                    user_auth=True,
                )
            except tweepy.TweepyException as e:
                results.append(
                    {
                        "article_title": item.get("article_title", "?"),
                        "error": str(e),
                        "tweet_ids": tweet_ids,
                    }
                )
                break
            data = getattr(resp, "data", None) if resp else None
            tid_val = data.get("id") if isinstance(data, dict) else getattr(data, "id", None)
            if tid_val is not None:
                tid = str(tid_val)
                tweet_ids.append(tid)
                in_reply_to = tid
        else:
            results.append(
                {
                    "article_title": item.get("article_title", "?"),
                    "tweet_ids": tweet_ids,
                    "url": f"https://twitter.com/i/status/{tweet_ids[0]}" if tweet_ids else None,
                }
            )

    return {"posted": True, "threads": results}


def register_twitter_tool(
    registry: Any,
    config: TwitterConfig,
) -> None:
    """Register the post_to_twitter tool with the given ToolRegistry."""

    tool = Tool(
        name="post_to_twitter",
        description=(
            "Post the approved threads to Twitter/X in live mode, or confirm in draft mode. "
            "Call with the same threads_json string you passed to set_output. "
            "In draft mode or if credentials are missing, no post is made and a message is returned."
        ),
        parameters={
            "type": "object",
            "properties": {
                "threads_json": {
                    "type": "string",
                    "description": "JSON string of the threads array (article_title, source, thread, tweet_count).",
                },
            },
            "required": ["threads_json"],
        },
    )
    registry.register(
        "post_to_twitter",
        tool,
        lambda inputs: post_threads_impl(inputs["threads_json"], config),
    )
