#!/usr/bin/env python
"""
Browser Edge Case Test Template

This script provides a template for testing and debugging browser tool failures
on specific websites. Use this to reproduce, isolate, and verify fixes.

Usage:
    1. Copy this file: cp test_case.py test_#[number]_[site].py
    2. Fill in the CONFIG section with your test details
    3. Run: uv run python test_#[number]_[site].py

Example:
    uv run python test_01_linkedin_scroll.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Add tools to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG: Fill in these values for your test case
# ═══════════════════════════════════════════════════════════════════════════════

TEST_CASE = {
    "number": 1,
    "name": "LinkedIn Nested Scroll Container",
    "site": "https://www.linkedin.com/feed",
    "simple_site": "https://example.com",
    "category": "scroll",  # scroll, click, input, snapshot, navigation
    "symptom": "scroll() returns success but page doesn't move",
}

BRIDGE_PORT = 9229
CONTEXT_NAME = "edge-case-test"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


async def test_simple_site(bridge: BeelineBridge, tab_id: int) -> dict:
    """Test that the tool works on a simple site (baseline)."""
    print("\n--- Baseline Test (Simple Site) ---")

    await bridge.navigate(tab_id, TEST_CASE["simple_site"], wait_until="load")
    await asyncio.sleep(1)

    # Adjust this based on category
    if TEST_CASE["category"] == "scroll":
        result = await bridge.scroll(tab_id, "down", 100)
        print(f"  Scroll result: {result}")
        return result
    elif TEST_CASE["category"] == "click":
        # Add click test
        pass
    elif TEST_CASE["category"] == "snapshot":
        result = await bridge.snapshot(tab_id, timeout_s=5.0)
        print(f"  Snapshot length: {len(result.get('tree', ''))}")
        return result

    return {"ok": True}


async def test_problematic_site(bridge: BeelineBridge, tab_id: int) -> dict:
    """Test the tool on the problematic site."""
    print("\n--- Problem Site Test ---")

    await bridge.navigate(tab_id, TEST_CASE["site"], wait_until="load", timeout_ms=30000)
    await asyncio.sleep(2)

    # Adjust this based on category
    if TEST_CASE["category"] == "scroll":
        # Get scroll positions before
        before = await bridge.evaluate(
            tab_id,
            """
            (function() {
                const results = { window: { y: window.scrollY } };
                document.querySelectorAll('*').forEach((el, i) => {
                    const style = getComputedStyle(el);
                    if ((style.overflowY === 'scroll' || style.overflowY === 'auto') &&
                        el.scrollHeight > el.clientHeight) {
                        results['el_' + i] = {
                            tag: el.tagName,
                            scrollTop: el.scrollTop,
                            class: el.className.substring(0, 30)
                        };
                    }
                });
                return results;
            })();
        """
        )
        print(f"  Before scroll: {before.get('result', {})}")

        # Try to scroll
        result = await bridge.scroll(tab_id, "down", 500)
        print(f"  Scroll result: {result}")

        await asyncio.sleep(1)

        # Get scroll positions after
        after = await bridge.evaluate(
            tab_id,
            """
            (function() {
                const results = { window: { y: window.scrollY } };
                document.querySelectorAll('*').forEach((el, i) => {
                    const style = getComputedStyle(el);
                    if ((style.overflowY === 'scroll' || style.overflowY === 'auto') &&
                        el.scrollHeight > el.clientHeight) {
                        results['el_' + i] = {
                            tag: el.tagName,
                            scrollTop: el.scrollTop,
                            class: el.className.substring(0, 30)
                        };
                    }
                });
                return results;
            })();
        """
        )
        print(f"  After scroll: {after.get('result', {})}")

        # Check if anything changed
        before_data = before.get("result", {}) or {}
        after_data = after.get("result", {}) or {}

        changed = False
        for key in after_data:
            if key in before_data:
                b_val = before_data[key].get("scrollTop", 0) if isinstance(before_data[key], dict) else 0
                a_val = after_data[key].get("scrollTop", 0) if isinstance(after_data[key], dict) else 0
                if a_val != b_val:
                    print(f"  ✓ CHANGE DETECTED: {key} scrolled from {b_val} to {a_val}")
                    changed = True

        if not changed:
            print("  ✗ NO CHANGE: Scroll did not affect any container")

        return {"ok": changed, "scroll_result": result}

    elif TEST_CASE["category"] == "snapshot":
        start = time.perf_counter()
        try:
            result = await bridge.snapshot(tab_id, timeout_s=15.0)
            elapsed = time.perf_counter() - start
            tree_len = len(result.get("tree", ""))
            print(f"  Snapshot completed in {elapsed:.2f}s, {tree_len} chars")
            return {"ok": True, "elapsed": elapsed, "tree_length": tree_len}
        except asyncio.TimeoutError:
            print("  ✗ SNAPSHOT TIMED OUT")
            return {"ok": False, "error": "timeout"}

    return {"ok": True}


async def detect_root_cause(bridge: BeelineBridge, tab_id: int) -> dict:
    """Run detection scripts to identify the root cause."""
    print("\n--- Root Cause Detection ---")

    detections = {}

    # Detection 1: Nested scrollable containers
    scroll_check = await bridge.evaluate(
        tab_id,
        """
        (function() {
            const candidates = [];
            document.querySelectorAll('*').forEach(el => {
                const style = getComputedStyle(el);
                if (style.overflow.includes('scroll') || style.overflow.includes('auto')) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 100) {
                        candidates.push({
                            tag: el.tagName,
                            area: rect.width * rect.height,
                            class: el.className.substring(0, 30)
                        });
                    }
                }
            });
            candidates.sort((a, b) => b.area - a.area);
            return {
                count: candidates.length,
                largest: candidates[0]
            };
        })();
    """
    )
    detections["nested_scroll"] = scroll_check.get("result", {})
    print(f"  Nested scroll containers: {detections['nested_scroll']}")

    # Detection 2: Shadow DOM
    shadow_check = await bridge.evaluate(
        tab_id,
        """
        (function() {
            const withShadow = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.shadowRoot) {
                    withShadow.push(el.tagName);
                }
            });
            return { count: withShadow.length, elements: withShadow.slice(0, 5) };
        })();
    """
    )
    detections["shadow_dom"] = shadow_check.get("result", {})
    print(f"  Shadow DOM: {detections['shadow_dom']}")

    # Detection 3: iframes
    iframe_check = await bridge.evaluate(
        tab_id,
        """
        (function() {
            const iframes = document.querySelectorAll('iframe');
            return { count: iframes.length };
        })();
    """
    )
    detections["iframes"] = iframe_check.get("result", {})
    print(f"  iframes: {detections['iframes']}")

    # Detection 4: DOM size
    dom_check = await bridge.evaluate(
        tab_id,
        """
        (function() {
            return {
                elements: document.querySelectorAll('*').length,
                body_children: document.body.children.length
            };
        })();
    """
    )
    detections["dom_size"] = dom_check.get("result", {})
    print(f"  DOM size: {detections['dom_size']}")

    # Detection 5: Framework detection
    framework_check = await bridge.evaluate(
        tab_id,
        """
        (function() {
            return {
                react: !!document.querySelector('[data-reactroot], [data-reactid]'),
                vue: !!document.querySelector('[data-v-]'),
                angular: !!document.querySelector('[ng-app], [ng-version]')
            };
        })();
    """
    )
    detections["frameworks"] = framework_check.get("result", {})
    print(f"  Frameworks: {detections['frameworks']}")

    return detections


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════


async def main():
    print("=" * 70)
    print(f"EDGE CASE TEST #{TEST_CASE['number']}: {TEST_CASE['name']}")
    print("=" * 70)
    print(f"Site: {TEST_CASE['site']}")
    print(f"Category: {TEST_CASE['category']}")
    print(f"Symptom: {TEST_CASE['symptom']}")

    bridge = BeelineBridge()

    try:
        print("\n--- Starting Bridge ---")
        await bridge.start()

        # Wait for extension connection
        for i in range(10):
            await asyncio.sleep(1)
            if bridge.is_connected:
                print("✓ Extension connected!")
                break
            print(f"Waiting for extension... ({i+1}/10)")
        else:
            print("✗ Extension not connected. Ensure Chrome with Beeline extension is running.")
            return

        # Create browser context
        context = await bridge.create_context(CONTEXT_NAME)
        tab_id = context.get("tabId")
        group_id = context.get("groupId")
        print(f"✓ Created tab: {tab_id}")

        # Run tests
        baseline_result = await test_simple_site(bridge, tab_id)
        problem_result = await test_problematic_site(bridge, tab_id)
        detections = await detect_root_cause(bridge, tab_id)

        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Baseline test: {'✓ PASS' if baseline_result.get('ok') else '✗ FAIL'}")
        print(f"Problem test: {'✓ PASS' if problem_result.get('ok') else '✗ FAIL'}")
        print(f"Root cause indicators: {list(k for k, v in detections.items() if v)}")

        # Cleanup
        print("\n--- Cleanup ---")
        await bridge.destroy_context(group_id)
        print("✓ Context destroyed")

    finally:
        await bridge.stop()
        print("✓ Bridge stopped")


if __name__ == "__main__":
    asyncio.run(main())
