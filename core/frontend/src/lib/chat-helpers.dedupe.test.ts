/**
 * Event-dedupe must survive the runtime restarting its `seq` counter.
 *
 * Every runtime run opens with a `queen_identity_selected` and restarts
 * `seq` at 1. A long-lived SSE connection (the chat page left open while
 * the queen runs several jobs) therefore sees the SAME low seq values
 * again and again across runs. A dedupe keyed on bare `seq` would treat a
 * fresh job's seq-1/2/3 events as already-seen and drop the whole job —
 * the reported bug where "latest messages get swallowed" and only a
 * force-reload brings them back. The key must pair `seq` with the event
 * timestamp so it stays unique across runs while still matching a
 * genuinely redelivered event (the SSE ring-buffer replay re-sends the
 * identical timestamp+seq).
 */
import { describe, it, expect } from "vitest";
import { eventDedupeKey, newReplayState, shouldSkipForDedupe } from "./chat-helpers";
import type { AgentEvent } from "@/api/types";

function evt(seq: number, timestamp: string, type = "client_output_delta"): AgentEvent {
  return {
    type: type as AgentEvent["type"],
    stream_id: "queen",
    node_id: "queen",
    execution_id: "session_x",
    data: {},
    timestamp,
    correlation_id: null,
    colony_id: null,
    seq,
  };
}

describe("eventDedupeKey", () => {
  it("pairs seq with timestamp so equal seqs from different runs differ", () => {
    const runA = eventDedupeKey(evt(2, "2026-05-18T11:14:00.000000"));
    const runB = eventDedupeKey(evt(2, "2026-05-18T11:20:00.000000"));
    expect(runA).not.toBeNull();
    expect(runA).not.toEqual(runB);
  });

  it("returns the same key for a genuinely redelivered event", () => {
    expect(eventDedupeKey(evt(7, "2026-05-18T11:14:00.000000"))).toEqual(
      eventDedupeKey(evt(7, "2026-05-18T11:14:00.000000")),
    );
  });

  it("returns null for events with no usable seq", () => {
    expect(eventDedupeKey(evt(0, "2026-05-18T11:14:00.000000"))).toBeNull();
    expect(
      eventDedupeKey({ ...evt(1, "2026-05-18T11:14:00.000000"), seq: undefined }),
    ).toBeNull();
  });
});

describe("shouldSkipForDedupe — across a runtime seq reset", () => {
  it("does NOT drop a new run's events that reuse an earlier run's seqs", () => {
    const state = newReplayState();

    // Run A — seq 1,2,3. First time seen: nothing skipped.
    const runA = [
      evt(1, "2026-05-18T11:14:01.000000", "queen_identity_selected"),
      evt(2, "2026-05-18T11:14:02.000000"),
      evt(3, "2026-05-18T11:14:03.000000"),
    ];
    expect(runA.map((e) => shouldSkipForDedupe(state, e))).toEqual([
      false,
      false,
      false,
    ]);

    // Run B — the runtime restarted, so seq is back to 1,2,3. These are
    // brand-new events (later timestamps) and must NOT be skipped.
    const runB = [
      evt(1, "2026-05-18T11:20:01.000000", "queen_identity_selected"),
      evt(2, "2026-05-18T11:20:02.000000"),
      evt(3, "2026-05-18T11:20:03.000000"),
    ];
    expect(runB.map((e) => shouldSkipForDedupe(state, e))).toEqual([
      false,
      false,
      false,
    ]);
  });

  it("still skips a genuinely redelivered event (ring-buffer replay)", () => {
    const state = newReplayState();
    const e = evt(5, "2026-05-18T11:14:05.000000");
    expect(shouldSkipForDedupe(state, e)).toBe(false);
    // Same event redelivered on an SSE resubscribe — identical ts+seq.
    expect(shouldSkipForDedupe(state, evt(5, "2026-05-18T11:14:05.000000"))).toBe(
      true,
    );
  });

  it("lets seq-less events through to id-based upsert dedupe", () => {
    const state = newReplayState();
    const e = { ...evt(1, "2026-05-18T11:14:00.000000"), seq: undefined };
    expect(shouldSkipForDedupe(state, e)).toBe(false);
    expect(shouldSkipForDedupe(state, e)).toBe(false);
  });
});
