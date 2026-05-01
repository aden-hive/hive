"""Playwright-driven chart renderer.

Why Playwright (and not pyecharts / matplotlib / a Node subprocess):
the desktop chat renders ECharts/Mermaid in a real browser. To
guarantee that the *downloaded* PNG looks pixel-equivalent to what
the user saw live in chat, we use the same engine — Chromium — to
do the server-side render. Playwright is already a runtime dep
(used by gcu-tools), so this adds zero new Python deps.

Design:
  - One persistent Chromium browser per process. First chart spawns
    it (~1.5s); subsequent charts reuse the same browser context for
    ~200-300ms total render time per chart.
  - Each render gets a fresh ``Page`` (its own DOM, no leakage between
    charts), but the underlying browser process is shared.
  - The ``shutdown()`` function is wired into the FastMCP lifespan
    hook so the browser dies cleanly on server exit.
  - Static JS assets (``echarts.min.js``, ``mermaid.min.js``) are
    bundled with chart-tools and loaded into the page via
    ``page.add_script_tag`` — no network access at render time.

Concurrency: one browser-wide lock around ``render()`` so concurrent
agent calls don't race on the same page. Chrome handles parallel
pages fine internally, but the simpler serial model is plenty fast
for v1 (200-300ms per chart, <5 charts/turn typical).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Static JS lives next to this module under ./static/. The files are
# downloaded at install time by ``scripts/fetch_chart_assets.py`` (see
# the chart-tools README). When missing we fall back to CDN URLs so dev
# environments aren't blocked on the install step.
_STATIC_DIR = Path(__file__).parent / "static"
_ECHARTS_JS = _STATIC_DIR / "echarts.min.js"
_MERMAID_JS = _STATIC_DIR / "mermaid.min.js"
_ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"
_MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11.4.0/dist/mermaid.min.js"


class RendererError(RuntimeError):
    """Raised when a chart fails to render (invalid spec, browser death, etc.)."""


class ChartRenderer:
    """One-per-process Chromium pool for chart rendering."""

    def __init__(self):
        self._browser = None
        self._playwright = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def _ensure_browser(self) -> Any:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        # --no-sandbox is required when running as root inside containers;
        # harmless on a desktop dev box and accepted by Playwright.
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        logger.info("chart-tools: launched headless Chromium")
        return self._browser

    async def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._browser is not None:
                await self._browser.close()
        except Exception as exc:
            logger.warning("chart-tools: browser close error: %s", exc)
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception as exc:
            logger.warning("chart-tools: playwright stop error: %s", exc)

    async def render(
        self,
        *,
        kind: str,
        spec: Any,
        width: int,
        height: int,
        dpi: int,
        theme: str,
    ) -> bytes:
        """Render a single chart and return PNG bytes.

        ``dpi`` controls the device-pixel-ratio of the screenshot (300 dpi
        gives crisp output in print/slide decks). The on-screen logical
        size remains ``width × height`` CSS pixels; the screenshot is
        scaled to ``width * dpi/96 × height * dpi/96`` actual pixels.
        """
        if kind not in ("echarts", "mermaid"):
            raise RendererError(f"unknown kind {kind!r}; expected 'echarts' or 'mermaid'")

        async with self._lock:
            browser = await self._ensure_browser()
            scale = max(1.0, dpi / 96.0)
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            try:
                page = await context.new_page()
                html = _build_html(kind=kind, spec=spec, width=width, height=height, theme=theme)
                await page.set_content(html, wait_until="load")
                # Inject the chart library. Prefer bundled static; fall
                # back to CDN. Mermaid takes a beat to typeset; ECharts
                # renders synchronously once setOption is called.
                await _inject_lib(page, kind)
                await _render_in_page(page, kind=kind, spec=spec, theme=theme, width=width, height=height)
                # Make sure fonts are loaded before screenshotting so
                # rotated text doesn't shift after the snapshot.
                await page.wait_for_function("() => document.fonts.ready.then(() => true)")
                # ECharts and Mermaid both animate by default. _render_in_page
                # disables animations, but on the off chance they're still
                # progressing we wait for the chart's 'finished' signal
                # (set by _render_in_page on window.__chartReady).
                # Without this, screenshots capture mid-animation frames
                # where most data points haven't been drawn yet (the
                # 2026-05-01 "all data points are gone" bug).
                await page.wait_for_function(
                    "() => window.__chartReady === true",
                    timeout=10000,
                )
                target = page.locator("#chart")
                png = await target.screenshot(type="png", omit_background=False)
                return png
            finally:
                await context.close()


# ── module-level singleton ─────────────────────────────────────────

_INSTANCE: ChartRenderer | None = None


def get_renderer() -> ChartRenderer:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ChartRenderer()
    return _INSTANCE


# ── HTML / library injection ───────────────────────────────────────


def _build_html(*, kind: str, spec: Any, width: int, height: int, theme: str) -> str:
    """Build the HTML shell containing a sized #chart div.

    Single-layer #chart at the full requested width × height — same
    structure as the LIVE in-chat EChartsBlock, which the user
    confirmed renders correctly. An earlier two-layer #wrap+#chart
    design (with 24px outer padding) clipped rotated axis names like
    "$ Billions" because ECharts rendered axis-name SVG outside the
    inner #chart bounds and the wrapper padding cropped it (feedback
    2026-05-01). Cozy spacing now comes purely from the ECharts theme
    grid (top:130, left:56, right:56, bottom:80) — agent doesn't
    have to think about it; theme defaults handle it.

    Background is solid (white / near-black) so the downloaded PNG
    works on any embed surface (light slack, dark slack, slide deck).
    """
    bg = "#ffffff" if theme == "light" else "#0e0e0d"
    fg = "#1a1a1a" if theme == "light" else "#e8e6e0"
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  html, body {{
    margin: 0; padding: 0;
    background: {bg};
    color: {fg};
    font-family: "Inter Tight", -apple-system, BlinkMacSystemFont,
                 "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  }}
  #chart {{
    width: {width}px;
    height: {height}px;
    background: {bg};
  }}
  /* Mermaid centres its SVG inside the container by default */
  .mermaid {{ display: flex; justify-content: center; align-items: center; }}
</style>
</head>
<body>
<div id="chart"></div>
</body>
</html>
"""


