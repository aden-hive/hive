"""
Visual highlight animations for browser interactions.

Injects CSS/JS overlays to show where actions target before they execute.
Purely cosmetic — pointer-events: none, self-removing, fire-and-forget.

Configure via environment variables:
    HIVE_BROWSER_HIGHLIGHTS=0   Disable entirely
    HIVE_HIGHLIGHT_COLOR        Override color (default: #FAC43B)
    HIVE_HIGHLIGHT_DURATION_MS  Override visible duration (default: 600)
"""

from __future__ import annotations

import asyncio
import logging
import os

from playwright.async_api import Page

logger = logging.getLogger(__name__)

_ENABLED = os.environ.get("HIVE_BROWSER_HIGHLIGHTS", "1") != "0"
_COLOR = os.environ.get("HIVE_HIGHLIGHT_COLOR", "#FAC43B")
_DURATION_MS = int(os.environ.get("HIVE_HIGHLIGHT_DURATION_MS", "1500"))
_ANIMATION_WAIT_S = 0.35

# ---------------------------------------------------------------------------
# JS templates
# ---------------------------------------------------------------------------

_ELEMENT_HIGHLIGHT_JS = """
([box, color, durationMs]) => {
    const sx = window.scrollX, sy = window.scrollY;
    const x = box.x + sx, y = box.y + sy;
    const w = box.width, h = box.height;

    const container = document.createElement('div');
    Object.assign(container.style, {
        position: 'absolute',
        left: x + 'px',
        top: y + 'px',
        width: w + 'px',
        height: h + 'px',
        pointerEvents: 'none',
        zIndex: '2147483647',
        transition: 'opacity 0.3s ease',
    });
    document.body.appendChild(container);

    const arm = Math.max(8, Math.min(20, 0.35 * Math.min(w, h)));
    const pad = 3;
    const startOffset = 10;

    const corners = [
        { top: -pad, left: -pad, borderTop: '3px solid ' + color, borderLeft: '3px solid ' + color,
          tx: -startOffset, ty: -startOffset },
        { top: -pad, right: -pad, borderTop: '3px solid ' + color, borderRight: '3px solid ' + color,
          tx: startOffset, ty: -startOffset },
        { bottom: -pad, left: -pad, borderBottom: '3px solid ' + color, borderLeft: '3px solid ' + color,
          tx: -startOffset, ty: startOffset },
        { bottom: -pad, right: -pad, borderBottom: '3px solid ' + color, borderRight: '3px solid ' + color,
          tx: startOffset, ty: startOffset },
    ];

    corners.forEach(c => {
        const el = document.createElement('div');
        Object.assign(el.style, {
            position: 'absolute',
            width: arm + 'px',
            height: arm + 'px',
            pointerEvents: 'none',
            transition: 'transform 0.15s ease-out',
            transform: 'translate(' + c.tx + 'px, ' + c.ty + 'px)',
        });
        if (c.top !== undefined) el.style.top = c.top + 'px';
        if (c.bottom !== undefined) el.style.bottom = c.bottom + 'px';
        if (c.left !== undefined) el.style.left = c.left + 'px';
        if (c.right !== undefined) el.style.right = c.right + 'px';
        if (c.borderTop) el.style.borderTop = c.borderTop;
        if (c.borderBottom) el.style.borderBottom = c.borderBottom;
        if (c.borderLeft) el.style.borderLeft = c.borderLeft;
        if (c.borderRight) el.style.borderRight = c.borderRight;
        container.appendChild(el);

        setTimeout(() => { el.style.transform = 'translate(0, 0)'; }, 10);
    });

    setTimeout(() => {
        container.style.opacity = '0';
        setTimeout(() => container.remove(), 300);
    }, durationMs);
}
"""

_COORDINATE_HIGHLIGHT_JS = """
([cx, cy, color, durationMs]) => {
    const sx = window.scrollX, sy = window.scrollY;
    const x = cx + sx, y = cy + sy;

    const container = document.createElement('div');
    Object.assign(container.style, {
        position: 'absolute',
        left: x + 'px',
        top: y + 'px',
        pointerEvents: 'none',
        zIndex: '2147483647',
    });
    document.body.appendChild(container);

    // Expanding ripple ring
    const ripple = document.createElement('div');
    Object.assign(ripple.style, {
        position: 'absolute',
        left: '0px',
        top: '0px',
        width: '0px',
        height: '0px',
        borderRadius: '50%',
        border: '2px solid ' + color,
        transform: 'translate(-50%, -50%)',
        opacity: '1',
        transition: 'width 0.5s ease-out, height 0.5s ease-out, opacity 0.5s ease-out',
        pointerEvents: 'none',
    });
    container.appendChild(ripple);
    setTimeout(() => {
        ripple.style.width = '60px';
        ripple.style.height = '60px';
        ripple.style.opacity = '0';
    }, 10);

    // Center dot
    const dot = document.createElement('div');
    Object.assign(dot.style, {
        position: 'absolute',
        left: '-4px',
        top: '-4px',
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        backgroundColor: color,
        transform: 'scale(0)',
        transition: 'transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
        pointerEvents: 'none',
    });
    container.appendChild(dot);
    setTimeout(() => { dot.style.transform = 'scale(1)'; }, 10);

    setTimeout(() => {
        dot.style.transition = 'opacity 0.3s ease';
        dot.style.opacity = '0';
        setTimeout(() => container.remove(), 300);
    }, durationMs);
}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def highlight_element(page: Page, selector: str) -> None:
    """Show corner-bracket highlight around *selector* before an action."""
    if not _ENABLED:
        return
    try:
        box = await page.locator(selector).first.bounding_box(timeout=2000)
        if box is None:
            return
        await page.evaluate(
            _ELEMENT_HIGHLIGHT_JS,
            [box, _COLOR, _DURATION_MS],
        )
        await asyncio.sleep(_ANIMATION_WAIT_S)
    except Exception:
        logger.debug("highlight_element failed for %s", selector, exc_info=True)


async def highlight_coordinate(page: Page, x: float, y: float) -> None:
    """Show ripple + dot highlight at *(x, y)* viewport coords."""
    if not _ENABLED:
        return
    try:
        await page.evaluate(
            _COORDINATE_HIGHLIGHT_JS,
            [x, y, _COLOR, _DURATION_MS],
        )
        await asyncio.sleep(_ANIMATION_WAIT_S)
    except Exception:
        logger.debug("highlight_coordinate failed at (%s, %s)", x, y, exc_info=True)
