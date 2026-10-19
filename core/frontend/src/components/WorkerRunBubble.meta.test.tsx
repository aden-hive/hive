/**
 * The load-bearing frontend claim of the worker-event split:
 *
 *   a worker's bubble must render from META events + the workers poll alone,
 *   with ZERO per-turn chatter — because the server no longer streams a
 *   worker's text deltas or tool calls unless the user is watching that worker.
 *
 * Before the split, a bubble only existed once the worker's first llm_text_delta
 * arrived, and its head/tail text was scraped from those deltas. If that were
 * still true, every unwatched worker would render either nothing at all or an
 * empty bubble. These tests pin the new behaviour.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WorkerSummary } from "@/api/colonyWorkers";
import { newReplayState, replayEventsToMessages } from "@/lib/chat-helpers";
import type { AgentEvent } from "@/api/types";

const WORKER_ID = "w-abc";
const STREAM = `worker:${WORKER_ID}`;

const worker: WorkerSummary = {
  worker_id: WORKER_ID,
  task: "Scrape the pricing page",
  status: "running",
  started_at: Date.now() / 1000,
  result: null,
  task_summary: { total: 4, completed: 1, in_progress: 1, pending: 2 },
  batch: null,
};

const workersState = { workers: [worker] as WorkerSummary[] };

vi.mock("@/context/ColonyWorkersContext", () => ({
  useColonyWorkers: () => ({
    workers: workersState.workers,
    openColonyWorkers: vi.fn(),
  }),
}));

// Imported after the mock so the component picks it up.
const { default: WorkerRunBubble } = await import("@/components/WorkerRunBubble");

function metaOnlyEvents(): AgentEvent[] {
  // Exactly what the server sends for an UNWATCHED worker: meta, no chatter.
  //
  // The start signal is `node_loop_started`, NOT `execution_started`. A real
  // 80-worker colony log contained 62 node_loop_started and ZERO
  // execution_started on worker streams — anchoring on execution_started is
  // precisely the bug that made worker bubbles invisible until a page refresh.
  return [
    {
      type: "node_loop_started",
      stream_id: STREAM,
      node_id: "worker",
      execution_id: "ex-1",
      data: {},
      timestamp: new Date().toISOString(),
      seq: 1,
    } as AgentEvent,
  ];
}

describe("worker bubble renders from META + poll, without chatter", () => {
  it("execution_started alone produces a worker-role message carrying the streamId", () => {
    const msgs = replayEventsToMessages(
      metaOnlyEvents(),
      "queen-dm",
      "Queen",
      undefined,
      newReplayState(),
    );

    const anchors = msgs.filter((m) => m.streamId === STREAM);
    expect(anchors.length).toBeGreaterThan(0);
    // role must be "worker" — that is the ONLY thing that makes ChatPanel open
    // a worker_run span. If this regresses, the bubble silently disappears.
    expect(anchors[0].role).toBe("worker");
  });

  it("bubble shows the task and task-progress from the poll, not from prose", () => {
    const msgs = replayEventsToMessages(
      metaOnlyEvents(),
      "queen-dm",
      "Queen",
      undefined,
      newReplayState(),
    );
    const group = { messages: msgs.filter((m) => m.streamId === STREAM) };

    render(<WorkerRunBubble runId="r1" group={group} label="Worker A-01" />);

    // Head text comes from the polled record's task…
    expect(screen.getByText(/Scrape the pricing page/)).toBeTruthy();
    // …progress from its task list, not from a tool count we never received…
    expect(screen.getByText("1/4 tasks")).toBeTruthy();
    // …and the status pill from the poll.
    expect(screen.getByText("running")).toBeTruthy();
    // The old placeholder must NOT be showing — that was the symptom of a
    // bubble with no chatter to render.
    expect(screen.queryByText(/waiting for first action/)).toBeNull();
  });

  it("prefers the queen-authored goal over the raw task prompt as the head", () => {
    // WHY: the raw task string is prompt-engineering (username lists,
    // bindings, protocol text) — unreadable for non-technical users. When
    // the poll carries `goal` (seeded at spawn), it must title the bubble;
    // the raw task stays available in the worker detail panel.
    workersState.workers = [
      {
        ...worker,
        status: "running",
        goal: "Checking 6 Instagram profiles for good fits",
      } as WorkerSummary,
    ];

    const msgs = replayEventsToMessages(
      metaOnlyEvents(),
      "queen-dm",
      "Queen",
      undefined,
      newReplayState(),
    );
    const group = { messages: msgs.filter((m) => m.streamId === STREAM) };

    render(<WorkerRunBubble runId="r-goal" group={group} label="Worker A-01" />);

    expect(screen.getByText(/Checking 6 Instagram profiles/)).toBeTruthy();
    expect(screen.queryByText(/Scrape the pricing page/)).toBeNull();
  });

  it("a finished worker shows its report summary as the tail", () => {
    workersState.workers = [
      {
        ...worker,
        status: "completed",
        result: {
          status: "ok",
          summary: "Found 3 pricing tiers",
          error: null,
          tokens_used: 100,
          duration_seconds: 4,
        },
        task_summary: { total: 4, completed: 4, in_progress: 0, pending: 0 },
      } as WorkerSummary,
    ];

    const msgs = replayEventsToMessages(
      metaOnlyEvents(),
      "queen-dm",
      "Queen",
      undefined,
      newReplayState(),
    );
    const group = { messages: msgs.filter((m) => m.streamId === STREAM) };

    render(<WorkerRunBubble runId="r2" group={group} label="Worker A-01" />);

    expect(screen.getByText(/Found 3 pricing tiers/)).toBeTruthy();
    expect(screen.getByText("4/4 tasks")).toBeTruthy();

    workersState.workers = [worker]; // restore
  });
});

describe("anchor fires regardless of which event arrives first", () => {
  // Regression guard for the "no worker bubbles until I refresh" bug: the
  // anchor used to be tied to `execution_started`, which a spawned worker
  // never emits. Each of these is a real first-event observed in production.
  it.each([
    ["node_loop_started", "a worker whose loop just started"],
    ["subagent_report", "a worker stopped while still queued"],
    ["execution_completed", "a worker that finished"],
    ["tool_call_started", "a watched worker whose first event is a tool call"],
  ])("anchors on %s (%s)", (type) => {
    const msgs = replayEventsToMessages(
      [
        {
          type,
          stream_id: STREAM,
          node_id: "worker",
          execution_id: "ex-1",
          data: {},
          timestamp: new Date().toISOString(),
          seq: 1,
        } as AgentEvent,
      ],
      "queen-dm",
      "Queen",
      undefined,
      newReplayState(),
    );
    const anchor = msgs.find((m) => m.id === `worker-anchor-${STREAM}`);
    expect(anchor, `no bubble anchor emitted for first event "${type}"`).toBeTruthy();
    expect(anchor!.role).toBe("worker");
  });

  it("anchors exactly once per worker, keeping createdAt stable", () => {
    const at = new Date("2026-07-13T12:00:00Z").toISOString();
    const later = new Date("2026-07-13T12:05:00Z").toISOString();
    const msgs = replayEventsToMessages(
      [
        { type: "node_loop_started", stream_id: STREAM, node_id: "worker",
          execution_id: "ex-1", data: {}, timestamp: at, seq: 1 } as AgentEvent,
        { type: "subagent_report", stream_id: STREAM, node_id: "worker",
          execution_id: "ex-1", data: {}, timestamp: later, seq: 2 } as AgentEvent,
      ],
      "queen-dm",
      "Queen",
      undefined,
      newReplayState(),
    );
    const anchors = msgs.filter((m) => m.id === `worker-anchor-${STREAM}`);
    expect(anchors).toHaveLength(1);
    // Pinned to the FIRST event — otherwise the bubble would jump down the
    // transcript every time another of its events landed.
    expect(anchors[0].createdAt).toBe(new Date(at).getTime());
  });
});
