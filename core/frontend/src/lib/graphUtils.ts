import { useEffect, useState } from "react";

// ── Shared graph utilities ──
// Shared helpers for graph-like components (TriggersPanel, etc.).

/** Read a CSS custom property value (space-separated HSL components). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Truncate label to fit within `availablePx` at the given fontSize. */
export function truncateLabel(label: string, availablePx: number, fontSize: number): string {
  const avgCharW = fontSize * 0.58;
  const maxChars = Math.floor(availablePx / avgCharW);
  if (label.length <= maxChars) return label;
  return label.slice(0, Math.max(maxChars - 1, 1)) + "\u2026";
}

// ── Trigger styling ──

export type TriggerColorSet = { bg: string; border: string; text: string; icon: string };

export function buildTriggerColors(): TriggerColorSet {
  const bg = cssVar("--trigger-bg") || "210 25% 14%";
  const border = cssVar("--trigger-border") || "210 30% 30%";
  const text = cssVar("--trigger-text") || "210 30% 65%";
  const icon = cssVar("--trigger-icon") || "210 40% 55%";
  return {
    bg: `hsl(${bg})`,
    border: `hsl(${border})`,
    text: `hsl(${text})`,
    icon: `hsl(${icon})`,
  };
}

export function buildActiveTriggerColors(): TriggerColorSet {
  const bg = cssVar("--trigger-active-bg") || "210 30% 90%";
  const border = cssVar("--trigger-active-border") || "210 40% 60%";
  const text = cssVar("--trigger-active-text") || "210 40% 30%";
  const icon = cssVar("--trigger-active-icon") || "210 50% 45%";
  return {
    bg: `hsl(${bg})`,
    border: `hsl(${border})`,
    text: `hsl(${text})`,
    icon: `hsl(${icon})`,
  };
}

/** Theme-reactive hook for active trigger colors. */
export function useActiveTriggerColors(): TriggerColorSet {
  const [colors, setColors] = useState<TriggerColorSet>(buildActiveTriggerColors);

  useEffect(() => {
    const rebuild = () => setColors(buildActiveTriggerColors());
    const obs = new MutationObserver(rebuild);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style"] });
    return () => obs.disconnect();
  }, []);

  return colors;
}

export const TRIGGER_ICONS: Record<string, string> = {
  webhook: "\u26A1",  // lightning bolt
  timer: "\u23F1",    // stopwatch
  api: "\u2192",      // right arrow
  event: "\u223F",    // sine wave
};

const DOW_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Convert a UTC hour/minute into the viewer's local clock, returning the
 *  rendered "9AM" / "9:30AM" string plus the day rollover (local day minus
 *  UTC day, -1/0/+1) so weekly labels can shift the weekday set back. */
function utcToLocalClock(
  utcH: number,
  utcM: number,
): { label: string; dayShift: number } {
  const d = new Date();
  d.setUTCHours(utcH, utcM, 0, 0);
  const h = d.getHours();
  const m = d.getMinutes();
  const suffix = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  const label = m === 0 ? `${h12}${suffix}` : `${h12}:${String(m).padStart(2, "0")}${suffix}`;
  const localDay = Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const utcDay = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  return { label, dayShift: Math.round((localDay - utcDay) / 86_400_000) };
}

/** Expand a cron day-of-week field (`1-5`, `0,6`, `1,3,5`) into a set of
 *  0–6 day numbers (Sunday=0), or null if it isn't a plain numeric list. */
function expandDow(field: string): Set<number> | null {
  const out = new Set<number>();
  for (const piece of field.split(",")) {
    const m = piece.match(/^(\d+)(?:-(\d+))?$/);
    if (!m) return null;
    const lo = parseInt(m[1], 10);
    const hi = m[2] != null ? parseInt(m[2], 10) : lo;
    if (lo > hi || hi > 7) return null;
    for (let v = lo; v <= hi; v++) out.add(v % 7); // cron 7 == Sunday == 0
  }
  return out;
}

/** Format a cron expression into a human-readable schedule label. */
export function cronToLabel(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [min, hour, dom, mon, dow] = parts;

  // */N * * * * -> "Every Nm"
  if (min.startsWith("*/") && hour === "*" && dom === "*" && mon === "*" && dow === "*") {
    return `Every ${min.slice(2)}m`;
  }
  // 0 */N * * * -> "Every Nh"
  if (min === "0" && hour.startsWith("*/") && dom === "*" && mon === "*" && dow === "*") {
    return `Every ${hour.slice(2)}h`;
  }

  // The remaining forms fix a specific minute + hour (stored in UTC); bail if
  // either is wildcarded.
  if (min.includes("*") || hour.includes("*")) return cron;
  const utcH = parseInt(hour, 10);
  const utcM = parseInt(min, 10);
  if (!Number.isFinite(utcH) || !Number.isFinite(utcM)) return cron;

  // 0 H * * * -> "Daily at Ham/pm" (in user's local timezone).
  //
  // The backend stores cron expressions in UTC, so "0 15 * * *" means
  // 15:00 UTC — which for a viewer in PDT (UTC-7) is 8:00 AM local. We
  // convert by stuffing the UTC hour/minute into a Date and reading back the
  // local fields; this also handles half-hour offsets like India's UTC+5:30.
  if (dom === "*" && mon === "*" && dow === "*") {
    return `Daily at ${utcToLocalClock(utcH, utcM).label}`;
  }

  // M H * * D[,D...] -> "Weekdays / Weekends / Mon, Wed at <local time>".
  // Both the local time AND the weekday set are converted from UTC: when the
  // local clock rolls across UTC midnight the days shift by ±1 (mirrors the
  // builder in lib/schedule.ts).
  if (dom === "*" && mon === "*" && dow !== "*") {
    const utcDows = expandDow(dow);
    if (utcDows) {
      const { label: timeLabel, dayShift } = utcToLocalClock(utcH, utcM);
      const localDows = new Set(
        [...utcDows].map((d) => (((d + dayShift) % 7) + 7) % 7),
      );
      let dayLabel: string;
      if (localDows.size === 7) dayLabel = "Daily";
      else if (localDows.size === 5 && [1, 2, 3, 4, 5].every((d) => localDows.has(d)))
        dayLabel = "Weekdays";
      else if (localDows.size === 2 && localDows.has(0) && localDows.has(6))
        dayLabel = "Weekends";
      else
        dayLabel = [...localDows]
          .sort((a, b) => a - b)
          .map((d) => DOW_SHORT[d])
          .join(", ");
      return dayLabel === "Daily"
        ? `Daily at ${timeLabel}`
        : `${dayLabel} at ${timeLabel}`;
    }
  }

  return cron;
}

/** Theme-reactive hook for inactive trigger colors. */
export function useTriggerColors(): TriggerColorSet {
  const [colors, setColors] = useState<TriggerColorSet>(buildTriggerColors);

  useEffect(() => {
    const rebuild = () => setColors(buildTriggerColors());
    const obs = new MutationObserver(rebuild);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style"] });
    return () => obs.disconnect();
  }, []);

  return colors;
}
