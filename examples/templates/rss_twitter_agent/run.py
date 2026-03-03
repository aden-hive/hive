#!/usr/bin/env python
"""RSS-to-Twitter interactive workflow runner (legacy behavior preserved)."""

from __future__ import annotations

import asyncio
import json
import os

from .fetch import _generate_thread_for_article, fetch_rss, post_to_twitter, summarize_articles


async def run_interactive(
    feed_url: str = "https://news.ycombinator.com/rss",
    max_articles: int = 3,
    twitter_credential_ref: str | None = None,
) -> dict:
    """Run fetch -> summarize -> per-thread y/n -> post (Playwright)."""
    if twitter_credential_ref:
        os.environ["TWITTER_CREDENTIAL_REF"] = twitter_credential_ref

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

    for i, summary in enumerate(summaries):
        article_title = summary.get("title", "Untitled")

        print(f"\n{'=' * 60}")
        print(
            f"Article {i + 1}/{len(summaries)}: "
            f"{article_title[:50]}{'...' if len(article_title) > 50 else ''}"
        )
        print("=" * 60)

        print("  Generating thread...")
        thread = _generate_thread_for_article(summary)
        if not thread:
            print("  Could not generate thread, skipping.")
            continue

        tweets = thread.get("tweets", [])

        print()
        for j, tweet in enumerate(tweets, 1):
            tweet_text = tweet.get("text", tweet) if isinstance(tweet, dict) else tweet
            prefix = "🧵" if j == 1 else f"{j}/"
            print(f"  {prefix} {tweet_text}")
            if len(tweet_text) > 280:
                print(f"     WARNING: {len(tweet_text)} chars (over 280)")

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

        print("  Posting...\n")
        result_json = await post_to_twitter(json.dumps([thread]))
        result = json.loads(result_json)
        results.append(result)
        if isinstance(result, dict) and result.get("success"):
            total_posted += 1
            print("  Posted")
        else:
            err = result.get("error", "Unknown error") if isinstance(result, dict) else result
            print(f"  Error: {err}")

        if i < len(summaries) - 1:
            try:
                input("\nPress Enter for next thread...")
            except EOFError:
                pass

    print(f"\n{'=' * 60}")
    print(f"Done! Posted {total_posted}/{reviewed} reviewed threads.")
    print("=" * 60)

    return {
        "success": True,
        "feed_url": feed_url,
        "articles_fetched": len(articles),
        "threads_reviewed": reviewed,
        "threads_posted": total_posted,
        "post_results": results,
    }


if __name__ == "__main__":
    output = asyncio.run(run_interactive())
    print(json.dumps(output, indent=2, default=str))
