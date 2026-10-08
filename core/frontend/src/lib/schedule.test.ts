import { afterEach, describe, expect, it } from "vitest";
import {
  buildTimerConfig,
  cronNextUtc,
  isValidCron,
  localTimeToUtcParts,
  type ScheduleForm,
} from "./schedule";

// Node honors runtime changes to process.env.TZ for subsequently-created
// Date objects. We exercise the local↔UTC math under several *non-DST* zones
// (fixed offsets) so the assertions don't drift with the date the test runs.
const originalTz = process.env.TZ;
afterEach(() => {
  process.env.TZ = originalTz;
});
function setTz(tz: string) {
  process.env.TZ = tz;
}

function form(overrides: Partial<ScheduleForm>): ScheduleForm {
  return {
    mode: "daily",
    hour: 9,
    minute: 0,
    intervalValue: 5,
    intervalUnit: "minutes",
    weekdays: [],
    cron: "",
    ...overrides,
  };
}

describe("localTimeToUtcParts", () => {
  it("shifts forward across midnight for positive offsets", () => {
    setTz("Asia/Tokyo"); // UTC+9, no DST
    // 01:00 local Tokyo is 16:00 UTC the *previous* day.
    expect(localTimeToUtcParts(1, 0)).toEqual({
      utcHour: 16,
      utcMinute: 0,
      dayDelta: -1,
    });
  });

  it("shifts backward across midnight for negative offsets", () => {
    setTz("Pacific/Honolulu"); // UTC-10, no DST
    // 23:00 local Honolulu is 09:00 UTC the *next* day.
    expect(localTimeToUtcParts(23, 0)).toEqual({
      utcHour: 9,
      utcMinute: 0,
      dayDelta: 1,
    });
  });

  it("handles half-hour offsets", () => {
    setTz("Asia/Kolkata"); // UTC+5:30, no DST
    expect(localTimeToUtcParts(9, 0)).toEqual({
      utcHour: 3,
      utcMinute: 30,
      dayDelta: 0,
    });
  });
});

describe("buildTimerConfig — daily", () => {
  it("UTC passes the local time straight through", () => {
    setTz("UTC");
    expect(buildTimerConfig(form({ mode: "daily", hour: 9, minute: 0 }))).toEqual({
      cron: "0 9 * * *",
    });
  });

  it("converts local morning to UTC for a +9 zone", () => {
    setTz("Asia/Tokyo");
    expect(buildTimerConfig(form({ mode: "daily", hour: 9, minute: 0 }))).toEqual({
      cron: "0 0 * * *",
    });
  });

  it("converts local morning to UTC for a -7 zone", () => {
    setTz("America/Phoenix"); // UTC-7, no DST
    expect(buildTimerConfig(form({ mode: "daily", hour: 9, minute: 0 }))).toEqual({
      cron: "0 16 * * *",
    });
  });
});

describe("buildTimerConfig — weekly", () => {
  it("returns null when no weekdays are selected", () => {
    setTz("UTC");
    expect(buildTimerConfig(form({ mode: "weekly", weekdays: [] }))).toBeNull();
  });

  it("keeps weekdays unshifted when the time doesn't cross UTC midnight", () => {
    setTz("UTC");
    // Mon–Fri at 09:00.
    expect(
      buildTimerConfig(
        form({ mode: "weekly", hour: 9, minute: 0, weekdays: [1, 2, 3, 4, 5] }),
      ),
    ).toEqual({ cron: "0 9 * * 1,2,3,4,5" });
  });

  it("shifts weekdays back a day when local time rolls to the previous UTC day", () => {
    setTz("Asia/Tokyo"); // +9
    // Monday 01:00 local → Sunday 16:00 UTC.
    expect(
      buildTimerConfig(form({ mode: "weekly", hour: 1, minute: 0, weekdays: [1] })),
    ).toEqual({ cron: "0 16 * * 0" });
  });

  it("shifts weekdays forward a day when local time rolls to the next UTC day", () => {
    setTz("Pacific/Honolulu"); // -10
    // Monday 23:00 local → Tuesday 09:00 UTC.
    expect(
      buildTimerConfig(form({ mode: "weekly", hour: 23, minute: 0, weekdays: [1] })),
    ).toEqual({ cron: "0 9 * * 2" });
  });

  it("wraps Saturday→Sunday correctly on a forward shift", () => {
    setTz("Pacific/Honolulu"); // -10
    // Saturday 23:00 local → Sunday 09:00 UTC (dow 6 → 0).
    expect(
      buildTimerConfig(form({ mode: "weekly", hour: 23, minute: 0, weekdays: [6] })),
    ).toEqual({ cron: "0 9 * * 0" });
  });
});

describe("buildTimerConfig — interval & advanced", () => {
  it("converts hours to minutes", () => {
    expect(
      buildTimerConfig(form({ mode: "interval", intervalValue: 2, intervalUnit: "hours" })),
    ).toEqual({ interval_minutes: 120 });
  });

  it("rejects a non-positive interval", () => {
    expect(
      buildTimerConfig(form({ mode: "interval", intervalValue: 0, intervalUnit: "minutes" })),
    ).toBeNull();
  });

  it("passes a valid advanced cron through and rejects a bad one", () => {
    expect(buildTimerConfig(form({ mode: "advanced", cron: "0 9 * * 1-5" }))).toEqual({
      cron: "0 9 * * 1-5",
    });
    expect(buildTimerConfig(form({ mode: "advanced", cron: "not a cron" }))).toBeNull();
  });
});

describe("isValidCron", () => {
  it.each(["0 9 * * *", "*/5 * * * *", "0 9 * * 1-5", "30 3 * * 0,6", "0 0 1 1 *"])(
    "accepts %s",
    (c) => expect(isValidCron(c)).toBe(true),
  );

  it.each(["0 9 * *", "60 9 * * *", "0 24 * * *", "0 9 32 * *", "abc", ""])(
    "rejects %s",
    (c) => expect(isValidCron(c)).toBe(false),
  );
});

describe("cronNextUtc", () => {
  const at = (
    y: number,
    mo: number,
    d: number,
    h: number,
    mi: number,
  ): number => Date.UTC(y, mo, d, h, mi, 0, 0);

  it("finds the next daily fire later the same day", () => {
    expect(cronNextUtc("0 9 * * *", at(2026, 0, 1, 8, 0))).toBe(at(2026, 0, 1, 9, 0));
  });

  it("rolls to the next day once today's fire has passed", () => {
    expect(cronNextUtc("0 9 * * *", at(2026, 0, 1, 9, 30))).toBe(at(2026, 0, 2, 9, 0));
  });

  it("honors */15 stepping", () => {
    expect(cronNextUtc("*/15 * * * *", at(2026, 0, 1, 10, 2))).toBe(at(2026, 0, 1, 10, 15));
  });

  it("finds the next matching weekday", () => {
    // 2026-01-01 is a Thursday (dow 4). Next Monday (dow 1) is 2026-01-05.
    expect(cronNextUtc("0 9 * * 1", at(2026, 0, 1, 12, 0))).toBe(at(2026, 0, 5, 9, 0));
  });
});
