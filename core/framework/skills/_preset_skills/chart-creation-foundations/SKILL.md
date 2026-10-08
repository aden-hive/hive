---
name: hive.chart-creation-foundations
description: Required reading whenever any chart_* tool is available. Teaches the one-tool embedding contract (call chart_render → live chart appears in chat AND a downloadable PNG lands in the queen session dir), the ECharts (data viz) vs Mermaid (structural diagrams) decision, the BI/financial-grade aesthetic baseline (no chartjunk, restrained palette, proper typography, single message per chart), and the canonical spec patterns for the 12 most-common chart types. Skipping this leads to 1990s-Excel charts, missing downloads, and the agent writing markdown image links by hand instead of letting chart_render drive the UI.
metadata:
  author: hive
  type: preset-skill
  version: "1.0"
---

# Chart creation foundations

These tools render BI/financial-analyst-grade charts and diagrams that show up live in the chat AND save as high-DPI PNGs in the user's queen session dir.

## The embedding contract — one rule

> **To put a chart in chat, call `chart_render`. The chat reads `result.spec` and renders the chart live in the message bubble. The download link is `result.file_url`. Do not write `![chart](...)` image markdown by hand — the tool's result drives the UI.**

That's it. One tool call, one chart in chat, one file on disk. No two-step "remember to also save it" pattern. The chat's chart-rendering UI is fed by the tool result envelope automatically.

## When to chart at all

Chart when the data is **visual at heart**: trends over time, distributions, comparisons across categories, hierarchies, flows, geo. Skip the chart when:

- The point is one number → just say it. ("Revenue was $4.2M, up 12% YoY.")
- The point is a ranking of 5 things → use a markdown table with bold and emoji indicators.
- The data is so noisy a chart would mislead → describe the takeaway in prose.

A chart costs the user attention. It must repay that cost with a takeaway they couldn't get from prose.

## ECharts vs Mermaid — the picking rule

| Use ECharts (`kind: "echarts"`) when... | Use Mermaid (`kind: "mermaid"`) when... |
|---|---|
| You're plotting **numbers over categories or time** | You're showing **structure, not data** |
| Bar / line / area / scatter / candlestick / heatmap / treemap / sankey / parallel coordinates / calendar / gauge / pie / sunburst / geo map | Flowchart / sequence / gantt / ERD / state diagram / mindmap / class diagram / C4 architecture |
| The viewer's question is "how much / how many / what's the trend" | The viewer's question is "what calls what / what depends on what / what happens after what" |

If both fit (rare), prefer ECharts — its rasterized output is a proper data chart for slides; Mermaid's diagrams are for technical docs.

## The aesthetic baseline (non-negotiable)

These are the rules that turn an Excel-default chart into a Tableau-grade one. Every chart you produce must follow them.

### 1. Theme & background
- `chart_render` has **no `theme` parameter**. The renderer reads the user's UI theme from the desktop env (`HIVE_DESKTOP_THEME`) so the saved PNG matches what the user is actually looking at. You don't pick; the system does.
- Title goes in `option.title.text`, NOT in the message body. The chart is self-contained.

### 2. Palette discipline — DO NOT set `color` on series

The OpenHive ECharts theme is auto-applied to every `chart_render` call. It defines:
- An 8-hue **categorical palette** for multi-series charts (honey orange, slate blue, sage, terracotta, bronze, indigo, olive, rust)
- Cozy spacing (`grid.top: 90`, `grid.bottom: 56`, etc.)
- Brand typography (Inter Tight)
- Tasteful axis lines + dashed gridlines

**Do not set `option.color`, `option.title.textStyle`, `option.grid`, or `option.itemStyle.color` on series.** The theme covers it. If you do override, you'll fight the brand palette and the chart will look generic.

When you need data-encoded color (NOT category color):
- **Sequential** (magnitude): use `visualMap` with `inRange.color: ['#fff7e0', '#db6f02']` (light-to-honey)
- **Diverging** (positive/negative): use `visualMap` with `inRange.color: ['#a8453d', '#f5f5f5', '#3d7a4a']` (terracotta/neutral/sage)
- **Semantic up/down** (candlestick is auto-themed): for explicit gain/loss bars use `#3d7a4a` (gain) and `#a8453d` (loss), NOT `#27ae60` / `#e74c3c`.

### 3. Typography
The default font (`-apple-system, "Inter Tight", system-ui`) is already wired in the renderer — don't override unless the user asked. Set `option.textStyle.fontSize: 13` for body labels, `16` for axis names, `18` bold for the title.

### 4. No chartjunk
- **No 3D**. Ever. 3D pie charts and 3D bar charts are visual lies.
- **No drop shadows** on bars or lines. The default flat ECharts look is correct.
- **No gradient fills** unless the gradient encodes data (e.g. heatmap fill).
- **No neon colors**. Saturation belongs on highlighted bars, not on every series.
- **No more than 5 stacked colors** in a stacked bar — past that the eye can't separate them.

