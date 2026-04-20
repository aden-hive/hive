#!/usr/bin/env python
"""RSS-to-Twitter interactive workflow runner (legacy behavior preserved)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .fetch import (
    _generate_thread_for_article,
    fetch_rss,
    post_to_twitter,
    summarize_articles,
)


def _render_thread_preview(thread: dict[str, Any], index: int, total: int) -> None:
    """Show the generated thread exactly as the legacy interactive flow did."""
    article_title = thread.get("title", "Untitled")
    tweets = thread.get("tweets", [])

    print(f"\n{'=' * 60}")
    print(
        f"Article {index}/{total}: "
        f"{article_title[:50]}{'...' if len(article_title) > 50 else ''}"
    )
    print("=" * 60)

    print()
    for tweet_index, tweet in enumerate(tweets, 1):
        tweet_text = tweet.get("text", tweet) if isinstance(tweet, dict) else tweet
        prefix = "🧵" if tweet_index == 1 else f"{tweet_index}/"
        print(f"  {prefix} {tweet_text}")
        if len(tweet_text) > 280:
            print(f"     WARNING: {len(tweet_text)} chars (over 280)")


async def run_workflow(
    feed_url: str = "https://news.ycombinator.com/rss",
    max_articles: int = 3,
    twitter_credential_ref: str | None = None,
) -> dict[str, Any]:
    """Run the original sequential RSS -> summarize -> approve -> post flow."""
    print("=" * 60)
    print("RSS-to-Twitter Agent")
    print("=" * 60 + "\n")

    print("Generates tweets from RSS feeds and posts automatically.\n")
    print("Uses Playwright for browser automation.\n")

    print("1. Fetching RSS...")
    articles_json = fetch_rss(feed_url=feed_url, max_articles=max_articles)
    articles = json.loads(articles_json)
    print(f"   Fetched {len(articles)} articles\n")

    print("2. Summarizing articles...")
    summaries_json = summarize_articles(articles_json)
    summaries = json.loads(summaries_json)
    print(f"   Summarized {len(summaries)} articles\n")

    total_posted = 0
    reviewed = 0
    results = []
    generated_threads = []
    approved_threads = []

    for i, summary in enumerate(summaries):
        print("  Generating thread...")
        thread = _generate_thread_for_article(summary)
        if not thread:
            print("  Could not generate thread, skipping.")
            continue
        generated_threads.append(thread)

        _render_thread_preview(thread, i + 1, len(summaries))
        print()
        try:
            response = input("Post this thread? (y/n/q): ").strip().lower()
        except EOFError:
            response = "n"

        reviewed += 1
        if response == "q":
            print("  Quitting...")
            break
        if response != "y":
            print("  Skipped")
            continue

        approved_threads.append(thread)
        print("  Posting...\n")
        result_json = await post_to_twitter(
            json.dumps([thread]), twitter_credential_ref=twitter_credential_ref
        )
        result = json.loads(result_json)
        results.append(result)
        if isinstance(result, dict) and result.get("success"):
            total_posted += 1
            print("  Posted")
        else:
            err = (
                result.get("error", "Unknown error")
                if isinstance(result, dict)
                else result
            )
            print(f"  Error: {err}")

        if i < len(summaries) - 1:
            try:
                input("\nPress Enter for next thread...")
            except EOFError:
                pass

    print(f"\n{'=' * 60}")
    print(f"Done! Posted {total_posted}/{reviewed} reviewed threads.")
    print("=" * 60)

    workflow_success = all(
        isinstance(result, dict) and result.get("success") for result in results
    )
    workflow_error = None
    if not workflow_success and results:
        errors = [
            result.get("error") or result.get("message", "Unknown posting error")
            for result in results
            if isinstance(result, dict) and not result.get("success")
        ]
        workflow_error = (
            "; ".join(error for error in errors if error) or "Posting failed"
        )

    return {
        "success": workflow_success if results else True,
        "error": workflow_error,
        "feed_url": feed_url,
        "articles_json": articles_json,
        "processed_json": summaries_json,
        "threads_json": json.dumps(generated_threads),
        "approved_json": json.dumps(approved_threads),
        "results_json": json.dumps(results),
        "articles_fetched": len(articles),
        "threads_reviewed": reviewed,
        "threads_posted": total_posted,
        "post_results": results,
    }


async def run_interactive(
    feed_url: str = "https://news.ycombinator.com/rss",
    max_articles: int = 3,
    twitter_credential_ref: str | None = None,
) -> dict[str, Any]:
    """Run fetch -> summarize -> per-thread y/n/q -> post (Playwright)."""
    workflow = await run_workflow(
        feed_url=feed_url,
        max_articles=max_articles,
        twitter_credential_ref=twitter_credential_ref,
    )
    return {
        "success": workflow["success"],
        "feed_url": workflow["feed_url"],
        "articles_fetched": workflow["articles_fetched"],
        "threads_reviewed": workflow["threads_reviewed"],
        "threads_posted": workflow["threads_posted"],
        "post_results": workflow["post_results"],
    }


if __name__ == "__main__":
    output = asyncio.run(run_interactive())
    print(json.dumps(output, indent=2, default=str))
