import { useEffect, useState } from "react";

// ── Shared graph utilities ──
// Common helpers used by both AgentGraph and DraftGraph.
// AgentGraph still has its own copies for now (separate cleanup PR).

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
  // 0 H * * * -> "Daily at Ham/pm"
  if (dom === "*" && mon === "*" && dow === "*" && !min.includes("*") && !hour.includes("*")) {
    const h = parseInt(hour, 10);
    const m = parseInt(min, 10);
    const suffix = h >= 12 ? "PM" : "AM";
    const h12 = h % 12 || 12;
    return m === 0 ? `Daily at ${h12}${suffix}` : `Daily at ${h12}:${String(m).padStart(2, "0")}${suffix}`;
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
