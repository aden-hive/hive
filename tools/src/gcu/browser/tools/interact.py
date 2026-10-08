"""
Unified browser interaction tool — ``browser_interact``.

A single action-dispatched tool that replaces eleven discrete
interaction tools (click / type / press / hover / scroll / drag / wait,
in their selector and coordinate variants) plus screenshot capture and
a new high-resolution ``zoom``. See ``BROWSER_INTERACT_DOC`` for the
agent-facing contract.

All operations go through the Beeline extension via CDP - no Playwright
required. Coordinates are fractions of the viewport (0..1), never
pixels, so they survive whatever resize the vision model applies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Annotated, Literal

from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
from pydantic import Field

from ..bridge import connection_error, get_bridge
from ..telemetry import log_tool_call
from .inspection import (
    _SCREENSHOT_WIDTH,
    _ensure_viewport_size,
    _resize_and_annotate,
    render_screenshot,
)
from .tabs import _get_context

logger = logging.getLogger(__name__)

# How long to let the page settle after an interaction before grabbing
# the auto-snapshot. Enough to cover most click → re-render cycles.
_AUTO_SNAPSHOT_SETTLE_S = 0.5

# Per-keystroke delay on the per-character fallback path. NOT exposed to
# the agent — the default is the right choice and an extra knob would
# just invite tuning loops.
_DEFAULT_TYPE_DELAY_MS = 1

# Zoom capture-scale clamp. The tool picks a scale that lands the
# captured region near _SCREENSHOT_WIDTH px wide so small UI stays
# crisp, bounded so a tiny region can't request an absurd image.
_ZOOM_MIN_SCALE = 1.0
_ZOOM_MAX_SCALE = 4.0

AutoSnapshotMode = Literal["default", "simple", "interactive", "off"]

# Actions whose effect can change page state — these get an
# accessibility snapshot / annotated screenshot attached so the agent
# can self-correct in the same turn.
_CLICK_ACTIONS = {"left_click", "right_click", "middle_click", "double_click", "triple_click"}

# Which actions legitimately consume each targeting param. A param set
# for any other action is a caller mistake — reject it loudly instead of
# silently ignoring it (and then acting on the wrong target, or none).
_PARAM_ACTIONS: dict[str, set[str]] = {
    "coordinate": _CLICK_ACTIONS | {"hover", "key", "drag"},
    "selector": _CLICK_ACTIONS | {"hover", "type", "key", "scroll", "drag", "screenshot"},
    "modifiers": {"key"},
    "region": {"zoom"},
    "start_selector": {"drag"},
    "start_coordinate": {"drag"},
}

# Extra guidance appended to specific (param, action) misuse errors.
_PARAM_HINTS: dict[tuple[str, str], str] = {
    ("coordinate", "type"): " — left_click at the coordinate to focus, then call type with no coordinate",
    ("selector", "wait"): " — wait matches elements via wait_for_selector, not selector",
    ("selector", "zoom"): " — zoom captures a rectangle; pass region=[x0,y0,x1,y1]",
}


# Side-panel verb per browser_interact action. Click variants collapse to
# "click" (the user doesn't care about left vs middle for the history); pure
# observation modes (screenshot, zoom) return None so they don't pollute the
# row list with "the agent looked at the page" entries.
_INTERACT_VERBS: dict[str, str | None] = {
    "left_click": "click",
    "right_click": "click",
    "middle_click": "click",
    "double_click": "click",
    "triple_click": "click",
    "hover": "hover",
    "type": "type",
    "key": "key",
    "scroll": "scroll",
    "drag": "drag",
    "wait": "wait",
    "screenshot": None,
    "zoom": None,
}


def _truncate_target(s: str, limit: int = 80) -> str:
    return s if len(s) <= limit else s[:limit] + "…"


def _interact_action(
    action: str,
    selector: str | None,
    coordinate: list[float] | None,
    start_selector: str | None,
    start_coordinate: list[float] | None,
    text: str | None,
    scroll_direction: str,
    wait_for_selector: str | None,
    wait_for_text: str | None,
    duration: float | None,
) -> tuple[str, str] | None:
    """Build the (verb, target) pair for the side panel's per-tab action
    history. Returns None for observation-only actions (screenshot, zoom)."""
    verb = _INTERACT_VERBS.get(action)
    if verb is None:
        return None
    if verb == "click" or action == "hover":
        if selector:
            return (verb, _truncate_target(selector))
        if isinstance(coordinate, (list, tuple)) and len(coordinate) == 2:
            return (verb, f"({coordinate[0]:.2f}, {coordinate[1]:.2f})")
        return (verb, "")
    if verb == "type":
        return (verb, _truncate_target(text or ""))
    if verb == "key":
        return (verb, text or "")
    if verb == "scroll":
        return (verb, scroll_direction or "")
    if verb == "drag":
        src = start_selector or (
            f"({start_coordinate[0]:.2f}, {start_coordinate[1]:.2f})"
            if isinstance(start_coordinate, (list, tuple)) and len(start_coordinate) == 2
            else ""
        )
        dst = selector or (f"({coordinate[0]:.2f}, {coordinate[1]:.2f})" if isinstance(coordinate, (list, tuple)) and len(coordinate) == 2 else "")
        return (verb, f"{src} → {dst}" if src and dst else (src or dst))
    if verb == "wait":
        if wait_for_selector:
            return (verb, f"selector={_truncate_target(wait_for_selector)}")
        if wait_for_text:
            return (verb, f"text={_truncate_target(wait_for_text)}")
        if duration is not None:
            return (verb, f"{duration}s")
        return (verb, "")
    return (verb, "")


def _param_misuse_error(param: str, action: str) -> str:
    """Build the error for a targeting param passed to an action that
    can't honour it."""
    allowed = ", ".join(sorted(_PARAM_ACTIONS[param]))
    msg = f"`{param}` is not used by action='{action}' (valid for: {allowed})"
    if param == "modifiers":
        msg += "; click modifiers are not supported"
    return msg + _PARAM_HINTS.get((param, action), "") + "."


