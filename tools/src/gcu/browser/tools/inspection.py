"""
Browser inspection tools - screenshot, console, pdf, snapshots.

Tools for extracting content and capturing page state.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from playwright.async_api import Error as PlaywrightError

from ..session import get_session


def _format_ax_tree(nodes: list[dict[str, Any]]) -> str:
    """Format a CDP Accessibility.getFullAXTree result into an indented text tree.

    Each node is rendered as:
        indent + "- " + role + ' "name"' + [properties]

    Ignored and invisible nodes are skipped.
    """
    if not nodes:
        return "(empty tree)"

    # Build nodeId → node lookup
    by_id = {n["nodeId"]: n for n in nodes}

    # Build nodeId → [child nodeId] mapping
    children_map: dict[str, list[str]] = {}
    for n in nodes:
        for child_id in n.get("childIds", []):
            children_map.setdefault(n["nodeId"], []).append(child_id)

    lines: list[str] = []

    def _walk(node_id: str, depth: int) -> None:
        node = by_id.get(node_id)
        if not node:
            return

        # Skip ignored nodes
        if node.get("ignored", False):
            # Still walk children — they may be visible
            for cid in children_map.get(node_id, []):
                _walk(cid, depth)
            return

        role_info = node.get("role", {})
        role = role_info.get("value", "unknown") if isinstance(role_info, dict) else str(role_info)

        # Skip generic/none roles that add no information
        if role in ("none", "Ignored"):
            for cid in children_map.get(node_id, []):
                _walk(cid, depth)
            return

        name_info = node.get("name", {})
        name = name_info.get("value", "") if isinstance(name_info, dict) else str(name_info)

        # Build property annotations
        props: list[str] = []
        for prop in node.get("properties", []):
            pname = prop.get("name", "")
            pval = prop.get("value", {})
            val = pval.get("value") if isinstance(pval, dict) else pval
            if pname in ("focused", "disabled", "checked", "expanded", "selected", "required"):
                if val is True:
                    props.append(pname)
            elif pname == "level" and val:
                props.append(f"level={val}")

        indent = "  " * depth
        label = f"- {role}"
        if name:
            label += f' "{name}"'
        if props:
            label += f" [{', '.join(props)}]"

        lines.append(f"{indent}{label}")

        for cid in children_map.get(node_id, []):
            _walk(cid, depth + 1)

    # Root is the first node in the list
    _walk(nodes[0]["nodeId"], 0)

    return "\n".join(lines) if lines else "(empty tree)"


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
    async def browser_snapshot(
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Get an AI-optimized accessibility snapshot of the page.

        Uses Playwright's aria_snapshot() to return a compact, indented text tree
        with role/name annotations. Much smaller than raw HTML and ideal for LLM
        consumption — typically 1-5 KB vs 100+ KB of HTML.

        Output format example:
            - navigation "Main":
              - link "Home"
              - link "About"
            - main:
              - heading "Welcome"
              - textbox "Search"

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with the snapshot text tree, URL, and target ID
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            snapshot = await page.locator(":root").aria_snapshot()

            return {
                "ok": True,
                "targetId": target_id or session.active_page_id,
                "url": page.url,
                "snapshot": snapshot,
            }
        except PlaywrightError as e:
            return {"ok": False, "error": f"Browser error: {e!s}"}

    @mcp.tool()
    async def browser_snapshot_aria(
        target_id: str | None = None,
        profile: str = "default",
    ) -> dict:
        """
        Get a full CDP accessibility tree snapshot of the page.

        Uses Chrome DevTools Protocol (Accessibility.getFullAXTree) to return
        the complete, low-level accessibility tree. More verbose than
        browser_snapshot but includes all ARIA properties and states.

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with the formatted accessibility tree, URL, and target ID
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            if not session.context:
                return {"ok": False, "error": "No browser context"}

            cdp = await session.context.new_cdp_session(page)
            try:
                result = await cdp.send("Accessibility.getFullAXTree")
                ax_nodes = result.get("nodes", [])
                snapshot = _format_ax_tree(ax_nodes)
            finally:
                await cdp.detach()

            return {
                "ok": True,
                "targetId": target_id or session.active_page_id,
                "url": page.url,
                "snapshot": snapshot,
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