### 5. Axis hygiene
- X-axis labels rotate 45° only when they overflow. Otherwise horizontal.
- Y-axis starts at 0 for bar/area charts (truncating misleads). Line charts can start at min - 5%.
- Use `option.yAxis.axisLabel.formatter: '{value} M'` to add units, NOT a separate "USD millions" subtitle.
- Date axes: pass ISO strings (`"2024-01-15"`) and ECharts handles the layout. Use `xAxis.type: "time"`.

### 6. One message per chart
Every chart goes in its own assistant message (or its own `chart_render` call). Do not pile 4 charts into one wall of tool calls — the user can't focus and the chat gets noisy.

## Calling `chart_render` — the canonical pattern

```
chart_render(
  kind="echarts",
  spec={
    "title": {"text": "Q4 revenue by region", "left": "center"},
    "tooltip": {"trigger": "axis"},
    "xAxis": {"type": "category", "data": ["NA", "EU", "APAC", "LATAM"]},
    "yAxis": {"type": "value", "axisLabel": {"formatter": "${value}M"}},
    "series": [{"type": "bar", "data": [12.4, 8.7, 5.3, 2.1], "itemStyle": {"color": "#db6f02"}}]
  },
  title="q4-revenue-by-region",
  width=1600, height=900, dpi=300
)
```

Returns:
```
{
  "kind": "echarts",
  "spec": {...echoed...},
  "file_path": "/.../charts/2026-04-30T...q4-revenue-by-region.png",
  "file_url": "file:///.../q4-revenue-by-region.png",
  "width": 1600, "height": 900, "dpi": 300, "bytes": 142318,
  "title": "q4-revenue-by-region", "runtime_ms": 287
}
```

The chat panel reads `result.spec` and mounts ECharts in the message bubble. The user sees the chart immediately. The PNG is on disk and the chat shows a download link from `result.file_url`. **You don't write that link — it appears automatically.**

## The 12 chart types you'll use 95% of the time

| When | ECharts type | Notes |
|---|---|---|
| Trend over time | `series.type: "line"` | Smooth = `smooth: true` only when data is noisy |
| Multi-metric trend | Two `line` series with `yAxis: [{}, {}]` | Separate scales when units differ |
| Category comparison | `series.type: "bar"` | Sort by value descending, not alphabetically |
| Stacked composition | `bar` with `stack: "total"` | Cap at 5 categories |
| Distribution | `series.type: "boxplot"` or `bar` of bins | Boxplot for ≥3 groups; histogram for one |
| Two-variable correlation | `series.type: "scatter"` | Add `regression` markline if relevant |
| Candlestick / OHLC | `series.type: "candlestick"` | Date axis + `dataZoom` range slider |
| Geo distribution | `series.type: "map"` | Bundled `world` and country GeoJSONs |
| Hierarchy / share | `series.type: "treemap"` or `sunburst` | Use treemap for >12 leaves; pie only for 2-5 |
| Flow | `series.type: "sankey"` | Names matter — keep them short |
| Calendar density | `series.type: "heatmap"` + `calendar` | Daily metrics over a year |
| KPI scorecard | `series.type: "gauge"` | Set `min`, `max`, threshold band |

Worked specs for each are in `references/` — paste, modify, render.

## Mermaid quick rules

```
chart_render(
  kind="mermaid",
  spec="""
flowchart LR
  A[Customer signs up] --> B{Onboarded?}
  B -- yes --> C[Activate trial]
  B -- no --> D[Email reminder]
""",
  title="signup-flow"
)
```

- One diagram per chart_render call.
- Keep node labels short (≤20 chars).
- Use `flowchart LR` for left-to-right; `TD` for top-down. LR reads better in a chat bubble.
- For sequence diagrams, indicate async with `->>` (open arrow) and sync return with `-->>` (dashed).
- Don't try to encode data in mermaid (no widths, no quantities) — that's an ECharts job.

## Common mistakes the agent makes

1. **Writing `![chart](file://...)` markdown by hand.** Don't. The chat renders from the tool result automatically. Manual image markdown will display nothing (file:// is blocked from arbitrary chat content).
2. **Calling chart_render twice for the same chart "to embed and to save".** Only one call. The single call does both.
3. **Overriding fonts to fancy display faces.** Stay with the default; the agent's job is data, not typography.
4. **Pie charts with 12 slices.** Use a horizontal bar chart sorted by value. Pie is only for 2-5 mutually-exclusive shares.
5. **Forgetting `axisLabel.formatter` for currency / percentage.** A y-axis showing "12000000" is unreadable; "12M" is correct.
6. **Putting a chart's title in the message body.** Set `option.title.text` instead so the title is part of the saved PNG.
