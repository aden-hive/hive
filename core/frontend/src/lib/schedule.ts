// Schedule math for the "Create scheduler" popup.
//
// The backend stores timer triggers as UTC cron expressions (or a plain
// interval_minutes). The user, however, thinks in their *local* wall clock.
// This module is the single source of truth for converting between the two,
// so the popup can let the user pick "9:00 AM on weekdays" and we hand the
// runtime the right UTC cron — and so a live preview can show the exact local
// instant the schedule will next fire.
//
// Everything here is pure and deterministic given `Date` + the host timezone,
// which is what makes it unit-testable (see schedule.test.ts).

export type ScheduleMode = "daily" | "interval" | "weekly" | "advanced";

export type IntervalUnit = "minutes" | "hours";

export interface ScheduleForm {
  mode: ScheduleMode;
  /** Local hour 0–23 (daily/weekly). */
  hour: number;
  /** Local minute 0–59 (daily/weekly). */
  minute: number;
  /** Interval magnitude (interval mode). */
  intervalValue: number;
  intervalUnit: IntervalUnit;
  /** Selected local weekdays, 0=Sun … 6=Sat (weekly mode). */
  weekdays: number[];
  /** Raw cron text (advanced mode). */
  cron: string;
}

export type TimerConfig = { cron: string } | { interval_minutes: number };

function mod(n: number, m: number): number {
  return ((n % m) + m) % m;
}

/**
 * Convert a local hour/minute to its UTC equivalent, plus the day rollover
 * that conversion induces. `dayDelta` is -1, 0, or +1: the difference between
 * the UTC calendar day and the local calendar day for that instant. Weekly
 * schedules need it because e.g. Monday 23:00 in UTC+2 is *Monday* 21:00 UTC
 * (delta 0), but Monday 01:00 in UTC+2 is *Sunday* 23:00 UTC (delta -1) — the
 * weekday set must shift accordingly.
 */
export function localTimeToUtcParts(
  hour: number,
  minute: number,
): { utcHour: number; utcMinute: number; dayDelta: number } {
  const d = new Date();
  d.setHours(hour, minute, 0, 0);
  // Compare date-only values (month/year-boundary safe) to get the rollover.
  const localDay = Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const utcDay = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  const dayDelta = Math.round((utcDay - localDay) / 86_400_000);
  return { utcHour: d.getUTCHours(), utcMinute: d.getUTCMinutes(), dayDelta };
}

/**
 * Build the `trigger_config` the backend expects from the popup's form state.
 * Returns null when the inputs don't describe a valid schedule (no weekdays
 * picked, non-positive interval, malformed advanced cron) so the caller can
 * keep the Create button disabled.
 */
export function buildTimerConfig(form: ScheduleForm): TimerConfig | null {
  switch (form.mode) {
    case "daily": {
      const { utcHour, utcMinute } = localTimeToUtcParts(form.hour, form.minute);
      return { cron: `${utcMinute} ${utcHour} * * *` };
    }
    case "weekly": {
      if (form.weekdays.length === 0) return null;
      const { utcHour, utcMinute, dayDelta } = localTimeToUtcParts(
        form.hour,
        form.minute,
      );
      const utcDows = Array.from(
        new Set(form.weekdays.map((d) => mod(d + dayDelta, 7))),
      ).sort((a, b) => a - b);
      return { cron: `${utcMinute} ${utcHour} * * ${utcDows.join(",")}` };
    }
    case "interval": {
      const minutes =
        form.intervalUnit === "hours"
          ? form.intervalValue * 60
          : form.intervalValue;
      if (!Number.isFinite(minutes) || minutes <= 0) return null;
      return { interval_minutes: minutes };
    }
    case "advanced": {
      const cron = form.cron.trim();
      return isValidCron(cron) ? { cron } : null;
    }
  }
}

// ── Cron parsing / evaluation ──────────────────────────────────────────────
//
// A small standard 5-field cron evaluator. Supports `*`, `*/n`, single values,
// lists `a,b`, ranges `a-b`, and range steps `a-b/n` in each field — enough to
// cover everything the popup generates plus typical hand-written crons.

