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

# Target width for normalized screenshots (px in the delivered image)
_SCREENSHOT_WIDTH = 600

# Maps tab_id -> physical scale: image_coord × scale = physical pixels (for CDP Input events)
_screenshot_scales: dict[int, float] = {}
# Maps tab_id -> CSS scale: image_coord × scale = CSS pixels (for DOM APIs / getBoundingClientRect)
_screenshot_css_scales: dict[int, float] = {}


def clear_tab_state(tab_ids) -> None:
    """Drop cached screenshot scales for the given tab_ids.

    Called when a tab closes or a profile's context is destroyed so stale
    scale values can't bleed into a later tab that Chrome happens to assign
    the same id. Accepts a single id or any iterable.
    """
    if isinstance(tab_ids, int):
        tab_ids = (tab_ids,)
    for tid in tab_ids:
        _screenshot_scales.pop(tid, None)
        _screenshot_css_scales.pop(tid, None)


def _resize_and_annotate(
    data: str,
    css_width: int,
    dpr: float = 1.0,
    highlights: list[dict] | None = None,
    width: int = _SCREENSHOT_WIDTH,
) -> tuple[str, float, float]:
    """Resize a base64 PNG to _SCREENSHOT_WIDTH wide, annotate highlights.

    Returns (new_b64, physical_scale, css_scale) where:
      physical_scale = physical_px_per_image_px  (multiply image coords → physical px)
      css_scale      = css_px_per_image_px        (multiply image coords → CSS px for DOM APIs)

    Highlights have x,y,w,h in CSS pixels (what getBoundingClientRect returns,
    and what CDP Input.dispatchMouseEvent accepts).
    Falls back to original data if Pillow unavailable or resize fails.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raw = base64.b64decode(data) if data else b""
        orig_w = 0
        if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
            import struct

            orig_w = struct.unpack(">I", raw[16:20])[0]
        raw_size_bytes = len(raw)
        physical_scale = orig_w / width if orig_w and width else 1.0
        css_scale = (css_width / width) if css_width else (physical_scale / max(dpr, 1.0))
        logger.warning(
            "PIL not available — screenshot resize SKIPPED (cannot downscale image). "
            "raw_size=%d bytes, png_width=%d, css_width=%s, dpr=%s, target_width=%d. "
            "Returning ORIGINAL image with computed scales: physicalScale=%.4f, cssScale=%.4f. "
            "Agent must use browser_coords() to convert image positions before clicking.",
            raw_size_bytes,
            orig_w,
            css_width,
            dpr,
            width,
            physical_scale,
            css_scale,
        )
        return data, round(physical_scale, 4), round(css_scale, 4)

    try:
        raw = base64.b64decode(data)
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        orig_w, orig_h = img.size

        physical_scale = orig_w / width
        css_scale = (css_width / width) if css_width else (physical_scale / max(dpr, 1.0))

        logger.info(
            "Screenshot resize: orig=%dx%d → target=%dx%d, css_width=%s, dpr=%s, physicalScale=%.4f, cssScale=%.4f",
            orig_w,
            orig_h,
            width,
            round(orig_h * width / orig_w),
            css_width,
            dpr,
            physical_scale,
            css_scale,
        )

        new_w = width
        new_h = round(orig_h * new_w / orig_w)
        img = img.resize((new_w, new_h), Image.LANCZOS)

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
                # Highlights are in CSS px → convert to image px
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

                # Label: show image pixel position so user knows where to look
                img_coords = f"img:({round(ix)},{round(iy)})"
                display_label = f"{img_coords} {label}" if label else img_coords
                lx, ly = ix, max(2, iy - 16)
                lx = max(2, min(lx, width - 120))
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
        img.save(buf, format="PNG", optimize=True)
        return (
            base64.b64encode(buf.getvalue()).decode(),
            round(physical_scale, 4),
            round(css_scale, 4),
        )
    except Exception:
        logger.warning(
            "Screenshot resize/annotate FAILED — returning original image with scale=1.0. "
            "css_width=%s, dpr=%s, target_width=%d. Clicks will be misaligned.",
            css_width,
            dpr,
            width,
            exc_info=True,
        )
        return data, 1.0, 1.0


def register_inspection_tools(mcp: FastMCP) -> None:
    """Register browser inspection tools."""

    @mcp.tool()
    async def browser_screenshot(
        tab_id: int | None = None,
        profile: str | None = None,
        full_page: bool = False,
        selector: str | None = None,
        image_type: Literal["png", "jpeg"] = "png",
        annotate: bool = True,
        width: int = _SCREENSHOT_WIDTH,
    ) -> list:
        """
        Take a screenshot of the current page.

        Returns a normalized image alongside text metadata (URL, size, scale
        factors, etc.). Automatically annotates the last interaction (click,
        hover, type) with a bounding box overlay.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            full_page: Capture full scrollable page (default: False)
            selector: CSS selector to screenshot a specific element (optional)
            image_type: Image format - png or jpeg (default: png)
            annotate: Draw bounding box of last interaction on image (default: True)
            width: Output image width in pixels (default: 600). Use 800+ for fine
                   text, 400 for quick layout checks.

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
            mime_type = screenshot_result.get("mimeType", "image/png")
            css_width = screenshot_result.get("cssWidth", 0)
            dpr = screenshot_result.get("devicePixelRatio", 1.0)

            # Collect highlights: last interaction from bridge + CDP already drew in browser
            from ..bridge import _interaction_highlights

            highlights: list[dict] | None = None
            if annotate and target_tab in _interaction_highlights:
                highlights = [_interaction_highlights[target_tab]]

            # Normalize to 800px wide and annotate. Offloaded to a
            # thread because PIL Image.open/resize/ImageDraw/composite on
            # a 2-megapixel PNG blocks for ~150-300ms of CPU — plenty to
            # freeze the asyncio event loop and delay every concurrent
            # tool call during a screenshot. The function is reentrant
            # (fresh PIL Image per call, no shared state), so to_thread
            # is safe.
            data, physical_scale, css_scale = await asyncio.to_thread(
                _resize_and_annotate,
                data,
                css_width,
                dpr,
                highlights,
                width,
            )
            _screenshot_scales[target_tab] = physical_scale
            _screenshot_css_scales[target_tab] = css_scale

            meta = json.dumps(
                {
                    "ok": True,
                    "tabId": target_tab,
                    "url": screenshot_result.get("url", ""),
                    "imageType": mime_type.split("/")[-1],
                    "size": len(base64.b64decode(data)) if data else 0,
                    "imageWidth": width,
                    "fullPage": full_page,
                    "devicePixelRatio": dpr,
                    "physicalScale": physical_scale,
                    "cssScale": css_scale,
                    "annotated": bool(highlights),
                    "scaleHint": (
                        f"image_coord × {css_scale} = CSS px "
                        f"→ feed to browser_click_coordinate, "
                        f"browser_hover_coordinate, browser_press_at "
                        f"(CDP Input events use CSS pixels). "
                        f"image_coord × {physical_scale} = physical px "
                        f"is debug-only on HiDPI displays and must NOT "
                        f"be used for clicks — it overshoots by DPR×."
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
                    "physicalScale": physical_scale,
                    "cssScale": css_scale,
                    "debug_cssWidth": css_width,
                    "debug_dpr": dpr,
                },
                duration_ms=(time.perf_counter() - start) * 1000,
            )

            return [
                TextContent(type="text", text=meta),
                ImageContent(type="image", data=data, mimeType=mime_type),
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
    def browser_coords(
        x: float,
        y: float,
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Convert screenshot image coordinates to browser click coordinates.

        After browser_screenshot returns a downscaled image, use this to
        translate pixel positions you see in the image into the CSS pixel
        coordinates that Chrome DevTools Protocol expects.

        **CDP Input.dispatchMouseEvent uses CSS pixels**, so you want
        ``css_x`` / ``css_y`` for every click/hover tool. ``physical_x/y``
        is kept in the return for debugging on HiDPI displays — do NOT
        feed it to clicks; on a DPR=2 screen it lands 2× too far.

        Edge case: pages using ``zoom`` or ``transform: scale()`` (e.g.
        LinkedIn's ``#interop-outlet`` shadow DOM) render in a scaled
        local coordinate space. For those, ``getBoundingClientRect()``
        reports pre-zoom coordinates and you may still need to multiply
        by the element's effective zoom. Use browser_shadow_query to
        get the zoomed rect directly.

        Args:
            x: X pixel position in the screenshot image
            y: Y pixel position in the screenshot image
            tab_id: Chrome tab ID (default: active tab for profile)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with css_x, css_y (primary — use these), physical_x,
            physical_y (debug only), and scale factors.
        """
        ctx = _get_context(profile)
        target_tab = tab_id or (ctx.get("activeTabId") if ctx else None)

        physical_scale = _screenshot_scales.get(target_tab, 1.0) if target_tab else 1.0
        # css_scale stored in second slot via _screenshot_css_scales
        css_scale = _screenshot_css_scales.get(target_tab, physical_scale) if target_tab else physical_scale

        return {
            "ok": True,
            # Primary output: CSS pixels. Feed these to click/hover/press.
            "css_x": round(x * css_scale, 1),
            "css_y": round(y * css_scale, 1),
            # Debug output: raw physical pixels. DO NOT feed to clicks on
            # HiDPI displays — CDP Input events use CSS pixels, so sending
            # physical coordinates lands the click at roughly DPR× the
            # intended position.
            "physical_x": round(x * physical_scale, 1),
            "physical_y": round(y * physical_scale, 1),
            "physicalScale": physical_scale,
            "cssScale": css_scale,
            "tabId": target_tab,
            "note": (
                "Use css_x/css_y with browser_click_coordinate, "
                "browser_hover_coordinate, browser_press_at — "
                "Chrome DevTools Protocol Input.dispatchMouseEvent "
                "operates in CSS pixels. physical_x/y is for debugging "
                "on HiDPI displays only; feeding it to clicks lands "
                "them at DPR× the intended coordinate."
            ),
        }

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
        Returns getBoundingClientRect in both CSS and physical pixels.

        Args:
            selector: CSS selectors joined by ' >>> ' to pierce shadow roots.
                      Example: '#interop-outlet >>> #ember37 >>> p'
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with rect (CSS px) and physical rect (CSS px × DPR) of the element
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
        physical_scale = _screenshot_scales.get(target_tab, 1.0)
        css_scale = _screenshot_css_scales.get(target_tab, 1.0)
        dpr = physical_scale / css_scale if css_scale else 1.0

        return {
            "ok": True,
            "selector": selector,
            "tag": rect.get("tag"),
            "css": {
                "x": rect["x"],
                "y": rect["y"],
                "w": rect["w"],
                "h": rect["h"],
                "cx": rect["cx"],
                "cy": rect["cy"],
            },
            "physical": {
                "x": round(rect["x"] * dpr, 1),
                "y": round(rect["y"] * dpr, 1),
                "w": round(rect["w"] * dpr, 1),
                "h": round(rect["h"] * dpr, 1),
                "cx": round(rect["cx"] * dpr, 1),
                "cy": round(rect["cy"] * dpr, 1),
            },
            "note": (
                "Use css.cx/cy with browser_click_coordinate, "
                "browser_hover_coordinate, browser_press_at — "
                "CDP Input events operate in CSS pixels. "
                "physical.* is debug-only; feeding it to clicks "
                "lands them DPR× too far on HiDPI displays."
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

        Supports '>>>' shadow-piercing selectors for overlay/shadow DOM content.
        Returns coordinates in CSS pixels (for clicks and DOM APIs); the
        physical-pixel variant is returned for debugging on HiDPI displays
        only — it must not be fed to click/hover/press tools, which use
        CSS pixels.

        Args:
            selector: CSS selector, optionally with ' >>> ' to pierce shadow roots.
                      Example: 'button.submit' or '#shadow-host >>> button'
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with css and physical bounding rects
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
        physical_scale = _screenshot_scales.get(target_tab, 1.0)
        css_scale = _screenshot_css_scales.get(target_tab, 1.0)
        dpr = physical_scale / css_scale if css_scale else 1.0

        return {
            "ok": True,
            "selector": selector,
            "tag": rect.get("tag"),
            "css": {
                "x": rect["x"],
                "y": rect["y"],
                "w": rect["w"],
                "h": rect["h"],
                "cx": rect["cx"],
                "cy": rect["cy"],
            },
            "physical": {
                "x": round(rect["x"] * dpr, 1),
                "y": round(rect["y"] * dpr, 1),
                "w": round(rect["w"] * dpr, 1),
                "h": round(rect["h"] * dpr, 1),
                "cx": round(rect["cx"] * dpr, 1),
                "cy": round(rect["cy"] * dpr, 1),
            },
            "note": (
                "Use css.cx/cy with browser_click_coordinate, "
                "browser_hover_coordinate, browser_press_at — "
                "CDP Input events operate in CSS pixels. "
                "physical.* is debug-only; feeding it to clicks "
                "lands them DPR× too far on HiDPI displays."
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
