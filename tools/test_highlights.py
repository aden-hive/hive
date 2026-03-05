"""
Manual test script for browser highlight animations.

Launches a visible browser, goes to Google, searches "aden hive",
and clicks the first result — with highlight animations on each action.

Usage:
    python tools/test_highlights.py
"""

import asyncio
import sys

# Ensure the package is importable
sys.path.insert(0, "tools/src")

from gcu.browser.highlight import highlight_coordinate, highlight_element
from gcu.browser.session import BrowserSession


async def step(label: str) -> None:
    print(f"\n→ {label}")


async def main() -> None:
    session = BrowserSession(profile="highlight-test")

    try:
        # 1. Start browser (visible)
        await step("Starting browser (headless=False)")
        result = await session.start(headless=False, persistent=False)
        print(f"  {result}")

        # 2. Open a tab and navigate to Google
        await step("Navigating to google.com")
        result = await session.open_tab("https://www.google.com")
        print(f"  {result}")

        page = session.get_active_page()
        assert page, "No active page"

        # Small pause so you can see the page load
        await asyncio.sleep(1)

        # 3. Highlight + fill the search bar
        selector = 'textarea[name="q"]'
        await step(f"Highlighting search bar: {selector}")
        await highlight_element(page, selector)

        await step("Filling search bar with 'aden hive'")
        await page.fill(selector, "aden hive")
        await asyncio.sleep(0.5)

        # 4. Press Enter to search
        await step("Pressing Enter")
        await page.press(selector, "Enter")
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        await asyncio.sleep(1)

        # 5. Highlight + click the first search result link
        first_result = "#search a h3"
        await step(f"Highlighting first result: {first_result}")
        await highlight_element(page, first_result)

        await step("Clicking first result")
        await page.click(first_result, timeout=10000)
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        await asyncio.sleep(1)

        # 6. Bonus: test coordinate highlight at center of viewport
        await step("Testing coordinate highlight at viewport center (960, 540)")
        await highlight_coordinate(page, 960, 540)

        print("\n✓ All steps complete. Browser stays open for 5 seconds...")
        await asyncio.sleep(5)

    finally:
        await step("Stopping browser")
        await session.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
