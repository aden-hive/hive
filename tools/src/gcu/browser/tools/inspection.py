"""
Browser inspection tools - screenshot, snapshot, console.

All operations go through the Beeline extension via CDP - no Playwright required.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
from pydantic import Field

from ..bridge import connection_error, get_bridge
from ..telemetry import log_tool_call
from .tabs import _get_context

logger = logging.getLogger(__name__)


def _resolve_browser_artifact_dir() -> Path:
    """Return the directory where browser_snapshot / browser_html write
    their raw payload files.

    Prefers ``<HIVE_STORAGE_PATH>/data`` so artifacts land beside the
    agent's spillover files (HIVE_STORAGE_PATH is injected per-agent
    into MCP subprocess env by the framework's tool_registry — see
    ``framework/loader/agent_loader.py``).  Falls back to the shared
    ``<HIVE_HOME>/tool-artifacts`` directory when the env var is absent
    — e.g., the queen's fast-path cached registry which is built before
    any session and never receives per-session env.  HIVE_HOME respects
    the desktop shell's override (e.g. macOS userData dir); defaults to
    ``~/.hive`` for the OSS install.
    """
    storage = os.environ.get("HIVE_STORAGE_PATH")
    if storage:
        return Path(storage) / "data"
    hive_home = os.environ.get("HIVE_HOME")
    base = Path(hive_home).expanduser() if hive_home else Path.home() / ".hive"
    return base / "tool-artifacts"


def _write_browser_artifact(tool_name: str, tab_id: int, raw_text: str, ext: str) -> Path:
    """Persist a snapshot/HTML payload as raw text (no JSON wrapping) and
    return the absolute path.  Filename: ``<tool>_<unix_ms>_tab<id><ext>``.
    """
    out_dir = _resolve_browser_artifact_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_ms = int(time.time() * 1000)
    path = out_dir / f"{tool_name}_{ts_ms}_tab{tab_id}{ext}"
    path.write_text(raw_text, encoding="utf-8")
    return path.resolve()


def _write_browser_artifact_bytes(tool_name: str, tab_id: int, raw: bytes, ext: str) -> Path:
    """Binary sibling of :func:`_write_browser_artifact` — used to spill a
    screenshot JPEG to disk so the ``hive-browser`` CLI can return a
    ``saved_to`` pointer (a terminal command can't return an inline image;
    the framework re-inlines the file into the agent's session)."""
    out_dir = _resolve_browser_artifact_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_ms = int(time.time() * 1000)
    path = out_dir / f"{tool_name}_{ts_ms}_tab{tab_id}{ext}"
    path.write_bytes(raw)
    return path.resolve()


# Fixed output width for all screenshots (bandwidth default). This
# number does NOT affect coordinate semantics — click / hover / press
# and rect tools all work in fractions of the viewport (0..1), which
# are invariant to whatever resize / tile the vision API applies. The
# 800 px width is simply small enough to keep JPEG payloads under
# ~150 KB on typical UI screenshots.
_SCREENSHOT_WIDTH = 800

# Bound concurrent PIL screenshot processing. Each _resize_and_annotate decodes
# the raw PNG to a full-resolution RGBA bitmap (a 2748x1382 shot ≈ 15 MB; a tall
# full-page shot can be 100+ MB) plus a same-size overlay — all NATIVE buffers
# (libpng/Pillow), invisible to tracemalloc. Because the call is dispatched via
# asyncio.to_thread, the default thread pool let many run at once, so a burst of
# concurrent screenshots stacked those buffers and spiked RSS to ~900 MB (glibc
# only partly returns native memory). This semaphore caps peak footprint at
# roughly N × image-size. Tunable; keep it small.
_SCREENSHOT_CONCURRENCY = max(1, int(os.environ.get("HIVE_GCU_SCREENSHOT_CONCURRENCY", "2") or "2"))
_resize_semaphore: asyncio.Semaphore | None = None


def _get_resize_semaphore() -> asyncio.Semaphore:
    """Lazily create the semaphore on the running loop (avoids binding at import
    time / to the wrong loop)."""
    global _resize_semaphore
    if _resize_semaphore is None:
        _resize_semaphore = asyncio.Semaphore(_SCREENSHOT_CONCURRENCY)
    return _resize_semaphore


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
    """Drop cached screenshot scales and viewport sizes for the given tab_ids.

    Called when a tab closes or a profile's context is destroyed so stale
    cache values can't bleed into a later tab that Chrome happens to assign
    the same id. Accepts a single id or any iterable.
    """
    if isinstance(tab_ids, int):
        tab_ids = (tab_ids,)
    for tid in tab_ids:
        _screenshot_scales.pop(tid, None)
        _viewport_sizes.pop(tid, None)


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
            "Screenshot resize/annotate FAILED — returning original image. css_width=%s, dpr=%s.",
            css_width,
            dpr,
            exc_info=True,
        )
        return data, 1.0


