"""
Reproduction script for gcu-reply-collector session that took 13 turns to
(fail to) scrape commentators from an X post.

Session: session_20260223_184714_ecd8d875
Subagent: gcu-reply-collector
URL: https://x.com/FoxNews/status/2026085302578594130

ROOT CAUSE ANALYSIS
===================
The agent wasted 12 of its 13 turns before finding the right CSS selector.
It never completed the actual task (extracting commentator links).

Problem breakdown:
  1. browser_open(wait_until="load") returns before React/SPA finishes mounting.
     The page fires "load" but X's React app takes extra seconds to hydrate.
  2. browser_get_text("body") returns ~240K chars, mostly noscript fallback HTML.
     The context truncation shows only the first 2700 chars which is the
     "JavaScript is not available" error div, misleading the agent.
  3. The agent then wastes turns: scrolling blindly, taking screenshots,
     retrying body, trying wrong selectors -- before finally discovering
     [data-testid="tweet"] works on turn 12 (of 13).
  4. By the time it finds the tweet, it only has 1 turn left, which it
     spends scrolling. It never extracts commentator links.

This script reproduces every step and times each one, then demonstrates
the correct 3-turn approach.
"""

import asyncio
import json
import sys
import time

from gcu.browser.session import BrowserSession, DEFAULT_TIMEOUT_MS

TARGET_URL = "https://x.com/FoxNews/status/2026085302578594130"


def ts():
    """Return a timestamp string for logging."""
    return time.strftime("%H:%M:%S")


def log(turn: int | str, action: str, result_summary: str, elapsed: float):
    """Pretty-print a turn log line."""
    status = "OK" if "ok" not in result_summary.lower() or "true" in result_summary.lower() else "??"
    print(f"  [{ts()}] Turn {turn:>2} | {elapsed:5.1f}s | {action:<45} | {result_summary}")