async def _inject_lib(page: Any, kind: str) -> None:
    """Add the appropriate chart library to the page.

    Prefers bundled static; falls back to CDN. Errors here surface as
    RendererError because nothing else will render without the library.
    """
    if kind == "echarts":
        target = _ECHARTS_JS if _ECHARTS_JS.exists() else None
        cdn = _ECHARTS_CDN
    else:
        target = _MERMAID_JS if _MERMAID_JS.exists() else None
        cdn = _MERMAID_CDN

    try:
        if target is not None:
            await page.add_script_tag(path=str(target))
        else:
            logger.info("chart-tools: bundled %s missing, loading from CDN", kind)
            await page.add_script_tag(url=cdn)
    except Exception as exc:
        raise RendererError(f"failed to load {kind} library: {exc}") from exc


async def _render_in_page(
    page: Any,
    *,
    kind: str,
    spec: Any,
    theme: str,
    width: int,
    height: int,
) -> None:
    """Run the kind-specific render call inside the page's JS context."""
    if kind == "echarts":
        # Spec must be a JSON-serializable dict. NOTE: callers are
        # expected to have already coerced JSON-string specs into dicts
        # in chart_tools/tools.py — this is a defense-in-depth check.
        if isinstance(spec, str):
            raise RendererError(
                "spec arrived as a string; it should have been parsed to a dict in chart_render"
            )
        try:
            json.dumps(spec)
        except (TypeError, ValueError) as exc:
            raise RendererError(f"spec is not JSON-serializable: {exc}") from exc

        # Register the OpenHive theme on the page, then init with that
        # theme name. This means the agent's spec doesn't need to set
        # color / textStyle / grid / axisLine — the brand defaults
        # cover all of it, and any explicit field in the spec wins.
        from chart_tools.theme import theme_json

        result = await page.evaluate(
            """async ({option, themeJson}) => {
              try {
                echarts.registerTheme('openhive', JSON.parse(themeJson));
                const el = document.getElementById('chart');
                const chart = echarts.init(el, 'openhive', {renderer: 'svg'});

                // Disable all animations for the SSR render. Without
                // this the screenshot fires mid-animation and most
                // data points are missing (the 2026-05-01 "all data
                // points are gone" bug). We don't need animation in
                // a static PNG anyway.
                const sanitized = Object.assign({}, option, {
                  animation: false,
                  animationDuration: 0,
                  animationDurationUpdate: 0,
                  animationEasing: 'linear',
                  animationEasingUpdate: 'linear',
                });

                // Signal "render complete" via window.__chartReady so
                // the Python side knows when it's safe to screenshot.
                // ECharts fires 'finished' once the layout pass has
                // settled (axis labels measured, line paths laid out,
                // bars positioned). With animation=false this is
                // typically synchronous, but we still wait for the
                // event to be safe.
                window.__chartReady = false;
                chart.on('finished', () => { window.__chartReady = true; });
                chart.setOption(sanitized);
                // Belt-and-braces: if 'finished' didn't fire (some
                // edge cases with empty series), force-flag ready
                // after the next animation frame so we don't hang.
                requestAnimationFrame(() => {
                  requestAnimationFrame(() => { window.__chartReady = true; });
                });
                return {ok: true};
              } catch (e) {
                return {ok: false, error: String(e)};
              }
            }""",
            {"option": spec, "themeJson": theme_json(theme)},
        )
        if not result.get("ok"):
            raise RendererError(f"ECharts render failed: {result.get('error')}")

    elif kind == "mermaid":
        if not isinstance(spec, str):
            raise RendererError("mermaid spec must be a string")
        # mermaid.render returns a promise resolving to {svg, bindFunctions}.
        # Insert the SVG into #chart, then signal ready.
        result = await page.evaluate(
            """async ({source, theme}) => {
              try {
                if (typeof mermaid === 'undefined') {
                  return {ok: false, error: 'mermaid not loaded'};
                }
                mermaid.initialize({
                  startOnLoad: false,
                  theme: theme === 'dark' ? 'dark' : 'default',
                  securityLevel: 'loose',
                });
                window.__chartReady = false;
                const out = await mermaid.render('mmd-' + Math.random().toString(36).slice(2), source);
                document.getElementById('chart').innerHTML = out.svg;
                window.__chartReady = true;
                return {ok: true};
              } catch (e) {
                return {ok: false, error: String(e)};
              }
            }""",
            {"source": spec, "theme": theme},
        )
        if not result.get("ok"):
            raise RendererError(f"Mermaid render failed: {result.get('error')}")


__all__ = ["ChartRenderer", "RendererError", "get_renderer"]
