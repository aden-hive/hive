import { describe, expect, it } from "vitest";

import {
  resolveInitialColonyPhase,
  shouldUsePrefetchedColonyRestore,
} from "./colony-session-restore";

describe("shouldUsePrefetchedColonyRestore", () => {
  it("reuses the cold prefetch when the backend restored that same session", () => {
    expect(
      shouldUsePrefetchedColonyRestore("session_forked", "session_forked"),
    ).toBe(true);
  });

  it("drops the cold prefetch when the backend restored a different session", () => {
    expect(
      shouldUsePrefetchedColonyRestore("session_source", "session_forked"),
    ).toBe(false);
  });
});

describe("resolveInitialColonyPhase", () => {
  it("keeps the prefetched phase when the prefetched session is still current", () => {
    expect(
      resolveInitialColonyPhase({
        prefetchedSessionId: "session_forked",
        resolvedSessionId: "session_forked",
        prefetchedPhase: "independent",
        serverPhase: "reviewing",
        hasWorker: true,
      }),
    ).toBe("independent");
  });

  it("ignores stale prefetched phase when the backend corrected the session", () => {
    expect(
      resolveInitialColonyPhase({
        prefetchedSessionId: "session_source",
        resolvedSessionId: "session_forked",
        prefetchedPhase: "independent",
        serverPhase: "reviewing",
        hasWorker: true,
      }),
    ).toBe("reviewing");
  });

  it("falls back to worker state when neither restore nor server phase is present", () => {
    expect(
      resolveInitialColonyPhase({
        prefetchedSessionId: undefined,
        resolvedSessionId: "session_forked",
        prefetchedPhase: null,
        serverPhase: undefined,
        hasWorker: true,
      }),
    ).toBe("working");
  });
});
