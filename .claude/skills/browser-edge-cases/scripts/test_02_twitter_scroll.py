#!/usr/bin/env python
"""
Test #2: Twitter/X Lazy Loading Scroll

Symptom: Infinite scroll doesn't load new content
Root Cause: Lazy loading requires content to be visible before loading more
Fix: Add wait_for_selector between scroll calls
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

BRIDGE_PORT = 9229
CONTEXT_NAME = "twitter-scroll-test"


async def test_twitter_lazy_scroll():
    """Test that repeated scrolls with waits load new content."""
    print("=" * 70)
    print("TEST #2: Twitter/X Lazy Loading Scroll")
    print("=" * 70)

    bridge = BeelineBridge()

    try:
        await bridge.start()

        for i in range(10):
            await asyncio.sleep(1)
            if bridge.is_connected:
                print("✓ Extension connected!")
                break
            print(f"Waiting for extension... ({i+1}/10)")
        else:
            print("✗ Extension not connected")
            return

        context = await bridge.create_context(CONTEXT_NAME)
        tab_id = context.get("tabId")
        group_id = context.get("groupId")
        print(f"✓ Created tab: {tab_id}")

        # Navigate to Twitter/X
        print("\n--- Navigating to X.com ---")
        await bridge.navigate(tab_id, "https://x.com", wait_until="networkidle", timeout_ms=30000)
        print("✓ Page loaded")

        # Wait for tweets to appear
        print("\n--- Waiting for tweets ---")
        await bridge.wait_for_selector(tab_id, '[data-testid="tweet"]', timeout_ms=10000)

        # Count initial tweets
        initial_count = await bridge.evaluate(
            tab_id,
            '(function() { return document.querySelectorAll(\'[data-testid="tweet"]\').length; })()'
        )
        print(f"Initial tweet count: {initial_count.get('result', 0)}")

        # Take screenshot of initial state
        screenshot = await bridge.screenshot(tab_id)
        print(f"Screenshot: {len(screenshot.get('data', ''))} bytes")

        # Scroll multiple times with waits
        print("\n--- Scrolling with waits ---")
        for i in range(3):
            result = await bridge.scroll(tab_id, "down", 500)
            print(f"  Scroll {i+1}: {result.get('method', 'unknown')} method")

            # Wait for new content to load
            await asyncio.sleep(2)

            # Count tweets after scroll
            count_result = await bridge.evaluate(
                tab_id,
                '(function() { return document.querySelectorAll(\'[data-testid="tweet"]\').length; })()'
            )
            count = count_result.get('result', 0)
            print(f"  Tweet count after scroll: {count}")

        # Final count
        final_count = await bridge.evaluate(
            tab_id,
            '(function() { return document.querySelectorAll(\'[data-testid="tweet"]\').length; })()'
        )
        final = final_count.get('result', 0)
        initial = initial_count.get('result', 0)

        print(f"\n--- Results ---")
        print(f"Initial tweets: {initial}")
        print(f"Final tweets: {final}")

        if final > initial:
            print(f"✓ PASS: Loaded {final - initial} new tweets")
        else:
            print("✗ FAIL: No new tweets loaded (may need login)")

        await bridge.destroy_context(group_id)
        print("\n✓ Context destroyed")

    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(test_twitter_lazy_scroll())
