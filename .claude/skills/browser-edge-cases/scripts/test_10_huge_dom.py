#!/usr/bin/env python
"""
Test #10: LinkedIn Huge DOM Tree

Symptom: browser_snapshot() hangs forever
Root Cause: 10k+ DOM nodes, accessibility tree has 50k+ nodes
Detection: document.querySelectorAll('*').length > 5000
Fix: Add timeout (10s default), truncate tree at 2000 nodes
"""

import asyncio
import sys
import time
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

CONTEXT_NAME = "huge-dom-test"


async def test_huge_dom():
    """Test snapshot performance on huge DOM trees."""
    print("=" * 70)
    print("TEST #10: Huge DOM Tree (LinkedIn-style)")
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

        # Test 1: Small DOM (baseline)
        print("\n--- Test 1: Small DOM (baseline) ---")
        small_html = """
        <!DOCTYPE html>
        <html><body>
            <h1>Small Page</h1>
            <p>A few elements</p>
            <button>Click me</button>
        </body></html>
        """
        data_url = f"data:text/html;base64,{base64.b64encode(small_html.encode()).decode()}"
        await bridge.navigate(tab_id, data_url, wait_until="load")

        start = time.perf_counter()
        snapshot = await bridge.snapshot(tab_id, timeout_s=5.0)
        elapsed = time.perf_counter() - start
        tree_len = len(snapshot.get("tree", ""))
        print(f"Small DOM snapshot: {elapsed:.3f}s, {tree_len} chars")

        # Test 2: Generate huge DOM
        print("\n--- Test 2: Huge DOM (5000+ elements) ---")
        huge_html = """
        <!DOCTYPE html>
        <html><body>
        <h1>Huge DOM Test</h1>
        <div id="container"></div>
        <script>
            const container = document.getElementById('container');
            for (let i = 0; i < 5000; i++) {
                const div = document.createElement('div');
                div.className = 'item-' + i;
                div.innerHTML = '<span>Item ' + i + '</span><button>Action</button>';
                container.appendChild(div);
            }
        </script>
        </body></html>
        """
        data_url = f"data:text/html;base64,{base64.b64encode(huge_html.encode()).decode()}"
        await bridge.navigate(tab_id, data_url, wait_until="load")

        # Count elements
        count_result = await bridge.evaluate(
            tab_id,
            "(function() { return document.querySelectorAll('*').length; })()"
        )
        elem_count = count_result.get("result", 0)
        print(f"DOM elements: {elem_count}")

        # Screenshot to verify page loaded
        screenshot = await bridge.screenshot(tab_id)
        print(f"Screenshot: {len(screenshot.get('data', ''))} bytes")

        # Test snapshot with timeout
        print("\n--- Testing snapshot with 10s timeout ---")
        start = time.perf_counter()
        try:
            snapshot = await bridge.snapshot(tab_id, timeout_s=10.0)
            elapsed = time.perf_counter() - start
            tree_len = len(snapshot.get("tree", ""))
            truncated = "(truncated)" in snapshot.get("tree", "")
            print(f"✓ Huge DOM snapshot: {elapsed:.3f}s, {tree_len} chars, truncated={truncated}")

            if elapsed < 5.0:
                print("✓ PASS: Snapshot completed quickly")
            else:
                print(f"⚠ WARNING: Snapshot took {elapsed:.1f}s")

            if truncated:
                print("✓ PASS: Tree was truncated to prevent hang")
            else:
                print("⚠ WARNING: Tree not truncated (may need adjustment)")

        except asyncio.TimeoutError:
            print("✗ FAIL: Snapshot timed out (this shouldn't happen)")

        # Test 3: Real LinkedIn
        print("\n--- Test 3: Real LinkedIn Feed ---")
        await bridge.navigate(tab_id, "https://www.linkedin.com/feed", wait_until="load", timeout_ms=30000)
        await asyncio.sleep(2)

        count_result = await bridge.evaluate(
            tab_id,
            "(function() { return document.querySelectorAll('*').length; })()"
        )
        elem_count = count_result.get("result", 0)
        print(f"LinkedIn DOM elements: {elem_count}")

        start = time.perf_counter()
        try:
            snapshot = await bridge.snapshot(tab_id, timeout_s=15.0)
            elapsed = time.perf_counter() - start
            tree_len = len(snapshot.get("tree", ""))
            truncated = "(truncated)" in snapshot.get("tree", "")
            print(f"LinkedIn snapshot: {elapsed:.3f}s, {tree_len} chars, truncated={truncated}")

            if elapsed < 5.0:
                print("✓ PASS: LinkedIn snapshot fast enough")
            elif elapsed < 15.0:
                print("⚠ WARNING: LinkedIn snapshot slow but within timeout")
            else:
                print("✗ FAIL: LinkedIn snapshot too slow")

        except asyncio.TimeoutError:
            print("✗ FAIL: LinkedIn snapshot timed out")

        await bridge.destroy_context(group_id)
        print("\n✓ Context destroyed")

    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(test_huge_dom())
