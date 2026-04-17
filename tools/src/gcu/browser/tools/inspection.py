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

from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from ..bridge import get_bridge
from ..telemetry import log_tool_call
from .tabs import _get_context

logger = logging.getLogger(__name__)


def _resize_and_annotate(
    data: str,
    css_width: int,
    dpr: float = 1.0,
    highlights: list[dict] | None = None,
) -> tuple[str, float]:
    """Resize a captured PNG so that image pixels == CSS pixels, then
    re-encode as JPEG quality 75.

    Output is ``css_width × round(orig_h × css_width / orig_w)``. The
    1:1 image↔CSS mapping means a coord the agent reads off the image
    is the same coord CDP expects — no conversion, no scale factors to
    remember. Highlight annotations are drawn directly in CSS px (which
    equal image px after resize).

    Returns ``(new_b64, physical_scale)`` where
    ``physical_scale = orig_png_w / css_width`` (= DPR). Kept for logs
    and HiDPI debugging only.
    """
    if not css_width or css_width <= 0:
        # Capture path always supplies css_width; only reach here on a
        # degraded bridge response. Return the raw image untouched.
        return data, 1.0

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raw = base64.b64decode(data) if data else b""
        orig_w = 0
        if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
            import struct

            orig_w = struct.unpack(">I", raw[16:20])[0]
        physical_scale = orig_w / css_width if orig_w else 1.0
        logger.warning(
            "PIL not available — screenshot resize+convert SKIPPED. "
            "Returning original physical-px PNG. physicalScale=%.4f, "
            "css_width=%d, dpr=%s. Clicks WILL be misaligned; install Pillow.",
            physical_scale,
            css_width,
            dpr,
        )
        return data, round(physical_scale, 4)

    try:
        raw = base64.b64decode(data)
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        orig_w, orig_h = img.size

        physical_scale = orig_w / css_width
        new_w = css_width
        new_h = round(orig_h * new_w / orig_w)
        if (new_w, new_h) != img.size:
            img = img.resize((new_w, new_h), Image.LANCZOS)

        logger.info(
            "Screenshot: orig=%dx%d → out=%dx%d (css_width=%d, dpr=%s), physicalScale=%.4f",
            orig_w,
            orig_h,
            new_w,
            new_h,
            css_width,
            dpr,
            physical_scale,
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
                # Highlights are in CSS px. Image px == CSS px, no conversion.
                ix = h["x"]
                iy = h["y"]
                iw = h.get("w", 0)
                ih = h.get("h", 0)

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
        )
    except Exception:
        logger.warning(
            "Screenshot resize/annotate FAILED — returning original image. "
            "css_width=%s, dpr=%s.",
            css_width,
            dpr,
            exc_info=True,
        )
        return data, 1.0


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

        The image is delivered at the CSS viewport's own dimensions, so
        a pixel you see in the screenshot is the same coordinate you
        pass to ``browser_click_coordinate`` / ``browser_hover_coordinate``
        / ``browser_press_at``. No conversion, no scale factors.

        Output is JPEG quality 75 (~150–250 KB for a typical UI).

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

            # Resize to CSS-viewport dimensions so image px == CSS px,
            # and re-encode as the chosen lossy format. Offloaded to a
            # thread because PIL Image.open/resize/ImageDraw/composite
            # on a 2-megapixel PNG blocks for ~150–300 ms of CPU —
            # plenty to freeze the asyncio event loop. The function is
            # reentrant (fresh PIL Image per call, no shared state), so
            # to_thread is safe.
            data, physical_scale = await asyncio.to_thread(
                _resize_and_annotate,
                data,
                css_width,
                dpr,
                highlights,
            )

            meta = json.dumps(
                {
                    "ok": True,
                    "tabId": target_tab,
                    "url": screenshot_result.get("url", ""),
                    "imageType": "jpeg",
                    "size": len(base64.b64decode(data)) if data else 0,
                    "imageWidth": css_width,
                    "fullPage": full_page,
                    "devicePixelRatio": dpr,
                    "physicalScale": physical_scale,
                    "annotated": bool(highlights),
                    "scaleHint": (
                        "Image pixel = CSS pixel. Feed any coord you see "
                        "in this image directly to browser_click_coordinate "
                        "/ browser_hover_coordinate / browser_press_at — "
                        "no conversion needed."
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
        Returns the element's bounding rect in CSS pixels. Screenshot
        pixels == CSS pixels, so the same numbers also match whatever
        the agent sees in a browser_screenshot — feed ``css.cx/cy``
        straight to browser_click_coordinate / hover_coordinate /
        press_at.

        Args:
            selector: CSS selectors joined by ' >>> ' to pierce shadow roots.
                      Example: '#interop-outlet >>> #ember37 >>> p'
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with ``css`` block (x, y, w, h, cx, cy).
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
            "note": (
                "Pass css.cx/cy → browser_click_coordinate / "
                "hover_coordinate / press_at. Screenshot pixels == CSS "
                "pixels, so these coords also match anything you see in "
                "browser_screenshot."
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
        content. Returns the rect in CSS pixels. Screenshot pixels ==
        CSS pixels, so the same numbers match anything visible in
        browser_screenshot — feed ``css.cx/cy`` straight to
        browser_click_coordinate / hover_coordinate / press_at.

        Args:
            selector: CSS selector, optionally with ' >>> ' to pierce shadow roots.
                      Example: 'button.submit' or '#shadow-host >>> button'
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with ``css`` block (x, y, w, h, cx, cy).
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
            "note": (
                "Pass css.cx/cy → browser_click_coordinate / "
                "hover_coordinate / press_at. Screenshot pixels == CSS "
                "pixels, so these coords also match anything you see in "
                "browser_screenshot."
            ),
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
