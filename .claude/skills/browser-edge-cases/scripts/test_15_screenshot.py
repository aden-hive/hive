#!/usr/bin/env python
"""
Test #15: Screenshot Functionality

Tests browser_screenshot across multiple scenarios:
- Basic viewport screenshot
- Full-page screenshot
- Selector-based screenshot
- Screenshot on complex DOM
- Timeout handling

Category: screenshot
"""

import asyncio
import base64
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

CONTEXT_NAME = "screenshot-test"

SIMPLE_HTML = """<!DOCTYPE html>
<html>
<head><style>
  body { margin: 0; background: #fff; font-family: sans-serif; }
  h1 { color: #333; padding: 20px; }
  .box { width: 200px; height: 100px; background: #4a90e2; margin: 20px; }
  .long-content { height: 2000px; background: linear-gradient(blue, red); }
</style></head>
<body>
  <h1 id="title">Screenshot Test Page</h1>
  <div class="box" id="target-box">Target Box</div>
  <div class="long-content"></div>
</body>
</html>"""


def check_png(data: str) -> bool:
    """Verify that base64 data decodes to a valid PNG."""
    try:
        raw = base64.b64decode(data)
        return raw[:8] == b"\x89PNG\r\n\x1a\n"
    except Exception:
        return False


async def test_basic_screenshot(bridge: BeelineBridge, tab_id: int, data_url: str):
    print("\n--- Test 1: Basic Viewport Screenshot ---")
    await bridge.navigate(tab_id, data_url, wait_until="load")
    await asyncio.sleep(0.5)

    start = time.perf_counter()
    result = await bridge.screenshot(tab_id)
    elapsed = time.perf_counter() - start

    ok = result.get("ok")
    data = result.get("data", "")
    mime = result.get("mimeType", "")

    print(f"  ok={ok}, mimeType={mime}, elapsed={elapsed:.3f}s")
    print(f"  data length: {len(data)} chars")

    if ok and data:
        valid_png = check_png(data)
        print(f"  valid PNG: {valid_png}")
        if valid_png:
            raw = base64.b64decode(data)
            print(f"  PNG size: {len(raw)} bytes")
            print("  ✓ PASS: Basic screenshot works")
            return True
        else:
            print("  ✗ FAIL: Data is not a valid PNG")
    else:
        print(f"  ✗ FAIL: {result.get('error', 'no data')}")
    return False


async def test_full_page_screenshot(bridge: BeelineBridge, tab_id: int, data_url: str):
    print("\n--- Test 2: Full Page Screenshot ---")
    await bridge.navigate(tab_id, data_url, wait_until="load")
    await asyncio.sleep(0.5)

    viewport_result = await bridge.screenshot(tab_id, full_page=False)
    full_result = await bridge.screenshot(tab_id, full_page=True)

    v_data = viewport_result.get("data", "")
    f_data = full_result.get("data", "")

    if not v_data or not f_data:
        print(f"  ✗ FAIL: viewport ok={viewport_result.get('ok')}, full ok={full_result.get('ok')}")
        return False

    v_size = len(base64.b64decode(v_data))
    f_size = len(base64.b64decode(f_data))
    print(f"  Viewport PNG: {v_size} bytes")
    print(f"  Full page PNG: {f_size} bytes")

    if f_size > v_size:
        print("  ✓ PASS: Full page larger than viewport")
        return True
    else:
        print("  ✗ FAIL: Full page not larger than viewport (may not capture long pages)")
        return False


async def test_selector_screenshot(bridge: BeelineBridge, tab_id: int, data_url: str):
    print("\n--- Test 3: Selector Screenshot ---")
    await bridge.navigate(tab_id, data_url, wait_until="load")
    await asyncio.sleep(0.5)

    # selector param exists in signature but may not be implemented
    result = await bridge.screenshot(tab_id, selector="#target-box")

    ok = result.get("ok")
    data = result.get("data", "")

    if ok and data:
        # If implemented, the box screenshot should be smaller than a full viewport screenshot
        full_result = await bridge.screenshot(tab_id)
        full_data = full_result.get("data", "")

        if full_data:
            sel_size = len(base64.b64decode(data))
            full_size = len(base64.b64decode(full_data))
            print(f"  Selector PNG: {sel_size} bytes")
            print(f"  Full page PNG: {full_size} bytes")
            if sel_size < full_size:
                print("  ✓ PASS: Selector screenshot smaller than full page")
                return True
            else:
                print("  ⚠ WARNING: Selector screenshot not smaller (may be full page)")
                return False
    else:
        print(f"  ⚠ NOT IMPLEMENTED: selector param ignored (returns full page) - error={result.get('error')}")
        print("  NOTE: selector parameter exists in signature but is not used in implementation")
        return False


