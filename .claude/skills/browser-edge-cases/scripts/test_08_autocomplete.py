#!/usr/bin/env python
"""
Test #8: Autocomplete Field Clearing

Symptom: Typed text gets cleared immediately
Root Cause: Field expects realistic keystroke timing for autocomplete
Detection: Field has autocomplete listeners or dropdown appears
Fix: Add delay_ms between keystrokes
"""

import asyncio
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

CONTEXT_NAME = "autocomplete-test"


async def test_autocomplete():
    """Test typing into fields with autocomplete behavior."""
    print("=" * 70)
    print("TEST #8: Autocomplete Field Clearing")
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

        # Create test page with autocomplete behavior
        test_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Autocomplete Test</title>
        <style>
            .autocomplete-items {
                position: absolute;
                border: 1px solid #d4d4d4;
                border-top: none;
                z-index: 99;
                top: 100%;
                left: 0;
                right: 0;
                max-height: 200px;
                overflow-y: auto;
                background: white;
            }
            .autocomplete-items div {
                padding: 10px;
                cursor: pointer;
            }
            .autocomplete-items div:hover {
                background-color: #e9e9e9;
            }
            .autocomplete-active {
                background-color: DodgerBlue !important;
                color: white;
            }
            .autocomplete { position: relative; display: inline-block; }
            input { width: 300px; padding: 10px; font-size: 16px; }
        </style></head>
        <body>
            <h2>Autocomplete Test</h2>

            <div class="autocomplete">
                <input id="search" type="text" placeholder="Search countries..." autocomplete="off">
            </div>

            <div id="log" style="margin-top:20px;font-family:monospace;"></div>

            <script>
                const countries = ["Afghanistan","Albania","Algeria","Andorra","Angola","Argentina","Armenia","Australia","Austria","Azerbaijan","Bahamas","Bahrain","Bangladesh","Belarus","Belgium","Belize","Benin","Bhutan","Bolivia","Brazil","Canada","China","Colombia","Denmark","Egypt","France","Germany","India","Indonesia","Italy","Japan","Mexico","Netherlands","Nigeria","Norway","Pakistan","Peru","Philippines","Poland","Portugal","Russia","Spain","Sweden","Switzerland","Thailand","Turkey","Ukraine","United Kingdom","United States","Vietnam"];

                const input = document.getElementById('search');
                const log = document.getElementById('log');
                let currentFocus = -1;
                let typingTimeout = null;

                // Track events for testing
                window.inputEvents = [];
                window.inputValue = '';

                function logEvent(type, value) {
                    window.inputEvents.push({ type, value, time: Date.now() });
                    const entry = document.createElement('div');
                    entry.textContent = type + ': ' + value;
                    log.insertBefore(entry, log.firstChild);
                }

                // Simulate autocomplete that clears fast typing
                input.addEventListener('input', function(e) {
                    const val = this.value;

                    // Clear previous dropdown
                    closeAllLists();

                    if (!val) return;

                    // If typing too fast (autocomplete-style), clear and restart
                    clearTimeout(typingTimeout);
                    typingTimeout = setTimeout(() => {
                        logEvent('input', val);
                        window.inputValue = val;

                        // Create dropdown
                        const div = document.createElement('div');
                        div.setAttribute('id', this.id + 'autocomplete-list');
                        div.setAttribute('class', 'autocomplete-items');
                        this.parentNode.appendChild(div);

                        countries.filter(c => c.substr(0, val.length).toUpperCase() === val.toUpperCase())
                            .slice(0, 5)
                            .forEach(country => {
                                const item = document.createElement('div');
                                item.innerHTML = '<strong>' + country.substr(0, val.length) + '</strong>' + country.substr(val.length);
                                item.addEventListener('click', function() {
                                    input.value = country;
                                    closeAllLists();
                                    logEvent('select', country);
                                    window.inputValue = country;
                                });
                                div.appendChild(item);
                            });
                    }, 100); // 100ms debounce
                });

                function closeAllLists() {
                    document.querySelectorAll('.autocomplete-items').forEach(el => el.remove());
                }

                document.addEventListener('click', function() {
                    closeAllLists();
                });
            </script>
        </body>
        </html>
        """

        data_url = f"data:text/html;base64,{base64.b64encode(test_html.encode()).decode()}"
        await bridge.navigate(tab_id, data_url, wait_until="load")
        print("✓ Page loaded")

        # Screenshot
        screenshot = await bridge.screenshot(tab_id)
        print(f"Screenshot: {len(screenshot.get('data', ''))} bytes")

        # Test 1: Fast typing (no delay) - may fail
        print("\n--- Test 1: Fast typing (delay_ms=0) ---")
        await bridge.click(tab_id, "#search")
        await bridge.type(tab_id, "#search", "Ger", clear_first=True, delay_ms=0)
        await asyncio.sleep(0.5)

        fast_result = await bridge.evaluate(
            tab_id,
            "(function() { return document.getElementById('search').value; })()"
        )
        fast_value = fast_result.get("result", "")
        print(f"Value after fast typing: '{fast_value}'")

        # Check events
        events_result = await bridge.evaluate(
            tab_id,
            "(function() { return window.inputEvents; })()"
        )
        print(f"Events logged: {events_result.get('result', [])}")

        # Test 2: Slow typing (with delay) - should work
        print("\n--- Test 2: Slow typing (delay_ms=100) ---")
        await bridge.click(tab_id, "#search")
        await bridge.type(tab_id, "#search", "United", clear_first=True, delay_ms=100)
        await asyncio.sleep(0.5)

        slow_result = await bridge.evaluate(
            tab_id,
            "(function() { return document.getElementById('search').value; })()"
        )
        slow_value = slow_result.get("result", "")
        print(f"Value after slow typing: '{slow_value}'")

        # Check if dropdown appeared
        dropdown_result = await bridge.evaluate(
            tab_id,
            "(function() { return document.querySelectorAll('.autocomplete-items div').length; })()"
        )
        dropdown_count = dropdown_result.get("result", 0)
        print(f"Dropdown items: {dropdown_count}")

        # Screenshot with dropdown
        screenshot_dropdown = await bridge.screenshot(tab_id)
        print(f"Screenshot with dropdown: {len(screenshot_dropdown.get('data', ''))} bytes")

        # Results
        print("\n--- Results ---")
        if "United" in slow_value:
            print("✓ PASS: Slow typing with delay_ms worked")
        else:
            print("✗ FAIL: Slow typing still didn't work")

        if dropdown_count > 0:
            print("✓ PASS: Autocomplete dropdown appeared")
        else:
            print("⚠ WARNING: No autocomplete dropdown")

        await bridge.destroy_context(group_id)
        print("\n✓ Context destroyed")

    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(test_autocomplete())
