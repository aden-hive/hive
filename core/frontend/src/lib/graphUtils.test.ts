import { afterEach, describe, expect, it } from "vitest";
import { cronToLabel } from "./graphUtils";
import { buildTimerConfig, type ScheduleForm } from "./schedule";

// cronToLabel renders UTC crons back into the viewer's local wall clock, so —
// like schedule.test.ts — we pin non-DST zones to keep assertions stable.
const originalTz = process.env.TZ;
afterEach(() => {
  process.env.TZ = originalTz;
});
function setTz(tz: string) {
  process.env.TZ = tz;
}

describe("cronToLabel — intervals", () => {
  it("renders minute and hour intervals", () => {
    expect(cronToLabel("*/5 * * * *")).toBe("Every 5m");
    expect(cronToLabel("0 */2 * * *")).toBe("Every 2h");
  });
});

describe("cronToLabel — daily", () => {
  it("converts UTC to local for a +9 zone", () => {
    setTz("Asia/Tokyo");
    expect(cronToLabel("0 0 * * *")).toBe("Daily at 9AM");
  });
  it("handles half-hour offsets", () => {
    setTz("Asia/Kolkata"); // +5:30
    expect(cronToLabel("30 3 * * *")).toBe("Daily at 9AM");
  });
});

describe("cronToLabel — weekly", () => {
  it("renders weekdays", () => {
    setTz("UTC");
    expect(cronToLabel("0 9 * * 1-5")).toBe("Weekdays at 9AM");
    expect(cronToLabel("0 9 * * 1,2,3,4,5")).toBe("Weekdays at 9AM");
  });
  it("renders weekends", () => {
    setTz("UTC");
    expect(cronToLabel("0 20 * * 0,6")).toBe("Weekends at 8PM");
  });
  it("renders a specific-day list", () => {
    setTz("UTC");
    expect(cronToLabel("30 7 * * 1,3,5")).toBe("Mon, Wed, Fri at 7:30AM");
  });
  it("shifts the weekday back when local time crosses UTC midnight", () => {
    setTz("Asia/Tokyo"); // +9
    // 16:00 UTC Sunday → 01:00 Monday local.
    expect(cronToLabel("0 16 * * 0")).toBe("Mon at 1AM");
  });
});

describe("builder ↔ label round-trip", () => {
  function form(overrides: Partial<ScheduleForm>): ScheduleForm {
    return {
      mode: "weekly",
      hour: 9,
      minute: 0,
      intervalValue: 5,
      intervalUnit: "minutes",
      weekdays: [],
      cron: "",
      ...overrides,
    };
  }

  it.each(["UTC", "Asia/Tokyo", "Pacific/Honolulu", "Asia/Kolkata"])(
    "weekdays 9am round-trips in %s",
    (tz) => {
      setTz(tz);
      const cfg = buildTimerConfig(form({ weekdays: [1, 2, 3, 4, 5], hour: 9, minute: 0 }));
      expect(cfg).not.toBeNull();
      const cron = (cfg as { cron: string }).cron;
      expect(cronToLabel(cron)).toBe("Weekdays at 9AM");
    },
  );

  it.each(["UTC", "Asia/Tokyo", "Pacific/Honolulu"])(
    "single Monday 11pm round-trips in %s",
    (tz) => {
      setTz(tz);
      const cfg = buildTimerConfig(form({ weekdays: [1], hour: 23, minute: 0 }));
      const cron = (cfg as { cron: string }).cron;
      expect(cronToLabel(cron)).toBe("Mon at 11PM");
    },
  );
});
