"""
Browser advanced tools - wait, evaluate, get_text, get_attribute, resize, upload, dialog.

Tools for advanced browser operations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
)

from ..highlight import highlight_element
from ..session import DEFAULT_TIMEOUT_MS, get_session


def register_advanced_tools(mcp: FastMCP) -> None:
    """Register browser advanced tools."""

    @mcp.tool()
    async def browser_wait(
        wait_ms: int = 1000,
        selector: str | None = None,
        text: str | None = None,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Wait for a condition.

        Args:
            wait_ms: Time to wait in milliseconds (if no selector/text provided)
            selector: Wait for element to appear (optional)
            text: Wait for text to appear on page (optional)
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Maximum wait time in milliseconds (default: 30000)

        Returns:
            Dict with wait result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            if selector:
                await page.wait_for_selector(selector, timeout=timeout_ms)
                return {"ok": True, "action": "wait", "condition": "selector", "selector": selector}
            elif text:
                await page.wait_for_function(
                    f"document.body.innerText.includes('{text}')",
                    timeout=timeout_ms,
                )
                return {"ok": True, "action": "wait", "condition": "text", "text": text}
            else:
                await page.wait_for_timeout(wait_ms)
                return {"ok": True, "action": "wait", "condition": "time", "ms": wait_ms}
        except PlaywrightTimeout:
            return {"ok": False, "error": "Wait condition not met within timeout"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Wait failed: {e!s}"}

    @mcp.tool()
    async def browser_evaluate(
        script: str,
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Execute JavaScript in the browser context.

        Args:
            script: JavaScript code to execute
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with evaluation result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            result = await page.evaluate(script)
            return {"ok": True, "action": "evaluate", "result": result}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Evaluate failed: {e!s}"}

    @mcp.tool()
    async def browser_get_text(
        selector: str,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Get text content of an element.

        Args:
            selector: CSS selector or element ref
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with element text content
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            element = await page.wait_for_selector(selector, timeout=timeout_ms)
            if not element:
                return {"ok": False, "error": f"Element not found: {selector}"}

            text = await element.text_content()
            return {"ok": True, "selector": selector, "text": text}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Get text failed: {e!s}"}

    @mcp.tool()
    async def browser_get_attribute(
        selector: str,
        attribute: str,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Get an attribute value of an element.

        Args:
            selector: CSS selector or element ref
            attribute: Attribute name to get (e.g., 'href', 'src', 'value')
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with attribute value
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            element = await page.wait_for_selector(selector, timeout=timeout_ms)
            if not element:
                return {"ok": False, "error": f"Element not found: {selector}"}

            value = await element.get_attribute(attribute)
            return {"ok": True, "selector": selector, "attribute": attribute, "value": value}
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Get attribute failed: {e!s}"}

    @mcp.tool()
    async def browser_resize(
        width: int,
        height: int,
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Resize the browser viewport.

        Args:
            width: Viewport width in pixels
            height: Viewport height in pixels
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with resize result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            await page.set_viewport_size({"width": width, "height": height})
            return {
                "ok": True,
                "action": "resize",
                "width": width,
                "height": height,
            }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Resize failed: {e!s}"}

    @mcp.tool()
    async def browser_upload(
        selector: str,
        file_paths: list[str],
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Upload files to a file input element.

        Args:
            selector: CSS selector for the file input element
            file_paths: List of file paths to upload
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout in milliseconds (default: 30000)

        Returns:
            Dict with upload result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            # Verify files exist
            for path in file_paths:
                if not Path(path).exists():
                    return {"ok": False, "error": f"File not found: {path}"}

            await highlight_element(page, selector)

            element = await page.wait_for_selector(selector, timeout=timeout_ms)
            if not element:
                return {"ok": False, "error": f"Element not found: {selector}"}

            await element.set_input_files(file_paths)
            return {
                "ok": True,
                "action": "upload",
                "selector": selector,
                "files": file_paths,
                "count": len(file_paths),
            }
        except PlaywrightTimeout:
            return {"ok": False, "error": f"Element not found: {selector}"}
        except PlaywrightError as e:
            return {"ok": False, "error": f"Upload failed: {e!s}"}

    @mcp.tool()
    async def browser_dialog(
        action: Literal["accept", "dismiss"] = "accept",
        prompt_text: str | None = None,
        target_id: str | None = None,
        profile: str = "default",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        """
        Handle browser dialogs (alert, confirm, prompt).

        This sets up a handler for the next dialog that appears.
        Call this BEFORE triggering the action that opens the dialog.

        Args:
            action: How to handle the dialog - "accept" or "dismiss"
            prompt_text: Text to enter for prompt dialogs (optional)
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout waiting for dialog (default: 30000)

        Returns:
            Dict with dialog handling result
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            dialog_info: dict = {"handled": False}

            async def handle_dialog(dialog):
                dialog_info["type"] = dialog.type
                dialog_info["message"] = dialog.message
                dialog_info["handled"] = True
                if action == "accept":
                    if prompt_text is not None:
                        await dialog.accept(prompt_text)
                    else:
                        await dialog.accept()
                else:
                    await dialog.dismiss()

            page.once("dialog", handle_dialog)

            # Wait briefly for dialog to appear
            await page.wait_for_timeout(min(timeout_ms, 1000))

            if dialog_info["handled"]:
                return {
                    "ok": True,
                    "action": action,
                    "dialogType": dialog_info.get("type"),
                    "dialogMessage": dialog_info.get("message"),
                }
            else:
                return {
                    "ok": True,
                    "action": "handler_set",
                    "message": "Dialog handler set, will handle next dialog",
                }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Dialog handling failed: {e!s}"}