# ── shared result helpers (moved here from interactions.py) ──────────


def _text_only(result: dict) -> list:
    """Wrap a dict result as a single-block MCP text response."""
    return [TextContent(type="text", text=json.dumps(result))]


def _normalize(result) -> list:
    """Coerce a handler result (dict or content-block list) into the
    list shape ``browser_interact`` always returns."""
    if isinstance(result, list):
        return result
    return _text_only(result)


async def _build_visual_response(result: dict, bridge, target_tab: int | None) -> list:
    """Wrap an interaction result and append an annotated post-action
    screenshot, so the agent always sees where a coordinate click /
    hover / key landed. Degrades to text-only on any failure.
    """
    text_block = TextContent(type="text", text=json.dumps(result))
    if not result.get("ok") or target_tab is None or bridge is None:
        return [text_block]
    try:
        from ..bridge import _interaction_highlights

        shot = await bridge.screenshot(target_tab, full_page=False)
        if not shot.get("ok"):
            return [text_block]
        highlights = [_interaction_highlights[target_tab]] if target_tab in _interaction_highlights else None
        data, _ = await asyncio.to_thread(
            _resize_and_annotate,
            shot["data"],
            shot.get("cssWidth", 0),
            shot.get("devicePixelRatio", 1.0),
            highlights,
        )
        return [text_block, ImageContent(type="image", data=data, mimeType="image/jpeg")]
    except Exception:
        return [text_block]


async def _attach_snapshot(
    result: dict,
    bridge,
    target_tab: int,
    auto_snapshot_mode: str,
    wait_after_ms: int = 0,
) -> dict:
    """On a successful interaction, optionally pause for
    ``wait_after_ms`` then (unless snapshots are off) attach an
    accessibility snapshot of the settled page under ``snapshot``.
    Snapshot failures surface under ``snapshot_error`` and never fail
    the interaction itself.
    """
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    if wait_after_ms and wait_after_ms > 0:
        try:
            await asyncio.sleep(wait_after_ms / 1000)
        except Exception:
            pass
    if auto_snapshot_mode == "off":
        return result
    try:
        await asyncio.sleep(_AUTO_SNAPSHOT_SETTLE_S)
        result["snapshot"] = await bridge.snapshot(target_tab, mode=auto_snapshot_mode)
    except Exception as e:
        result["snapshot_error"] = str(e)
    return result


# ── coordinate helpers ───────────────────────────────────────────────


def _bad_fraction(coordinate: list[float]) -> str | None:
    """Return an error string if ``coordinate`` doesn't look like a
    valid [x, y] fraction pair (0..1, small overshoot allowed), else
    None."""
    if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
        return "coordinate must be [x, y]"
    x, y = coordinate[0], coordinate[1]
    if x > 1.5 or y > 1.5 or x < -0.1 or y < -0.1:
        return (
            f"Coords ({x}, {y}) look like pixels. coordinate expects "
            "fractions 0..1 of the viewport. Read the target's "
            "proportional position off a screenshot, or pass rect.cx / "
            "rect.cy from browser_shadow_query."
        )
    return None


