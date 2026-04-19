"""
Browser interaction tools - click, type, fill, press, hover, select, scroll, drag.

All operations go through the Beeline extension via CDP - no Playwright required.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from fastmcp import FastMCP

from ..bridge import get_bridge
from ..telemetry import log_tool_call
from .tabs import _get_context

logger = logging.getLogger(__name__)

# How long to let the page settle after an interaction before grabbing
# the auto-snapshot. Enough to cover most click → re-render cycles
# (React commit + layout) without adding much observable latency.
_AUTO_SNAPSHOT_SETTLE_S = 0.5


AutoSnapshotMode = Literal["default", "simple", "interactive", "off"]


async def _attach_snapshot(
    result: dict, bridge, target_tab: int, auto_snapshot_mode: str
) -> dict:
    """If the interaction succeeded and the caller opted into auto-snapshot,
    wait for the page to settle and attach an accessibility snapshot under
    the ``snapshot`` key using ``auto_snapshot_mode`` as the snapshot filter
    mode. ``"off"`` skips the capture entirely. Snapshot failures surface
    under ``snapshot_error`` and do NOT fail the interaction itself."""
    if (
        auto_snapshot_mode == "off"
        or not isinstance(result, dict)
        or not result.get("ok")
    ):
        return result
    try:
        await asyncio.sleep(_AUTO_SNAPSHOT_SETTLE_S)
        result["snapshot"] = await bridge.snapshot(target_tab, mode=auto_snapshot_mode)
    except Exception as e:
        result["snapshot_error"] = str(e)
    return result


def register_interaction_tools(mcp: FastMCP) -> None:
    """Register browser interaction tools."""

    @mcp.tool()
    async def browser_click(
        selector: str,
        tab_id: int | None = None,
        profile: str | None = None,
        button: Literal["left", "right", "middle"] = "left",
        double_click: bool = False,
        timeout_ms: int = 5000,
        auto_snapshot_mode: AutoSnapshotMode = "default",
    ) -> dict:
        """
        Click an element on the page.

        Args:
            selector: CSS selector for the element
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            button: Mouse button to click (left, right, middle)
            double_click: Perform double-click (default: False)
            timeout_ms: How long to poll for the element to appear in the
                DOM before giving up. Default 5000ms (fast-fail). A missing
                or hallucinated selector returns "Element not found" in
                <=5s so the agent can try a different approach quickly.
                Pass a larger value (e.g. 15000) ONLY when you know the
                element will take longer than 5s to render — for example
                right after a navigation that triggers slow hydration.
            auto_snapshot_mode: Controls the accessibility snapshot taken
                0.5s after a successful click. ``"default"`` (the default)
                returns the full tree; ``"simple"`` trims unnamed structural
                nodes; ``"interactive"`` returns only controls (buttons,
                links, inputs) for the tightest token footprint;
                ``"off"`` skips the capture entirely — use when batching
                multiple interactions.

        Returns:
            Dict with click result and coordinates. Includes ``snapshot``
            unless ``auto_snapshot_mode="off"`` or the click failed.
        """
        start = time.perf_counter()
        params = {
            "selector": selector,
            "tab_id": tab_id,
            "profile": profile,
            "button": button,
            "double_click": double_click,
        }

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_click", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_click", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_click", params, result=result)
            return result

        try:
            click_result = await bridge.click(
                target_tab,
                selector,
                button=button,
                click_count=2 if double_click else 1,
                timeout_ms=timeout_ms,
            )
            log_tool_call(
                "browser_click",
                params,
                result=click_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return await _attach_snapshot(click_result, bridge, target_tab, auto_snapshot_mode)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call("browser_click", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
            return result

    @mcp.tool()
    async def browser_click_coordinate(
        x: float,
        y: float,
        tab_id: int | None = None,
        profile: str | None = None,
        button: Literal["left", "right", "middle"] = "left",
    ) -> dict:
        """
        Click at a FRACTION of the viewport (0..1, 0..1).

        Coordinates are **fractions of the viewport**, not pixels:
        ``(0.5, 0.5)`` is the center, ``(0.1, 0.2)`` is 10 % from the
        left and 20 % from the top. Read a target's proportional
        position off ``browser_screenshot`` (or pass
        ``rect.cx`` / ``rect.cy`` from ``browser_get_rect`` /
        ``browser_shadow_query`` directly — they return fractions too).

        Fractions are used because every vision model resizes or tiles
        images differently (Claude ~1.15 MP target, GPT-4o 512-px
        tiles, etc.). Proportional positions survive every such
        transform; pixel coords do not.

        Args:
            x: X fraction of the viewport (0..1).
            y: Y fraction of the viewport (0..1).
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            button: Mouse button to click (left, right, middle)

        Returns:
            Dict with click result, including ``focused_element``
            describing what the click focused. ``focused_element.rect``
            is also in fractions.
        """
        start = time.perf_counter()
        params = {"x": x, "y": y, "tab_id": tab_id, "profile": profile, "button": button}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_click_coordinate", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_click_coordinate", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_click_coordinate", params, result=result)
            return result

        # Pixel-input guard: legitimate fractions live in [0, 1]. Allow a
        # small overshoot tolerance for edge targets.
        if x > 1.5 or y > 1.5 or x < -0.1 or y < -0.1:
            result = {
                "ok": False,
                "error": (
                    f"Coords ({x}, {y}) look like pixels. This tool expects "
                    "fractions 0..1 of the viewport. Read the target's "
                    "proportional position off browser_screenshot, or pass "
                    "rect.cx / rect.cy from browser_get_rect / "
                    "browser_shadow_query (they return fractions)."
                ),
            }
            log_tool_call("browser_click_coordinate", params, result=result)
            return result

        try:
            from .inspection import _ensure_viewport_size

            cw, ch = await _ensure_viewport_size(target_tab)
            css_x = x * cw
            css_y = y * ch
            click_result = await bridge.click_coordinate(target_tab, css_x, css_y, button=button)
            log_tool_call(
                "browser_click_coordinate",
                params,
                result={**click_result, "cssWidth": cw, "cssHeight": ch},
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return click_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_click_coordinate",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

    @mcp.tool()
    async def browser_type(
        selector: str,
        text: str,
        tab_id: int | None = None,
        profile: str | None = None,
        delay_ms: int = 1,
        clear_first: bool = True,
        timeout_ms: int = 30000,
        use_insert_text: bool = True,
        auto_snapshot_mode: AutoSnapshotMode = "default",
    ) -> dict:
        """
        Click a selector to focus it, then type text into it.

        Uses CDP ``Input.insertText`` by default, which works for both
        standard inputs and many rich-text editors. Use
        ``browser_type_focused`` when the target is already focused or
        you cannot reliably address it with a selector.

        Args:
            selector: CSS selector for the input element.
            text: Text to type.
            tab_id: Chrome tab ID (default: active tab).
            profile: Browser profile name (default: "default").
            delay_ms: Delay between keystrokes in ms (default: 1).
                Forces the per-keystroke fallback when > 0.
            clear_first: Clear existing text before typing (default: True).
            timeout_ms: Timeout waiting for element (default: 30000).
            use_insert_text: Use CDP Input.insertText (default: True) for
                reliable insertion into rich-text editors. Set False for
                per-keystroke dispatch.
            auto_snapshot_mode: Controls the accessibility snapshot taken
                0.5s after successful typing. ``"default"`` returns the
                full tree; ``"simple"`` trims unnamed structural nodes;
                ``"interactive"`` returns only controls for the tightest
                token footprint; ``"off"`` skips the capture entirely —
                use when batching multiple interactions.

        Returns:
            Dict with type result. Includes ``snapshot`` unless
            ``auto_snapshot_mode="off"`` or typing failed.
        """
        start = time.perf_counter()
        params = {"selector": selector, "text": text, "tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_type", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_type", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_type", params, result=result)
            return result

        try:
            type_result = await bridge.type_text(
                target_tab,
                selector,
                text,
                clear_first=clear_first,
                delay_ms=delay_ms,
                timeout_ms=timeout_ms,
                use_insert_text=use_insert_text,
            )
            log_tool_call(
                "browser_type",
                params,
                result=type_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return await _attach_snapshot(type_result, bridge, target_tab, auto_snapshot_mode)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call("browser_type", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
            return result

    @mcp.tool()
    async def browser_fill(
        selector: str,
        value: str,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
        auto_snapshot_mode: AutoSnapshotMode = "default",
    ) -> dict:
        """
        Fill an input element with a value (clears existing content first).

        Faster than browser_type for filling form fields.

        Args:
            selector: CSS selector for the input element
            value: Value to fill
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout waiting for element (default: 30000)
            auto_snapshot_mode: Controls the accessibility snapshot taken
                0.5s after a successful fill. ``"default"`` returns the
                full tree; ``"simple"`` / ``"interactive"`` return tighter
                trees; ``"off"`` skips the capture — use when batching.

        Returns:
            Dict with fill result. Includes ``snapshot`` unless
            ``auto_snapshot_mode="off"`` or the fill failed.
        """
        return await browser_type(
            selector=selector,
            text=value,
            tab_id=tab_id,
            profile=profile,
            delay_ms=0,
            clear_first=True,
            timeout_ms=timeout_ms,
            auto_snapshot_mode=auto_snapshot_mode,
        )

    @mcp.tool()
    async def browser_type_focused(
        text: str,
        tab_id: int | None = None,
        profile: str | None = None,
        delay_ms: int = 1,
        clear_first: bool = True,
        use_insert_text: bool = True,
        auto_snapshot_mode: AutoSnapshotMode = "default",
    ) -> dict:
        """
        Type text into the already-focused element.

        Targets ``document.activeElement`` and is ideal after a
        coordinate click, or when the editable cannot be reached
        reliably with a selector. Faster than repeated
        ``browser_press`` calls for multi-character input.

        Args:
            text: Text to insert at the current cursor position.
            tab_id: Chrome tab ID (default: active tab).
            profile: Browser profile name (default: "default").
            delay_ms: Delay between keystrokes in ms (default: 1).
                      Forces per-keystroke dispatch when > 0.
            clear_first: Clear existing text before typing (default: True).
            use_insert_text: Use CDP Input.insertText (default: True).
            auto_snapshot_mode: Controls the accessibility snapshot taken
                0.5s after successful typing. ``"default"`` returns the
                full tree; ``"simple"`` / ``"interactive"`` return tighter
                trees; ``"off"`` skips the capture — use when batching.

        Returns:
            Dict with type result. Includes ``snapshot`` unless
            ``auto_snapshot_mode="off"`` or typing failed.
        """
        start = time.perf_counter()
        params = {"text": text, "tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_type_focused", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_type_focused", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_type_focused", params, result=result)
            return result

        try:
            type_result = await bridge.type_text(
                target_tab,
                None,
                text,
                clear_first=clear_first,
                delay_ms=delay_ms,
                use_insert_text=use_insert_text,
            )
            log_tool_call(
                "browser_type_focused",
                params,
                result=type_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return await _attach_snapshot(type_result, bridge, target_tab, auto_snapshot_mode)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call("browser_type_focused", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
            return result

    @mcp.tool()
    async def browser_press(
        key: str,
        selector: str | None = None,
        tab_id: int | None = None,
        profile: str | None = None,
        modifiers: list[str] | None = None,
    ) -> dict:
        """
        Press a keyboard key, optionally with modifier keys held.

        Args:
            key: Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown',
                 or a character like 'a')
            selector: Focus element first (optional)
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            modifiers: Hold these modifier keys while pressing ``key``. Accepted
                values (case-insensitive): "alt", "ctrl"/"control", "meta"/"cmd",
                "shift". Examples: ``modifiers=["ctrl"], key="a"`` = Ctrl+A
                (select all); ``modifiers=["shift"], key="Tab"`` = Shift+Tab;
                ``modifiers=["meta"], key="Enter"`` = Cmd+Enter.

        Returns:
            Dict with press result
        """
        start = time.perf_counter()
        params = {
            "key": key,
            "selector": selector,
            "tab_id": tab_id,
            "profile": profile,
            "modifiers": modifiers,
        }

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_press", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_press", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_press", params, result=result)
            return result

        try:
            press_result = await bridge.press_key(target_tab, key, selector=selector, modifiers=modifiers)
            log_tool_call(
                "browser_press",
                params,
                result=press_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return press_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call("browser_press", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
            return result

    @mcp.tool()
    async def browser_hover(
        selector: str,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Hover over an element.

        Args:
            selector: CSS selector for the element
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout waiting for element (default: 30000)

        Returns:
            Dict with hover result
        """
        start = time.perf_counter()
        params = {"selector": selector, "tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_hover", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_hover", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_hover", params, result=result)
            return result

        try:
            hover_result = await bridge.hover(target_tab, selector, timeout_ms=timeout_ms)
            log_tool_call(
                "browser_hover",
                params,
                result=hover_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return hover_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call("browser_hover", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
            return result

    @mcp.tool()
    async def browser_hover_coordinate(
        x: float,
        y: float,
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Hover at a FRACTION of the viewport (0..1, 0..1).

        Use this instead of browser_hover when the element is in an overlay,
        shadow DOM, or virtual-rendered component that isn't in the regular DOM.
        ``x`` / ``y`` are fractions of the viewport (``0.5`` = center);
        the tool converts to CSS px internally.

        Args:
            x: X fraction of the viewport (0..1).
            y: Y fraction of the viewport (0..1).
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with hover result
        """
        start = time.perf_counter()
        params = {"x": x, "y": y, "tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_hover_coordinate", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_hover_coordinate", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_hover_coordinate", params, result=result)
            return result

        if x > 1.5 or y > 1.5 or x < -0.1 or y < -0.1:
            result = {
                "ok": False,
                "error": (f"Coords ({x}, {y}) look like pixels. This tool expects fractions 0..1 of the viewport."),
            }
            log_tool_call("browser_hover_coordinate", params, result=result)
            return result

        try:
            from .inspection import _ensure_viewport_size

            cw, ch = await _ensure_viewport_size(target_tab)
            hover_result = await bridge.hover_coordinate(target_tab, x * cw, y * ch)
            log_tool_call(
                "browser_hover_coordinate",
                params,
                result=hover_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return hover_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_hover_coordinate",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

    @mcp.tool()
    async def browser_press_at(
        x: float,
        y: float,
        key: str,
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Move mouse to a FRACTION of the viewport (0..1, 0..1), then press a key.

        Use this instead of browser_press when the focused element is in an overlay
        or virtual-rendered component. Moving the mouse first routes the key event
        through native browser hit-testing instead of the DOM focus chain.
        ``x`` / ``y`` are fractions of the viewport; the tool converts
        to CSS px internally.

        Args:
            x: X fraction of the viewport (0..1).
            y: Y fraction of the viewport (0..1).
            key: Key to press (e.g. 'Enter', 'Space', 'Escape', 'ArrowDown')
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with press result
        """
        start = time.perf_counter()
        params = {"x": x, "y": y, "key": key, "tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_press_at", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_press_at", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_press_at", params, result=result)
            return result

        if x > 1.5 or y > 1.5 or x < -0.1 or y < -0.1:
            result = {
                "ok": False,
                "error": (f"Coords ({x}, {y}) look like pixels. This tool expects fractions 0..1 of the viewport."),
            }
            log_tool_call("browser_press_at", params, result=result)
            return result

        try:
            from .inspection import _ensure_viewport_size

            cw, ch = await _ensure_viewport_size(target_tab)
            press_result = await bridge.press_key_at(target_tab, x * cw, y * ch, key)
            log_tool_call(
                "browser_press_at",
                params,
                result=press_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return press_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_press_at",
                params,
                error=e,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return result

    @mcp.tool()
    async def browser_select(
        selector: str,
        values: list[str],
        tab_id: int | None = None,
        profile: str | None = None,
    ) -> dict:
        """
        Select option(s) in a dropdown/select element.

        Args:
            selector: CSS selector for the select element
            values: List of values to select
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")

        Returns:
            Dict with select result
        """
        start = time.perf_counter()
        params = {"selector": selector, "values": values, "tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_select", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_select", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_select", params, result=result)
            return result

        try:
            select_result = await bridge.select_option(target_tab, selector, values)
            log_tool_call(
                "browser_select",
                params,
                result=select_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return select_result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call("browser_select", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
            return result

    @mcp.tool()
    async def browser_scroll(
        direction: Literal["up", "down", "left", "right"] = "down",
        amount: int = 500,
        tab_id: int | None = None,
        profile: str | None = None,
        auto_snapshot_mode: AutoSnapshotMode = "default",
    ) -> dict:
        """
        Scroll the page.

        Args:
            direction: Scroll direction (up, down, left, right)
            amount: Scroll amount in pixels (default: 500)
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            auto_snapshot_mode: Controls the accessibility snapshot taken
                0.5s after a successful scroll. ``"default"`` returns the
                full tree; ``"simple"`` / ``"interactive"`` return tighter
                trees — useful on virtual-scroll UIs that produce huge
                default trees; ``"off"`` skips the capture — use when
                issuing many scrolls in a row.

        Returns:
            Dict with scroll result. Includes ``snapshot`` unless
            ``auto_snapshot_mode="off"`` or the scroll failed.
        """
        start = time.perf_counter()
        params = {"direction": direction, "amount": amount, "tab_id": tab_id, "profile": profile}

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_scroll", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_scroll", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_scroll", params, result=result)
            return result

        try:
            scroll_result = await bridge.scroll(target_tab, direction=direction, amount=amount)
            log_tool_call(
                "browser_scroll",
                params,
                result=scroll_result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return await _attach_snapshot(scroll_result, bridge, target_tab, auto_snapshot_mode)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call("browser_scroll", params, error=e, duration_ms=(time.perf_counter() - start) * 1000)
            return result

    @mcp.tool()
    async def browser_drag(
        start_selector: str,
        end_selector: str,
        tab_id: int | None = None,
        profile: str | None = None,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Drag from one element to another.

        Note: This is implemented via CDP mouse events and may not work
        for all drag-and-drop scenarios (e.g., HTML5 drag-drop).

        Args:
            start_selector: CSS selector for drag start element
            end_selector: CSS selector for drag end element
            tab_id: Chrome tab ID (default: active tab)
            profile: Browser profile name (default: "default")
            timeout_ms: Timeout waiting for elements (default: 30000)

        Returns:
            Dict with drag result
        """
        drag_start = time.perf_counter()
        params = {
            "start_selector": start_selector,
            "end_selector": end_selector,
            "tab_id": tab_id,
            "profile": profile,
        }

        bridge = get_bridge()
        if not bridge or not bridge.is_connected:
            result = {"ok": False, "error": "Browser extension not connected"}
            log_tool_call("browser_drag", params, result=result)
            return result

        ctx = _get_context(profile)
        if not ctx:
            result = {"ok": False, "error": "Browser not started. Call browser_start first."}
            log_tool_call("browser_drag", params, result=result)
            return result

        target_tab = tab_id or ctx.get("activeTabId")
        if target_tab is None:
            result = {"ok": False, "error": "No active tab"}
            log_tool_call("browser_drag", params, result=result)
            return result

        try:
            # Get coordinates for both elements and perform drag via CDP
            await bridge.cdp_attach(target_tab)
            await bridge._cdp(target_tab, "DOM.enable")
            await bridge._cdp(target_tab, "Input.enable")

            doc = await bridge._cdp(target_tab, "DOM.getDocument")
            root_id = doc.get("root", {}).get("nodeId")

            deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
            start_node = None
            while asyncio.get_event_loop().time() < deadline:
                result = await bridge._cdp(
                    target_tab,
                    "DOM.querySelector",
                    {"nodeId": root_id, "selector": start_selector},
                )
                start_node = result.get("nodeId")
                if start_node:
                    break
                await asyncio.sleep(0.1)

            if not start_node:
                result = {"ok": False, "error": f"Start element not found: {start_selector}"}
                log_tool_call("browser_drag", params, result=result)
                return result

            end_node = None
            while asyncio.get_event_loop().time() < deadline:
                result = await bridge._cdp(
                    target_tab,
                    "DOM.querySelector",
                    {"nodeId": root_id, "selector": end_selector},
                )
                end_node = result.get("nodeId")
                if end_node:
                    break
                await asyncio.sleep(0.1)

            if not end_node:
                result = {"ok": False, "error": f"End element not found: {end_selector}"}
                log_tool_call("browser_drag", params, result=result)
                return result

            # Get box models
            start_box = await bridge._cdp(target_tab, "DOM.getBoxModel", {"nodeId": start_node})
            end_box = await bridge._cdp(target_tab, "DOM.getBoxModel", {"nodeId": end_node})

            sc = start_box.get("content", [])
            ec = end_box.get("content", [])

            start_x = (sc[0] + sc[2] + sc[4] + sc[6]) / 4
            start_y = (sc[1] + sc[3] + sc[5] + sc[7]) / 4
            end_x = (ec[0] + ec[2] + ec[4] + ec[6]) / 4
            end_y = (ec[1] + ec[3] + ec[5] + ec[7]) / 4

            # Perform drag: mouse down at start, move to end, mouse up
            await bridge._cdp(
                target_tab,
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    "x": start_x,
                    "y": start_y,
                    "button": "left",
                    "clickCount": 1,
                },
            )
            await bridge._cdp(
                target_tab,
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": end_x, "y": end_y},
            )
            await bridge._cdp(
                target_tab,
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    "x": end_x,
                    "y": end_y,
                    "button": "left",
                    "clickCount": 1,
                },
            )

            result = {
                "ok": True,
                "action": "drag",
                "from": start_selector,
                "to": end_selector,
                "fromCoords": {"x": start_x, "y": start_y},
                "toCoords": {"x": end_x, "y": end_y},
            }
            log_tool_call(
                "browser_drag",
                params,
                result=result,
                duration_ms=(time.perf_counter() - drag_start) * 1000,
            )
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            log_tool_call(
                "browser_drag",
                params,
                error=e,
                duration_ms=(time.perf_counter() - drag_start) * 1000,
            )
            return result
