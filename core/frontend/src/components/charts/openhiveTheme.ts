/**
 * OpenHive ECharts theme — must stay in sync with
 * tools/src/chart_tools/theme.py on the runtime side.
 *
 * Same palette + spacing both for the live in-chat ECharts mount
 * (see EChartsBlock.tsx) and the headless server-side render that
 * produces the downloadable PNG. Without this both diverge: the chat
 * shows ECharts default colors and the PNG shows OpenHive colors,
 * confusing the user.
 */

const PALETTE_LIGHT = [
  "#db6f02", // honey orange (primary)
  "#456a8d", // slate blue
  "#3d7a4a", // sage green
  "#a8453d", // terracotta brick
  "#c48820", // warm bronze
  "#5d5b88", // indigo
  "#7d6b51", // olive
  "#8e4200", // rust
];

const PALETTE_DARK = [
  "#ffb825",
  "#7ba2c4",
  "#7bb285",
  "#d97470",
  "#e0a83a",
  "#9892c4",
  "#b8a685",
  "#d97e3a",
];

export function buildOpenHiveTheme(theme: "light" | "dark" = "light") {
  const isDark = theme === "dark";
  const fg = isDark ? "#e8e6e0" : "#1a1a1a";
  const fgMuted = isDark ? "#8a8a8a" : "#6b6b6b";
  const gridLine = isDark ? "#2a2724" : "#ebe9e2";
  const axisLine = isDark ? "#3a3733" : "#d0cfca";
  const tooltipBg = isDark ? "#181715" : "#ffffff";
  const tooltipBorder = isDark ? "#2a2724" : "#d0cfca";
  const palette = isDark ? PALETTE_DARK : PALETTE_LIGHT;

  return {
    color: palette,
    backgroundColor: "transparent",
    textStyle: {
      fontFamily:
        '"Inter Tight", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
      color: fg,
      fontSize: 12,
    },
    title: {
      left: "center",
      top: 28,
      textStyle: { color: fg, fontSize: 16, fontWeight: 600 },
      subtextStyle: { color: fgMuted, fontSize: 12 },
    },
    legend: {
      top: 64,
      icon: "roundRect",
      itemWidth: 12,
      itemHeight: 12,
      itemGap: 20,
      textStyle: { color: fgMuted, fontSize: 12 },
    },
    grid: {
      top: 116,
      left: 48,
      right: 48,
      bottom: 72,
      containLabel: true,
    },
    categoryAxis: {
      axisLine: { show: true, lineStyle: { color: axisLine } },
      axisTick: { show: false },
      axisLabel: { color: fgMuted, fontSize: 11, margin: 14 },
      splitLine: { show: false },
      nameLocation: "middle",
      nameGap: 36,
      nameTextStyle: { color: fgMuted, fontSize: 12 },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: fgMuted, fontSize: 11, margin: 14 },
      splitLine: { lineStyle: { color: gridLine, type: "dashed" } },
      nameLocation: "middle",
      nameGap: 42,
      nameTextStyle: { color: fgMuted, fontSize: 12, fontWeight: 500 },
      // Don't auto-rotate value-axis names — the theme can't tell xAxis
      // (horizontal bar) from yAxis (vertical bar), so rotating both at
      // 90° vertical-mounts the xAxis name on horizontal-bar charts and
      // it collides with the legend (peer_val regression). Let specs
      // set nameRotate explicitly when they want a vertical y-name.
    },
    timeAxis: {
      axisLine: { show: true, lineStyle: { color: axisLine } },
      axisLabel: { color: fgMuted, fontSize: 11, margin: 14 },
      splitLine: { show: false },
      nameLocation: "middle",
      nameGap: 36,
      nameTextStyle: { color: fgMuted, fontSize: 12 },
    },
    tooltip: {
      backgroundColor: tooltipBg,
      borderColor: tooltipBorder,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: fg, fontSize: 12 },
      axisPointer: {
        lineStyle: { color: axisLine, type: "dashed" },
        crossStyle: { color: axisLine },
      },
    },
    bar: { itemStyle: { borderRadius: [3, 3, 0, 0] } },
    line: {
      lineStyle: { width: 2.5 },
      symbol: "circle",
      symbolSize: 6,
    },
    candlestick: {
      itemStyle: {
        color: "#3d7a4a",
        color0: "#a8453d",
        borderColor: "#3d7a4a",
        borderColor0: "#a8453d",
      },
    },
  };
}
