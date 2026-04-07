#!/usr/bin/env python
"""
Test #13: SPA Navigation Events

Symptom: wait_until="load" fires before content ready
Root Cause: SPA uses client-side routing, no full page load
Detection: URL changes but load event already fired
Fix: Use wait_until="networkidle" or wait_for_selector
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

CONTEXT_NAME = "spa-nav-test"


async def test_spa_navigation():
    """Test navigation timing on SPA pages."""
    print("=" * 70)
    print("TEST #13: SPA Navigation Events")
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

        # Create a test SPA
        spa_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>SPA Test</title>
            <style>
                nav a { margin-right: 10px; }
                .page { padding: 20px; border: 1px solid #ccc; margin-top: 10px; }
            </style>
        </head>
        <body>
            <nav>
                <a href="#home" onclick="navigate('home')">Home</a>
                <a href="#about" onclick="navigate('about')">About</a>
                <a href="#contact" onclick="navigate('contact')">Contact</a>
            </nav>
            <div id="app" class="page">
                <h1>Loading...</h1>
            </div>
            <script>
                // Simulate SPA routing
                let currentPage = '';

                async function navigate(page) {
                    event.preventDefault();
                    currentPage = page;

                    // Show loading state
                    document.getElementById('app').innerHTML = '<h1>Loading...</h1>';

                    // Simulate async content loading (like real SPAs)
                    await new Promise(r => setTimeout(r, 500));

                    // Render content
                    const content = {
                        home: '<h1>Home Page</h1><p>Welcome!</p>'
                            + '<button id="home-btn">Home Action</button>',
                        about: '<h1>About Page</h1><p>Simulated SPA.</p>'
                            + '<button id="about-btn">About Action</button>',
                        contact: '<h1>Contact Page</h1>'
                            + '<p>Contact us at test@example.com</p>'
                            + '<button id="contact-btn">Contact Action</button>'
                    };

                    document.getElementById('app').innerHTML = content[page] || '<h1>404</h1>';
                    window.location.hash = page;
                }

                // Initial load with delay (simulates SPA hydration)
                setTimeout(() => {
                    navigate('home');
                }, 1000);

                // Track for testing
                window.pageLoads = [];
                window.addEventListener('hashchange', () => {
                    window.pageLoads.push(window.location.hash);
                });
            </script>
        </body>
        </html>
        """

        # Write to file and use file:// URL (data: URLs don't work well with extension)
        test_file = Path("/tmp/spa_test.html")
        test_file.write_text(spa_html.strip())
        file_url = f"file://{test_file}"

        # Test 1: wait_until="load" - may fire before content ready
        print("\n--- Test 1: wait_until='load' ---")
        start = time.perf_counter()
        await bridge.navigate(tab_id, file_url, wait_until="load")
        elapsed = time.perf_counter() - start
        print(f"Navigation completed in {elapsed:.3f}s")

        # Check content immediately
        content = await bridge.evaluate(
            tab_id,
            "(function() { return document.getElementById('app').innerText; })()",
        )
        print(f"Content immediately after load: '{content.get('result', '')}'")

        # Screenshot
        screenshot = await bridge.screenshot(tab_id)
        print(f"Screenshot: {len(screenshot.get('data', ''))} bytes")

        # Wait for content
        print("\n--- Waiting for content to hydrate ---")
        await bridge.wait_for_selector(tab_id, "#home-btn", timeout_ms=5000)
        print("✓ Content loaded")

        # Check content after wait
        content_after = await bridge.evaluate(
            tab_id,
            "(function() { return document.getElementById('app').innerText; })()",
        )
        print(f"Content after wait: '{content_after.get('result', '')}'")

        # Test 2: SPA navigation (no full page load)
        print("\n--- Test 2: SPA client-side navigation ---")

        # Click "About" link
        await bridge.click(tab_id, 'a[href="#about"]')
        await asyncio.sleep(1)

        # Check if content changed
        about_content = await bridge.evaluate(
            tab_id,
            "(function() { return document.getElementById('app').innerText; })()",
        )
        print(f"Content after SPA nav: '{about_content.get('result', '')}'")

        if "About Page" in about_content.get("result", ""):
            print("✓ PASS: SPA navigation worked")
        else:
            print("✗ FAIL: SPA navigation didn't update content")

        # Test 3: wait_until="networkidle"
        print("\n--- Test 3: wait_until='networkidle' ---")
        await bridge.navigate(tab_id, file_url, wait_until="networkidle", timeout_ms=10000)

        # Check content immediately
        content_networkidle = await bridge.evaluate(
            tab_id,
            "(function() { return document.getElementById('app').innerText; })()",
        )
        print(f"Content after networkidle: '{content_networkidle.get('result', '')}'")

        if "Home Page" in content_networkidle.get("result", ""):
            print("✓ PASS: networkidle waited for content")
        else:
            print("⚠ WARNING: networkidle didn't wait long enough")

        await bridge.destroy_context(group_id)
        print("\n✓ Context destroyed")

    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(test_spa_navigation())
