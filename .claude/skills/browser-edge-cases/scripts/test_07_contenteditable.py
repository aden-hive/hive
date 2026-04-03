#!/usr/bin/env python
"""
Test #7: ContentEditable / Rich Text Editors

Symptom: browser_type() doesn't insert text
Root Cause: Element is contenteditable, not an <input> or <textarea>
Detection: element.contentEditable === 'true'
Fix: Focus via JavaScript, use execCommand('insertText') or Input.dispatchKeyEvent
"""

import asyncio
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools" / "src"))

from gcu.browser.bridge import BeelineBridge

CONTEXT_NAME = "contenteditable-test"


async def test_contenteditable():
    """Test typing into contenteditable elements."""
    print("=" * 70)
    print("TEST #7: ContentEditable / Rich Text Editors")
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

        # Create test page with contenteditable
        test_html = """
        <!DOCTYPE html>
        <html>
        <head><title>ContentEditable Test</title></head>
        <body>
            <h2>ContentEditable Test</h2>

            <h3>1. Simple contenteditable div</h3>
            <div id="editor1" contenteditable="true" style="border:1px solid #ccc;padding:10px;min-height:50px;">Start text</div>

            <h3>2. Rich text editor (like Notion)</h3>
            <div id="editor2" contenteditable="true" style="border:1px solid #ccc;padding:10px;min-height:50px;">
                <p>Type here...</p>
            </div>

            <h3>3. Regular input (for comparison)</h3>
            <input id="input1" type="text" placeholder="Regular input" />

            <script>
                // Track content changes
                window.editor1Content = '';
                window.editor2Content = '';

                document.getElementById('editor1').addEventListener('input', (e) => {
                    window.editor1Content = e.target.innerText;
                });
                document.getElementById('editor2').addEventListener('input', (e) => {
                    window.editor2Content = e.target.innerText;
                });
            </script>
        </body>
        </html>
        """

        # Write to file and use file:// URL (data: URLs don't work well with extension)
        test_file = Path("/tmp/contenteditable_test.html")
        test_file.write_text(test_html.strip())
        file_url = f"file://{test_file}"
        await bridge.navigate(tab_id, file_url, wait_until="load")
        print("✓ Page loaded")

        # Screenshot with timeout protection
        try:
            screenshot = await asyncio.wait_for(bridge.screenshot(tab_id), timeout=10.0)
            print(f"Screenshot: {len(screenshot.get('data', ''))} bytes")
        except asyncio.TimeoutError:
            print("Screenshot timed out (skipping)")

        # Detect contenteditable
        print("\n--- Detecting contenteditable elements ---")
        detection = await bridge.evaluate(
            tab_id,
            """
            (function() {
                const editables = document.querySelectorAll('[contenteditable="true"]');
                return {
                    count: editables.length,
                    ids: Array.from(editables).map(el => el.id)
                };
            })();
        """
        )
        print(f"Contenteditable detection: {detection.get('result', {})}")

        # Test 1: Type into regular input (baseline)
        print("\n--- Test 1: Regular input ---")
        await bridge.click(tab_id, "#input1")
        await bridge.type_text(tab_id, "#input1", "Hello input")
        input_result = await bridge.evaluate(
            tab_id,
            "(function() { return document.getElementById('input1').value; })()"
        )
        print(f"Input value: {input_result.get('result', '')}")

        # Test 2: Type into contenteditable div
        print("\n--- Test 2: Contenteditable div ---")
        await bridge.click(tab_id, "#editor1")
        await bridge.type_text(tab_id, "#editor1", "Hello contenteditable", clear_first=True)
        editor_result = await bridge.evaluate(
            tab_id,
            "(function() { return document.getElementById('editor1').innerText; })()"
        )
        print(f"Editor1 innerText: {editor_result.get('result', '')}")

        # Test 3: Use JavaScript insertText for rich editor
        print("\n--- Test 3: JavaScript insertText for rich editor ---")
        insert_result = await bridge.evaluate(
            tab_id,
            """
            (function() {
                const editor = document.getElementById('editor2');
                editor.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, 'Hello from execCommand');
                return editor.innerText;
            })();
        """
        )
        print(f"Editor2 after execCommand: {insert_result.get('result', '')}")

        # Screenshot after with timeout protection
        try:
            screenshot_after = await asyncio.wait_for(bridge.screenshot(tab_id), timeout=10.0)
            print(f"Screenshot after: {len(screenshot_after.get('data', ''))} bytes")
        except asyncio.TimeoutError:
            print("Screenshot after timed out (skipping)")

        # Results
        print("\n--- Results ---")
        input_val = input_result.get("result", "")
        editor1_val = editor_result.get("result", "")
        editor2_val = insert_result.get("result", "")

        input_pass = "Hello input" in input_val
        editor1_pass = "Hello contenteditable" in editor1_val
        editor2_pass = "execCommand" in editor2_val

        print(f"Input: {'✓ PASS' if input_pass else '✗ FAIL'} - {input_val}")
        print(f"Editor1: {'✓ PASS' if editor1_pass else '✗ FAIL'} - {editor1_val}")
        print(f"Editor2: {'✓ PASS' if editor2_pass else '✗ FAIL'} - {editor2_val}")

        await bridge.destroy_context(group_id)
        print("\n✓ Context destroyed")

    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(test_contenteditable())
