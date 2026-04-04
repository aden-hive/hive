"""
Browser inspection tools - screenshot, snapshot, console.

All operations go through the Beeline extension via CDP - no Playwright required.
"""

from __future__ import annotations

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

        raw = base64.b64decode(data)
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        orig_w, orig_h = img.size
        new_w = width
        new_h = round(orig_h * new_w / orig_w)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Physical scale: how many native/physical pixels per image pixel
        physical_scale = orig_w / width
        # CSS scale: physical_scale / DPR
        css_scale = (css_width / width) if css_width else (physical_scale / max(dpr, 1.0))

        if highlights:
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11
                )
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
                    draw.line(
                        [(cx - r - 4, cy), (cx + r + 4, cy)], fill=(239, 68, 68, 220), width=2
                    )
                    draw.line(
                        [(cx, cy - r - 4), (cx, cy + r + 4)], fill=(239, 68, 68, 220), width=2
                    )
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
        logger.debug("Screenshot resize/annotate failed, using original", exc_info=True)
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
            log_tool_call(
                "browser_screenshot", params, result={"ok": False, "error": "Browser not started"}
            )
            return [TextContent(type="text", text=err_msg)]

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = [
                TextContent(type="text", text=json.dumps({"ok": False, "error": "No active tab"}))
            ]
            log_tool_call(
                "browser_screenshot", params, result={"ok": False, "error": "No active tab"}
            )
            return result

        try:
            screenshot_result = await bridge.screenshot(
                target_tab, full_page=full_page, selector=selector
            )

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

            # Normalize to 800px wide and annotate
            data, physical_scale, css_scale = _resize_and_annotate(
                data, css_width, dpr=dpr, highlights=highlights, width=width
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
                        f"image_coord × {physical_scale} = physical px "
                        f"(for browser_click_coordinate/"
                        f"hover_coordinate); "
                        f"image_coord × {css_scale} = CSS px "
                        f"(for getBoundingClientRect)"
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
        Convert screenshot image coordinates to browser coordinates.

        After browser_screenshot returns an 800px-wide image, use this to translate
        pixel positions you see in the image into the two coordinate spaces used by
        browser tools:

        - physical_x/y → use with browser_click_coordinate, browser_hover_coordinate,
          browser_press_at (CDP Input events work in physical pixels)
        - css_x/y → use with getBoundingClientRect comparisons and DOM APIs

        Args:
            x: X pixel position in the 800px screenshot image
            y: Y pixel position in the 800px screenshot image
            tab_id: Chrome tab ID (default: active tab for profile)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with physical_x, physical_y, css_x, css_y, and scale factors
        """
        ctx = _get_context(profile)
        target_tab = tab_id or (ctx.get("activeTabId") if ctx else None)

        physical_scale = _screenshot_scales.get(target_tab, 1.0) if target_tab else 1.0
        # css_scale stored in second slot via _screenshot_css_scales
        css_scale = (
            _screenshot_css_scales.get(target_tab, physical_scale) if target_tab else physical_scale
        )

        return {
            "ok": True,
            "physical_x": round(x * physical_scale, 1),
            "physical_y": round(y * physical_scale, 1),
            "css_x": round(x * css_scale, 1),
            "css_y": round(y * css_scale, 1),
            "physicalScale": physical_scale,
            "cssScale": css_scale,
            "tabId": target_tab,
            "note": (
                "Use physical_x/y with browser_click_coordinate,"
                " browser_hover_coordinate, browser_press_at."
                " Use css_x/y with getBoundingClientRect"
                " and DOM APIs."
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
                "Use physical.cx/cy with"
                " browser_click_coordinate or"
                " browser_hover_coordinate."
                " Use css.cx/cy with"
                " getBoundingClientRect comparisons."
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
        Returns coordinates in both CSS pixels (for DOM APIs) and physical pixels
        (for browser_click_coordinate, browser_hover_coordinate, browser_press_at).

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
            "note": "Use physical.cx/cy with browser_click_coordinate or browser_hover_coordinate.",
        }

    @mcp.tool()
    async def browser_snapshot(
        tab_id: int | None = None,
        profile: str | None = None,
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

        Returns:
            Dict with the snapshot text tree, URL, and tab ID
        """
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile}

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
            snapshot_result = await bridge.snapshot(target_tab)
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
        log_tool_call(
            "browser_console", {"tab_id": tab_id, "profile": profile, "level": level}, result=result
        )
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
            log_tool_call(
                "browser_html", params, error=e, duration_ms=(time.perf_counter() - start) * 1000
            )
            return result