# ── drag ─────────────────────────────────────────────────────────────


async def _resolve_drag_point(
    bridge,
    tab: int,
    *,
    selector: str | None,
    coordinate: list[float] | None,
    root_id,
    deadline: float,
    cw: int,
    ch: int,
    label: str,
) -> tuple[float, float]:
    """Resolve a drag endpoint to CSS-px (x, y). A coordinate is a
    viewport fraction; a selector is polled in the DOM and its box-model
    centre is used. Raises ValueError on a missing selector."""
    if coordinate is not None:
        return coordinate[0] * cw, coordinate[1] * ch
    node = None
    while asyncio.get_event_loop().time() < deadline:
        res = await bridge._cdp(tab, "DOM.querySelector", {"nodeId": root_id, "selector": selector})
        node = res.get("nodeId")
        if node:
            break
        await asyncio.sleep(0.1)
    if not node:
        raise ValueError(f"{label} element not found: {selector}")
    box = await bridge._cdp(tab, "DOM.getBoxModel", {"nodeId": node})
    c = box.get("content", [])
    if len(c) < 8:
        raise ValueError(f"{label} element has no box model: {selector}")
    return (c[0] + c[2] + c[4] + c[6]) / 4, (c[1] + c[3] + c[5] + c[7]) / 4


async def _do_drag(
    bridge,
    target_tab: int,
    *,
    start_selector: str | None,
    start_coordinate: list[float] | None,
    end_selector: str | None,
    end_coordinate: list[float] | None,
    timeout_ms: int,
) -> dict:
    """Drag from one point to another.

    Uses CDP mouse events for the physical gesture AND synthesises
    HTML5 drag-and-drop events (dragstart/dragover/drop) via JS so
    pages that rely on the Drag-and-Drop API receive the full event
    sequence.  Pure mouse-event drags (canvas painters, sliders) and
    HTML5 drag-and-drop pages both work.
    """
    if start_selector is None and start_coordinate is None:
        return {"ok": False, "error": "drag requires start_selector or start_coordinate"}
    if end_selector is None and end_coordinate is None:
        return {"ok": False, "error": "drag requires selector or coordinate for the end point"}

    await bridge.cdp_attach(target_tab)
    await bridge._cdp(target_tab, "DOM.enable")
    doc = await bridge._cdp(target_tab, "DOM.getDocument")
    root_id = doc.get("root", {}).get("nodeId")
    if start_coordinate is not None or end_coordinate is not None:
        cw, ch = await _ensure_viewport_size(target_tab, _caller="browser_interact:drag")
    else:
        cw, ch = 0, 0
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000

    sx, sy = await _resolve_drag_point(
        bridge,
        target_tab,
        selector=start_selector,
        coordinate=start_coordinate,
        root_id=root_id,
        deadline=deadline,
        cw=cw,
        ch=ch,
        label="Start",
    )
    ex, ey = await _resolve_drag_point(
        bridge,
        target_tab,
        selector=end_selector,
        coordinate=end_coordinate,
        root_id=root_id,
        deadline=deadline,
        cw=cw,
        ch=ch,
        label="End",
    )

    # 1. CDP mouse events — drives canvas/slider-style drag listeners.
    await bridge._cdp(
        target_tab,
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": sx, "y": sy, "button": "left", "clickCount": 1},
    )
    await bridge._cdp(
        target_tab,
        "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": ex, "y": ey},
    )
    await bridge._cdp(
        target_tab,
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", "x": ex, "y": ey, "button": "left", "clickCount": 1},
    )

    # 2. Synthesise HTML5 drag-and-drop events via JS so pages using the
    #    Drag-and-Drop API (dragstart/dragover/drop) respond correctly.
    #    CDP mouse events alone never fire these.
    drag_js = (
        """
    (function(sx, sy, ex, ey) {
      var src = document.elementFromPoint(sx, sy);
      var dst = document.elementFromPoint(ex, ey);
      if (!src || !dst) return JSON.stringify({ok: false, reason: 'no element at point'});
      var dt = new DataTransfer();
      var ds = new DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: dt});
      src.dispatchEvent(ds);
      if (ds.defaultPrevented) return JSON.stringify({ok: false, reason: 'dragstart prevented'});
      dst.dispatchEvent(new DragEvent('dragenter', {bubbles: true, cancelable: true, dataTransfer: dt}));
      dst.dispatchEvent(new DragEvent('dragover',  {bubbles: true, cancelable: true, dataTransfer: dt}));
      dst.dispatchEvent(new DragEvent('drop',      {bubbles: true, cancelable: true, dataTransfer: dt}));
      src.dispatchEvent(new DragEvent('dragend',   {bubbles: true, cancelable: false, dataTransfer: dt}));
      return JSON.stringify({ok: true});
    })"""
        + f"({sx}, {sy}, {ex}, {ey})"
    )

    await bridge._cdp(
        target_tab,
        "Runtime.evaluate",
        {"expression": drag_js, "returnByValue": True},
    )

    return {
        "ok": True,
        "action": "drag",
        "fromCoords": {"x": sx, "y": sy},
        "toCoords": {"x": ex, "y": ey},
    }


