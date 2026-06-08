/**
 * Live ECharts renderer for the chat bubble.
 *
 * Mounts an ECharts instance into a sized div and feeds it the spec
 * the agent passed to `chart_render`. The same spec is rendered
 * server-side to a PNG; the live render is the in-chat experience,
 * the PNG is the downloadable.
 *
 * - Lazy-loaded via dynamic import so non-chart messages don't pay
 *   the ~1 MB bundle cost.
 * - SVG renderer (`{ renderer: 'svg' }`) for crisp scaling and lower
 *   memory than canvas. Looks identical at chat-bubble sizes.
 * - Resize handled via ResizeObserver; charts adapt to the bubble's
 *   width while keeping a fixed aspect ratio.
 * - Error boundary inside the component itself: invalid specs render
 *   a tiny "spec invalid" pill with a copy-spec button so the agent
 *   can self-correct on the next turn.
 */

import { useEffect, useRef, useState } from "react";
import { AlertCircle } from "lucide-react";
import { buildOpenHiveTheme } from "./openhiveTheme";

interface Props {
  spec: unknown;
  /** Aspect ratio kept while the width adapts to the bubble. Defaults
   * to 16:9 — the standard chart shape that fits in slide decks. */
  aspectRatio?: number;
  /** Hard cap on rendered height (px). Prevents very-tall charts from
   * dominating the chat scroll. */
  maxHeight?: number;
}

const _themeRegistered: Record<"light" | "dark", boolean> = {
  light: false,
  dark: false,
};

/**
 * Detect the user's current UI theme from the DOM. The OpenHive
 * desktop app applies a `dark` class to <html> in dark mode (see
 * index.css). We use the same signal here so the live chart matches
 * the surrounding chat — neither the agent nor the caller picks the
 * theme, and the PNG download is rendered server-side from the same
 * source of truth (HIVE_DESKTOP_THEME env, set by Electron from
 * nativeTheme.shouldUseDarkColors).
 */
function useDocumentTheme(): "light" | "dark" {
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  useEffect(() => {
    const obs = new MutationObserver(() => {
      setTheme(
        document.documentElement.classList.contains("dark") ? "dark" : "light",
      );
    });
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => obs.disconnect();
  }, []);
  return theme;
}