const CRON_TERM = String.raw`(\*|\d+(-\d+)?)(\/\d+)?`;
const CRON_FIELD = new RegExp(`^${CRON_TERM}(,${CRON_TERM})*$`);

export function isValidCron(cron: string): boolean {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return false;
  const bounds: [number, number][] = [
    [0, 59],
    [0, 23],
    [1, 31],
    [1, 12],
    [0, 7],
  ];
  return parts.every((p, i) => {
    if (!CRON_FIELD.test(p)) return false;
    try {
      parseField(p, bounds[i][0], bounds[i][1]);
      return true;
    } catch {
      return false;
    }
  });
}

/** Expand one cron field into the set of matching integers within [min,max]. */
function parseField(expr: string, min: number, max: number): Set<number> {
  const out = new Set<number>();
  for (const piece of expr.split(",")) {
    const [rangePart, stepPart] = piece.split("/");
    const step = stepPart ? parseInt(stepPart, 10) : 1;
    if (!Number.isFinite(step) || step <= 0) throw new Error("bad step");
    let lo = min;
    let hi = max;
    if (rangePart !== "*") {
      const m = rangePart.split("-");
      lo = parseInt(m[0], 10);
      hi = m.length > 1 ? parseInt(m[1], 10) : lo;
      if (!Number.isFinite(lo) || !Number.isFinite(hi)) throw new Error("nan");
      if (lo < min || hi > max || lo > hi) throw new Error("out of range");
    }
    for (let v = lo; v <= hi; v += step) out.add(v);
  }
  return out;
}

interface ParsedCron {
  minutes: Set<number>;
  hours: Set<number>;
  doms: Set<number>;
  months: Set<number>;
  dows: Set<number>;
  domRestricted: boolean;
  dowRestricted: boolean;
}

function parseCron(cron: string): ParsedCron {
  const [mn, hr, dom, mon, dow] = cron.trim().split(/\s+/);
  const dows = parseField(dow, 0, 7);
  // Normalize Sunday: cron allows both 0 and 7.
  if (dows.has(7)) {
    dows.delete(7);
    dows.add(0);
  }
  return {
    minutes: parseField(mn, 0, 59),
    hours: parseField(hr, 0, 23),
    doms: parseField(dom, 1, 31),
    months: parseField(mon, 1, 12),
    dows,
    domRestricted: dom.trim() !== "*",
    dowRestricted: dow.trim() !== "*",
  };
}

/**
 * Next time (epoch ms, UTC) at or after `fromMs` that the cron fires. Returns
 * null if nothing matches within a year (e.g. an impossible Feb-31 cron).
 *
 * Brute-force minute scan: simple, correct, and instant in practice — a full
 * year is ~525k iterations. Cron is interpreted in UTC, matching the runtime.
 * Standard dom/dow semantics: when *both* are restricted a day matches if it
 * satisfies *either* (the historical cron OR rule); our generated crons only
 * restrict one at a time, but we honor the rule for hand-written ones.
 */
export function cronNextUtc(cron: string, fromMs: number): number | null {
  let parsed: ParsedCron;
  try {
    parsed = parseCron(cron);
  } catch {
    return null;
  }
  // Start at the next whole minute (a schedule fires at minute boundaries).
  const start = new Date(fromMs);
  start.setUTCSeconds(0, 0);
  start.setUTCMinutes(start.getUTCMinutes() + 1);

  const limit = 366 * 24 * 60;
  const cursor = start;
  for (let i = 0; i < limit; i++) {
    if (
      parsed.minutes.has(cursor.getUTCMinutes()) &&
      parsed.hours.has(cursor.getUTCHours()) &&
      parsed.months.has(cursor.getUTCMonth() + 1) &&
      dayMatches(parsed, cursor.getUTCDate(), cursor.getUTCDay())
    ) {
      return cursor.getTime();
    }
    cursor.setUTCMinutes(cursor.getUTCMinutes() + 1);
  }
  return null;
}

function dayMatches(p: ParsedCron, dom: number, dow: number): boolean {
  if (p.domRestricted && p.dowRestricted) {
    return p.doms.has(dom) || p.dows.has(dow);
  }
  if (p.domRestricted) return p.doms.has(dom);
  if (p.dowRestricted) return p.dows.has(dow);
  return true;
}
