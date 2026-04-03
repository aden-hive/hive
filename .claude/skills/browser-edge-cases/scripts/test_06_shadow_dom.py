#!/usr/bin/env python
"""
Test #6: Shadow DOM Elements

Symptom: querySelector can't find element
Root Cause: Element is inside a shadow root, not main DOM tree
Detection: element.shadowRoot !== null on parent elements
Fix: Use piercing selector (host >>> target) or traverse shadow roots
"""

import asyncio
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

CONTEXT_NAME = "shadow-dom-test"


async def test_shadow_dom():
    """Test clicking elements inside Shadow DOM."""
    print("=" * 70)
    print("TEST #6: Shadow DOM Elements")
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

        # Create test page with Shadow DOM
        print("\n--- Creating test page with Shadow DOM ---")
        test_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Shadow DOM Test</title></head>
        <body>
            <div id="shadow-host"></div>
            <script>
                const host = document.getElementById('shadow-host');
                const shadow = host.attachShadow({ mode: 'open' });
                shadow.innerHTML = `
                    <style>
                        button { padding: 10px 20px; font-size: 16px; }
                    </style>
                    <button id="shadow-btn">Shadow Button</button>
                `;
                shadow.getElementById('shadow-btn').addEventListener('click', () => {
                    window.shadowClickCount = (window.shadowClickCount || 0) + 1;
                    console.log('Shadow button clicked:', window.shadowClickCount);
                });
            </script>
        </body>
        </html>
        """

        # Write to file and use file:// URL (data: URLs don't work well with extension)
        test_file = Path("/tmp/shadow_dom_test.html")
        test_file.write_text(test_html.strip())
        file_url = f"file://{test_file}"
        await bridge.navigate(tab_id, file_url, wait_until="load")
        print("✓ Page loaded")

        # Screenshot
        screenshot = await bridge.screenshot(tab_id)
        print(f"Screenshot: {len(screenshot.get('data', ''))} bytes")

        # Detect Shadow DOM
        print("\n--- Detecting Shadow DOM ---")
        detection = await bridge.evaluate(
            tab_id,
            """
            (function() {
                const hosts = [];
                document.querySelectorAll('*').forEach(el => {
                    if (el.shadowRoot) {
                        hosts.push({
                            tag: el.tagName,
                            id: el.id,
                            hasButton: el.shadowRoot.querySelector('button') !== null
                        });
                    }
                });
                return { count: hosts.length, hosts };
            })();
        """
        )
        print(f"Shadow DOM detection: {detection.get('result', {})}")

        # Try to click shadow button using regular selector (should fail)
        print("\n--- Attempting click with regular selector ---")
        try:
            result = await bridge.click(tab_id, "#shadow-btn", timeout_ms=3000)
            print(f"Result: {result}")
        except Exception as e:
            print(f"Expected failure: {e}")

        # Try to click using JavaScript that pierces shadow DOM
        print("\n--- Clicking via JavaScript shadow piercing ---")
        click_result = await bridge.evaluate(
            tab_id,
            """
            (function() {
                const host = document.getElementById('shadow-host');
                const btn = host.shadowRoot.getElementById('shadow-btn');
                if (btn) {
                    btn.click();
                    return { success: true, clicked: 'shadow-btn' };
                }
                return { success: false, error: 'Button not found' };
            })();
        """
        )
        print(f"JS click result: {click_result.get('result', {})}")

        # Verify click was registered
        count_result = await bridge.evaluate(
            tab_id,
            "(function() { return window.shadowClickCount || 0; })()"
        )
        count = count_result.get("result") or 0
        print(f"Shadow click count: {count}")

        if count and count > 0:
            print("✓ PASS: Shadow DOM element clicked successfully")
        else:
            print("✗ FAIL: Could not click Shadow DOM element")

        await bridge.destroy_context(group_id)
        print("\n✓ Context destroyed")

    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(test_shadow_dom())