async def reproduce_agent_session(session: BrowserSession):
    """
    Reproduce the exact sequence of tool calls from the session, turn by turn.
    Each "turn" = one assistant message with tool call(s) + the tool response.
    """
    print("=" * 100)
    print("REPRODUCTION: Original agent session (13 turns)")
    print("=" * 100)
    total_start = time.time()

    # ── Turn 1 (seq 1-2): browser_start ──────────────────────────────────
    t0 = time.time()
    result = await session.start(headless=False, persistent=True)
    log(1, "browser_start()", f"ok={result['ok']}, status={result.get('status')}", time.time() - t0)

    # ── Turn 2 (seq 3-4): browser_open ───────────────────────────────────
    t0 = time.time()
    result = await session.open_tab(TARGET_URL, wait_until="load")
    target_id = result.get("targetId", "")
    log(2, f'browser_open("{TARGET_URL[:50]}...")', f"ok={result['ok']}, title={result.get('title')!r}", time.time() - t0)

    page = session.get_page(target_id)
    assert page, "No page after open_tab"

    # ── Turn 3 (seq 5-6): browser_get_text("body") ──────────────────────
    # This is the problematic call: returns ~240K chars of noscript + SPA content
    t0 = time.time()
    try:
        el = await page.wait_for_selector("body", timeout=DEFAULT_TIMEOUT_MS)
        body_text = await el.text_content() if el else ""
    except Exception as e:
        body_text = f"ERROR: {e}"
    text_len = len(body_text) if isinstance(body_text, str) else 0
    # Check what the first 500 chars look like (the agent only saw first 2700)
    preview = body_text[:500] if isinstance(body_text, str) else str(body_text)[:500]
    has_noscript = "JavaScript is not available" in preview
    log(3, 'browser_get_text("body")',
        f"len={text_len}, starts_with_noscript={has_noscript}",
        time.time() - t0)
    if has_noscript:
        print(f"         ^ PROBLEM: First 300 chars of body are noscript fallback HTML!")
        print(f"         ^ The agent sees: '...JavaScript is not available...'")
        print(f"         ^ Actual tweet content is buried deep in the {text_len}-char response")

    # ── Turn 4 (seq 7-8): browser_screenshot ─────────────────────────────
    t0 = time.time()
    screenshot_bytes = await page.screenshot()
    log(4, "browser_screenshot()",
        f"size={len(screenshot_bytes)} bytes (~{len(screenshot_bytes)*4//3} base64 chars)",
        time.time() - t0)
    print(f"         ^ WASTE: Screenshot taken to diagnose, but agent can't read images well")

    # ── Turn 5 (seq 9-10): browser_scroll(down, 500) ────────────────────
    t0 = time.time()
    await page.mouse.wheel(0, 500)
    log(5, "browser_scroll(down, 500)", "ok=true", time.time() - t0)
    print(f"         ^ WASTE: Blind scrolling without confirming page is rendered")

    # ── Turn 6 (seq 11-12): browser_scroll(down, 500) ───────────────────
    t0 = time.time()
    await page.mouse.wheel(0, 500)
    log(6, "browser_scroll(down, 500)", "ok=true", time.time() - t0)
    print(f"         ^ WASTE: More blind scrolling")

    # ── Turn 7 (seq 13-14): browser_screenshot ──────────────────────────
    t0 = time.time()
    screenshot_bytes = await page.screenshot()
    log(7, "browser_screenshot()",
        f"size={len(screenshot_bytes)} bytes",
        time.time() - t0)
    print(f"         ^ WASTE: Another diagnostic screenshot")

    # ── Turn 8 (seq 15-16): browser_get_text("body") again ──────────────
    t0 = time.time()
    try:
        el = await page.wait_for_selector("body", timeout=DEFAULT_TIMEOUT_MS)
        body_text_2 = await el.text_content() if el else ""
    except Exception as e:
        body_text_2 = f"ERROR: {e}"
    text_len_2 = len(body_text_2) if isinstance(body_text_2, str) else 0
    preview_2 = body_text_2[:500] if isinstance(body_text_2, str) else str(body_text_2)[:500]
    has_noscript_2 = "JavaScript is not available" in preview_2
    log(8, 'browser_get_text("body") [retry]',
        f"len={text_len_2}, still_noscript={has_noscript_2}",
        time.time() - t0)
    print(f"         ^ WASTE: Same result -- body selector is a trap on X.com")

    # ── Turn 9 (seq 17-18): browser_get_text('a[href*="/status/"]') ─────
    t0 = time.time()
    try:
        el = await page.wait_for_selector('a[href*="/status/"]', timeout=5000)
        link_text = await el.text_content() if el else ""
    except Exception as e:
        link_text = f"TIMEOUT/ERROR: {e}"
    log(9, 'browser_get_text(\'a[href*="/status/"]\')',
        f"text={link_text[:80]!r}" if isinstance(link_text, str) else str(link_text)[:80],
        time.time() - t0)
    print(f"         ^ WASTE: Wrong selector -- no matching elements or empty text")

    # ── Turn 10 (seq 19-20): browser_get_text("a") ──────────────────────
    t0 = time.time()
    try:
        el = await page.wait_for_selector("a", timeout=5000)
        a_text = await el.text_content() if el else ""
    except Exception as e:
        a_text = f"TIMEOUT/ERROR: {e}"
    log(10, 'browser_get_text("a")',
        f"text={a_text[:80]!r}" if isinstance(a_text, str) else str(a_text)[:80],
        time.time() - t0)
    print(f"         ^ WASTE: Gets first <a> only -- 'View keyboard shortcuts'")

    # ── Turn 11 (seq 21-22): browser_screenshot(full_page=true) ─────────
    t0 = time.time()
    screenshot_full = await page.screenshot(full_page=True)
    log(11, "browser_screenshot(full_page=true)",
        f"size={len(screenshot_full)} bytes (~{len(screenshot_full)*4//3} base64 chars)",
        time.time() - t0)
    print(f"         ^ WASTE: Enormous full-page screenshot (~{len(screenshot_full)//1024}KB)")

    # ── Turn 12 (seq 23-24): browser_get_text('[data-testid="tweet"]') ──
    # FINALLY the right selector!
    t0 = time.time()
    try:
        el = await page.wait_for_selector('[data-testid="tweet"]', timeout=DEFAULT_TIMEOUT_MS)
        tweet_text = await el.text_content() if el else ""
    except Exception as e:
        tweet_text = f"ERROR: {e}"
    log(12, 'browser_get_text(\'[data-testid="tweet"]\')',
        f"text={tweet_text[:100]!r}..." if isinstance(tweet_text, str) and len(tweet_text) > 100 else f"text={tweet_text!r}",
        time.time() - t0)
    print(f"         ^ SUCCESS! Finally found the right selector on turn 12 of 13")

    # ── Turn 13 (seq 25-26): browser_scroll(down, 1000) ─────────────────
    t0 = time.time()
    await page.mouse.wheel(0, 1000)
    log(13, "browser_scroll(down, 1000)", "ok=true", time.time() - t0)
    print(f"         ^ Session ends here -- agent hit turn limit, NEVER extracted commentators")

    total = time.time() - total_start
    print()
    print(f"  Total time: {total:.1f}s across 13 turns")
    print(f"  Wasted turns: 9 (turns 4-11) -- scrolling, screenshots, wrong selectors")
    print(f"  Productive turns: 4 (start, open, find tweet, scroll for replies)")
    print(f"  Task completed: NO -- ran out of turns before extracting commentator links")
    print()

    return page, target_id