# ── zoom ─────────────────────────────────────────────────────────────


async def _do_zoom(bridge, target_tab: int, region: list[float]) -> list:
    """Capture ``region`` (viewport fractions [x0, y0, x1, y1]) at a
    capture scale chosen so the result stays crisp, then resize/encode
    to a JPEG content block."""
    if not isinstance(region, (list, tuple)) or len(region) != 4:
        return _text_only({"ok": False, "error": "zoom requires region [x0, y0, x1, y1]"})
    x0, y0, x1, y1 = region
    cw, ch = await _ensure_viewport_size(target_tab, _caller="browser_interact:zoom")
    region_css_w = max(1.0, abs(x1 - x0) * cw)
    # Pick a capture scale that lands the region near the standard
    # output width — a small region gets scaled up at capture time
    # (true higher-res), a large region is captured 1:1 and downscaled.
    scale = max(_ZOOM_MIN_SCALE, min(_ZOOM_MAX_SCALE, _SCREENSHOT_WIDTH / region_css_w))
    shot = await bridge.screenshot_region(target_tab, x0, y0, x1, y1, scale=scale)
    if not shot.get("ok"):
        return _text_only(shot)
    data, _ = await asyncio.to_thread(
        _resize_and_annotate,
        shot["data"],
        int(shot.get("regionCssWidth", region_css_w)),
        shot.get("devicePixelRatio", 1.0),
        None,
    )
    # crop_box: the viewport-fraction rectangle this zoom image spans,
    # clamped and corner-ordered. A coordinate read off the zoom image is
    # crop-relative; crop_box maps it back to viewport space (used by the
    # vision-fallback remap so non-vision models can still point).
    cx0, cx1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    cy0, cy1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    crop_box = [round(cx0, 4), round(cy0, 4), round(cx1, 4), round(cy1, 4)]
    meta = json.dumps(
        {
            "ok": True,
            "action": "zoom",
            "tabId": target_tab,
            "url": shot.get("url", ""),
            "imageType": "jpeg",
            "region": list(region),
            "crop_box": crop_box,
            "captureScale": shot.get("captureScale"),
            "regionCssWidth": shot.get("regionCssWidth"),
            "regionCssHeight": shot.get("regionCssHeight"),
            "note": (
                "This image is a zoomed crop of the viewport. A position "
                "read off it is crop-relative — map it to a viewport "
                "coordinate via crop_box: vx = crop_box[0] + fx*(crop_box[2]"
                "-crop_box[0]), vy = crop_box[1] + fy*(crop_box[3]-crop_box"
                "[1]). Prefer browser_shadow_query for an exact clickable "
                "rect."
            ),
        }
    )
    return [
        TextContent(type="text", text=meta),
        ImageContent(type="image", data=data, mimeType="image/jpeg"),
    ]


# ── tool documentation ───────────────────────────────────────────────