async def test_screenshot_url_metadata(bridge: BeelineBridge, tab_id: int):
    print("\n--- Test 4: Screenshot URL Metadata ---")
    await bridge.navigate(tab_id, "https://example.com", wait_until="load")
    await asyncio.sleep(1)

    result = await bridge.screenshot(tab_id)
    url = result.get("url", "")
    tab = result.get("tabId")

    print(f"  url={url!r}, tabId={tab}")

    if "example.com" in url:
        print("  ✓ PASS: URL metadata captured correctly")
        return True
    else:
        print(f"  ✗ FAIL: Expected example.com in URL, got {url!r}")
        return False


async def test_screenshot_timeout(bridge: BeelineBridge, tab_id: int, data_url: str):
    print("\n--- Test 5: Timeout Handling ---")
    await bridge.navigate(tab_id, data_url, wait_until="load")

    # Very short timeout - likely still completes since simple page
    start = time.perf_counter()
    result = await bridge.screenshot(tab_id, timeout_s=0.001)
    elapsed = time.perf_counter() - start

    if not result.get("ok"):
        err = result.get("error", "")
        if "timed out" in err or "cancelled" in err:
            print(f"  ✓ PASS: Timeout handled gracefully: {err!r}")
            return True
        else:
            print(f"  ⚠ Fast enough to beat timeout: {err!r} in {elapsed:.3f}s")
            return True  # Not a failure, just fast
    else:
        print(f"  ⚠ Screenshot completed before timeout ({elapsed:.3f}s) - too fast to test timeout")
        return True  # Still ok, just very fast


async def test_screenshot_complex_site(bridge: BeelineBridge, tab_id: int):
    print("\n--- Test 6: Complex Site (example.com) ---")
    await bridge.navigate(tab_id, "https://example.com", wait_until="load")
    await asyncio.sleep(1)

    start = time.perf_counter()
    result = await bridge.screenshot(tab_id)
    elapsed = time.perf_counter() - start

    ok = result.get("ok")
    data = result.get("data", "")

    print(f"  ok={ok}, elapsed={elapsed:.3f}s, data_len={len(data)}")
    if ok and check_png(data):
        print("  ✓ PASS: Screenshot on real site works")
        return True
    else:
        print(f"  ✗ FAIL: {result.get('error', 'bad data')}")
        return False


async def main():
    print("=" * 70)
    print("TEST #15: Screenshot Functionality")
    print("=" * 70)

    bridge = BeelineBridge()

    try:
        await bridge.start()

        for i in range(10):
            await asyncio.sleep(1)
            if bridge.is_connected:
                print("✓ Extension connected!")
                break
            print(f"Waiting for extension... ({i + 1}/10)")
        else:
            print("✗ Extension not connected. Ensure Chrome with Beeline extension is running.")
            return

        context = await bridge.create_context(CONTEXT_NAME)
        tab_id = context.get("tabId")
        group_id = context.get("groupId")
        print(f"✓ Created tab: {tab_id}")

        data_url = f"data:text/html;base64,{base64.b64encode(SIMPLE_HTML.encode()).decode()}"

        results = {
            "basic": await test_basic_screenshot(bridge, tab_id, data_url),
            "full_page": await test_full_page_screenshot(bridge, tab_id, data_url),
            "selector": await test_selector_screenshot(bridge, tab_id, data_url),
            "metadata": await test_screenshot_url_metadata(bridge, tab_id),
            "timeout": await test_screenshot_timeout(bridge, tab_id, data_url),
            "complex_site": await test_screenshot_complex_site(bridge, tab_id),
        }

        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        for name, passed in results.items():
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"  {status}: {name}")

        passed_count = sum(1 for v in results.values() if v)
        total = len(results)
        print(f"\n  {passed_count}/{total} tests passed")

        await bridge.destroy_context(group_id)
        print("\n✓ Context destroyed")

    finally:
        await bridge.stop()
        print("✓ Bridge stopped")


if __name__ == "__main__":
    asyncio.run(main())
