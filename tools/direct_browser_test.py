#!/usr/bin/env python
"""
Direct browser control test - uses the bridge directly.
Run: uv run python direct_browser_test.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gcu.browser.bridge import BeelineBridge


async def main():
    print("=" * 60)
    print("DIRECT BROWSER TEST")
    print("=" * 60)

    bridge = BeelineBridge()
    await bridge.start()

    # Wait for connection
    print("\nWaiting for extension connection...")
    for i in range(10):
        await asyncio.sleep(1)
        if bridge.is_connected:
            print("✓ Extension connected!")
            break
        print(f"  Waiting... ({i+1}/10)")
    else:
        print("✗ Extension not connected")
        await bridge.stop()
        return

    # Create a context (tab group)
    print("\n--- Creating browser context ---")
    ctx = await bridge.create_context("test-session")
    tab_id = ctx.get("tabId")
    group_id = ctx.get("groupId")
    print(f"✓ Context created: tabId={tab_id}, groupId={group_id}")

    # Navigate
    print("\n--- Navigating to example.com ---")
    result = await bridge.navigate(tab_id, "https://example.com", wait_until="load")
    print(f"✓ Navigated: {result}")

    await asyncio.sleep(1)

    # Get snapshot
    print("\n--- Getting page snapshot ---")
    snapshot = await bridge.snapshot(tab_id)
    tree = snapshot.get("tree", "")
    print(f"✓ Snapshot ({len(tree)} chars):")
    print(tree[:500] + "..." if len(tree) > 500 else tree)

    # Click the link
    print("\n--- Clicking link ---")
    result = await bridge.click(tab_id, "a", timeout_ms=5000)
    print(f"Click result: {result}")

    if result.get("ok"):
        print("✓ Click succeeded!")
        await asyncio.sleep(2)
        # Go back
        await bridge.go_back(tab_id)
        await asyncio.sleep(1)

    # Test type
    print("\n--- Testing type on Google ---")
    await bridge.navigate(tab_id, "https://www.google.com", wait_until="load")
    await asyncio.sleep(2)

    result = await bridge.type_text(tab_id, "textarea[name='q']", "hello world")
    print(f"Type result: {result}")

    if result.get("ok"):
        print("✓ Type succeeded!")

    # Cleanup
    print("\n--- Cleaning up ---")
    await bridge.destroy_context(group_id)
    print("✓ Context destroyed")

    await bridge.stop()
    print("✓ Bridge stopped")


if __name__ == "__main__":
    asyncio.run(main())
