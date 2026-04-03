#!/usr/bin/env python
"""
Debug browser click - specifically tests the Input.enable domain issue.

Run: uv run python manual_click_debug.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gcu.browser.bridge import BeelineBridge


async def main():
    print("=" * 60)
    print("BROWSER CLICK DEBUG")
    print("=" * 60)
    print("\nThis tests the click functionality and CDP domain handling.\n")

    bridge = BeelineBridge()

    try:
        print("Starting bridge...")
        await bridge.start()

        for i in range(5):
            await asyncio.sleep(1)
            if bridge.is_connected:
                print("✓ Extension connected!")
                break
            print(f"Waiting for extension... ({i+1}/5)")
        else:
            print("✗ Extension not connected")
            return

        # Create context
        context = await bridge.create_context("click-debug")
        tab_id = context.get("tabId")
        group_id = context.get("groupId")
        print(f"✓ Created tab: {tab_id}")

        # Navigate to a simple page
        print("\nNavigating to example.com...")
        await bridge.navigate(tab_id, "https://example.com", wait_until="load")
        await asyncio.sleep(1)
        print("✓ Page loaded")

        # Test 1: Get snapshot first
        print("\n--- Test 1: Snapshot ---")
        try:
            snapshot = await bridge.snapshot(tab_id)
            print(f"✓ Snapshot: {snapshot.get('tree', '')[:200]}...")
        except Exception as e:
            print(f"✗ Snapshot failed: {e}")

        # Test 2: Click the "More information" link (example.com has <p> with link inside)
        print("\n--- Test 2: Click Link ---")
        try:
            # First, let's see what elements are on the page
            check_script = """
                const links = document.querySelectorAll('a');
                return Array.from(links).map(a => ({
                    href: a.href,
                    text: a.innerText.substring(0, 50)
                }));
            """
            result = await bridge.evaluate(tab_id, check_script)
            # The evaluate method returns {"ok": True, "result": value}
            links = result.get("result", [])
            print(f"  Found {len(links) if isinstance(links, list) else 0} links: {links}")

            if links and isinstance(links, list) and len(links) > 0:
                # example.com structure: <p><a href="...">More information...</a></p>
                result = await bridge.click(tab_id, "a", timeout_ms=5000)
                print(f"  Click result: {result}")
                if result.get("ok"):
                    print("  ✓ Click succeeded!")
                    await asyncio.sleep(2)
                    # Go back
                    await bridge.go_back(tab_id)
                    await asyncio.sleep(1)
                else:
                    print(f"  ✗ Click failed: {result.get('error')}")
            else:
                print("  No links found to click")
        except Exception as e:
            print(f"  ✗ Click exception: {e}")

        # Test 3: Click at coordinates
        print("\n--- Test 3: Click Coordinates ---")
        try:
            result = await bridge.click_coordinate(tab_id, 100, 100)
            print(f"Click coordinate result: {result}")
        except Exception as e:
            print(f"✗ Click coordinate exception: {e}")

        # Test 4: Type text (requires input)
        print("\n--- Test 4: Type Text ---")
        try:
            # Navigate to Google
            await bridge.navigate(tab_id, "https://www.google.com", wait_until="load")
            await asyncio.sleep(2)

            result = await bridge.type_text(tab_id, "textarea[name='q']", "test query")
            print(f"Type result: {result}")
            if result.get("ok"):
                print("✓ Type succeeded!")
            else:
                print(f"✗ Type failed: {result.get('error')}")
        except Exception as e:
            print(f"✗ Type exception: {e}")

        # Test 5: Hover (on a visible button)
        print("\n--- Test 5: Hover ---")
        try:
            # Stay on Google, hover over the "Google Search" button
            result = await bridge.hover(tab_id, "input[value='Google Search']", timeout_ms=5000)
            print(f"Hover result: {result}")
            if result.get("ok"):
                print("✓ Hover succeeded!")
            else:
                # Try hovering over the search input instead
                print(f"  First hover failed: {result.get('error')}")
                result = await bridge.hover(tab_id, "textarea[name='q']", timeout_ms=3000)
                print(f"  Hover input result: {result}")
                if result.get("ok"):
                    print("✓ Hover on input succeeded!")
                else:
                    print(f"✗ Hover failed: {result.get('error')}")
        except Exception as e:
            import traceback
            print(f"✗ Hover exception: {e}")
            traceback.print_exc()

        # Cleanup
        print("\n=== Cleanup ===")
        await bridge.destroy_context(group_id)
        print("✓ Done")

    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())
