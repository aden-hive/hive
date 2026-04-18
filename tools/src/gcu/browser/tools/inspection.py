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


# Fixed output width for all screenshots (bandwidth default). This
# number does NOT affect coordinate semantics — click / hover / press
# and rect tools all work in fractions of the viewport (0..1), which
# are invariant to whatever resize / tile the vision API applies. The
# 800 px width is simply small enough to keep JPEG payloads under
# ~150 KB on typical UI screenshots.
_SCREENSHOT_WIDTH = 800

# Per-tab viewport-size cache populated on every browser_screenshot
# and on lazy-init inside the click tools. Stores CSS-pixel viewport
# dimensions (window.innerWidth / window.innerHeight). Click tools
# multiply fractional inputs by these to get CSS coords before
# dispatching CDP events; rect tools divide CSS-pixel DOM rects by
# these to produce fractions for the agent.
_viewport_sizes: dict[int, tuple[int, int]] = {}

# Optional debug cache — physical-px scale per tab (orig_png_w /
# _SCREENSHOT_WIDTH). Logged only; no consumer.
_screenshot_scales: dict[int, float] = {}


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


def _resize_and_annotate(
    data: str,
    css_width: int,
    dpr: float = 1.0,
    highlights: list[dict] | None = None,
) -> tuple[str, float]:
    """Resize the captured PNG down to ``_SCREENSHOT_WIDTH`` (=800 px)
    and re-encode as JPEG quality 75.

    The image dimensions do NOT determine click coordinates any more —
    the tools work in viewport fractions. This helper exists purely
    for bandwidth + annotation overlay. Returns ``(new_b64,
    physical_scale)`` where ``physical_scale = orig_png_w / output_w``
    is kept for debug logging.

    Highlight rects arrive in CSS px; they're converted to image-space
    for overlay drawing via the local ``css_to_image = css_width /
    output_w`` factor (computed inline — no external cache).
    """
    if not css_width or css_width <= 0:
        # Bridge always supplies css_width from window.innerWidth; only
        # reach here on a degraded response. Return the raw PNG.
        return data, 1.0

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raw = base64.b64decode(data) if data else b""
        orig_w = 0
        if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
            import struct

            orig_w = struct.unpack(">I", raw[16:20])[0]
        physical_scale = orig_w / _SCREENSHOT_WIDTH if orig_w else 1.0
        logger.warning(
            "PIL not available — screenshot resize SKIPPED. "
            "Returning raw physical-px PNG. physicalScale=%.4f, "
            "css_width=%d, dpr=%s. Install Pillow for annotation.",
            physical_scale,
            css_width,
            dpr,
        )
        return data, round(physical_scale, 4)

    try:
        raw = base64.b64decode(data)
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        orig_w, orig_h = img.size

        physical_scale = orig_w / _SCREENSHOT_WIDTH
        new_w = _SCREENSHOT_WIDTH
        new_h = round(orig_h * new_w / orig_w)
        if (new_w, new_h) != img.size:
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # Local CSS → image px factor for overlay draws. Kept local —
        # not exported, not stored, not leaked to the agent.
        css_to_image = css_width / _SCREENSHOT_WIDTH

        logger.info(
            "Screenshot: orig=%dx%d → out=%dx%d (css_width=%d, dpr=%s), physicalScale=%.4f, css_to_image=%.4f",
            orig_w,
            orig_h,
            new_w,
            new_h,
            css_width,
            dpr,
            physical_scale,
            css_to_image,
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
                ix = h["x"] / css_to_image
                iy = h["y"] / css_to_image
                iw = h.get("w", 0) / css_to_image
                ih = h.get("h", 0) / css_to_image

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


async def _ensure_viewport_size(tab_id: int) -> tuple[int, int]:
    """Return ``(cssWidth, cssHeight)`` for ``tab_id``, populating the
    cache via ``window.innerWidth`` / ``window.innerHeight`` on miss.

    Used by click / hover / press tools to turn fractional inputs
    (0..1) into CSS px, and by rect tools to turn CSS-px rects into
    fractions. Degrades to ``(1, 1)`` if the bridge can't be queried
    — that makes every coord an identity op, which is a safe no-op
    (and preferable to crashing).
    """
    cached = _viewport_sizes.get(tab_id)
    if cached is not None and cached[0] > 0 and cached[1] > 0:
        return cached
    bridge = get_bridge()
    try:
        result = await bridge.evaluate(tab_id, "({w: window.innerWidth, h: window.innerHeight})")
        inner = (result or {}).get("result") or {}
        cw = int(float(inner.get("w") or 0))
        ch = int(float(inner.get("h") or 0))
    except Exception:
        cw, ch = 0, 0
    if cw <= 0 or ch <= 0:
        # Degraded: bridge didn't return viewport. Cache an identity
        # so we don't retry on every call; corrects itself after the
        # next successful browser_screenshot.
        cw, ch = 1, 1
    _viewport_sizes[tab_id] = (cw, ch)
    return cw, ch


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

        Image is 800 px wide (JPEG quality 75, ~50–120 KB). All
        coordinate tools work in **fractions of the viewport (0..1)**,
        not pixels — so read a target's proportional position off this
        image ("~35 % from the left, ~20 % from the top") and pass
        ``(0.35, 0.20)`` to ``browser_click_coordinate`` /
        ``browser_hover_coordinate`` / ``browser_press_at``.
        ``browser_get_rect`` and ``browser_shadow_query`` likewise
        return coordinates as fractions.

        Args:
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            full_page: Capture full scrollable page (default: False).
                Note: full_page images extend beyond the viewport, so
                fractions read off them do NOT map cleanly to
                viewport-space clicks. Use for reading / overview only,
                not for pointing.
            selector: CSS selector to screenshot a specific element (optional)
            annotate: Draw bounding box of last interaction on image (default: True)

        Returns:
            List of content blocks: text metadata + image.
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
            css_height_raw = screenshot_result.get("cssHeight", 0)
            dpr = screenshot_result.get("devicePixelRatio", 1.0)
            png_w = screenshot_result.get("pngWidth", 0)
            png_h = screenshot_result.get("pngHeight", 0)

            # Diagnostic for the y-axis offset hunt: clicks convert
            # fractions through cssHeight, but the displayed image is
            # resized using the PNG's aspect ratio. If png_h differs
            # from cssHeight × dpr the two coordinate systems drift.
            # X is checked too — should always read delta_x ≈ 0 since
            # physical_scale is derived from pngWidth.
            try:
                from ..telemetry import write_log
                expected_w = css_width * dpr
                expected_h = css_height_raw * dpr
                write_log({
                    "type": "screenshot_geometry",
                    "tab_id": target_tab,
                    "url": screenshot_result.get("url", ""),
                    "pngWidth": png_w,
                    "pngHeight": png_h,
                    "cssWidth": css_width,
                    "cssHeight": css_height_raw,
                    "dpr": dpr,
                    "expectedPngWidth": expected_w,
                    "expectedPngHeight": expected_h,
                    "deltaPngWidthPx": png_w - expected_w,
                    "deltaPngHeightPx": png_h - expected_h,
                    # If the PNG is taller than cssHeight×dpr (e.g. a
                    # devtools-attached banner adds rows above the page
                    # in the capture), clicks land BELOW intended at
                    # the top of the page and converge to 0 error at
                    # the bottom. Reverse signs if PNG is shorter.
                    # Worst-case error in CSS px at fy=0:
                    "yErrorAtTopCssPx": (
                        (png_h - expected_h) / dpr if dpr else 0
                    ),
                })
            except Exception:
                pass

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
            data, physical_scale = await asyncio.to_thread(
                _resize_and_annotate,
                data,
                css_width,
                dpr,
                highlights,
            )
            # Cache live viewport dimensions so click / hover / press /
            # rect tools can translate fractions ↔ CSS px without
            # asking the page again.
            css_height = int(screenshot_result.get("cssHeight", 0)) or 0
            if target_tab is not None and css_width > 0 and css_height > 0:
                _viewport_sizes[target_tab] = (int(css_width), css_height)
                _screenshot_scales[target_tab] = physical_scale

            meta = json.dumps(
                {
                    "ok": True,
                    "tabId": target_tab,
                    "url": screenshot_result.get("url", ""),
                    "imageType": "jpeg",
                    "size": len(base64.b64decode(data)) if data else 0,
                    "imageWidth": _SCREENSHOT_WIDTH,
                    "cssWidth": css_width,
                    "cssHeight": css_height,
                    "fullPage": full_page,
                    "devicePixelRatio": dpr,
                    "physicalScale": physical_scale,
                    "annotated": bool(highlights),
                    "scaleHint": (
                        "Coordinates for click / hover / press are "
                        "fractions 0..1 of the viewport. Read a "
                        "target's proportional position off this image "
                        "(e.g. '~35 % from the left, ~20 % from the top' "
                        "→ (0.35, 0.20)) and pass that to "
                        "browser_click_coordinate / "
                        "browser_hover_coordinate / browser_press_at. "
                        "browser_get_rect / browser_shadow_query / "
                        "focused_element.rect return fractions too."
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
                    "cssHeight": css_height,
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
        Returns the element's bounding rect as **fractions of the
        viewport (0..1)** — feed ``rect.cx`` / ``rect.cy`` straight
        into browser_click_coordinate / hover_coordinate / press_at.

        Args:
            selector: CSS selectors joined by ' >>> ' to pierce shadow roots.
                      Example: '#interop-outlet >>> #ember37 >>> p'
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with ``rect`` block (x, y, w, h, cx, cy) as fractions,
            plus ``cssWidth`` / ``cssHeight`` for reference.
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
        cw, ch = await _ensure_viewport_size(target_tab)
        cw_f = float(cw) if cw > 0 else 1.0
        ch_f = float(ch) if ch > 0 else 1.0
        return {
            "ok": True,
            "selector": selector,
            "tag": rect.get("tag"),
            "rect": {
                "x": round(rect["x"] / cw_f, 4),
                "y": round(rect["y"] / ch_f, 4),
                "w": round(rect["w"] / cw_f, 4),
                "h": round(rect["h"] / ch_f, 4),
                "cx": round(rect["cx"] / cw_f, 4),
                "cy": round(rect["cy"] / ch_f, 4),
            },
            "cssWidth": cw,
            "cssHeight": ch,
            "note": (
                "rect fields are fractions of the viewport (0..1). "
                "Pass rect.cx / rect.cy to browser_click_coordinate / "
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
        content. Returns the rect as **fractions of the viewport
        (0..1)** — the same coordinate space browser_click_coordinate
        / hover_coordinate / press_at expect.

        Args:
            selector: CSS selector, optionally with ' >>> ' to pierce shadow roots.
                      Example: 'button.submit' or '#shadow-host >>> button'
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with ``rect`` block (x, y, w, h, cx, cy) as fractions,
            plus ``cssWidth`` / ``cssHeight`` for reference.
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
        cw, ch = await _ensure_viewport_size(target_tab)
        cw_f = float(cw) if cw > 0 else 1.0
        ch_f = float(ch) if ch > 0 else 1.0
        return {
            "ok": True,
            "selector": selector,
            "tag": rect.get("tag"),
            "rect": {
                "x": round(rect["x"] / cw_f, 4),
                "y": round(rect["y"] / ch_f, 4),
                "w": round(rect["w"] / cw_f, 4),
                "h": round(rect["h"] / ch_f, 4),
                "cx": round(rect["cx"] / cw_f, 4),
                "cy": round(rect["cy"] / ch_f, 4),
            },
            "cssWidth": cw,
            "cssHeight": ch,
            "note": (
                "rect fields are fractions of the viewport (0..1). "
                "Pass rect.cx / rect.cy to browser_click_coordinate / "
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
