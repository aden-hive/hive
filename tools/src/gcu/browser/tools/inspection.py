"""
Browser inspection tools - screenshot, console, pdf.

Tools for extracting content and capturing page state.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from playwright.async_api import Error as PlaywrightError

from ..session import get_session


def register_inspection_tools(mcp: FastMCP) -> None:
    """Register browser inspection tools."""

    @mcp.tool()
    async def browser_screenshot(
        target_id: str | None = None,
        profile: str = "default",
        full_page: bool = False,
        selector: str | None = None,
        image_type: Literal["png", "jpeg"] = "png",
    ) -> dict:
        """
        Take a screenshot of the current page.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            full_page: Capture full scrollable page (default: False)
            selector: CSS selector to screenshot specific element (optional)
            image_type: Image format - png or jpeg (default: png)

        Returns:
            Dict with screenshot data (base64 encoded) and metadata
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            if selector:
                element = await page.query_selector(selector)
                if not element:
                    return {"ok": False, "error": f"Element not found: {selector}"}
                screenshot_bytes = await element.screenshot(type=image_type)
            else:
                screenshot_bytes = await page.screenshot(
                    full_page=full_page,
                    type=image_type,
                )

            return {
                "ok": True,
                "targetId": target_id or session.active_page_id,
                "url": page.url,
                "imageType": image_type,
                "imageBase64": base64.b64encode(screenshot_bytes).decode(),
                "size": len(screenshot_bytes),
            }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Browser error: {e!s}"}

    @mcp.tool()
    async def browser_console(
        target_id: str | None = None,
        profile: str = "default",
        level: str | None = None,
    ) -> dict:
        """
        Get console messages from the browser.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            level: Filter by level (log, info, warn, error) (optional)

        Returns:
            Dict with console messages
        """
        session = get_session(profile)
        tid = target_id or session.active_page_id
        if not tid:
            return {"ok": False, "error": "No active tab"}

        messages = session.console_messages.get(tid, [])
        if level:
            messages = [m for m in messages if m.get("type") == level]

        return {
            "ok": True,
            "targetId": tid,
            "messages": messages,
            "count": len(messages),
        }

    @mcp.tool()
    async def browser_pdf(
        target_id: str | None = None,
        profile: str = "default",
        path: str | None = None,
    ) -> dict:
        """
        Save the current page as PDF.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            path: File path to save PDF (optional, returns base64 if not provided)

        Returns:
            Dict with PDF data or file path
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            pdf_bytes = await page.pdf()

            if path:
                Path(path).write_bytes(pdf_bytes)
                return {
                    "ok": True,
                    "targetId": target_id or session.active_page_id,
                    "path": path,
                    "size": len(pdf_bytes),
                }
            else:
                return {
                    "ok": True,
                    "targetId": target_id or session.active_page_id,
                    "pdfBase64": base64.b64encode(pdf_bytes).decode(),
                    "size": len(pdf_bytes),
                }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Browser error: {e!s}"}
