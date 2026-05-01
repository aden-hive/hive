"""OpenHive ECharts theme — brand palette + cozy spacing defaults.

Why this exists: ECharts ships with two built-in themes (default and 'dark')
that look generic-web-2010. The agent will reach for `#27ae60` / `#e74c3c`
and other hello-world hex codes unless we set sensible defaults at the
theme level. Centralizing the theme means BOTH the server-side renderer
(headless Chromium → PNG) and the live in-chat ECharts mount use the
same palette and spacing — pixel-equivalent output guaranteed.

The theme dict is shipped as a JSON string and loaded via
`echarts.registerTheme('openhive', themeObj)` before `echarts.init`.
"""

from __future__ import annotations

import json

# OpenHive brand palette — categorical, alternating warm/cool for
# adjacent-series distinguishability. Honey-amber primary follows our
# desktop app's `TOOL_HEX` palette; the cool counters (slate, sage,
# indigo) keep multi-series charts legible without resorting to neon.
_BRAND_PALETTE_LIGHT = [
    "#db6f02",  # honey orange (primary)
    "#456a8d",  # slate blue
    "#3d7a4a",  # sage green
    "#a8453d",  # terracotta brick
    "#c48820",  # warm bronze
    "#5d5b88",  # indigo
    "#7d6b51",  # olive
    "#8e4200",  # rust
]

# Dark theme variant: brighter saturations to maintain contrast against
# near-black backgrounds without becoming neon.
_BRAND_PALETTE_DARK = [
    "#ffb825",  # bright honey
    "#7ba2c4",  # cool slate
    "#7bb285",  # bright sage
    "#d97470",  # warm coral
    "#e0a83a",  # bright bronze
    "#9892c4",  # bright indigo
    "#b8a685",  # warm taupe
    "#d97e3a",  # bright rust
]


def build_theme(theme: str = "light") -> dict:
    """Return the OpenHive ECharts theme dict for the given mode.

    Cozy by default: title sits 24px from the top, axis ticks have
    breathing room, grid defaults give 80px above (for title+legend)
    and 60px below (for x-axis labels). The agent can still override
    everything via the spec — this is the floor, not the ceiling.
    """
    is_dark = theme == "dark"
    fg = "#e8e6e0" if is_dark else "#1a1a1a"
    fg_muted = "#8a8a8a" if is_dark else "#6b6b6b"
    grid_line = "#2a2724" if is_dark else "#ebe9e2"
    axis_line = "#3a3733" if is_dark else "#d0cfca"
    tooltip_bg = "#181715" if is_dark else "#ffffff"
    tooltip_border = "#2a2724" if is_dark else "#d0cfca"
    palette = _BRAND_PALETTE_DARK if is_dark else _BRAND_PALETTE_LIGHT

    return {
        "color": palette,
        "backgroundColor": "transparent",
        "textStyle": {
            "fontFamily": (
                '"Inter Tight", -apple-system, BlinkMacSystemFont, '
                '"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
            ),
            "color": fg,
            "fontSize": 12,
        },
        # Title sits cozy at the top with breathing room. Top:32 keeps
        # the title clear of the canvas edge AND well separated from
        # both the legend (top:72) and any axis name (which inherits
        # the value-axis name padding below).
        "title": {
            "left": "center",
            "top": 32,
            "textStyle": {"color": fg, "fontSize": 18, "fontWeight": 600},
            "subtextStyle": {"color": fg_muted, "fontSize": 13},
        },
        # Legend below the title with explicit gap so the two don't
        # visually fight. Pill-shaped icons read as buttons not bullets.
        "legend": {
            "top": 72,
            "icon": "roundRect",
            "itemWidth": 12,
            "itemHeight": 12,
            "itemGap": 20,
            "textStyle": {"color": fg_muted, "fontSize": 12},
        },
        # The plot area has *real* margins. top:130 leaves room for
        # title (32) + title text (24) + gap (16) + legend (20) +
        # legend-to-grid gap (18). bottom:80 fits two-line x-axis
        # labels like "Q1 FY26\n(Apr '25)" plus an axis name.
        # `containLabel: True` auto-shrinks the plot to fit axis labels.
        "grid": {
            "top": 130,
            "left": 56,
            "right": 56,
            "bottom": 80,
            "containLabel": True,
        },
        "categoryAxis": {
            "axisLine": {"show": True, "lineStyle": {"color": axis_line}},
            "axisTick": {"show": False},
            "axisLabel": {"color": fg_muted, "fontSize": 11, "margin": 14},
            "splitLine": {"show": False},
            # Axis name on the side, not crammed into the corner.
            "nameLocation": "middle",
            "nameGap": 38,
            "nameTextStyle": {"color": fg_muted, "fontSize": 12},
        },
        "valueAxis": {
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {"color": fg_muted, "fontSize": 11, "margin": 14},
            "splitLine": {"lineStyle": {"color": grid_line, "type": "dashed"}},
            # Y-axis name vertically-centered on the axis instead of
            # floating in the upper-left corner where it competes with
            # the title and legend.
            "nameLocation": "middle",
            "nameGap": 44,
            "nameTextStyle": {"color": fg_muted, "fontSize": 12, "fontWeight": 500},
            "nameRotate": 90,
        },
        # Same for log/time/etc. — keep the look consistent.
        "logAxis": {
            "axisLine": {"show": False},
            "axisLabel": {"color": fg_muted, "fontSize": 11},
            "splitLine": {"lineStyle": {"color": grid_line, "type": "dashed"}},
            "nameLocation": "middle",
            "nameGap": 44,
            "nameTextStyle": {"color": fg_muted, "fontSize": 12, "fontWeight": 500},
            "nameRotate": 90,
        },
        "timeAxis": {
            "axisLine": {"show": True, "lineStyle": {"color": axis_line}},
            "axisLabel": {"color": fg_muted, "fontSize": 11, "margin": 14},
            "splitLine": {"show": False},
            "nameLocation": "middle",
            "nameGap": 38,
            "nameTextStyle": {"color": fg_muted, "fontSize": 12},
        },
        # Tooltip styled to match the chat bubble palette.
        "tooltip": {
            "backgroundColor": tooltip_bg,
            "borderColor": tooltip_border,
            "borderWidth": 1,
            "padding": [8, 12],
            "textStyle": {"color": fg, "fontSize": 12},
            "axisPointer": {
                "lineStyle": {"color": axis_line, "type": "dashed"},
                "crossStyle": {"color": axis_line},
            },
        },
        # Bar series: subtle border-radius so bars look modern, not blocky.
        "bar": {"itemStyle": {"borderRadius": [3, 3, 0, 0]}},
        # Line series: thicker than the ECharts default for legibility on retina screens.
        "line": {
            "lineStyle": {"width": 2.5},
            "symbol": "circle",
            "symbolSize": 6,
        },
        # Candlestick: warm green up / brick red down — readable without
        # being CSS-hello-world green/red.
        "candlestick": {
            "itemStyle": {
                "color": "#3d7a4a",      # up body
                "color0": "#a8453d",     # down body
                "borderColor": "#3d7a4a",
                "borderColor0": "#a8453d",
            },
        },
    }


def theme_json(theme: str = "light") -> str:
    """Theme dict serialized as a JSON string, ready to be embedded in
    a JS `echarts.registerTheme(...)` call."""
    return json.dumps(build_theme(theme))


__all__ = ["build_theme", "theme_json"]