async def _ensure_viewport_size(tab_id: int, _caller: str = "unknown") -> tuple[int, int]:
    """Return ``(cssWidth, cssHeight)`` for ``tab_id``, always
    refreshing from ``window.innerWidth`` / ``window.innerHeight``.

    Used by click / hover / press tools to turn fractional inputs
    (0..1) into CSS px, and by rect tools to turn CSS-px rects into
    fractions.

    Every call emits a ``viewport_sample`` telemetry entry so we
    can build a timeline of Chrome's reported viewport across an
    agent run — needed to diagnose the sessions where cssH changes
    silently (no visible layout shift) between screenshot and
    click. The entry records the live value, the cached value, and
    the delta so the transition point is trivial to locate in
    ``~/.hive/browser-logs/browser-YYYY-MM-DD.jsonl``.

    Falls back to the cached value on evaluate failure, then to
    ``(1, 1)`` if there's no cache — identity-op is a safe no-op.
    """
    bridge = get_bridge()
    cw = ch = 0
    evaluate_error: str | None = None
    try:
        result = await bridge.evaluate(tab_id, "({w: window.innerWidth, h: window.innerHeight})")
        inner = (result or {}).get("result") or {}
        cw = int(float(inner.get("w") or 0))
        ch = int(float(inner.get("h") or 0))
    except Exception as e:
        evaluate_error = str(e)
        cw = ch = 0

    cached_before = _viewport_sizes.get(tab_id)

    if cw <= 0 or ch <= 0:
        if cached_before is not None and cached_before[0] > 0 and cached_before[1] > 0:
            result_cw, result_ch = cached_before
        else:
            result_cw, result_ch = 1, 1
    else:
        result_cw, result_ch = cw, ch
        _viewport_sizes[tab_id] = (cw, ch)

    try:
        from ..telemetry import write_log

        write_log(
            {
                "type": "viewport_sample",
                "tab_id": tab_id,
                "caller": _caller,
                "live_w": cw,
                "live_h": ch,
                "cached_w": cached_before[0] if cached_before else None,
                "cached_h": cached_before[1] if cached_before else None,
                "deltaH_vs_cache": ((ch - cached_before[1]) if (cached_before and ch > 0) else None),
                "returned_w": result_cw,
                "returned_h": result_ch,
                "evaluate_error": evaluate_error,
            }
        )
    except Exception:
        pass

    return result_cw, result_ch