BROWSER_INTERACT_DOC = """\
Interact with a web browser tab: click, type, press keys, hover,
scroll, drag, screenshot, zoom, and wait — all through one ``action``.
If you don't have a valid tab_id, call browser_tabs first.

TARGETING — most actions accept either:
* ``selector``: a CSS selector (preferred — robust to layout shifts).
  Supports ' >>> ' to pierce Shadow DOM.
* ``coordinate``: [x, y] as FRACTIONS of the viewport (0..1, NOT
  pixels). (0.5, 0.5) is the centre. Read a target's proportional
  position off a screenshot, or pass rect.cx / rect.cy from
  browser_shadow_query (it returns fractions).
If both are given, ``selector`` wins. ``type`` and ``key`` with neither
target act on the currently focused element.

ACTIONS
* left_click / right_click / middle_click — click ``selector`` or
  ``coordinate``.
* double_click / triple_click — multi-click ``selector`` or
  ``coordinate``.
* hover — move the cursor to ``selector`` or ``coordinate`` without
  clicking (reveals tooltips / menus).
* type — type ``text`` into ``selector`` (or the focused element).
  ``clear_first`` (default true) overwrites existing content.
* key — press ``text`` as a key, e.g. "Enter", "ArrowDown", or with
  modifiers "cmd+a" / "ctrl+shift+Tab". ``modifiers`` may also be
  passed separately. ``repeat`` repeats the press. Targets
  ``coordinate`` first if given (routes through native hit-testing),
  else ``selector``, else the focused element. Modifiers work on the
  selector / focused path only — combining them with a ``coordinate``
  is rejected with an error, not silently dropped.
* scroll — scroll ``scroll_direction`` by ``scroll_amount`` PIXELS, in
  ``selector`` (a scrollable container) or the page. For lazy feeds
  pass a large amount (3000-6000) and a container selector.
* drag — drag from ``start_selector`` / ``start_coordinate`` to
  ``selector`` / ``coordinate``.
* screenshot — capture the tab (800px JPEG). ``intent`` is required:
  name the entity, the target element, and your planned action.
  Optional ``full_page`` or element ``selector``.
* zoom — capture ``region`` ([x0, y0, x1, y1] viewport fractions) at
  higher resolution for close inspection of small UI. A position read
  off a zoom image is crop-relative — use zoom to *read*; for an exact
  clickable coordinate use ``browser_shadow_query`` or a plain
  screenshot. The result carries a ``crop_box`` for mapping back.
* wait — pause for ``duration`` seconds, or until ``wait_for_selector``
  / ``wait_for_text`` appears.

NOTES
* Before clicking by coordinate, take a screenshot to locate the
  element; the post-action screenshot shows a marker so you can
  self-correct a near-miss.
* For navigation, tab management, page reads (HTML / text /
  accessibility snapshot), dropdowns (browser_select), uploads, and
  dialogs, use the dedicated browser_* tools — this tool covers input
  and visual capture only.

Returns a list of content blocks: a JSON text block, plus an image
block for screenshot / zoom and for coordinate click / hover / key."""


def _p(desc: str):
    """Shorthand for an Annotated optional field."""
    return Field(description=desc)


BROWSER_SELECT_DOC = """\
Select option(s) in a dropdown/select element.

Returns a dict with the select result."""

BROWSER_SELECT_PARAMS = {
    "selector": "CSS selector for the select element",
    "values": "List of values to select",
    "tab_id": "Chrome tab ID (default: active tab)",
    "profile": 'Browser profile name (default: "default")',
}


