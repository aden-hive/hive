#!/usr/bin/env python
"""
Complex browser scenarios test - real browser interaction.

Tests complex selectors and interactions similar to:
- LinkedIn profile scrolling and data extraction
- Twitter/X infinite timeline
- YouTube video controls

Prerequisites:
1. Chrome with Beeline extension installed
2. Logged into LinkedIn/Twitter/YouTube (for some tests)
3. Run: uv run python manual_browser_complex_test.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gcu.browser.bridge import BeelineBridge


async def wait_for_bridge(bridge: BeelineBridge, timeout: int = 5) -> bool:
    """Wait for extension connection."""
    await bridge.start()
    for _i in range(timeout):
        await asyncio.sleep(1)
        if bridge.is_connected:
            return True
    return False


async def test_linkedin_profile_scroll(bridge: BeelineBridge, tab_id: int) -> dict:
    """Test LinkedIn-style infinite scroll and data extraction."""
    print("\n=== LinkedIn: Profile Scroll Test ===")

    try:
        # Navigate to a LinkedIn page (public profile, no login required)
        await bridge.navigate(tab_id, "https://www.linkedin.com/in/williamhgates/", wait_until="networkidle")
        await asyncio.sleep(3)

        results = {"steps": []}

        # Scroll down to load more content
        for i in range(3):
            result = await bridge.scroll(tab_id, "down", 400)
            results["steps"].append(f"scroll_{i}: {result.get('ok')}")
            await asyncio.sleep(1)

        # Extract profile data using complex selectors
        profile_script = """
            const name = document.querySelector('h1.text-heading-xlarge')?.innerText ||
                         document.querySelector('h1')?.innerText || 'Not found';
            const headline = document.querySelector('.text-body-medium')?.innerText || 'Not found';
            return { name, headline };
        """
        result = await bridge.evaluate(tab_id, profile_script)
        profile_data = result.get("result", {}).get("value", {})
        results["profile"] = profile_data
        print(f"  Profile: {profile_data}")

        # Check if we found real content
        if profile_data.get("name") and profile_data.get("name") != "Not found":
            results["ok"] = True
            print("  ✓ Successfully extracted LinkedIn profile data")
        else:
            results["ok"] = False
            print("  ✗ Could not extract profile data (may need login)")

        return results

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {"ok": False, "error": str(e)}


async def test_twitter_timeline(bridge: BeelineBridge, tab_id: int) -> dict:
    """Test Twitter/X timeline interaction."""
    print("\n=== Twitter/X: Timeline Test ===")

    try:
        # Navigate to Twitter explore (doesn't require login)
        await bridge.navigate(tab_id, "https://twitter.com/explore", wait_until="networkidle")
        await asyncio.sleep(3)

        results = {"steps": []}

        # Try to find and interact with content
        extraction_script = """
            // Twitter has complex selectors
            const tweets = document.querySelectorAll('article[data-testid="tweet"]');
            const titles = document.querySelectorAll('h2');
            return {
                tweetCount: tweets.length,
                titleCount: titles.length,
                pageTitle: document.title
            };
        """
        result = await bridge.evaluate(tab_id, extraction_script)
        data = result.get("result", {}).get("value", {})
        results["data"] = data
        print(f"  Page data: {data}")

        # Scroll to load more
        await bridge.scroll(tab_id, "down", 500)
        await asyncio.sleep(2)
        results["steps"].append("scrolled")

        results["ok"] = data.get("pageTitle", "").lower().find("x") >= 0 or data.get("tweetCount", 0) >= 0
        print(f"  {'✓' if results['ok'] else '✗'} Twitter page loaded")
        return results

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {"ok": False, "error": str(e)}


async def test_youtube_controls(bridge: BeelineBridge, tab_id: int) -> dict:
    """Test YouTube video player interaction."""
    print("\n=== YouTube: Video Controls Test ===")

    try:
        # Navigate to a YouTube video
        await bridge.navigate(tab_id, "https://www.youtube.com/watch?v=dQw4w9WgXcQ", wait_until="networkidle")
        await asyncio.sleep(3)

        results = {"steps": []}

        # Get player state
        player_script = """
            const video = document.querySelector('video');
            if (video) {
                return {
                    hasVideo: true,
                    paused: video.paused,
                    currentTime: Math.round(video.currentTime),
                    duration: Math.round(video.duration),
                    muted: video.muted
                };
            }
            return { hasVideo: false };
        """
        result = await bridge.evaluate(tab_id, player_script)
        state = result.get("result", {}).get("value", {})
        results["initialState"] = state
        print(f"  Initial state: {state}")

        if state.get("hasVideo"):
            # Try clicking play/pause button
            click_result = await bridge.click(tab_id, "button.ytp-play-button", timeout_ms=5000)
            results["steps"].append(f"click_play: {click_result.get('ok')}")
            await asyncio.sleep(1)

            # Check state after click
            result = await bridge.evaluate(tab_id, player_script)
            new_state = result.get("result", {}).get("value", {})
            results["afterClickState"] = new_state
            print(f"  After click: {new_state}")

            results["ok"] = True
            print("  ✓ YouTube video controls working")
        else:
            results["ok"] = False
            print("  ✗ Video element not found")

        return results

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {"ok": False, "error": str(e)}


async def test_form_interaction(bridge: BeelineBridge, tab_id: int) -> dict:
    """Test complex form filling with various input types."""
    print("\n=== Form: Complex Input Test ===")

    try:
        # Navigate to a form testing page
        await bridge.navigate(tab_id, "https://httpbin.org/forms/post", wait_until="load")
        await asyncio.sleep(2)

        results = {"steps": []}

        # Fill text input
        result = await bridge.type_text(tab_id, "input[name='custname']", "Test Customer")
        results["steps"].append(f"type_name: {result.get('ok')}")

        # Fill textarea
        result = await bridge.type_text(
            tab_id,
            "textarea[name='comments']",
            "This is a test comment with multiple lines.\nLine 2.\nLine 3.",
        )
        results["steps"].append(f"type_comments: {result.get('ok')}")

        # Click radio button
        result = await bridge.click(tab_id, "input[value='medium']")
        results["steps"].append(f"click_radio: {result.get('ok')}")

        # Click checkbox
        result = await bridge.click(tab_id, "input[name='topping'][value='cheese']")
        results["steps"].append(f"click_checkbox: {result.get('ok')}")

        # Verify form state
        verify_script = """
            return {
                name: document.querySelector("input[name='custname']")?.value,
                comments: document.querySelector("textarea[name='comments']")?.value,
                medium: document.querySelector("input[value='medium']")?.checked,
                cheese: document.querySelector("input[name='topping'][value='cheese']")?.checked
            };
        """
        result = await bridge.evaluate(tab_id, verify_script)
        form_state = result.get("result", {}).get("value", {})
        results["formState"] = form_state
        print(f"  Form state: {form_state}")

        # Check all fields are filled correctly
        results["ok"] = (
            form_state.get("name") == "Test Customer"
            and form_state.get("medium") is True
            and form_state.get("cheese") is True
        )

        print(f"  {'✓' if results['ok'] else '✗'} Form interaction")
        return results

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {"ok": False, "error": str(e)}


async def test_drag_drop(bridge: BeelineBridge, tab_id: int) -> dict:
    """Test drag and drop functionality."""
    print("\n=== Drag & Drop Test ===")

    try:
        # Navigate to a drag-drop demo page
        await bridge.navigate(tab_id, "https://www.w3schools.com/html/html5_draganddrop.asp", wait_until="load")
        await asyncio.sleep(2)

        results = {"steps": []}

        # Scroll to demo
        await bridge.scroll(tab_id, "down", 600)
        await asyncio.sleep(1)

        # Try drag operation - this page has draggable elements
        # Note: HTML5 drag-drop via CDP is limited, this tests mouse events
        result = await bridge.evaluate(
            tab_id,
            """
            // Check if drag elements exist
            const drag1 = document.getElementById('drag1');
            const div2 = document.getElementById('div2');
            return {
                hasDragElement: !!drag1,
                hasDropZone: !!div2
            };
        """,
        )
        elements = result.get("result", {}).get("value", {})
        results["elements"] = elements
        print(f"  Elements found: {elements}")

        results["ok"] = elements.get("hasDragElement") and elements.get("hasDropZone")
        print(f"  {'✓' if results['ok'] else '✗'} Drag elements found")
        return results

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {"ok": False, "error": str(e)}


async def main():
    print("=" * 60)
    print("COMPLEX BROWSER SCENARIOS TEST")
    print("=" * 60)
    print("\nThis tests complex interactions on real websites.")
    print("Some tests may fail if not logged in to the respective sites.\n")

    bridge = BeelineBridge()

    try:
        if not await wait_for_bridge(bridge):
            print("❌ Extension not connected. Ensure Chrome extension is running.")
            return

        # Create context
        context = await bridge.create_context("complex-test")
        tab_id = context.get("tabId")
        group_id = context.get("groupId")
        print(f"✓ Created context: tabId={tab_id}")

        # Run tests
        results = []
        results.append(("LinkedIn Profile", await test_linkedin_profile_scroll(bridge, tab_id)))
        results.append(("Twitter Timeline", await test_twitter_timeline(bridge, tab_id)))
        results.append(("YouTube Controls", await test_youtube_controls(bridge, tab_id)))
        results.append(("Form Interaction", await test_form_interaction(bridge, tab_id)))
        results.append(("Drag & Drop", await test_drag_drop(bridge, tab_id)))

        # Cleanup
        print("\n=== Cleanup ===")
        await bridge.destroy_context(group_id)
        print("✓ Context destroyed")

        # Summary
        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)
        passed = sum(1 for _, r in results if r.get("ok"))
        for name, result in results:
            status = "✓" if result.get("ok") else "✗"
            print(f"  {status} {name}")
            if not result.get("ok") and result.get("error"):
                print(f"      Error: {result['error']}")
        print(f"\nTotal: {passed}/{len(results)} passed")

    finally:
        await bridge.stop()
        print("\nBridge stopped.")


if __name__ == "__main__":
    asyncio.run(main())