async def render_screenshot(
    bridge,
    target_tab: int,
    *,
    full_page: bool = False,
    selector: str | None = None,
    annotate: bool = True,
    log_name: str = "browser_screenshot",
    log_params: dict | None = None,
    start: float | None = None,
    spill: bool = False,
    intent: str | None = None,
    selector_timeout_ms: int = 5000,
) -> list | dict:
    """Capture a screenshot of ``target_tab``, resize + annotate it, and
    return MCP content blocks ``[TextContent(metadata), ImageContent]``.

    Shared by the standalone ``browser_screenshot`` tool and the
    ``screenshot`` action of ``browser_interact`` so both produce
    byte-identical output. ``bridge`` and ``target_tab`` must already be
    resolved by the caller.

    When ``spill=True`` (the ``hive-browser`` CLI path), the JPEG is written to
    a sibling artifact file instead of being returned inline, and the function
    returns a JSON dict of the same metadata plus ``saved_to`` and an ``_image``
    marker. The framework recognizes that marker on the ``terminal_exec`` result
    and re-inlines the image into the agent's session — so the agent still
    "sees" the screenshot without a manual read step.
    """
    if start is None:
        start = time.perf_counter()
    if log_params is None:
        log_params = {"tab_id": target_tab, "full_page": full_page, "selector": selector}
    try:
        screenshot_result = await bridge.screenshot(target_tab, full_page=full_page, selector=selector, selector_timeout_ms=selector_timeout_ms)

        if not screenshot_result.get("ok"):
            log_tool_call(
                log_name,
                log_params,
                result=screenshot_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return screenshot_result if spill else [TextContent(type="text", text=json.dumps(screenshot_result))]

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
        try:
            from ..telemetry import write_log

            expected_w = css_width * dpr
            expected_h = css_height_raw * dpr
            write_log(
                {
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
                    "yErrorAtTopCssPx": ((png_h - expected_h) / dpr if dpr else 0),
                }
            )
        except Exception:
            pass

        # Collect highlights: last interaction from bridge + CDP already drew in browser
        from ..bridge import _interaction_highlights

        highlights: list[dict] | None = None
        if annotate and target_tab in _interaction_highlights:
            highlights = [_interaction_highlights[target_tab]]

        # Resize to CSS-viewport dimensions (image px == CSS px) and
        # re-encode as JPEG. Offloaded to a thread because PIL on a
        # 2-megapixel PNG blocks for ~150–300 ms of CPU. The semaphore bounds
        # how many of these run at once so concurrent screenshots can't stack
        # their large native PIL buffers into a multi-hundred-MB RSS spike.
        async with _get_resize_semaphore():
            data, physical_scale = await asyncio.to_thread(
                _resize_and_annotate,
                data,
                css_width,
                dpr,
                highlights,
            )
        # Cache live viewport dimensions so click / hover / press / rect
        # tools can translate fractions ↔ CSS px without re-querying.
        css_height = int(screenshot_result.get("cssHeight", 0)) or 0
        if target_tab is not None and css_width > 0 and css_height > 0:
            _viewport_sizes[target_tab] = (int(css_width), css_height)
            _screenshot_scales[target_tab] = physical_scale

        # crop_box: when the capture is a clip (element selector or
        # full_page) rather than the plain viewport, record the
        # viewport-fraction rectangle the image spans. A coordinate read
        # off this image is image-relative; crop_box is what maps it back
        # to viewport space (used by the vision-fallback remap).
        crop_box = None
        clip = screenshot_result.get("clip")
        if clip and css_width > 0 and css_height > 0:
            crop_box = [
                round(clip["x"] / css_width, 4),
                round(clip["y"] / css_height, 4),
                round((clip["x"] + clip["width"]) / css_width, 4),
                round((clip["y"] + clip["height"]) / css_height, 4),
            ]

        meta_obj = {
            "ok": True,
            "tabId": target_tab,
            "url": screenshot_result.get("url", ""),
            "imageType": "jpeg",
            "size": len(base64.b64decode(data)) if data else 0,
            "imageWidth": _SCREENSHOT_WIDTH,
            "cssWidth": css_width,
            "cssHeight": css_height,
            # The raw captured pixel dimensions. For a --full-page shot these
            # reflect the WHOLE document (cssWidth/cssHeight above are only the
            # viewport), so the metadata no longer implies the capture was
            # viewport-sized when it wasn't.
            "capturedWidth": png_w,
            "capturedHeight": png_h,
            "fullPage": full_page,
            "crop_box": crop_box,
            "devicePixelRatio": dpr,
            "physicalScale": physical_scale,
            "annotated": bool(highlights),
            "scaleHint": (
                "Coordinates for click / hover / press are "
                "fractions 0..1 of the viewport. Read a target's "
                "proportional position off this image (e.g. '~35 % "
                "from the left, ~20 % from the top' → (0.35, 0.20)) "
                "and pass that as the coordinate to browser interact. "
                "shadow-query / focused_element.rect return "
                "fractions too."
            ),
        }

        log_tool_call(
            log_name,
            log_params,
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

        if spill:
            # CLI path: write the JPEG to disk and return a pointer + an
            # ``_image`` marker the framework re-inlines into the session.
            raw_jpeg = base64.b64decode(data) if data else b""
            artifact = _write_browser_artifact_bytes("browser_screenshot", target_tab, raw_jpeg, ".jpg")
            return {
                **meta_obj,
                "saved_to": str(artifact),
                "_image": {"path": str(artifact), "mime": "image/jpeg", "intent": intent},
            }

        return [
            TextContent(type="text", text=json.dumps(meta_obj)),
            ImageContent(type="image", data=data, mimeType="image/jpeg"),
        ]
    except Exception as e:
        log_tool_call(
            log_name,
            log_params,
            error=e,
            duration_ms=(time.perf_counter() - start) * 1000,
        )
        err = {"ok": False, "error": str(e)}
        return err if spill else [TextContent(type="text", text=json.dumps(err))]


# ── browser_screenshot prompts ─────────────────────────────────────

BROWSER_SCREENSHOT_DOC = """\
Take a screenshot of the current page.

Image is 800 px wide (JPEG quality 75, ~50–120 KB). All
coordinate tools work in **fractions of the viewport (0..1)**,
not pixels — so read a target's proportional position off this
image ("~35 % from the left, ~20 % from the top") and pass
``[0.35, 0.20]`` as the ``coordinate`` of a ``browser_interact``
left_click / hover / key action. ``browser_shadow_query``
likewise returns coordinates as fractions.

Returns a list of content blocks: text metadata + image."""

BROWSER_SCREENSHOT_PARAMS = {
    "intent": (
        "What you are looking for in this screenshot. Must "
        "mention: (1) the entity name (person, page title, post "
        "author), (2) the target element (submit button, text "
        "input, dropdown, etc.), (3) the action you plan to take. "
        "Example: \"Jamie Davidson's OpenAI post — looking for the "
        'Comment submit button to post my reply".'
    ),
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
    "full_page": (
        "Capture full scrollable page (default: False). "
        "Note: full_page images extend beyond the viewport, so "
        "fractions read off them do NOT map cleanly to "
        "viewport-space clicks. Use for reading / overview only, "
        "not for pointing."
    ),
    "selector": "CSS selector to screenshot a specific element (optional)",
    "annotate": "Draw bounding box of last interaction on image (default: True)",
}


# ── browser_shadow_query prompts ─────────────────────────────────────

BROWSER_SHADOW_QUERY_DOC = """\
Locate an element by CSS selector and return its bounding rect.

Works with ordinary selectors AND '>>>' shadow-piercing syntax —
joining selectors with ' >>> ' traverses shadow roots to reach
elements inside closed/open shadow DOM, overlays, and virtual-rendered
components (e.g. LinkedIn's #interop-outlet). Use it whenever you need
an element's exact position to act on it.

Returns the rect as **fractions of the viewport (0..1)** — feed
``rect.cx`` / ``rect.cy`` straight into a browser_interact left_click /
hover / key action as the ``coordinate``.

Returns a dict with ``rect`` block (x, y, w, h, cx, cy) as fractions,
plus ``cssWidth`` / ``cssHeight`` for reference."""

BROWSER_SHADOW_QUERY_PARAMS = {
    "selector": ("CSS selector. Join selectors with ' >>> ' to pierce shadow roots — e.g. 'button.submit' or '#interop-outlet >>> #ember37 >>> p'"),
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
}


# ── browser_snapshot prompts ─────────────────────────────────────

BROWSER_SNAPSHOT_DOC = """\
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

Returns a dict with the snapshot text tree, URL, and tab ID."""

BROWSER_SNAPSHOT_PARAMS = {
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
    "mode": (
        'Snapshot filtering mode (default: "default")\n'
        '    - "default": full accessibility tree\n'
        '    - "simple": interactive + content nodes, skip unnamed structural nodes\n'
        '    - "interactive": only interactive nodes (buttons, links, inputs, etc.)'
    ),
}


# ── browser_console prompts ─────────────────────────────────────

BROWSER_CONSOLE_DOC = """\
Get console messages from the browser.

Note: Console capture requires Runtime.enable and event handling.
Currently returns a message indicating this feature needs implementation.

Returns a dict with console messages."""

BROWSER_CONSOLE_PARAMS = {
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
    "level": "Filter by level (log, info, warn, error) (optional)",
}


# ── browser_html prompts ─────────────────────────────────────

BROWSER_HTML_DOC = """\
Get the HTML content of the page or a specific element.

Returns a dict with HTML content."""

BROWSER_HTML_PARAMS = {
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
    "selector": "CSS selector to get specific element HTML (optional)",
}


def register_inspection_tools(mcp: FastMCP) -> None:
    """Register browser inspection tools."""

    @mcp.tool(description=BROWSER_SCREENSHOT_DOC)
    async def browser_screenshot(
        intent: Annotated[str, Field(description=BROWSER_SCREENSHOT_PARAMS["intent"])],
        tab_id: Annotated[int | None, Field(description=BROWSER_SCREENSHOT_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_SCREENSHOT_PARAMS["profile"])] = None,
        full_page: Annotated[bool, Field(description=BROWSER_SCREENSHOT_PARAMS["full_page"])] = False,
        selector: Annotated[str | None, Field(description=BROWSER_SCREENSHOT_PARAMS["selector"])] = None,
        annotate: Annotated[bool, Field(description=BROWSER_SCREENSHOT_PARAMS["annotate"])] = True,
    ) -> list:
        start = time.perf_counter()
        params = {
            "tab_id": tab_id,
            "profile": profile,
            "full_page": full_page,
            "selector": selector,
        }

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            err = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_screenshot", params, result=err)
            return [TextContent(type="text", text=json.dumps(err))]

        ctx = _get_context(profile)
        if not ctx:
            err = {"ok": False, "error": "Browser not started"}
            log_tool_call("browser_screenshot", params, result=err)
            return [TextContent(type="text", text=json.dumps(err))]

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            err = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_screenshot", params, result=err)
            return [TextContent(type="text", text=json.dumps(err))]

        return await render_screenshot(
            bridge,
            target_tab,
            full_page=full_page,
            selector=selector,
            annotate=annotate,
            log_name="browser_screenshot",
            log_params=params,
            start=start,
        )

    @mcp.tool(description=BROWSER_SHADOW_QUERY_DOC)
    async def browser_shadow_query(
        selector: Annotated[str, Field(description=BROWSER_SHADOW_QUERY_PARAMS["selector"])],
        tab_id: Annotated[int | None, Field(description=BROWSER_SHADOW_QUERY_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_SHADOW_QUERY_PARAMS["profile"])] = None,
    ) -> dict:
        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            return {"ok": False, "error": connection_error(bridge)}
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
        cw, ch = await _ensure_viewport_size(target_tab, _caller="browser_shadow_query")
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
                "Pass rect.cx / rect.cy as the coordinate of a "
                "browser_interact left_click / hover / key action."
            ),
        }

    @mcp.tool(description=BROWSER_SNAPSHOT_DOC)
    async def browser_snapshot(
        tab_id: Annotated[int | None, Field(description=BROWSER_SNAPSHOT_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_SNAPSHOT_PARAMS["profile"])] = None,
        mode: Annotated[
            Literal["default", "simple", "interactive"],
            Field(description=BROWSER_SNAPSHOT_PARAMS["mode"]),
        ] = "default",
    ) -> dict:
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile, "mode": mode}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_snapshot", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_open(url) first to open a tab."}
            log_tool_call("browser_snapshot", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_snapshot", params, result=result)
            return result

        # Native browser dialogs (alert/confirm/prompt/beforeunload) aren't
        # DOM nodes — they never appear in the AX tree. They also pause the
        # renderer and hold the tab's CDP lock, so bridge.snapshot() would
        # block. Check first and surface the dialog so the agent's normal
        # "look around" loop can notice it and call browser_dialog_respond.
        # ``get_pending_dialog`` is sync on the in-process bridge but a
        # coroutine via the client-mode RemoteBridge RPC proxy, so await it
        # conditionally — exactly as connected_profiles is handled in
        # lifecycle.py. Without this, client mode (the normal gcu case)
        # leaves an un-awaited coroutine and ``pending.get(...)`` below
        # raises "'coroutine' object has no attribute 'get'".
        pending = bridge.get_pending_dialog(target_tab)
        if inspect.isawaitable(pending):
            pending = await pending
        if pending:
            result = {
                "ok": False,
                "error": "Page is blocked by a native browser dialog",
                "pending_dialog": {
                    "tab_id": target_tab,
                    "type": pending.get("type"),
                    "message": pending.get("message"),
                    "default_prompt": pending.get("default_prompt"),
                    "url": pending.get("url"),
                },
            }
            log_tool_call("browser_snapshot", params, result=result)
            return result

        try:
            snapshot_result = await bridge.snapshot(target_tab, mode=mode)
            # Spill the raw AX-tree text to a sibling file so the
            # LLM-visible result stays tiny (a JSON-wrapped multi-KB
            # tree forces escaping of every newline / quote, which is
            # noisy and token-hostile). The model receives only a
            # pointer; it can read_file or grep the artifact on demand.
            if isinstance(snapshot_result, dict) and snapshot_result.get("ok") and isinstance(snapshot_result.get("tree"), str):
                tree_text = snapshot_result["tree"]
                try:
                    artifact_path = _write_browser_artifact("browser_snapshot", target_tab, tree_text, ".txt")
                    result = {
                        "ok": True,
                        "tabId": snapshot_result.get("tabId", target_tab),
                        "url": snapshot_result.get("url"),
                        "length": len(tree_text),
                        "saved_to": str(artifact_path),
                    }
                except OSError as write_err:
                    # If disk write fails, surface the error rather than
                    # silently returning the inline tree (which would
                    # spike context and defeat the whole point).
                    result = {
                        "ok": False,
                        "error": f"Failed to write snapshot artifact: {write_err}",
                    }
            else:
                # Error shapes (ok=false, dialog-blocked, etc.) pass
                # through unchanged — the model needs to see them.
                result = snapshot_result
            log_tool_call(
                "browser_snapshot",
                params,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_snapshot",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

    @mcp.tool(description=BROWSER_CONSOLE_DOC)
    async def browser_console(
        tab_id: Annotated[int | None, Field(description=BROWSER_CONSOLE_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_CONSOLE_PARAMS["profile"])] = None,
        level: Annotated[str | None, Field(description=BROWSER_CONSOLE_PARAMS["level"])] = None,
    ) -> dict:
        result = {
            "ok": True,
            "message": "Console capture not yet implemented",
            "suggestion": "Use browser_evaluate to check specific values or errors",
        }
        log_tool_call("browser_console", {"tab_id": tab_id, "profile": profile, "level": level}, result=result)
        return result

    @mcp.tool(description=BROWSER_HTML_DOC)
    async def browser_html(
        tab_id: Annotated[int | None, Field(description=BROWSER_HTML_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, Field(description=BROWSER_HTML_PARAMS["profile"])] = None,
        selector: Annotated[str | None, Field(description=BROWSER_HTML_PARAMS["selector"])] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"tab_id": tab_id, "profile": profile, "selector": selector}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_html", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_open(url) first to open a tab."}
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
                script = f"(function() {{ const el = document.querySelector({sel_json}); return el ? el.outerHTML : null; }})()"
            else:
                script = "document.documentElement.outerHTML"

            eval_result = await bridge.evaluate(target_tab, script)

            if eval_result.get("ok"):
                html_value = eval_result.get("result")
                if isinstance(html_value, str):
                    # Spill raw HTML to a sibling file. See
                    # browser_snapshot for rationale — JSON-wrapping
                    # multi-KB HTML escapes every newline/quote and
                    # poisons the agent's context.
                    try:
                        artifact_path = _write_browser_artifact("browser_html", target_tab, html_value, ".html")
                        result = {
                            "ok": True,
                            "tabId": target_tab,
                            "selector": selector,
                            "length": len(html_value),
                            "saved_to": str(artifact_path),
                        }
                    except OSError as write_err:
                        result = {
                            "ok": False,
                            "error": f"Failed to write html artifact: {write_err}",
                        }
                else:
                    # Selector matched nothing → html is None. Tiny
                    # payload, no need to spill.
                    result = {
                        "ok": True,
                        "tabId": target_tab,
                        "html": html_value,
                        "selector": selector,
                    }
                log_tool_call(
                    "browser_html",
                    params,
                    result={
                        "ok": result.get("ok"),
                        "selector": selector,
                        "html_length": len(html_value) if isinstance(html_value, str) else 0,
                        "saved_to": result.get("saved_to"),
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
