#!/usr/bin/env python
"""
Test #4: Element Covered by Overlay

Symptom: Click succeeds but no action triggered
Root Cause: Element is covered by transparent overlay, tooltip, or iframe
Detection: document.elementFromPoint(x, y) !== target
Fix: Wait for overlay to disappear, or use JavaScript element.click()
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

CONTEXT_NAME = "overlay-click-test"


async def test_overlay_click():
    """Test clicking elements that are covered by overlays."""
    print("=" * 70)
    print("TEST #4: Element Covered by Overlay")
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

        # Create a test page with overlay
        print("\n--- Creating test page with overlay ---")
        test_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Overlay Test</title></head>
        <body>
            <button id="target-btn" onclick="alert('Clicked!')">Click Me</button>
            <div id="overlay" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.3);z-index:1000;"></div>
            <script>
                window.clickCount = 0;
                document.getElementById('target-btn').addEventListener('click', () => {
                    window.clickCount++;
                });
            </script>
        </body>
        </html>
        """

        # Navigate to data URL
        import base64
        data_url = f"data:text/html;base64,{base64.b64encode(test_html.encode()).decode()}"
        await bridge.navigate(tab_id, data_url, wait_until="load")

        # Screenshot before
        screenshot = await bridge.screenshot(tab_id)
        print(f"Screenshot: {len(screenshot.get('data', ''))} bytes")

        # Try to click the covered button
        print("\n--- Attempting to click covered button ---")

        # First, check if element is covered
        coverage_check = await bridge.evaluate(
            tab_id,
            """
            (function() {
                const btn = document.getElementById('target-btn');
                const rect = btn.getBoundingClientRect();
                const centerX = rect.left + rect.width / 2;
                const centerY = rect.top + rect.height / 2;
                const topElement = document.elementFromPoint(centerX, centerY);
                return {
                    isCovered: topElement !== btn && !btn.contains(topElement),
                    topElement: topElement?.tagName,
                    targetElement: btn.tagName
                };
            })();
        """
        )
        print(f"Coverage check: {coverage_check.get('result', {})}")

        # Try CDP click (may fail due to overlay)
        click_result = await bridge.click(tab_id, "#target-btn", timeout_ms=5000)
        print(f"Click result: {click_result}")

        # Check if click registered
        count_result = await bridge.evaluate(
            tab_id,
            "(function() { return window.clickCount; })()"
        )
        count = count_result.get("result", 0)
        print(f"Click count after CDP click: {count}")

        if count > 0:
            print("✓ PASS: JavaScript click penetrated overlay")
        else:
            print("✗ FAIL: Click did not reach button (overlay blocked it)")

        await bridge.destroy_context(group_id)
        print("\n✓ Context destroyed")

    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(test_overlay_click())
