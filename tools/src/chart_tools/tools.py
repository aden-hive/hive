"""``chart_render`` — the single agent-facing tool.

Calling it both renders the chart in chat (the rich envelope is the
embedding signal — see ChartToolDetail.tsx in the desktop renderer) and
produces a downloadable PNG file the user can save.

The result envelope echoes the spec back so the chat panel can render
the chart live from the same data the server rasterized. This means
the chart can be reconstructed even when the user reopens an old
session — the spec lives in events.jsonl as the tool's result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chart_tools.renderer import RendererError

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


_DEFAULT_WIDTH = 1600
_DEFAULT_HEIGHT = 900
_DEFAULT_DPI = 300
_MIN_PNG_BYTES = 200  # sanity floor for "did the screenshot actually contain anything"


def _system_theme() -> str:
    """Resolve the user's UI theme from the desktop env var.

    The Electron main process sets ``HIVE_DESKTOP_THEME`` to ``"light"``
    or ``"dark"`` when spawning the runtime, sourced from
    ``nativeTheme.shouldUseDarkColors`` so the rendered PNG matches
    whatever the user is actually looking at. Theme is intentionally
    NOT exposed to the agent (the agent has no UI context, and saved
    charts should match the user's app). Falls back to "light" for
    headless / non-desktop runtimes.
    """
    val = (os.environ.get("HIVE_DESKTOP_THEME") or "").strip().lower()
    return "dark" if val == "dark" else "light"


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def chart_render(
        kind: str,
        spec: Any,
        title: str = "",
        width: int = _DEFAULT_WIDTH,
        height: int = _DEFAULT_HEIGHT,
        dpi: int = _DEFAULT_DPI,
        output_path: str | None = None,
    ) -> dict:
        """Render a chart or diagram to a high-DPI PNG and return a rich
        envelope so the chat can also render the chart live.

        This single tool drives both the live in-chat embedding (chat
        reads `result.spec` and mounts the same lib in the bubble) and
        the downloadable file (chat shows `result.file_url` as a link).
        Calling this tool IS the embedding — there is no separate
        "show in chat" step.

        Args:
            kind: "echarts" for ECharts JSON specs (general BI: bar, line,
                  area, scatter, candlestick, heatmap, treemap, sankey,
                  parallel, calendar, gauge, pie, sunburst, geo maps).
                  "mermaid" for diagrams (flowchart, sequence, gantt, ERD,
                  state, mindmap, C4).
            spec: For kind="echarts", a dict matching the ECharts option
                  schema (https://echarts.apache.org/en/option.html).
                  For kind="mermaid", the raw mermaid source string.
            title: Short slug used in the auto-generated filename.
                   Trims to lowercase-hyphenated. Required for
                   discoverability via chart_list_recent later.
            width, height: Logical viewport size in CSS pixels. Default
                  1600×900 is good for slide decks; 1200×800 for web;
                  640×400 for inline thumbnails.
            dpi: Device pixel ratio for the screenshot. 300 is print
                  quality; 150 is web-retina; 96 is screen-default.
                  Higher dpi = larger file, no quality difference once
                  past the display's native ratio.
            output_path: Override where the PNG lands. Default is
                  $HIVE_HOME/charts/<UTC-timestamp>-<title>.png.

        Note: theme is NOT an argument. It's resolved automatically
        from the desktop's HIVE_DESKTOP_THEME env var so the saved
        chart matches the user's UI without the agent picking.

        Returns:
            {
              "kind": "echarts" | "mermaid",
              "spec": <echoed spec>,
              "file_path": "/abs/path/to/chart.png",
              "file_url": "file:///abs/path/to/chart.png",
              "width": 1600,
              "height": 900,
              "dpi": 300,
              "bytes": 142318,
              "title": "revenue-by-region"
            }

            On error, returns {"error": "...", "spec": <echoed>, "kind": ...}
            so the chat can still surface a "spec invalid" pill rather
            than swallowing the failure.
        """
        if kind not in ("echarts", "mermaid"):
            return {
                "error": f"kind must be 'echarts' or 'mermaid', got {kind!r}",
                "kind": kind,
                "spec": spec,
            }

        # Theme is sourced from the desktop env, not the agent. The
        # Electron main process sets HIVE_DESKTOP_THEME from
        # nativeTheme.shouldUseDarkColors when it spawns the runtime,
        # so the rendered PNG matches whatever the user is looking at.
        # Falls back to "light" for headless / non-desktop runs.
        theme = _system_theme()

        # Coerce JSON-string specs to dicts. Common LLM mistake: agent
        # serializes the ECharts option to JSON before passing it instead
        # of letting the MCP layer marshal a dict. Without this we'd hand
        # JS a string and `chart.setOption("...")` blows up with
        # "Cannot create property 'series' on string '...'" — the exact
        # error reported by the user on 2026-05-01.
        if kind == "echarts" and isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except json.JSONDecodeError as exc:
                return {
                    "error": (
                        f"spec was a string but not valid JSON: {exc}. "
                        "Pass the spec as a dict, not a JSON-encoded string."
                    ),
                    "kind": kind,
                    "spec": spec,
                }

        # Resolve output path
        try:
            resolved_path = _resolve_output_path(output_path, title)
        except OSError as exc:
            return {"error": f"could not create output dir: {exc}", "kind": kind, "spec": spec}

        # One retry on transient errors (browser cold-start race, font
        # loading flake). Persistent spec errors fail fast.
        start = time.monotonic()
        last_error: Exception | None = None
        png_bytes: bytes | None = None
        for attempt in range(2):
            try:
                png_bytes = await _render_async(
                    kind=kind,
                    spec=spec,
                    width=int(width),
                    height=int(height),
                    dpi=int(dpi),
                    theme=theme,
                )
                break
            except RendererError as exc:
                last_error = exc
                # RendererError wraps both spec-syntax errors and
                # browser-side flakes. We retry once for the latter; if
                # the second attempt fails too, surface the error so the
                # agent can fix it.
                logger.warning("chart_render attempt %d/%d failed: %s", attempt + 1, 2, exc)
                if attempt == 0:
                    await asyncio.sleep(0.15)
                    continue
                return {"error": str(exc), "kind": kind, "spec": spec, "retried": True}
            except Exception as exc:  # noqa: BLE001 — surface unexpected errors to the agent
                logger.exception("chart_render unexpected failure (attempt %d)", attempt + 1)
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(0.15)
                    continue
                msg = repr(exc) if str(exc) == "" else str(exc)
                return {
                    "error": f"renderer crashed: {type(exc).__name__}: {msg}",
                    "kind": kind,
                    "spec": spec,
                    "retried": True,
                }

        if png_bytes is None:
            return {
                "error": f"renderer produced no bytes after retry; last error: {last_error}",
                "kind": kind,
                "spec": spec,
                "retried": True,
            }

        if len(png_bytes) < _MIN_PNG_BYTES:
            return {
                "error": f"render produced suspiciously small PNG ({len(png_bytes)} bytes)",
                "kind": kind,
                "spec": spec,
            }

        try:
            resolved_path.write_bytes(png_bytes)
        except OSError as exc:
            return {
                "error": f"could not write {resolved_path}: {exc}",
                "kind": kind,
                "spec": spec,
            }

        runtime_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "chart_render: kind=%s title=%s %dx%d@%ddpi → %s (%d bytes, %dms)",
            kind,
            title or "(untitled)",
            width,
            height,
            dpi,
            resolved_path,
            len(png_bytes),
            runtime_ms,
        )

        return {
            "kind": kind,
            "spec": spec,
            "file_path": str(resolved_path),
            "file_url": resolved_path.as_uri(),
            "width": int(width),
            "height": int(height),
            "dpi": int(dpi),
            "bytes": len(png_bytes),
            "title": title,
            "runtime_ms": runtime_ms,
        }

    # NOTE: chart_list_recent was dropped as redundant per design feedback
    # 2026-05-01. The agent rarely needed to enumerate past charts; when
    # it does, the existing files-tools.list_directory works against
    # $HIVE_HOME/charts/ with the same outcome.


# ── helpers ────────────────────────────────────────────────────────


def _hive_home() -> Path:
    override = os.environ.get("HIVE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".hive"


def _charts_dir() -> Path:
    return _hive_home() / "charts"


def _slugify(s: str) -> str:
    """Lowercase, hyphenate, strip non-[a-z0-9-]. Empty input → 'chart'."""
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "chart"


def _resolve_output_path(override: str | None, title: str) -> Path:
    if override:
        p = Path(override).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    charts_dir = _charts_dir()
    charts_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
    return charts_dir / f"{ts}-{_slugify(title)}.png"


async def _render_async(*, kind: str, spec: Any, width: int, height: int, dpi: int, theme: str) -> bytes:
    """Render with a fresh Chromium per call.

    Playwright proxy objects are bound to the asyncio loop that
    created them, and pytest creates a new loop per test, so a
    persistent module-level renderer can't be reused safely across
    test boundaries. Cost: ~700ms per render (Chromium cold start
    dominates). For production, a worker-thread pool with its own
    long-lived loop is the optimization (TODO).
    """
    from chart_tools.renderer import ChartRenderer

    renderer = ChartRenderer()
    try:
        return await renderer.render(
            kind=kind,
            spec=spec,
            width=width,
            height=height,
            dpi=dpi,
            theme=theme,
        )
    finally:
        await renderer.shutdown()


__all__ = ["register_tools"]
