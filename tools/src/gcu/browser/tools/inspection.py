"""
Browser inspection tools - screenshot, snapshot, console.

All operations go through the Beeline extension via CDP - no Playwright required.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
from typing import Literal

from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from ..bridge import get_bridge
from ..telemetry import log_tool_call
from .tabs import _get_context

logger = logging.getLogger(__name__)


# Fixed output width for all screenshots. Chosen well below Anthropic's
# ~1568-px vision-API resize threshold so the image the server emits is
# the SAME image (pixel-for-pixel) the LLM sees. That preserves
# image_px == model_px, which is the cornerstone of the "LLM works in
# screenshot pixels only" contract — all click/hover/press/rect tools
# translate between image pixels and CSS pixels internally.
_SCREENSHOT_WIDTH = 800

# Per-tab scale caches populated on every browser_screenshot and on
# lazy-init inside the click tools. Both are ``image_px × scale =
# target_px`` multipliers.
# - _screenshot_scales[tab]      → physical scale (image → physical px, debug only)
# - _screenshot_css_scales[tab]  → css scale      (image → CSS px, used for Input events)
_screenshot_scales: dict[int, float] = {}
_screenshot_css_scales: dict[int, float] = {}


def _resize_and_annotate(
    data: str,
    css_width: int,
    dpr: float = 1.0,
    highlights: list[dict] | None = None,
) -> tuple[str, float, float]:
    """Resize the captured PNG down to ``_SCREENSHOT_WIDTH`` (=800 px)
    and re-encode as JPEG quality 75.

    CDP captures at the physical-pixel resolution (DPR × CSS). We
    downscale to 800 px wide so the delivered image stays under
    Anthropic's vision-API resize cap — the model sees pixel-for-pixel
    what we send.

    Returns ``(new_b64, physical_scale, css_scale)`` where
    - ``physical_scale = orig_png_w / _SCREENSHOT_WIDTH`` (image → physical px)
    - ``css_scale      = css_width / _SCREENSHOT_WIDTH`` (image → CSS px)

    Highlight rects arrive in CSS px and are divided by ``css_scale``
    before drawing so overlays land in the correct spot on the
    800-wide output.
    """
    if not css_width or css_width <= 0:
        # Bridge always supplies css_width from window.innerWidth; only
        # reach here on a degraded response. Return the raw PNG.
        return data, 1.0, 1.0

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raw = base64.b64decode(data) if data else b""
        orig_w = 0
        if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
            import struct

            orig_w = struct.unpack(">I", raw[16:20])[0]
        physical_scale = orig_w / _SCREENSHOT_WIDTH if orig_w else 1.0
        css_scale = css_width / _SCREENSHOT_WIDTH
        logger.warning(
            "PIL not available — screenshot resize SKIPPED. "
            "Returning raw physical-px PNG. physicalScale=%.4f, "
            "cssScale=%.4f, css_width=%d, dpr=%s. Install Pillow for correct clicks.",
            physical_scale,
            css_scale,
            css_width,
            dpr,
        )
        return data, round(physical_scale, 4), round(css_scale, 4)

    try:
        raw = base64.b64decode(data)
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        orig_w, orig_h = img.size

        physical_scale = orig_w / _SCREENSHOT_WIDTH
        css_scale = css_width / _SCREENSHOT_WIDTH
        new_w = _SCREENSHOT_WIDTH
        new_h = round(orig_h * new_w / orig_w)
        if (new_w, new_h) != img.size:
            img = img.resize((new_w, new_h), Image.LANCZOS)

        logger.info(
            "Screenshot: orig=%dx%d → out=%dx%d (css_width=%d, dpr=%s), physicalScale=%.4f, cssScale=%.4f",
            orig_w,
            orig_h,
            new_w,
            new_h,
            css_width,
            dpr,
            physical_scale,
            css_scale,
        )

        if highlights:
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
            except Exception:
                font = ImageFont.load_default()

            for h in highlights:
                kind = h.get("kind", "rect")
                label = h.get("label", "")
                # Highlights arrive in CSS px → convert to image px.
                ix = h["x"] / css_scale
                iy = h["y"] / css_scale
                iw = h.get("w", 0) / css_scale
                ih = h.get("h", 0) / css_scale

                if kind == "point":
                    cx, cy, r = ix, iy, 10
                    draw.ellipse(
                        [(cx - r, cy - r), (cx + r, cy + r)],
                        fill=(239, 68, 68, 100),
                        outline=(239, 68, 68, 220),
                        width=2,
                    )
                    draw.line([(cx - r - 4, cy), (cx + r + 4, cy)], fill=(239, 68, 68, 220), width=2)
                    draw.line([(cx, cy - r - 4), (cx, cy + r + 4)], fill=(239, 68, 68, 220), width=2)
                else:
                    draw.rectangle(
                        [(ix, iy), (ix + iw, iy + ih)],
                        fill=(59, 130, 246, 70),
                        outline=(59, 130, 246, 220),
                        width=2,
                    )

                display_label = f"({round(ix)},{round(iy)}) {label}".strip()
                lx, ly = ix, max(2, iy - 16)
                lx = max(2, min(lx, new_w - 120))
                bbox = draw.textbbox((lx, ly), display_label, font=font)
                pad = 3
                draw.rectangle(
                    [(bbox[0] - pad, bbox[1] - pad), (bbox[2] + pad, bbox[3] + pad)],
                    fill=(59, 130, 246, 200),
                )
                draw.text((lx, ly), display_label, fill=(255, 255, 255, 255), font=font)

            img = Image.alpha_composite(img, overlay).convert("RGB")
        else:
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        return (
            base64.b64encode(buf.getvalue()).decode(),
            round(physical_scale, 4),
            round(css_scale, 4),
        )
    except Exception:
        logger.warning(
            "Screenshot resize/annotate FAILED — returning original image. "
            "css_width=%s, dpr=%s.",
            css_width,
            dpr,
            exc_info=True,
        )
        return data, 1.0, 1.0


async def _ensure_css_scale(tab_id: int) -> float:
    """Return the image→CSS scale for ``tab_id``, populating the cache
    via ``window.innerWidth`` if missing. Used by click tools when the
    agent clicks before the first screenshot has been taken.
    """
    cached = _screenshot_css_scales.get(tab_id)
    if cached is not None and cached > 0:
        return cached
    bridge = get_bridge()
    try:
        result = await bridge.evaluate(tab_id, "({w: window.innerWidth})")
        inner = float(((result or {}).get("result") or {}).get("w") or 0)
    except Exception:
        inner = 0.0
    if inner <= 0:
        # Degraded: no viewport width available. Treat image px as CSS px.
        scale = 1.0
    else:
        scale = inner / _SCREENSHOT_WIDTH
    _screenshot_css_scales[tab_id] = scale
    return scale


def register_inspection_tools(mcp: FastMCP) -> None:
    """Register browser inspection tools."""

    @mcp.tool()
    async def browser_screenshot(
        tab_id: int | None = None,
        profile: str | None = None,
        full_page: bool = False,
        selector: str | None = None,
        annotate: bool = True,
    ) -> list:
        """
        Take a screenshot of the current page.

        Image is 800 px wide (JPEG quality 75, ~50–120 KB). A pixel you
        see in this image is the same number you pass to
        ``browser_click_coordinate`` / ``browser_hover_coordinate`` /
        ``browser_press_at`` — the tools translate to CSS internally.
        ``browser_get_rect`` and ``browser_shadow_query`` likewise
        return coordinates in screenshot pixels.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            full_page: Capture full scrollable page (default: False)
            selector: CSS selector to screenshot a specific element (optional)
            annotate: Draw bounding box of last interaction on image (default: True)

        Returns:
            List of content blocks: text metadata + image
        """
        start = time.perf_counter()
        params = {
            "tab_id": tab_id,
            "profile": profile,
            "full_page": full_page,
            "selector": selector,
        }

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = [
                TextContent(
                    type="text",
                    text=json.dumps({"ok": False, "error": "Extension not connected"}),
                )
            ]
            log_tool_call(
                "browser_screenshot",
                params,
                result={"ok": False, "error": "Extension not connected"},
            )
            return result

        ctx = _get_context(profile)
        if not ctx:
            err_msg = json.dumps({"ok": False, "error": "Browser not started"})
            log_tool_call("browser_screenshot", params, result={"ok": False, "error": "Browser not started"})
            return [TextContent(type="text", text=err_msg)]

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = [TextContent(type="text", text=json.dumps({"ok": False, "error": "No active tab"}))]
            log_tool_call("browser_screenshot", params, result={"ok": False, "error": "No active tab"})
            return result

        try:
            screenshot_result = await bridge.screenshot(target_tab, full_page=full_page, selector=selector)

            if not screenshot_result.get("ok"):
                log_tool_call(
                    "browser_screenshot",
                    params,
                    result=screenshot_result,
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
                return [TextContent(type="text", text=json.dumps(screenshot_result))]

            data = screenshot_result.get("data")
            css_width = screenshot_result.get("cssWidth", 0)
            dpr = screenshot_result.get("devicePixelRatio", 1.0)

            # Collect highlights: last interaction from bridge + CDP already drew in browser
            from ..bridge import _interaction_highlights

            highlights: list[dict] | None = None
            if annotate and target_tab in _interaction_highlights:
                highlights = [_interaction_highlights[target_tab]]

            # Resize to CSS-viewport dimensions (image px == CSS px)
            # and re-encode as JPEG. Offloaded to a thread because PIL
            # Image.open/resize/ImageDraw/composite on a 2-megapixel
            # PNG blocks for ~150–300 ms of CPU — plenty to freeze the
            # asyncio event loop. Reentrant: no shared state.
            data, physical_scale, css_scale = await asyncio.to_thread(
                _resize_and_annotate,
                data,
                css_width,
                dpr,
                highlights,
            )
            # Refresh caches so click / hover / press / rect tools can
            # translate image px ↔ CSS px without asking the page again.
            if target_tab is not None:
                _screenshot_scales[target_tab] = physical_scale
                _screenshot_css_scales[target_tab] = css_scale

            meta = json.dumps(
                {
                    "ok": True,
                    "tabId": target_tab,
                    "url": screenshot_result.get("url", ""),
                    "imageType": "jpeg",
                    "size": len(base64.b64decode(data)) if data else 0,
                    "imageWidth": _SCREENSHOT_WIDTH,
                    "cssWidth": css_width,
                    "fullPage": full_page,
                    "devicePixelRatio": dpr,
                    "physicalScale": physical_scale,
                    "cssScale": css_scale,
                    "annotated": bool(highlights),
                    "scaleHint": (
                        "Image is 800 px wide. Pass pixel coordinates "
                        "you read off this image straight into "
                        "browser_click_coordinate / "
                        "browser_hover_coordinate / browser_press_at — "
                        "the tools translate image px → CSS px "
                        "internally (cssScale is for debug only)."
                    ),
                }
            )

            log_tool_call(
                "browser_screenshot",
                params,
                result={
                    "ok": True,
                    "size": len(base64.b64decode(data)) if data else 0,
                    "url": screenshot_result.get("url", ""),
                    "cssWidth": css_width,
                    "cssScale": css_scale,
                    "physicalScale": physical_scale,
                    "dpr": dpr,
                },
                duration_ms=(time.perf_counter() - start) * 1000,
            )

            return [
                TextContent(type="text", text=meta),
                ImageContent(type="image", data=data, mimeType="image/jpeg"),
            ]
        except Exception as e:
            log_tool_call(
                "browser_screenshot",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return [TextContent(type="text", text=json.dumps({"ok": False, "error": str(e)}))]

    @mcp.tool()
    async def browser_shadow_query(
        selector: str,
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Shadow-piercing querySelector using '>>>' syntax.

        Traverses shadow roots to find elements inside closed/open shadow DOM,
        overlays, and virtual-rendered components (e.g. LinkedIn's #interop-outlet).
        Returns the element's bounding rect in screenshot pixels — feed
        ``rect.cx`` / ``rect.cy`` straight into browser_click_coordinate
        / hover_coordinate / press_at.

        Args:
            selector: CSS selectors joined by ' >>> ' to pierce shadow roots.
                      Example: '#interop-outlet >>> #ember37 >>> p'
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with ``rect`` block (x, y, w, h, cx, cy) in screenshot pixels.
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}
        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}
        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        result = await bridge.shadow_query(target_tab, selector)
        if not result.get("ok"):
            return result

        rect = result["rect"]
        css_scale = await _ensure_css_scale(target_tab)
        s = css_scale if css_scale > 0 else 1.0
        return {
            "ok": True,
            "selector": selector,
            "tag": rect.get("tag"),
            "rect": {
                "x": round(rect["x"] / s, 1),
                "y": round(rect["y"] / s, 1),
                "w": round(rect["w"] / s, 1),
                "h": round(rect["h"] / s, 1),
                "cx": round(rect["cx"] / s, 1),
                "cy": round(rect["cy"] / s, 1),
            },
            "note": (
                "rect fields are in screenshot pixels. Pass rect.cx / "
                "rect.cy to browser_click_coordinate / "
                "hover_coordinate / press_at."
            ),
        }

    @mcp.tool()
    async def browser_get_rect(
        selector: str,
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Get the bounding rect of an element by CSS selector.

        Supports '>>>' shadow-piercing selectors for overlay/shadow DOM
        content. Returns the rect in screenshot pixels — the same
        numbers you'd read off a browser_screenshot, and the same
        numbers browser_click_coordinate expects.

        Args:
            selector: CSS selector, optionally with ' >>> ' to pierce shadow roots.
                      Example: 'button.submit' or '#shadow-host >>> button'
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with ``rect`` block (x, y, w, h, cx, cy) in screenshot pixels.
        """
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": "Browser extension not connected"}
        ctx = _get_context(profile)
        if not ctx:
            return {"ok": False, "error": "Browser not started"}
        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            return {"ok": False, "error": "No active tab"}

        result = await bridge.shadow_query(target_tab, selector)
        if not result.get("ok"):
            return result

        rect = result["rect"]
        css_scale = await _ensure_css_scale(target_tab)
        s = css_scale if css_scale > 0 else 1.0
        return {
            "ok": True,
            "selector": selector,
            "tag": rect.get("tag"),
            "rect": {
                "x": round(rect["x"] / s, 1),
                "y": round(rect["y"] / s, 1),
                "w": round(rect["w"] / s, 1),
                "h": round(rect["h"] / s, 1),
                "cx": round(rect["cx"] / s, 1),
                "cy": round(rect["cy"] / s, 1),
            },
            "note": (
                "rect fields are in screenshot pixels. Pass rect.cx / "
                "rect.cy to browser_click_coordinate / "
                "hover_coordinate / press_at."
            ),
        }

    @mcp.tool()
    async def browser_snapshot(
        tab_id: int | None = None,
        profile: str | None = None,
        mode: Literal["default", "simple", "interactive"] = "default",
    ) -> dict:
        """
        Get an accessibility snapshot of the page.

        Uses CDP Accessibility.getFullAXTree to build a compact, readable
        tree of the page's interactive elements. Ideal for LLM consumption.

        Output format example:
            - navigation "Main":
              - link "Home" [ref=e1]
              - link "About" [ref=e2]
            - main:
              - heading "Welcome"
              - textbox "Search" [ref=e3]

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            mode: Snapshot filtering mode (default: "default")
                - "default": full accessibility tree
                - "simple": interactive + content nodes, skip unnamed structural nodes
                - "interactive": only interactive nodes (buttons, links, inputs, etc.)

        Returns:
            Dict with the snapshot text tree, URL, and tab ID
        """
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile, "mode": mode}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_snapshot", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_snapshot", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_snapshot", params, result=result)
            return result

        try:
            snapshot_result = await bridge.snapshot(target_tab, mode=mode)
            log_tool_call(
                "browser_snapshot",
                params,
                result=snapshot_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return snapshot_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_snapshot",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

    @mcp.tool()
    async def browser_console(
        tab_id: int | None = None,
        profile: str | None = None,
        level: str | None = None,
    ) -> dict:
        """
        Get console messages from the browser.

        Note: Console capture requires Runtime.enable and event handling.
        Currently returns a message indicating this feature needs implementation.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            level: Filter by level (log, info, warn, error) (optional)

        Returns:
            Dict with console messages
        """
        result = {
            "ok": True,
            "message": "Console capture not yet implemented",
            "suggestion": "Use browser_evaluate to check specific values or errors",
        }
        log_tool_call("browser_console", {"tab_id": tab_id, "profile": profile, "level": level}, result=result)
        return result

    @mcp.tool()
    async def browser_html(
        tab_id: int | None = None,
        profile: str | None = None,
        selector: str | None = None,
    ) -> dict:
        """
        Get the HTML content of the page or a specific element.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            selector: CSS selector to get specific element HTML (optional)

        Returns:
            Dict with HTML content
        """
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile, "selector": selector}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_html", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_html", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_html", params, result=result)
            return result

        try:
            import json as json_mod

            if selector:
                sel_json = json_mod.dumps(selector)
                script = (
                    f"(function() {{ const el = document.querySelector({sel_json}); "
                    f"return el ? el.outerHTML : null; }})()"
                )
            else:
                script = "document.documentElement.outerHTML"

            eval_result = await bridge.evaluate(target_tab, script)

            if eval_result.get("ok"):
                result = {
                    "ok": True,
                    "tabId": target_tab,
                    "html": eval_result.get("result"),
                    "selector": selector,
                }
                log_tool_call(
                    "browser_html",
                    params,
                    result={
                        "ok": True,
                        "selector": selector,
                        "html_length": len(eval_result.get("result") or ""),
                    },
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
                return result
            log_tool_call(
                "browser_html",
                params,
                result=eval_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return eval_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call("browser_html", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
            return result
