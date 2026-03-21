"""
Browser inspection tools - screenshot, console, pdf, snapshots.

Tools for extracting content and capturing page state.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
from playwright.async_api import Error as PlaywrightError

from ..session import get_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Screenshot normalization
# ---------------------------------------------------------------------------

_QUALITY_STEPS = (85, 70, 50)
_MIN_DIMENSION = 400
_DIMENSION_STEP = 200


def _normalize_screenshot(
    raw_bytes: bytes,
    image_type: str,
    *,
    max_dimension: int = 2000,
    max_bytes: int = 5_000_000,
) -> tuple[bytes, str]:
    """Normalize a screenshot to fit within size and dimension limits.

    Progressively resizes and compresses to JPEG until the image fits
    under *max_bytes* and *max_dimension*.  If Pillow is not installed
    the original bytes are returned unchanged.

    Args:
        raw_bytes: Raw PNG or JPEG image bytes from Playwright.
        image_type: Original format (``"png"`` or ``"jpeg"``).
        max_dimension: Maximum width or height in pixels.
        max_bytes: Maximum file size in bytes.

    Returns:
        ``(normalized_bytes, image_type)`` where *image_type* may change
        to ``"jpeg"`` if compression was applied.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.debug("Pillow not installed — skipping screenshot normalization")
        return raw_bytes, image_type

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        width, height = img.size
        max_dim = max(width, height)

        # Already within limits — return as-is
        if len(raw_bytes) <= max_bytes and max_dim <= max_dimension:
            return raw_bytes, image_type

        # Build candidate dimensions (descending), skip anything >= original
        candidates = [
            d for d in range(max_dimension, _MIN_DIMENSION - 1, -_DIMENSION_STEP) if d < max_dim
        ]
        # If the original is already <= max_dimension but over max_bytes,
        # still try compressing at original size first.
        if max_dim <= max_dimension:
            candidates = [max_dim] + candidates

        smallest: tuple[bytes, int] | None = None

        for side in candidates:
            # Re-open from source each iteration (thumbnail is destructive)
            img = Image.open(io.BytesIO(raw_bytes))
            img.thumbnail((side, side), Image.LANCZOS)

            # JPEG doesn't support alpha
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")

            for quality in _QUALITY_STEPS:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                out_bytes = buf.getvalue()

                if smallest is None or len(out_bytes) < smallest[1]:
                    smallest = (out_bytes, len(out_bytes))

                if len(out_bytes) <= max_bytes:
                    return out_bytes, "jpeg"

        # Nothing fit — return the smallest we produced
        if smallest is not None:
            logger.warning(
                "Screenshot normalization: could not fit under %d bytes (best: %d bytes)",
                max_bytes,
                smallest[1],
            )
            return smallest[0], "jpeg"

        return raw_bytes, image_type

    except Exception:
        logger.warning("Screenshot normalization failed — returning original", exc_info=True)
        return raw_bytes, image_type


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
    ) -> list:
        """
        Take a screenshot of the current page.

        Returns the screenshot as an image the LLM can see, alongside
        text metadata (URL, size, etc.).

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            full_page: Capture full scrollable page (default: False)
            selector: CSS selector to screenshot specific element (optional)
            image_type: Image format - png or jpeg (default: png)

        Returns:
            List of content blocks: text metadata + image
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return [
                    TextContent(
                        type="text", text=json.dumps({"ok": False, "error": "No active tab"})
                    )
                ]

            if selector:
                from ..refs import resolve_selector

                selector = resolve_selector(selector, session, target_id)
                element = await page.query_selector(selector)
                if not element:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {"ok": False, "error": f"Element not found: {selector}"}
                            ),
                        )
                    ]
                screenshot_bytes = await element.screenshot(type=image_type)
            else:
                screenshot_bytes = await page.screenshot(
                    full_page=full_page,
                    type=image_type,
                )

            normalized_bytes, normalized_type = _normalize_screenshot(screenshot_bytes, image_type)
            meta = json.dumps(
                {
                    "ok": True,
                    "targetId": target_id or session.active_page_id,
                    "url": page.url,
                    "imageType": normalized_type,
                    "size": len(normalized_bytes),
                    "originalSize": len(screenshot_bytes),
                }
            )
            return [
                TextContent(type="text", text=meta),
                ImageContent(
                    type="image",
                    data=base64.b64encode(normalized_bytes).decode(),
                    mimeType=f"image/{normalized_type}",
                ),
            ]
        except PlaywrightError as e:
            return [
                TextContent(
                    type="text", text=json.dumps({"ok": False, "error": f"Browser error: {e!s}"})
                )
            ]

    @mcp.tool()
    async def browser_snapshot(
        target_id: str | None = None,
        profile: str = "default",
        mode: Literal["aria", "cdp"] = "aria",
    ) -> dict:
        """
        Get an accessibility snapshot of the page.

        Two modes:
          - "aria" (default): Uses Playwright's aria_snapshot() for a compact,
            indented text tree with role/name annotations. Much smaller than raw
            HTML and ideal for LLM consumption — typically 1-5 KB vs 100+ KB.
          - "cdp": Uses Chrome DevTools Protocol (Accessibility.getFullAXTree)
            for the complete, low-level accessibility tree. More verbose but
            includes all ARIA properties and states.

        Aria output format example:
            - navigation "Main":
              - link "Home"
              - link "About"
            - main:
              - heading "Welcome"
              - textbox "Search"

        Args:
            target_id: Tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            mode: Snapshot mode - "aria" (compact) or "cdp" (full tree). Default: "aria"

        Returns:
            Dict with the snapshot text tree, URL, and target ID
        """
        try:
            session = get_session(profile)
            page = session.get_page(target_id)
            if not page:
                return {"ok": False, "error": "No active tab"}

            if mode == "cdp":
                if not session.context:
                    return {"ok": False, "error": "No browser context"}

                cdp = await session.context.new_cdp_session(page)
                try:
                    result = await cdp.send("Accessibility.getFullAXTree")
                    ax_nodes = result.get("nodes", [])
                    snapshot = _format_ax_tree(ax_nodes)
                finally:
                    await cdp.detach()
            else:
                snapshot = await page.locator(":root").aria_snapshot()
                # Annotate with [ref=eN] markers for interactive elements
                from ..refs import annotate_snapshot

                snapshot, ref_map = annotate_snapshot(snapshot)
                tid = target_id or session.active_page_id
                if tid:
                    session.ref_maps[tid] = ref_map

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
