#!/usr/bin/env python
"""
Manual browser tools test - connects to real Chrome extension.

Prerequisites:
1. Chrome with Beeline extension installed and enabled
2. Run: uv run python manual_browser_test.py

This will test:
- Bridge connection
- Tab group creation
- Navigation
- Click, type, scroll interactions
- Snapshot/screenshot
- Complex JS execution (LinkedIn-style selectors)
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gcu.browser.bridge import BeelineBridge


async def test_connection(bridge: BeelineBridge) -> bool:
    """Test 1: Extension connection."""
    print("\n=== Test 1: Extension Connection ===")
    print("Starting bridge on port 9229...")
    await bridge.start()

    for i in range(5):
        await asyncio.sleep(1)
        if bridge.is_connected:
            print("✓ Extension connected!")
            return True
        print(f"  Waiting... ({i+1}/5)")

    print("✗ Extension not connected. Ensure Chrome extension is installed.")
    return False


async def test_context_creation(bridge: BeelineBridge) -> dict | None:
    """Test 2: Create tab group/context."""
    print("\n=== Test 2: Create Tab Group ===")
    try:
        result = await bridge.create_context("manual-test-agent")
        print(f"✓ Created context: groupId={result.get('groupId')}, tabId={result.get('tabId')}")
        return result
    except Exception as e:
        print(f"✗ Failed: {e}")
        return None


async def test_navigation(bridge: BeelineBridge, tab_id: int) -> bool:
    """Test 3: Navigate to example.com."""
    print("\n=== Test 3: Navigation ===")
    try:
        result = await bridge.navigate(tab_id, "https://example.com", wait_until="load")
        print(f"✓ Navigated to: {result.get('url')}")
        await asyncio.sleep(1)
        return True
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


async def test_snapshot(bridge: BeelineBridge, tab_id: int) -> bool:
    """Test 4: Get accessibility snapshot."""
    print("\n=== Test 4: Accessibility Snapshot ===")
    try:
        result = await bridge.snapshot(tab_id)
        tree = result.get("tree", "")
        lines = tree.split("\n")[:10]
        print(f"✓ Got snapshot ({len(tree)} chars)")
        print("  First 10 lines:")
        for line in lines:
            print(f"    {line}")
        return True
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


async def test_click(bridge: BeelineBridge, tab_id: int) -> bool:
    """Test 5: Click a link."""
    print("\n=== Test 5: Click Element ===")
    try:
        # example.com has a link to "More information..."
        result = await bridge.click(tab_id, "a", timeout_ms=5000)
        if result.get("ok"):
            print(f"✓ Clicked link at ({result.get('x')}, {result.get('y')})")
            await asyncio.sleep(2)
            # Go back
            await bridge.go_back(tab_id)
            await asyncio.sleep(1)
            return True
        else:
            print(f"✗ Click failed: {result.get('error')}")
            return False
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


async def test_type_and_clear(bridge: BeelineBridge, tab_id: int) -> bool:
    """Test 6: Type into an input field."""
    print("\n=== Test 6: Type Text ===")
    try:
        # Navigate to a page with an input
        await bridge.navigate(tab_id, "https://www.google.com", wait_until="load")
        await asyncio.sleep(2)

        # Type in search box
        result = await bridge.type_text(tab_id, "textarea[name='q']", "hello world")
        if result.get("ok"):
            print("✓ Typed 'hello world' into search box")
            await asyncio.sleep(0.5)

            # Clear and type something else
            await bridge.press_key(tab_id, "Control+a")
            await asyncio.sleep(0.2)
            await bridge.type_text(tab_id, "textarea[name='q']", "new search")
            print("✓ Replaced with 'new search'")
            return True
        else:
            print(f"✗ Type failed: {result.get('error')}")
            return False
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


async def test_scroll(bridge: BeelineBridge, tab_id: int) -> bool:
    """Test 7: Scroll page."""
    print("\n=== Test 7: Scroll ===")
    try:
        # Scroll down
        result = await bridge.scroll(tab_id, "down", 500)
        if result.get("ok"):
            print("✓ Scrolled down 500px")
            await asyncio.sleep(0.5)

            # Scroll up
            await bridge.scroll(tab_id, "up", 250)
            print("✓ Scrolled up 250px")
            return True
        else:
            print(f"✗ Scroll failed: {result.get('error')}")
            return False
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


async def test_evaluate_js(bridge: BeelineBridge, tab_id: int) -> bool:
    """Test 8: Execute JavaScript."""
    print("\n=== Test 8: JavaScript Execution ===")
    try:
        # Simple return
        result = await bridge.evaluate(tab_id, "return document.title;")
        print(f"✓ Page title: {result.get('result', {}).get('value')}")

        # Complex selector (LinkedIn-style)
        complex_script = """
            const links = document.querySelectorAll('a');
            return {
                total: links.length,
                first: links[0]?.href || null
            };
        """
        result = await bridge.evaluate(tab_id, complex_script)
        value = result.get("result", {}).get("value", {})
        print(f"✓ Found {value.get('total')} links, first: {value.get('first', 'N/A')[:50]}...")
        return True
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


async def test_screenshot(bridge: BeelineBridge, tab_id: int) -> bool:
    """Test 9: Take screenshot."""
    print("\n=== Test 9: Screenshot ===")
    try:
        result = await bridge.screenshot(tab_id, full_page=False)
        if result.get("ok"):
            data = result.get("data", "")
            print(f"✓ Screenshot captured ({len(data)} chars base64)")
            return True
        else:
            print(f"✗ Screenshot failed: {result.get('error')}")
            return False
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


async def test_tab_management(bridge: BeelineBridge, group_id: int, tab_id: int) -> bool:
    """Test 10: Create and close tabs."""
    print("\n=== Test 10: Tab Management ===")
    try:
        # Create new tab
        new_tab = await bridge.create_tab(group_id, "https://httpbin.org")
        new_tab_id = new_tab.get("tabId")
        print(f"✓ Created new tab: {new_tab_id}")
        await asyncio.sleep(2)

        # List tabs
        tabs = await bridge.list_tabs(group_id)
        print(f"✓ Group has {len(tabs.get('tabs', []))} tabs")

        # Close the new tab
        await bridge.close_tab(new_tab_id)
        print(f"✓ Closed tab {new_tab_id}")
        return True
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


async def main():
    print("=" * 60)
    print("MANUAL BROWSER TOOLS TEST")
    print("=" * 60)

    bridge = BeelineBridge()

    try:
        # Test 1: Connection
        if not await test_connection(bridge):
            print("\n❌ Cannot proceed without extension connection")
            return

        # Test 2: Context creation
        context = await test_context_creation(bridge)
        if not context:
            print("\n❌ Cannot proceed without context")
            return

        tab_id = context.get("tabId")
        group_id = context.get("groupId")

        results = []

        # Run all tests
        results.append(("Navigation", await test_navigation(bridge, tab_id)))
        results.append(("Snapshot", await test_snapshot(bridge, tab_id)))
        results.append(("Click", await test_click(bridge, tab_id)))
        results.append(("Type", await test_type_and_clear(bridge, tab_id)))
        results.append(("Scroll", await test_scroll(bridge, tab_id)))
        results.append(("Evaluate JS", await test_evaluate_js(bridge, tab_id)))
        results.append(("Screenshot", await test_screenshot(bridge, tab_id)))
        results.append(("Tab Management", await test_tab_management(bridge, group_id, tab_id)))

        # Cleanup
        print("\n=== Cleanup ===")
        await bridge.destroy_context(group_id)
        print("✓ Destroyed context")

        # Summary
        print("\n" + "=" * 60)
        print("RESULTS SUMMARY")
        print("=" * 60)
        passed = sum(1 for _, r in results if r)
        total = len(results)
        for name, result in results:
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"  {status}: {name}")
        print(f"\nTotal: {passed}/{total} passed")

    finally:
        await bridge.stop()
        print("\nBridge stopped.")


if __name__ == "__main__":
    asyncio.run(main())
