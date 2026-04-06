#!/usr/bin/env python
"""
Test browser tools on LinkedIn - specifically tests scroll and snapshot fixes.

Run: uv run python linkedin_browser_test.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gcu.browser.bridge import BeelineBridge


async def main():
    print("=" * 60)
    print("LINKEDIN BROWSER TEST")
    print("=" * 60)
    print("\nThis tests the fixes for:")
    print("1. Scroll on nested scrollable containers (LinkedIn feed)")
    print("2. Snapshot timeout on large DOM trees")
    print()

    bridge = BeelineBridge()

    try:
        print("Starting bridge...")
        await bridge.start()

        for i in range(10):
            await asyncio.sleep(1)
            if bridge.is_connected:
                print("✓ Extension connected!")
                break
            print(f"Waiting for extension... ({i + 1}/10)")
        else:
            print("✗ Extension not connected")
            return

        # Create context
        context = await bridge.create_context("linkedin-test")
        tab_id = context.get("tabId")
        group_id = context.get("groupId")
        print(f"✓ Created tab: {tab_id}")

        # Navigate to LinkedIn
        print("\n--- Navigating to LinkedIn ---")
        try:
            await bridge.navigate(
                tab_id, "https://www.linkedin.com", wait_until="load", timeout_ms=30000
            )
            print("✓ Page loaded")
        except Exception as e:
            print(f"Navigation result: {e}")

        await asyncio.sleep(2)

        # Test 1: Snapshot with timeout
        print("\n--- Test 1: Snapshot (with timeout protection) ---")
        try:
            import time

            start = time.perf_counter()
            snapshot = await bridge.snapshot(tab_id, timeout_s=15.0)
            elapsed = time.perf_counter() - start
            tree = snapshot.get("tree", "")
            print(f"✓ Snapshot completed in {elapsed:.2f}s")
            print(f"  Tree length: {len(tree)} chars")
            if "truncated" in tree:
                print("  (Tree was truncated due to size)")
            print(f"  First 300 chars:\n{tree[:300]}...")
        except TimeoutError:
            print("✗ Snapshot timed out (this shouldn't happen with 15s timeout)")
        except Exception as e:
            print(f"✗ Snapshot error: {e}")

        # Test 2: Scroll - should now find nested scrollable container
        print("\n--- Test 2: Scroll (finds nested scrollable container) ---")

        # Get scroll position of ALL scrollable elements before
        get_scroll_positions = """
            (function() {
                const results = { window: { x: window.scrollX, y: window.scrollY } };
                const scrollables = document.querySelectorAll('*');
                let idx = 0;
                for (const el of scrollables) {
                    const style = getComputedStyle(el);
                    if ((style.overflowY === 'scroll' || style.overflowY === 'auto') &&
                        el.scrollHeight > el.clientHeight) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 200 && rect.height > 200) {
                            results['container_' + idx] = {
                                tag: el.tagName,
                                class: el.className.substring(0, 30),
                                scrollTop: el.scrollTop,
                                scrollHeight: el.scrollHeight
                            };
                            idx++;
                        }
                    }
                }
                return results;
            })();
        """

        try:
            pos_before = await bridge.evaluate(tab_id, get_scroll_positions)
            before_data = pos_before.get("result", {}) if pos_before else {}
            print("  Positions before scroll:")
            if isinstance(before_data, dict):
                for key, val in before_data.items():
                    print(f"    {key}: {val}")
            else:
                print(f"    {before_data}")

            result = await bridge.scroll(tab_id, "down", 500)
            print(f"  Scroll result: {result}")

            if result.get("ok"):
                method = result.get("method", "unknown")
                container = result.get("container", "unknown")  # noqa: F841
                print(f"  ✓ Scroll command succeeded using {method}")
            else:
                print(f"  ✗ Scroll command failed: {result.get('error')}")

            await asyncio.sleep(1)

            # Get scroll positions after
            pos_after = await bridge.evaluate(tab_id, get_scroll_positions)
            after_data = pos_after.get("result", {}) if pos_after else {}
            print("  Positions after scroll:")
            if isinstance(after_data, dict):
                for key, val in after_data.items():
                    print(f"    {key}: {val}")
            else:
                print(f"    {after_data}")

            # Check if any position changed
            changed = False
            if isinstance(before_data, dict) and isinstance(after_data, dict):
                for key in after_data:
                    if key in before_data:
                        b_val = (
                            before_data[key].get("scrollTop", 0)
                            if isinstance(before_data[key], dict)
                            else 0
                        )
                        a_val = (
                            after_data[key].get("scrollTop", 0)
                            if isinstance(after_data[key], dict)
                            else 0
                        )
                        if a_val != b_val:
                            print(f"  ✓ SCROLL CONFIRMED: {key} changed from {b_val} to {a_val}")
                            changed = True
            if not changed:
                print("  ✗ NO SCROLL DETECTED: No scroll positions changed")

        except Exception as e:
            import traceback

            print(f"✗ Scroll error: {e}")
            traceback.print_exc()

        # Test 3: Multiple scrolls
        print("\n--- Test 3: Multiple Scrolls ---")
        for i in range(3):
            try:
                result = await bridge.scroll(tab_id, "down", 200)
                print(
                    f"  Scroll {i + 1}: "
                    f"{result.get('method', 'failed')} "
                    f"on {result.get('container', 'unknown')}"
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  Scroll {i + 1} failed: {e}")

        # Test 4: Snapshot after scroll
        print("\n--- Test 4: Snapshot After Scroll ---")
        try:
            snapshot = await bridge.snapshot(tab_id, timeout_s=10.0)
            tree = snapshot.get("tree", "")
            print(f"✓ Snapshot: {len(tree)} chars")
        except Exception as e:
            print(f"✗ Snapshot error: {e}")

        # Cleanup
        print("\n=== Cleanup ===")
        await bridge.destroy_context(group_id)
        print("✓ Context destroyed")

    finally:
        await bridge.stop()
        print("✓ Bridge stopped")


if __name__ == "__main__":
    asyncio.run(main())
