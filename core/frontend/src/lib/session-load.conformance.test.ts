/**
 * Session-load conformance — proves the replay machinery loads sessions
 * with no mismatch: nothing duplicated, dropped, or reordered.
 *
 * The bulk of the suite runs against the user's REAL session event logs
 * (`~/.hive/event_logs`), so it exercises the exact data the app restores.
 * When that directory is absent the real-data tests skip themselves and
 * the synthetic tests still run.
 */
import { describe, expect, it } from "vitest";
import type { AgentEvent } from "@/api/types";
import {
  eventDedupeKey,
  newReplayState,
  replayEvent,
  replayEventsToMessages,
  shouldSkipForDedupe,
} from "@/lib/chat-helpers";
import {
  hasFullSeqCoverage,
  loadRealLogs,
  realLogsAvailable,
  realLogsDir,
  type RealLog,
} from "@/test/realLogs";

const THREAD = "agent";
const AGENT = "Test Agent";
const QUEEN = "Alexandra";

const realLogs = loadRealLogs();
const seqLogs = realLogs.filter(hasFullSeqCoverage);

if (!realLogsAvailable()) {
  // eslint-disable-next-line no-console
  console.warn(
    `[conformance] ${realLogsDir()} not found — real-data tests skipped.`,
  );
} else {
  // eslint-disable-next-line no-console
  console.info(
    `[conformance] ${realLogs.length} real logs loaded (${seqLogs.length} with full seq coverage).`,
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────

/** Replay a colony-chat-style live SSE handoff: the disk restore already
 *  applied `restoredPrefix`; the live ring buffer then re-delivers
 *  `liveStream`. Mirrors handleSSEEvent — `shouldSkipForDedupe` gates
 *  message emission, the rest is upserted by id (newest wins, oldest
 *  createdAt kept), exactly like replayEventsToMessages' own loop. */
function simulateLiveHandoff(
  restored: ReturnType<typeof replayEventsToMessages>,
  state: ReturnType<typeof newReplayState>,
  liveStream: AgentEvent[],
) {
  const byId = new Map(restored.map((m) => [m.id, m]));
  for (const evt of liveStream) {
    if (evt.type === "colony_fork_marker") continue;
    const alreadyApplied = shouldSkipForDedupe(state, evt);
    const emitted = alreadyApplied
      ? []
      : replayEvent(state, evt, THREAD, AGENT, QUEEN);
    for (const m of emitted) {
      const prev = byId.get(m.id);
      byId.set(m.id, prev ? { ...m, createdAt: prev.createdAt ?? m.createdAt } : m);
    }
  }
  return [...byId.values()].sort(
    (a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0),
  );
}

function ev(partial: Partial<AgentEvent> & Pick<AgentEvent, "type">): AgentEvent {
  return {
    stream_id: "queen",
    node_id: "queen",
    execution_id: "exec-1",
    data: {},
    timestamp: "2026-05-15T10:00:00.000",
    correlation_id: null,
    colony_id: null,
    ...partial,
  } as AgentEvent;
}

// ── 1. Idempotency ───────────────────────────────────────────────────────

describe("replay is idempotent on real session logs", () => {
  it.runIf(realLogs.length > 0)(
    "replaying the same log twice yields byte-identical messages",
    () => {
      for (const log of realLogs) {
        const a = replayEventsToMessages(log.events, THREAD, AGENT, QUEEN);
        const b = replayEventsToMessages(log.events, THREAD, AGENT, QUEEN);
        expect(JSON.stringify(b), `mismatch for ${log.name}`).toBe(
          JSON.stringify(a),
        );
      }
    },
  );
});

// ── 2. Structural invariants ─────────────────────────────────────────────

describe("restored transcripts hold their invariants on real data", () => {
  it.runIf(realLogs.length > 0)(
    "message ids are unique, timestamps are real and chronologically sorted",
    () => {
      for (const log of realLogs) {
        const msgs = replayEventsToMessages(log.events, THREAD, AGENT, QUEEN);
        const ids = msgs.map((m) => m.id);
        expect(new Set(ids).size, `duplicate id in ${log.name}`).toBe(
          ids.length,
        );
        let prev = -Infinity;
        for (const m of msgs) {
          expect(
            typeof m.createdAt === "number" && Number.isFinite(m.createdAt),
            `non-finite createdAt in ${log.name} (${m.id})`,
          ).toBe(true);
          expect(
            (m.createdAt ?? 0) > 0,
            `zero/negative createdAt in ${log.name} (${m.id})`,
          ).toBe(true);
          expect(
            (m.createdAt ?? 0) >= prev,
            `out-of-order message in ${log.name} (${m.id})`,
          ).toBe(true);
          prev = m.createdAt ?? 0;
        }
      }
    },
  );
});

// ── 3. Restore ↔ live-SSE handoff dedupe is exact (Part B1) ───────────────

describe("seq dedupe makes the restore↔SSE handoff exact", () => {
  it.runIf(seqLogs.length > 0)(
    "every event already applied by the disk restore is skipped on SSE re-delivery",
    () => {
      for (const log of seqLogs) {
        const state = newReplayState();
        replayEventsToMessages(log.events, THREAD, AGENT, QUEEN, state);
        // The live SSE ring buffer re-delivers the whole tail.
        for (const evt of log.events) {
          if (evt.type === "colony_fork_marker") continue;
          expect(
            shouldSkipForDedupe(state, evt),
            `re-delivered event not deduped in ${log.name} (seq ${evt.seq})`,
          ).toBe(true);
        }
      }
    },
  );

  it.runIf(seqLogs.length > 0)(
    "a partial restore skips exactly the restored prefix and applies the rest",
    () => {
      for (const log of seqLogs) {
        const splitAt = Math.floor(log.events.length / 2);
        if (splitAt < 1 || splitAt >= log.events.length) continue;
        const state = newReplayState();
        const prefix = log.events.slice(0, splitAt);
        replayEventsToMessages(prefix, THREAD, AGENT, QUEEN, state);
        // After the prefix replay, `state.seenEventKeys` holds exactly the
        // prefix's dedupe keys. A re-delivered event is skipped iff a
        // matching key was already seen — by the prefix replay or earlier
        // in this same re-delivery pass. Membership is tracked on the
        // composite `<timestamp>|<seq>` key, never bare `seq`: the runtime
        // restarts `seq` at 1 every run, so one log can hold many events
        // sharing a seq, and only the timestamp tells them apart.
        const seen = new Set(state.seenEventKeys);
        for (const evt of log.events) {
          if (evt.type === "colony_fork_marker") continue;
          const key = eventDedupeKey(evt);
          const expectedSkip = key !== null && seen.has(key);
          const skipped = shouldSkipForDedupe(state, evt);
          expect(
            skipped,
            `dedupe disagrees with prefix membership in ${log.name} (seq ${evt.seq})`,
          ).toBe(expectedSkip);
          if (key !== null) seen.add(key);
        }
      }
    },
  );

  it.runIf(seqLogs.length > 0)(
    "restoring then re-delivering the full SSE stream changes nothing (no dup pills)",
    () => {
      for (const log of seqLogs) {
        const state = newReplayState();
        const restored = replayEventsToMessages(
          log.events,
          THREAD,
          AGENT,
          QUEEN,
          state,
        );
        const afterLive = simulateLiveHandoff(restored, state, log.events);
        expect(
          JSON.stringify(afterLive),
          `live re-delivery mutated the transcript for ${log.name}`,
        ).toBe(JSON.stringify(restored));
      }
    },
  );
});

// ── 4. Truncation orphans render instead of vanishing (Part B3) ───────────

describe("tool_call_completed without its tool_call_started still renders", () => {
  it("synthesizes a terminal pill from an orphan completion", () => {
    const started = ev({
      type: "tool_call_started",
      seq: 1,
      timestamp: "2026-05-15T10:00:00.000",
      data: { tool_name: "run_command", tool_use_id: "tu-1" },
    });
    const completed = ev({
      type: "tool_call_completed",
      seq: 2,
      timestamp: "2026-05-15T10:00:01.000",
      data: {
        tool_name: "run_command",
        tool_use_id: "tu-1",
        result: "done",
        is_error: false,
      },
    });

    const full = replayEventsToMessages([started, completed], THREAD, AGENT, QUEEN);
    const fullPills = full.filter((m) => m.type === "tool_status");
    expect(fullPills).toHaveLength(1);

    // Truncated: the started event was dropped from the log tail.
    const orphan = replayEventsToMessages([completed], THREAD, AGENT, QUEEN);
    const orphanPills = orphan.filter((m) => m.type === "tool_status");
    expect(orphanPills, "orphan completion produced no pill").toHaveLength(1);
    expect(orphanPills[0].id).toBe(fullPills[0].id);
    const tools = JSON.parse(orphanPills[0].content).tools as {
      done: boolean;
    }[];
    expect(tools[0].done).toBe(true);
  });

  it.runIf(realLogs.length > 0)(
    "dropping a tool_call_started from a real log keeps the tool visible",
    () => {
      const log = realLogs.find((l: RealLog) =>
        l.events.some(
          (e) =>
            e.type === "tool_call_started" &&
            typeof e.data?.tool_use_id === "string",
        ),
      );
      if (!log) return; // no matched tool call in the sampled logs
      const startIdx = log.events.findIndex(
        (e) =>
          e.type === "tool_call_started" &&
          typeof e.data?.tool_use_id === "string",
      );
      const full = replayEventsToMessages(log.events, THREAD, AGENT, QUEEN);
      const truncated = replayEventsToMessages(
        log.events.filter((_, i) => i !== startIdx),
        THREAD,
        AGENT,
        QUEEN,
      );
      const fullPillIds = new Set(
        full.filter((m) => m.type === "tool_status").map((m) => m.id),
      );
      const truncPillIds = new Set(
        truncated.filter((m) => m.type === "tool_status").map((m) => m.id),
      );
      // Every tool pill in the full replay still exists after truncation.
      for (const id of fullPillIds) {
        expect(truncPillIds.has(id), `tool pill ${id} vanished`).toBe(true);
      }
    },
  );
});

// ── 5. Real sessions reproduce the stuck-spinner condition (Part A) ───────

describe("real sessions exhibit the short-window condition the fix targets", () => {
  it.runIf(realLogs.length > 0)(
    "reports sessions whose last 30 messages are tool-pill dominated",
    () => {
      const INITIAL_WINDOW = 30;
      const reproducers: string[] = [];
      for (const log of realLogs) {
        const msgs = replayEventsToMessages(log.events, THREAD, AGENT, QUEEN);
        if (msgs.length <= INITIAL_WINDOW) continue;
        const window = msgs.slice(-INITIAL_WINDOW);
        const toolPills = window.filter((m) => m.type === "tool_status").length;
        if (toolPills >= INITIAL_WINDOW * 0.7) {
          reproducers.push(
            `${log.name}: ${msgs.length} msgs, last-${INITIAL_WINDOW} = ${toolPills} tool pills`,
          );
        }
      }
      // eslint-disable-next-line no-console
      console.info(
        reproducers.length > 0
          ? `[conformance] stuck-spinner reproduced by:\n  ${reproducers.join("\n  ")}`
          : "[conformance] no tool-heavy-tail sessions in the sampled logs.",
      );
      // Informational — the count is data-dependent, so we only assert the
      // analysis ran without error.
      expect(Array.isArray(reproducers)).toBe(true);
    },
  );
});