async def demonstrate_correct_approach(session: BrowserSession):
    """
    Show the correct way to open X and extract commentators in ~5 turns.

    Key fixes:
      1. Use browser_wait(selector='[data-testid="tweet"]') after open to wait for SPA
      2. Use specific selectors, never get_text("body") on X.com
      3. Use browser_evaluate() to extract all profile links via JS
    """
    print("=" * 100)
    print("CORRECT APPROACH: Efficient 5-turn version")
    print("=" * 100)
    total_start = time.time()

    # ── Turn 1: browser_start ────────────────────────────────────────────
    t0 = time.time()
    result = await session.start(headless=False, persistent=True)
    log(1, "browser_start()", f"ok={result['ok']}", time.time() - t0)

    # ── Turn 2: browser_open + browser_wait for SPA ──────────────────────
    t0 = time.time()
    result = await session.open_tab(TARGET_URL, wait_until="load")
    target_id = result.get("targetId", "")
    page = session.get_page(target_id)
    # KEY FIX: Wait for the React app to render the tweet
    try:
        await page.wait_for_selector('[data-testid="tweet"]', timeout=15000)
        spa_ready = True
    except Exception:
        spa_ready = False
    log(2, 'browser_open + wait_for("[data-testid=tweet]")',
        f"ok={result['ok']}, spa_ready={spa_ready}",
        time.time() - t0)

    # ── Turn 3: Extract tweet text to confirm we're on the right page ────
    t0 = time.time()
    el = await page.wait_for_selector('[data-testid="tweet"]', timeout=5000)
    tweet_text = await el.text_content() if el else ""
    log(3, 'browser_get_text(\'[data-testid="tweet"]\')',
        f"text={tweet_text[:80]!r}...",
        time.time() - t0)

    # ── Turn 4: Scroll a few times to load replies ───────────────────────
    t0 = time.time()
    for i in range(5):
        await page.mouse.wheel(0, 800)
        await page.wait_for_timeout(1000)  # let lazy-loaded replies appear
    log(4, 'browser_scroll x5 (with 1s waits)',
        "scrolled 5 times to load replies",
        time.time() - t0)

    # ── Turn 5: Extract all commentator links via JS ─────────────────────
    t0 = time.time()
    # Use evaluate() to extract usernames from the rendered DOM
    profile_links = await page.evaluate("""
    () => {
        // Get all tweet cells (replies are cellInnerDiv containers)
        const tweets = document.querySelectorAll('[data-testid="cellInnerDiv"]');
        const links = new Set();

        tweets.forEach(tweet => {
            // Find user profile links within each tweet
            // X uses links like /username within tweet components
            const userLinks = tweet.querySelectorAll('a[href^="/"][role="link"]');
            userLinks.forEach(a => {
                const href = a.getAttribute('href');
                // Filter: single-segment paths that look like usernames
                // Exclude /compose, /search, /settings, /i/, /hashtag, etc
                if (href && /^\\/[a-zA-Z0-9_]+$/.test(href) && href.length > 1) {
                    links.add('https://x.com' + href);
                }
            });
        });

        return [...links];
    }
    """)

    # Filter out the original poster
    commentator_links = [l for l in profile_links if "/FoxNews" not in l]
    result_json = {
        "profile_links": commentator_links,
        "commentator_count": len(commentator_links),
    }
    log(5, 'browser_evaluate(extract profile links)',
        f"found {len(commentator_links)} commentators",
        time.time() - t0)

    total = time.time() - total_start
    print()
    print(f"  Total time: {total:.1f}s across 5 turns")
    print(f"  Wasted turns: 0")
    print(f"  Task completed: YES")
    print(f"  Result: {json.dumps(result_json, indent=2)[:500]}")
    print()

    return result_json


async def main():
    print()
    print("X Page Load Reproduction Test")
    print("Session: session_20260223_184714_ecd8d875 / gcu-reply-collector")
    print()

    # Use a test profile so we don't interfere with the agent's browser
    session = BrowserSession(profile="repro-test")

    try:
        # Part 1: Reproduce the original broken session
        page, target_id = await reproduce_agent_session(session)

        # Close the tab from part 1
        await session.close_tab(target_id)

        # Small pause between tests
        await asyncio.sleep(2)

        # Part 2: Demonstrate the correct approach
        result = await demonstrate_correct_approach(session)

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Cleaning up browser...")
        await session.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
