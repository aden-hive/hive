"""Twitter posting via Playwright with persistent session support."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .credentials import resolve_twitter_session_dir

TwitterConfig = Any


def _session_dir() -> Path:
    configured = resolve_twitter_session_dir(os.environ.get("TWITTER_CREDENTIAL_REF"))
    return Path(configured).expanduser()


def _session_marker() -> Path:
    return _session_dir() / ".logged_in"


def _is_logged_in() -> bool:
    return _session_marker().exists()


async def _post_thread_with_playwright(thread: dict) -> dict:
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    from playwright.async_api import async_playwright

    tweets = thread.get("thread") or thread.get("tweets") or []
    title = thread.get("article_title") or thread.get("title", "Untitled")

    if not tweets:
        return {"title": title, "posted": 0, "error": "No tweets in thread"}

    session_dir = _session_dir()
    session_marker = _session_marker()
    session_dir.mkdir(parents=True, exist_ok=True)
    first_run = not _is_logged_in()

    print(f"\n{'=' * 60}")
    print(f"Thread: {title[:55]}{'...' if len(title) > 55 else ''}")
    print(f"Tweets: {len(tweets)}")
    print("=" * 60)

    if first_run:
        print("\nFIRST RUN — Browser will open for manual login.")
        print("Log in to X/Twitter, then press Enter here to continue.\n")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=False,
            slow_mo=80,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            viewport={"width": 1280, "height": 800},
        )

        page = await context.new_page()

        if first_run:
            await page.goto("https://x.com/login", wait_until="domcontentloaded")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: input("   -> Log in to X in the browser, then press Enter here: "),
            )
            await page.goto("https://x.com/home", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            if "login" in page.url or "i/flow" in page.url:
                await context.close()
                return {
                    "title": title,
                    "posted": 0,
                    "error": "Login not detected. Please try again.",
                }
            session_marker.touch()
            print("Session saved — future runs will be fully automatic.\n")

        posted = 0
        first_tweet_url = None

        for i, tweet_text in enumerate(tweets):
            if isinstance(tweet_text, dict):
                tweet_text = tweet_text.get("text", "")
            tweet_text = tweet_text.strip()
            if not tweet_text:
                continue

            print(f"\n  Posting tweet {i + 1}/{len(tweets)}...")

            try:
                if i == 0:
                    await page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded")
                    await asyncio.sleep(1.5)

                    if "login" in page.url or "i/flow" in page.url:
                        session_marker.unlink(missing_ok=True)
                        await context.close()
                        return {
                            "title": title,
                            "posted": posted,
                            "error": "Session expired. Re-login and run again.",
                        }

                    textarea = page.locator(
                        "[data-testid='tweetTextarea_0'], "
                        "div[role='textbox'][data-testid='tweetTextarea_0'], "
                        "div.public-DraftEditor-content"
                    ).first
                    await textarea.wait_for(timeout=10000)
                    await textarea.click()
                    await asyncio.sleep(0.5)
                    await page.keyboard.type(tweet_text, delay=30)
                    await asyncio.sleep(0.8)

                    post_btn = page.locator(
                        "[data-testid='tweetButtonInline'], "
                        "[data-testid='tweetButton']"
                    ).first
                    await post_btn.wait_for(timeout=8000)
                    await post_btn.click()
                    await asyncio.sleep(2.5)

                    first_tweet_url = page.url
                    posted += 1
                    print("  Posted tweet 1")

                else:
                    if first_tweet_url and "status" in first_tweet_url:
                        await page.goto(first_tweet_url, wait_until="domcontentloaded")
                        await asyncio.sleep(1.5)

                        reply_btn = page.locator("[data-testid='reply']").first
                        await reply_btn.wait_for(timeout=8000)
                        await reply_btn.click()
                        await asyncio.sleep(1.0)
                    else:
                        await page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded")
                        await asyncio.sleep(1.5)

                    textarea = page.locator(
                        "div[data-testid='tweetTextarea_0'], "
                        "div[role='textbox']"
                    ).last
                    await textarea.wait_for(timeout=10000)
                    await textarea.click()
                    await asyncio.sleep(0.5)
                    await page.keyboard.type(tweet_text, delay=30)
                    await asyncio.sleep(0.8)

                    post_btn = page.locator(
                        "[data-testid='tweetButtonInline'], "
                        "[data-testid='tweetButton']"
                    ).first
                    await post_btn.wait_for(timeout=8000)
                    await post_btn.click()
                    await asyncio.sleep(2.5)

                    posted += 1
                    print(f"  Posted tweet {i + 1}")

            except PlaywrightTimeout as e:
                print(f"  Timeout on tweet {i + 1}: {e}")
            except Exception as e:
                print(f"  Error on tweet {i + 1}: {e}")

        await context.close()

    return {
        "title": title,
        "posted": posted,
        "total": len(tweets),
        "url": first_tweet_url,
    }


async def post_threads_impl(
    threads_json: str,
    config: TwitterConfig,
    credential_ref: str | None = None,
) -> str | dict[str, Any]:
    if credential_ref:
        os.environ["TWITTER_CREDENTIAL_REF"] = credential_ref

    try:
        threads = json.loads(threads_json)
    except (json.JSONDecodeError, TypeError) as e:
        return f"Invalid threads_json: {e!s}"

    if not isinstance(threads, list):
        return "threads_json must be a JSON array of thread objects."

    if not threads:
        return "No threads to post."

    results = []
    total_posted = 0

    for thread in threads:
        if not isinstance(thread, dict):
            continue
        result = await _post_thread_with_playwright(thread)
        results.append(result)
        total_posted += result.get("posted", 0)

    return {
        "success": True,
        "threads": results,
        "message": f"Posted {total_posted} tweets across {len(results)} threads",
    }


def register_twitter_tool(registry: Any, config: TwitterConfig) -> None:
    from framework.llm.provider import Tool

    tool = Tool(
        name="post_to_twitter",
        description="Post threads to Twitter/X using Playwright automation.",
        parameters={
            "type": "object",
            "properties": {
                "threads_json": {
                    "type": "string",
                    "description": "JSON string of the threads array.",
                },
                "twitter_credential_ref": {
                    "type": "string",
                    "description": "Optional credential ref in {name}/{alias} format.",
                },
            },
            "required": ["threads_json"],
        },
    )
    registry.register(
        "post_to_twitter",
        tool,
        lambda inputs: post_threads_impl(
            inputs["threads_json"],
            config,
            inputs.get("twitter_credential_ref"),
        ),
    )
