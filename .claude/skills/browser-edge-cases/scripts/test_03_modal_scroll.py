#!/usr/bin/env python
"""
Test #3: Modal/Dialog Scroll Container

Symptom: Scroll scrolls background page, not modal content
Root Cause: Modal has its own scroll container with overflow: scroll
Fix: Find visible modal container (highest z-index scrollable), scroll that
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

BRIDGE_PORT = 9229
CONTEXT_NAME = "modal-scroll-test"

# Test site with modal - using a demo site
MODAL_DEMO_URL = "https://www.w3schools.com/howto/howto_css_modals.asp"


async def test_modal_scroll():
    """Test that scroll targets modal content, not background."""
    print("=" * 70)
    print("TEST #3: Modal/Dialog Scroll Container")
    print("=" * 70)

    bridge = BeelineBridge()

    try:
        await bridge.start()

        for i in range(10):
            await asyncio.sleep(1)
            if bridge.is_connected:
                print("✓ Extension connected!")
                break
        else:
            print("✗ Extension not connected")
            return

        context = await bridge.create_context(CONTEXT_NAME)
        tab_id = context.get("tabId")
        group_id = context.get("groupId")
        print(f"✓ Created tab: {tab_id}")

        # Navigate to modal demo
        print("\n--- Navigating to modal demo ---")
        await bridge.navigate(tab_id, MODAL_DEMO_URL, wait_until="load")
        print("✓ Page loaded")

        # Take screenshot before
        screenshot_before = await bridge.screenshot(tab_id)
        print(f"Screenshot before: {len(screenshot_before.get('data', ''))} bytes")

        # Click button to open modal
        print("\n--- Opening modal ---")
        # Find and click the "Open Modal" button
        result = await bridge.click(tab_id, '.ws-btn', timeout_ms=5000)
        print(f"Click result: {result}")

        await asyncio.sleep(1)

        # Take screenshot with modal open
        screenshot_modal = await bridge.screenshot(tab_id)
        print(f"Screenshot modal open: {len(screenshot_modal.get('data', ''))} bytes")

        # Try to scroll within modal
        print("\n--- Scrolling modal content ---")
        result = await bridge.scroll(tab_id, "down", 100)
        print(f"Scroll result: {result}")

        await asyncio.sleep(0.5)

        # Take screenshot after scroll
        screenshot_after = await bridge.screenshot(tab_id)
        print(f"Screenshot after scroll: {len(screenshot_after.get('data', ''))} bytes")

        # Check if modal content scrolled (not background)
        # This is a visual check - we can verify by comparing screenshots
        print("\n--- Results ---")
        print(f"Modal scroll test completed. Method used: {result.get('method', 'unknown')}")
        print("Visual verification needed: Check if modal content scrolled vs background")

        await bridge.destroy_context(group_id)
        print("\n✓ Context destroyed")

    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(test_modal_scroll())