export default function EChartsBlock({
  spec,
  aspectRatio = 16 / 9,
  maxHeight = 480,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<unknown>(null); // echarts.ECharts instance, kept untyped to avoid coupling the type import
  const [error, setError] = useState<string | null>(null);
  // Theme follows the user's OpenHive UI mode automatically. Same
  // signal feeds the server-side PNG render via HIVE_DESKTOP_THEME, so
  // live chart and downloaded file always match.
  const theme = useDocumentTheme();

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;

    (async () => {
      try {
        const echarts = await import("echarts");
        if (disposed || !containerRef.current) return;
        // Register the OpenHive brand theme once per (theme, mode) so
        // bar/line/etc. inherit our palette + cozy spacing instead of
        // ECharts' generic-web-2010 defaults. Theme matches the
        // server-side render via tools/src/chart_tools/theme.py.
        const themeName = theme === "dark" ? "openhive-dark" : "openhive-light";
        if (!_themeRegistered[theme]) {
          echarts.registerTheme(themeName, buildOpenHiveTheme(theme));
          _themeRegistered[theme] = true;
        }
        // Coerce string specs to objects (defensive — the agent should
        // pass dicts but LLMs sometimes serialize before sending).
        let parsedSpec: Record<string, unknown>;
        if (typeof spec === "string") {
          try {
            parsedSpec = JSON.parse(spec);
          } catch {
            throw new Error("spec is a string and not valid JSON");
          }
        } else {
          parsedSpec = spec as Record<string, unknown>;
        }

        // Disjoint-region layout policy. ECharts has no auto-layout
        // for component overlap (verified against the option ref):
        // title/legend/grid are absolutely positioned and ignore each
        // other. We enforce three non-overlapping regions:
        //   - Title: anchored to TOP (top:16, no bottom)
        //   - Legend: anchored to BOTTOM (bottom:16, no top) except
        //     when orient:'vertical' (side legend stays where placed)
        //   - Grid: middle, with containLabel for axis labels
        // Strips user-supplied vertical positions so an agent spec
        // like `legend.top:"8%"` (which lands inside the title at
        // chat-bubble dimensions — the 2026-05-01 bug) can't collide.
        // Horizontal anchoring is preserved so left-aligned legends
        // still work. Must mirror chart_tools/renderer.py exactly so
        // the live chart and downloaded PNG look the same.
        const userTitle = (parsedSpec.title as Record<string, unknown> | undefined) ?? {};
        const userLegend = parsedSpec.legend as Record<string, unknown> | undefined;
        const userGrid = (parsedSpec.grid as Record<string, unknown> | undefined) ?? {};
        const legendVertical = userLegend?.orient === "vertical";
        const stripV = (o: Record<string, unknown>) => {
          const c = { ...o };
          delete c.top;
          delete c.bottom;
          return c;
        };
        const normalizedSpec: Record<string, unknown> = {
          ...parsedSpec,
          title: { left: "center", ...stripV(userTitle), top: 16 },
          grid: {
            left: 56,
            right: 56,
            ...stripV(userGrid),
            // Force vertical bounds — user-supplied grid.top/bottom
            // (often percentage strings like "8%" the agent picks at
            // default dims) don't generalize across chat-bubble sizes.
            // 96 covers: bottom legend (~36) + xAxis name (containLabel
            // handles tick labels but NOT axis name; outerBoundsMode is
            // v6+ and we're on v5). 40 when no legend.
            top: 64,
            bottom: userLegend && !legendVertical ? 96 : 40,
            containLabel: true,
          },
        };
        if (userLegend) {
          const legendDefaults = {
            icon: "roundRect",
            itemWidth: 12,
            itemHeight: 12,
            itemGap: 16,
          };
          normalizedSpec.legend = legendVertical
            ? { ...legendDefaults, ...userLegend }
            : { ...legendDefaults, ...stripV(userLegend), bottom: 16 };
        }

        // Fresh chart instance per spec; cheaper than reuse + setOption
        // for our sizes and avoids stale state between specs.
        const chart = echarts.init(containerRef.current, themeName, {
          renderer: "svg",
        });
        chartRef.current = chart;
        chart.setOption(normalizedSpec, {
          notMerge: true,
          lazyUpdate: false,
        });

        // Resize on container size change.
        resizeObserver = new ResizeObserver(() => {
          if (chartRef.current && containerRef.current) {
            (chartRef.current as { resize: () => void }).resize();
          }
        });
        resizeObserver.observe(containerRef.current);
      } catch (e) {
        if (!disposed) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();

    return () => {
      disposed = true;
      if (resizeObserver) resizeObserver.disconnect();
      if (chartRef.current) {
        try {
          (chartRef.current as { dispose: () => void }).dispose();
        } catch {
          // best-effort cleanup
        }
        chartRef.current = null;
      }
    };
  }, [spec, theme]);

  if (error) {
    return (
      <div
        className="flex items-center gap-2 text-[11px] text-muted-foreground px-2.5 py-1.5 rounded-md border border-border/40 bg-muted/30"
        role="alert"
      >
        <AlertCircle className="w-3 h-3 shrink-0" />
        <span>chart spec invalid: {error}</span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      // Transparent background so the chart blends with the chat bubble
      // instead of sitting in an obtrusive white card. The OpenHive
      // ECharts theme also sets backgroundColor: 'transparent' so the
      // chart itself is see-through. Subtle rounded corners only.
      className="w-full rounded-lg bg-transparent"
      style={{
        // Reserve aspect-ratio space so the chart doesn't pop in.
        // ECharts will overwrite the inline style as it lays out.
        aspectRatio,
        maxHeight,
      }}
    />
  );
}