def register_interact_tools(mcp: FastMCP) -> None:
    """Register the unified ``browser_interact`` tool plus ``browser_select``.

    ``browser_select`` stays a distinct tool because a list of option
    values doesn't fit the action-dispatched shape cleanly — but it
    registers here so there's a single browser-interaction entry point.
    """

    @mcp.tool(description=BROWSER_INTERACT_DOC)
    async def browser_interact(
        action: Annotated[
            Literal[
                "left_click",
                "right_click",
                "middle_click",
                "double_click",
                "triple_click",
                "hover",
                "type",
                "key",
                "scroll",
                "drag",
                "screenshot",
                "zoom",
                "wait",
            ],
            _p("The interaction to perform. See the tool description for each action."),
        ],
        tab_id: Annotated[int | None, _p("Chrome tab ID. Defaults to the active tab.")] = None,
        profile: Annotated[str | None, _p('Browser profile name. Defaults to "default".')] = None,
        selector: Annotated[
            str | None,
            _p(
                "CSS selector for the target element. ' >>> ' pierces Shadow DOM. "
                "For drag this is the end element; for screenshot it captures just "
                "that element."
            ),
        ] = None,
        coordinate: Annotated[
            list[float] | None,
            _p("[x, y] as fractions of the viewport (0..1), not pixels. Target for click / hover / key; end point for drag."),
        ] = None,
        start_selector: Annotated[str | None, _p("CSS selector for the drag start element.")] = None,
        start_coordinate: Annotated[list[float] | None, _p("[x, y] viewport fractions (0..1) for the drag start point.")] = None,
        text: Annotated[
            str | None,
            _p('For type: the string to type. For key: the key to press, optionally with modifiers joined by "+" (e.g. "Enter", "cmd+a").'),
        ] = None,
        clear_first: Annotated[bool, _p("For type: clear the field before typing. Default true.")] = True,
        use_insert_text: Annotated[
            bool,
            _p(
                "For type: use CDP Input.insertText (default true — reliable for rich-text "
                "editors). Set false for per-keystroke dispatch (e.g. Monaco)."
            ),
        ] = True,
        modifiers: Annotated[
            str | None,
            _p('Modifier keys for the key action, e.g. "ctrl" or "cmd+shift". Applies on the selector / focused path only.'),
        ] = None,
        repeat: Annotated[int, _p("For key: repeat the press this many times (1-100). Default 1.")] = 1,
        scroll_direction: Annotated[Literal["up", "down", "left", "right"], _p("Direction for the scroll action.")] = "down",
        scroll_amount: Annotated[int, _p("For scroll: distance in pixels (default 500). For lazy feeds use 3000-6000.")] = 500,
        intent: Annotated[
            str | None,
            _p("Required for screenshot: one phrase naming the entity, the target element, and the action you plan to take."),
        ] = None,
        full_page: Annotated[bool, _p("For screenshot: capture the full scrollable page. Default false.")] = False,
        annotate: Annotated[bool, _p("For screenshot: draw the last interaction's marker on the image. Default true.")] = True,
        region: Annotated[
            list[float] | None,
            _p("For zoom: [x0, y0, x1, y1] viewport fractions (0..1) of the rectangle to capture."),
        ] = None,
        duration: Annotated[float | None, _p("For wait: seconds to pause (max 10) when no condition is given.")] = None,
        wait_for_selector: Annotated[str | None, _p("For wait: pause until this CSS selector appears.")] = None,
        wait_for_text: Annotated[str | None, _p("For wait: pause until this text appears on the page.")] = None,
        timeout_ms: Annotated[
            int | None,
            _p(
                "Timeout for resolving a selector target or a wait condition. Per-action "
                "defaults apply when omitted (5000 for clicks/waits, 30000 for type/drag)."
            ),
        ] = None,
        auto_snapshot_mode: Annotated[
            AutoSnapshotMode,
            _p(
                'Accessibility snapshot attached after a state-changing action: "simple" '
                '(default), "default" (full tree), "interactive" (controls only), "off" '
                "(skip — use when batching interactions)."
            ),
        ] = "simple",
        wait_after_ms: Annotated[int, _p("Pause this many ms after the action before snapshotting (animations / lazy fetches). Default 0.")] = 0,
    ) -> list:
        start = time.perf_counter()
        log_params = {"action": action, "tab_id": tab_id, "profile": profile, "selector": selector}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            err = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_interact", log_params, result=err)
            return _text_only(err)

        ctx = _get_context(profile)
        if not ctx:
            err = {"ok": False, "error": "Browser not started. Call browser_open(url) first to open a tab."}
            log_tool_call("browser_interact", log_params, result=err)
            return _text_only(err)

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            err = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_interact", log_params, result=err)
            return _text_only(err)

        try:
            result = await _dispatch(
                action,
                bridge,
                target_tab,
                selector=selector,
                coordinate=coordinate,
                start_selector=start_selector,
                start_coordinate=start_coordinate,
                text=text,
                clear_first=clear_first,
                use_insert_text=use_insert_text,
                modifiers=modifiers,
                repeat=repeat,
                scroll_direction=scroll_direction,
                scroll_amount=scroll_amount,
                intent=intent,
                full_page=full_page,
                annotate=annotate,
                region=region,
                duration=duration,
                wait_for_selector=wait_for_selector,
                wait_for_text=wait_for_text,
                timeout_ms=timeout_ms,
                auto_snapshot_mode=auto_snapshot_mode,
                wait_after_ms=wait_after_ms,
                log_params=log_params,
                start=start,
            )
            blocks = _normalize(result)
            history_action = _interact_action(
                action,
                selector,
                coordinate,
                start_selector,
                start_coordinate,
                text,
                scroll_direction,
                wait_for_selector,
                wait_for_text,
                duration,
            )
            log_tool_call(
                "browser_interact",
                log_params,
                result={"ok": True, "action": action} if _blocks_ok(blocks) else _first_dict(blocks),
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=history_action,
            )
            return blocks
        except Exception as e:
            err = {"ok": False, "error": str(e)}
            history_action = _interact_action(
                action,
                selector,
                coordinate,
                start_selector,
                start_coordinate,
                text,
                scroll_direction,
                wait_for_selector,
                wait_for_text,
                duration,
            )
            log_tool_call(
                "browser_interact",
                log_params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=history_action,
            )
            return _text_only(err)

    @mcp.tool(description=BROWSER_SELECT_DOC)
    async def browser_select(
        selector: Annotated[str, _p(BROWSER_SELECT_PARAMS["selector"])],
        values: Annotated[list[str], _p(BROWSER_SELECT_PARAMS["values"])],
        tab_id: Annotated[int | None, _p(BROWSER_SELECT_PARAMS["tab_id"])] = None,
        profile: Annotated[str | None, _p(BROWSER_SELECT_PARAMS["profile"])] = None,
    ) -> dict:
        start = time.perf_counter()
        params = {"selector": selector, "values": values, "tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": connection_error(bridge)}
            log_tool_call("browser_select", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_open(url) first to open a tab."}
            log_tool_call("browser_select", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_select", params, result=result)
            return result

        select_target = _truncate_target(f"{selector} = {', '.join(values)}" if values else selector)
        try:
            select_result = await bridge.select_option(target_tab, selector, values)
            log_tool_call(
                "browser_select",
                params,
                result=select_result,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=("select", select_target),
            )
            return select_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_select",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
                tab_id=target_tab,
                action=("select", select_target),
            )
            return result


def _first_dict(blocks: list) -> dict:
    """Extract the JSON payload from the first text block, for logging."""
    for b in blocks:
        if isinstance(b, TextContent):
            try:
                return json.loads(b.text)
            except Exception:
                return {"ok": False}
    return {"ok": False}


def _blocks_ok(blocks: list) -> bool:
    return _first_dict(blocks).get("ok", False)


async def _dispatch(
    action: str,
    bridge,
    target_tab: int,
    *,
    selector,
    coordinate,
    start_selector,
    start_coordinate,
    text,
    clear_first,
    use_insert_text,
    modifiers,
    repeat,
    scroll_direction,
    scroll_amount,
    intent,
    full_page,
    annotate,
    region,
    duration,
    wait_for_selector,
    wait_for_text,
    timeout_ms,
    auto_snapshot_mode,
    wait_after_ms,
    log_params,
    start,
):
    """Route a ``browser_interact`` call to the matching bridge
    operation. Returns a dict or a content-block list."""

    # ── parameter-relevance guard ─────────────────────────────────────
    # Reject a targeting param the chosen action can't honour, rather
    # than silently ignoring it (and acting on the wrong target).
    for _param, _present in (
        ("coordinate", coordinate is not None),
        ("selector", selector is not None),
        ("modifiers", bool(modifiers)),
        ("region", region is not None),
        ("start_selector", start_selector is not None),
        ("start_coordinate", start_coordinate is not None),
    ):
        if _present and action not in _PARAM_ACTIONS[_param]:
            return {"ok": False, "error": _param_misuse_error(_param, action)}

    # ── clicks ───────────────────────────────────────────────────────
    if action in _CLICK_ACTIONS:
        button = {"right_click": "right", "middle_click": "middle"}.get(action, "left")
        click_count = {"double_click": 2, "triple_click": 3}.get(action, 1)
        if selector:
            res = await bridge.click(
                target_tab,
                selector,
                button=button,
                click_count=click_count,
                timeout_ms=timeout_ms or 5000,
            )
            return await _attach_snapshot(res, bridge, target_tab, auto_snapshot_mode, wait_after_ms)
        if coordinate is not None:
            bad = _bad_fraction(coordinate)
            if bad:
                return {"ok": False, "error": bad}
            cw, ch = await _ensure_viewport_size(target_tab, _caller=f"browser_interact:{action}")
            res = await bridge.click_coordinate(
                target_tab,
                coordinate[0] * cw,
                coordinate[1] * ch,
                button=button,
                click_count=click_count,
            )
            return await _build_visual_response(res, bridge, target_tab)
        return {"ok": False, "error": f"{action} requires a selector or coordinate"}

    # ── hover ────────────────────────────────────────────────────────
    if action == "hover":
        if selector:
            res = await bridge.hover(target_tab, selector, timeout_ms=timeout_ms or 30000)
            return res
        if coordinate is not None:
            bad = _bad_fraction(coordinate)
            if bad:
                return {"ok": False, "error": bad}
            cw, ch = await _ensure_viewport_size(target_tab, _caller="browser_interact:hover")
            res = await bridge.hover_coordinate(target_tab, coordinate[0] * cw, coordinate[1] * ch)
            return await _build_visual_response(res, bridge, target_tab)
        return {"ok": False, "error": "hover requires a selector or coordinate"}

    # ── type ─────────────────────────────────────────────────────────
    if action == "type":
        if text is None:
            return {"ok": False, "error": "type requires text"}
        res = await bridge.type_text(
            target_tab,
            selector,
            text,
            clear_first=clear_first,
            delay_ms=_DEFAULT_TYPE_DELAY_MS,
            timeout_ms=timeout_ms or 30000,
            use_insert_text=use_insert_text,
        )
        return await _attach_snapshot(res, bridge, target_tab, auto_snapshot_mode, wait_after_ms)

    # ── key ──────────────────────────────────────────────────────────
    if action == "key":
        if not text:
            return {"ok": False, "error": "key requires text (the key to press)"}
        # A key string may carry modifiers joined by "+": the last
        # token is the key, the rest are modifiers. Combine with any
        # explicitly-passed modifiers.
        mods: list[str] = []
        key = text
        if "+" in text and len(text) > 1:
            parts = text.split("+")
            key, mods = parts[-1], parts[:-1]
        if modifiers:
            mods += [m for m in modifiers.split("+") if m]
        if not key:
            return {
                "ok": False,
                "error": f"key text '{text}' resolved to an empty key — give a key name like 'Enter' or 'ctrl+a'.",
            }
        repeat_n = max(1, min(100, repeat or 1))

        if coordinate is not None:
            # A key dispatched at a point goes through native hit-testing
            # and cannot carry held modifiers — fail loud rather than
            # silently pressing the bare key without them.
            if mods:
                return {
                    "ok": False,
                    "error": (
                        f"Modifier keys ({'+'.join(mods)}) are not supported with a "
                        "coordinate target. Use a selector instead, or focus the "
                        "element first and call key with no coordinate."
                    ),
                }
            bad = _bad_fraction(coordinate)
            if bad:
                return {"ok": False, "error": bad}
            cw, ch = await _ensure_viewport_size(target_tab, _caller="browser_interact:key")
            res: dict = {"ok": False, "error": "no key dispatched"}
            for _ in range(repeat_n):
                res = await bridge.press_key_at(target_tab, coordinate[0] * cw, coordinate[1] * ch, key)
            return await _build_visual_response(res, bridge, target_tab)
        res = {"ok": False, "error": "no key dispatched"}
        for _ in range(repeat_n):
            res = await bridge.press_key(target_tab, key, selector=selector, modifiers=mods or None)
        return res

    # ── scroll ───────────────────────────────────────────────────────
    if action == "scroll":
        res = await bridge.scroll(
            target_tab,
            direction=scroll_direction,
            amount=scroll_amount,
            selector=selector,
        )
        return await _attach_snapshot(res, bridge, target_tab, auto_snapshot_mode, wait_after_ms)

    # ── drag ─────────────────────────────────────────────────────────
    if action == "drag":
        return await _do_drag(
            bridge,
            target_tab,
            start_selector=start_selector,
            start_coordinate=start_coordinate,
            end_selector=selector,
            end_coordinate=coordinate,
            timeout_ms=timeout_ms or 30000,
        )

    # ── screenshot ───────────────────────────────────────────────────
    if action == "screenshot":
        if not (intent or "").strip():
            return {
                "ok": False,
                "error": ("screenshot requires `intent` — one phrase naming the entity, the target element, and the action you plan to take."),
            }
        return await render_screenshot(
            bridge,
            target_tab,
            full_page=full_page,
            selector=selector,
            annotate=annotate,
            log_name="browser_interact",
            log_params=log_params,
            start=start,
        )

    # ── zoom ─────────────────────────────────────────────────────────
    if action == "zoom":
        if region is None:
            return {"ok": False, "error": "zoom requires region [x0, y0, x1, y1]"}
        return await _do_zoom(bridge, target_tab, region)

    # ── wait ─────────────────────────────────────────────────────────
    if action == "wait":
        if wait_for_selector:
            res = await bridge.wait_for_selector(target_tab, wait_for_selector, timeout_ms=timeout_ms or 5000)
            if res.get("ok"):
                return {"ok": True, "action": "wait", "condition": "selector", "selector": wait_for_selector}
            return res
        if wait_for_text:
            res = await bridge.wait_for_text(target_tab, wait_for_text, timeout_ms=timeout_ms or 5000)
            if res.get("ok"):
                return {"ok": True, "action": "wait", "condition": "text", "text": wait_for_text}
            return res
        secs = max(0.0, min(10.0, duration if duration is not None else 1.0))
        await asyncio.sleep(secs)
        return {"ok": True, "action": "wait", "condition": "time", "seconds": secs}

    return {"ok": False, "error": f"unknown action: {action}"}
