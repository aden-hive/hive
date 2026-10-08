import { describe, it, expect } from "vitest";
import {
  extractLastPhase,
  sseEventToChatMessage,
  formatAgentDisplayName,
  replayEventsToMessages,
} from "./chat-helpers";
import type { AgentEvent } from "@/api/types";

// ---------------------------------------------------------------------------
// sseEventToChatMessage
// ---------------------------------------------------------------------------

let __seqCounter = 0;

function makeEvent(overrides: Partial<AgentEvent>): AgentEvent {
  __seqCounter += 1;
  return {
    type: "execution_started",
    stream_id: "s1",
    node_id: null,
    execution_id: null,
    data: {},
    timestamp: "2026-01-01T00:00:00Z",
    correlation_id: null,
    colony_id: null,
    seq: __seqCounter,
    ...overrides,
  };
}

describe("sseEventToChatMessage", () => {
  it("converts client_output_delta to streaming message with snapshot", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: "abc",
      data: { content: "hello", snapshot: "hello world" },
    });
    const result = sseEventToChatMessage(event, "inbox-management");
    expect(result).not.toBeNull();
    expect(result!.id).toBe("stream-abc-chat");
    expect(result!.content).toBe("hello world");
    expect(result!.role).toBe("worker");
    expect(result!.agent).toBe("chat");
  });

  it("produces same ID for same execution_id + node_id (enables upsert)", () => {
    const event1 = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: "abc",
      data: { snapshot: "first" },
    });
    const event2 = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: "abc",
      data: { snapshot: "second" },
    });
    expect(sseEventToChatMessage(event1, "t")!.id).toBe(
      sseEventToChatMessage(event2, "t")!.id,
    );
  });

  it("uses turnId for message ID when provided", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: null,
      data: { snapshot: "hello" },
    });
    const result = sseEventToChatMessage(event, "t", undefined, 3);
    expect(result!.id).toBe("stream-3-chat");
  });

  it("different turnIds produce different message IDs (separate bubbles)", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: null,
      data: { snapshot: "hello" },
    });
    const r1 = sseEventToChatMessage(event, "t", undefined, 1);
    const r2 = sseEventToChatMessage(event, "t", undefined, 2);
    expect(r1!.id).not.toBe(r2!.id);
  });

  it("same turnId produces same ID within a turn (enables streaming upsert)", () => {
    const e1 = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: null,
      data: { snapshot: "partial" },
    });
    const e2 = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: null,
      data: { snapshot: "partial response" },
    });
    expect(sseEventToChatMessage(e1, "t", undefined, 5)!.id).toBe(
      sseEventToChatMessage(e2, "t", undefined, 5)!.id,
    );
  });

  it("falls back to execution_id when turnId is not provided", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: "exec-123",
      data: { snapshot: "hello" },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result!.id).toBe("stream-exec-123-chat");
  });

  it("combines execution_id and turnId to differentiate loop iterations", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: "exec-1",
      data: { snapshot: "hello" },
    });
    const r1 = sseEventToChatMessage(event, "t", undefined, 1);
    const r2 = sseEventToChatMessage(event, "t", undefined, 2);
    expect(r1!.id).toBe("stream-exec-1-1-chat");
    expect(r2!.id).toBe("stream-exec-1-2-chat");
    expect(r1!.id).not.toBe(r2!.id);
  });

  it("same execution_id + same turnId produces same ID (streaming upsert within iteration)", () => {
    const e1 = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: "exec-1",
      data: { snapshot: "partial" },
    });
    const e2 = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: "exec-1",
      data: { snapshot: "partial response" },
    });
    expect(sseEventToChatMessage(e1, "t", undefined, 3)!.id).toBe(
      sseEventToChatMessage(e2, "t", undefined, 3)!.id,
    );
  });

  it("uses data.iteration over turnId when present", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: null,
      data: { snapshot: "hello", iteration: 5 },
    });
    const result = sseEventToChatMessage(event, "t", undefined, 2);
    expect(result!.id).toBe("stream-5-queen");
  });

  it("falls back to turnId when data.iteration is absent", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: null,
      data: { snapshot: "hello" },
    });
    const result = sseEventToChatMessage(event, "t", undefined, 2);
    expect(result!.id).toBe("stream-2-queen");
  });

  it("different iterations from same node produce different message IDs", () => {
    const e1 = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "",
      data: { snapshot: "first response", iteration: 0 },
    });
    const e2 = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "",
      data: { snapshot: "second response", iteration: 3 },
    });
    const r1 = sseEventToChatMessage(e1, "t");
    const r2 = sseEventToChatMessage(e2, "t");
    expect(r1!.id).not.toBe(r2!.id);
  });

  it("same iteration produces same ID for streaming upsert", () => {
    const e1 = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "",
      data: { snapshot: "partial", iteration: 2 },
    });
    const e2 = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "",
      data: { snapshot: "partial response", iteration: 2 },
    });
    expect(sseEventToChatMessage(e1, "t")!.id).toBe(
      sseEventToChatMessage(e2, "t")!.id,
    );
  });

  it("different inner_turn values produce different message IDs", () => {
    const e1 = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "exec-1",
      data: { snapshot: "first response", iteration: 0, inner_turn: 0 },
    });
    const e2 = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "exec-1",
      data: { snapshot: "after tool call", iteration: 0, inner_turn: 1 },
    });
    const r1 = sseEventToChatMessage(e1, "t");
    const r2 = sseEventToChatMessage(e2, "t");
    expect(r1!.id).not.toBe(r2!.id);
  });

  it("same inner_turn produces same ID (streaming upsert within one LLM call)", () => {
    const e1 = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "exec-1",
      data: { snapshot: "partial", iteration: 0, inner_turn: 1 },
    });
    const e2 = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "exec-1",
      data: { snapshot: "partial response", iteration: 0, inner_turn: 1 },
    });
    expect(sseEventToChatMessage(e1, "t")!.id).toBe(
      sseEventToChatMessage(e2, "t")!.id,
    );
  });

  it("absent inner_turn produces same ID as inner_turn=0 (backward compat)", () => {
    const withField = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "exec-1",
      data: { snapshot: "hello", iteration: 2, inner_turn: 0 },
    });
    const withoutField = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "exec-1",
      data: { snapshot: "hello", iteration: 2 },
    });
    expect(sseEventToChatMessage(withField, "t")!.id).toBe(
      sseEventToChatMessage(withoutField, "t")!.id,
    );
  });

  it("inner_turn=0 produces no suffix (matches old ID format)", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "exec-1",
      data: { snapshot: "hello", iteration: 3, inner_turn: 0 },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result!.id).toBe("stream-exec-1-3-queen");
  });

  it("inner_turn>0 adds -t suffix to ID", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "queen",
      execution_id: "exec-1",
      data: { snapshot: "hello", iteration: 3, inner_turn: 2 },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result!.id).toBe("stream-exec-1-3-t2-queen");
  });

  it("llm_text_delta also uses inner_turn for distinct IDs", () => {
    const e1 = makeEvent({
      type: "llm_text_delta",
      node_id: "research",
      execution_id: "exec-1",
      data: { snapshot: "first", inner_turn: 0 },
    });
    const e2 = makeEvent({
      type: "llm_text_delta",
      node_id: "research",
      execution_id: "exec-1",
      data: { snapshot: "second", inner_turn: 1 },
    });
    const r1 = sseEventToChatMessage(e1, "t");
    const r2 = sseEventToChatMessage(e2, "t");
    expect(r1!.id).not.toBe(r2!.id);
    expect(r1!.id).toBe("stream-exec-1-research");
    expect(r2!.id).toBe("stream-exec-1-t1-research");
  });

  it("uses timestamp fallback when both turnId and execution_id are null", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "chat",
      execution_id: null,
      data: { snapshot: "hello" },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result!.id).toMatch(/^stream-t-\d+-chat$/);
  });

  it("converts single client_input_requested question to a queen-style bubble", () => {
    const event = makeEvent({
      type: "client_input_requested",
      node_id: "queen",
      execution_id: "abc",
      data: {
        questions: [{ id: "q0", prompt: "Which folder?" }],
      },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result).not.toBeNull();
    expect(result!.content).toBe("Which folder?");
    expect(result!.id).toMatch(/^ask-user-abc-/);
  });

  it("converts multi-question client_input_requested to a numbered list", () => {
    const event = makeEvent({
      type: "client_input_requested",
      node_id: "queen",
      execution_id: "abc",
      data: {
        questions: [
          { id: "q0", prompt: "Which folder?" },
          { id: "q1", prompt: "Which date range?" },
        ],
      },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result).not.toBeNull();
    expect(result!.content).toBe("1. Which folder?\n2. Which date range?");
  });

  it("returns null for client_input_requested with no questions (auto-wait park)", () => {
    const event = makeEvent({
      type: "client_input_requested",
      node_id: "queen",
      execution_id: "abc",
      data: {},
    });
    expect(sseEventToChatMessage(event, "t")).toBeNull();
  });

  it("converts client_input_received to user message", () => {
    const event = makeEvent({
      type: "client_input_received",
      node_id: "queen",
      execution_id: "abc",
      data: { content: "do the thing" },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result).not.toBeNull();
    expect(result!.agent).toBe("You");
    expect(result!.type).toBe("user");
    expect(result!.content).toBe("do the thing");
  });

  it("returns null for client_input_received with empty content", () => {
    const event = makeEvent({
      type: "client_input_received",
      node_id: "queen",
      execution_id: "abc",
      data: { content: "" },
    });
    expect(sseEventToChatMessage(event, "t")).toBeNull();
  });

  it("converts execution_failed to system error message", () => {
    const event = makeEvent({
      type: "execution_failed",
      execution_id: "abc",
      data: { error: "timeout" },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result).not.toBeNull();
    expect(result!.type).toBe("system");
    expect(result!.content).toContain("timeout");
  });

  it("returns null for execution_started (no chat message)", () => {
    const event = makeEvent({ type: "execution_started", execution_id: "abc" });
    expect(sseEventToChatMessage(event, "t")).toBeNull();
  });

  it("uses agentDisplayName instead of node_id when provided", () => {
    const event = makeEvent({
      type: "client_output_delta",
      node_id: "research",
      execution_id: "abc",
      data: { snapshot: "results" },
    });
    const result = sseEventToChatMessage(event, "t", "Competitive Intel Agent");
    expect(result).not.toBeNull();
    expect(result!.agent).toBe("Competitive Intel Agent");
  });

  it("converts llm_text_delta with snapshot to worker message", () => {
    const event = makeEvent({
      type: "llm_text_delta",
      node_id: "news-search",
      execution_id: "abc",
      data: { content: "Searching", snapshot: "Searching for news articles..." },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result).not.toBeNull();
    expect(result!.id).toBe("stream-abc-news-search");
    expect(result!.content).toBe("Searching for news articles...");
    expect(result!.role).toBe("worker");
    expect(result!.agent).toBe("news-search");
  });

  it("returns null for llm_text_delta with empty snapshot", () => {
    const event = makeEvent({
      type: "llm_text_delta",
      node_id: "news-search",
      execution_id: "abc",
      data: { content: "", snapshot: "" },
    });
    expect(sseEventToChatMessage(event, "t")).toBeNull();
  });

  it("uses node_id (not agentDisplayName) for llm_text_delta", () => {
    const event = makeEvent({
      type: "llm_text_delta",
      node_id: "news-search",
      execution_id: "abc",
      data: { snapshot: "results" },
    });
    const result = sseEventToChatMessage(event, "t", "Competitive Intel Agent");
    expect(result).not.toBeNull();
    expect(result!.agent).toBe("news-search");
  });

  it("still uses 'System' for execution_failed even when agentDisplayName is provided", () => {
    const event = makeEvent({
      type: "execution_failed",
      execution_id: "abc",
      data: { error: "boom" },
    });
    const result = sseEventToChatMessage(event, "t", "My Agent");
    expect(result!.agent).toBe("System");
  });
});

// ---------------------------------------------------------------------------
// replayEventsToMessages
// ---------------------------------------------------------------------------

describe("replayEventsToMessages", () => {
  it("merges queen inner turns from the same iteration into one restored bubble", () => {
    const events = [
      makeEvent({
        type: "client_output_delta",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-1",
        timestamp: "2026-04-20T12:45:25.234Z",
        data: {
          snapshot: "I will create the ERD.",
          iteration: 0,
          inner_turn: 0,
        },
      }),
      makeEvent({
        type: "tool_call_started",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-1",
        timestamp: "2026-04-20T12:45:25.238Z",
        data: {
          tool_name: "write_file",
          tool_use_id: "tool-1",
        },
      }),
      makeEvent({
        type: "tool_call_completed",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-1",
        timestamp: "2026-04-20T12:45:25.250Z",
        data: {
          tool_name: "write_file",
          tool_use_id: "tool-1",
          result: "ok",
        },
      }),
      makeEvent({
        type: "client_output_delta",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-1",
        timestamp: "2026-04-20T12:46:07.911Z",
        data: {
          snapshot: "Saved to `database_erd.md`.",
          iteration: 0,
          inner_turn: 2,
        },
      }),
    ];

    const restored = replayEventsToMessages(events, "queen-dm", "Alexandra");
    const queenMessages = restored.filter(
      (m) => m.role === "queen" && !m.type,
    );

    expect(queenMessages).toHaveLength(1);
    expect(queenMessages[0].id).toBe("queen-stream-session-1-0-s0");
    // Inner-turn spans are exposed separately so the bubble can render a
    // wider (1.5x paragraph) gap between them; `content` joins them with a
    // blank line so copy/print/plain-text read as paragraphs.
    expect(queenMessages[0].innerTurns).toEqual([
      "I will create the ERD.",
      "Saved to `database_erd.md`.",
    ]);
    // Each span carries its inner turn's (first-seen) time, for the per-node
    // hover tooltip on the timeline.
    expect(queenMessages[0].innerTurnTimes).toEqual([
      new Date("2026-04-20T12:45:25.234Z").getTime(),
      new Date("2026-04-20T12:46:07.911Z").getTime(),
    ]);
    expect(queenMessages[0].content).toBe(
      "I will create the ERD.\n\nSaved to `database_erd.md`.",
    );
    expect(queenMessages[0].createdAt).toBe(
      new Date("2026-04-20T12:45:25.234Z").getTime(),
    );
  });

  it("keeps worker inner turns as distinct restored bubbles", () => {
    const events = [
      makeEvent({
        type: "llm_text_delta",
        stream_id: "worker",
        node_id: "research",
        execution_id: "session-1",
        data: { snapshot: "First pass", iteration: 0, inner_turn: 0 },
      }),
      makeEvent({
        type: "llm_text_delta",
        stream_id: "worker",
        node_id: "research",
        execution_id: "session-1",
        data: { snapshot: "After tool", iteration: 0, inner_turn: 1 },
      }),
    ];

    const restored = replayEventsToMessages(events, "agent", "Research Agent");

    expect(restored.map((m) => m.id)).toEqual([
      "stream-session-1-0-research",
      "stream-session-1-0-t1-research",
    ]);
  });

  it("does not carry completed queen tools into a scheduler run", () => {
    const events = [
      makeEvent({
        type: "tool_call_started",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-setup",
        data: { tool_name: "create_colony", tool_use_id: "tool-create" },
      }),
      makeEvent({
        type: "tool_call_completed",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-setup",
        data: { tool_name: "create_colony", tool_use_id: "tool-create" },
      }),
      makeEvent({
        type: "llm_turn_complete",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-setup",
      }),
      makeEvent({
        type: "node_loop_started",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-scheduler",
      }),
      makeEvent({
        type: "tool_call_started",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-scheduler",
        data: {
          tool_name: "list_worker_questions",
          tool_use_id: "tool-questions",
        },
      }),
      makeEvent({
        type: "tool_call_started",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-scheduler",
        data: { tool_name: "get_worker_status", tool_use_id: "tool-status" },
      }),
      makeEvent({
        type: "tool_call_completed",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-scheduler",
        data: {
          tool_name: "list_worker_questions",
          tool_use_id: "tool-questions",
        },
      }),
      makeEvent({
        type: "tool_call_completed",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "session-scheduler",
        data: { tool_name: "get_worker_status", tool_use_id: "tool-status" },
      }),
    ];

    const restored = replayEventsToMessages(events, "queen-dm", "Alexandra");
    // One tool_status message per call, all completed: 3 messages
    // (create_colony, list_worker_questions, get_worker_status).
    const toolRows = restored.filter((m) => m.type === "tool_status");
    expect(toolRows).toHaveLength(3);

    const ts = new Date("2026-01-01T00:00:00Z").getTime();
    const parse = (m: { content: string }) =>
      JSON.parse(m.content) as { tools: unknown[]; allDone: boolean };
    expect(parse(toolRows[0])).toEqual({
      tools: [
        {
          name: "create_colony",
          done: true,
          callKey: "tool-create",
          startedAt: ts,
          endedAt: ts,
        },
      ],
      allDone: true,
    });
    expect(parse(toolRows[1])).toEqual({
      tools: [
        {
          name: "list_worker_questions",
          done: true,
          callKey: "tool-questions",
          startedAt: ts,
          endedAt: ts,
        },
      ],
      allDone: true,
    });
    expect(parse(toolRows[2])).toEqual({
      tools: [
        {
          name: "get_worker_status",
          done: true,
          callKey: "tool-status",
          startedAt: ts,
          endedAt: ts,
        },
      ],
      allDone: true,
    });
  });

  it("uses execution id when resolving tool completions", () => {
    const events = [
      makeEvent({
        type: "tool_call_started",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "exec-a",
        data: { tool_name: "first_run_tool", tool_use_id: "shared-id" },
      }),
      makeEvent({
        type: "tool_call_started",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "exec-b",
        data: { tool_name: "second_run_tool", tool_use_id: "shared-id" },
      }),
      makeEvent({
        type: "tool_call_completed",
        stream_id: "queen",
        node_id: "queen",
        execution_id: "exec-a",
        data: { tool_name: "first_run_tool", tool_use_id: "shared-id" },
      }),
    ];

    const restored = replayEventsToMessages(events, "queen-dm", "Alexandra");
    // Each tool_call_started gets its own tool_status message; the
    // completion for exec-a resolves via the (stream, execution_id,
    // tool_use_id) lookup even though both calls share the same
    // tool_use_id, and only the first message flips to done.
    const toolRows = restored.filter((m) => m.type === "tool_status");
    expect(toolRows).toHaveLength(2);
    const ts2 = new Date("2026-01-01T00:00:00Z").getTime();
    const parse = (m: { content: string }) =>
      JSON.parse(m.content) as { tools: unknown[]; allDone: boolean };
    expect(parse(toolRows[0])).toEqual({
      tools: [
        {
          name: "first_run_tool",
          done: true,
          callKey: "shared-id",
          startedAt: ts2,
          endedAt: ts2,
        },
      ],
      allDone: true,
    });
    // The exec-b call never completed in this event stream, so
    // finalizeOpenToolRows marks it interrupted at end-of-replay (a
    // tool that started but didn't finish should not render as
    // forever-running once the session ended).
    expect(parse(toolRows[1])).toEqual({
      tools: [
        {
          name: "second_run_tool",
          done: true,
          callKey: "shared-id",
          startedAt: ts2,
          isInterrupted: true,
        },
      ],
      allDone: true,
    });
  });

  it("produces a path-independent msg.id for tool calls", () => {
    // Regression: when the user switches away from a session and back,
    // the same logical tool_call event arrives via two paths — the disk
    // events.jsonl reload and the SSE ring-buffer resubscribe. `seq`
    // is not stable across paths (separate runtime counters), but
    // `tool_use_id` is stamped by the LLM provider and persisted with
    // the event, so it's the same in both places. The msgId derives
    // from `tool_use_id` so the by-id merge in queen-dm dedupes the
    // two deliveries instead of rendering the same pill twice.
    const tool = {
      type: "tool_call_started" as const,
      stream_id: "queen",
      node_id: "queen",
      execution_id: "exec-1",
      data: { tool_name: "web_scrape", tool_use_id: "tool-xyz" },
    };
    const fromDisk = replayEventsToMessages(
      [makeEvent({ ...tool, seq: 7 })],
      "queen-dm",
      "Alexandra",
    );
    const fromSse = replayEventsToMessages(
      [makeEvent({ ...tool, seq: 9001 })],
      "queen-dm",
      "Alexandra",
    );
    const diskRow = fromDisk.find((m) => m.type === "tool_status");
    const sseRow = fromSse.find((m) => m.type === "tool_status");
    expect(diskRow).toBeDefined();
    expect(sseRow).toBeDefined();
    expect(diskRow!.id).toBe(sseRow!.id);
  });

  it("streaming reasoning deltas then the final block upsert one reasoning bubble", () => {
    const base = {
      stream_id: "queen",
      node_id: "queen",
      execution_id: "session-1",
    };
    const restored = replayEventsToMessages(
      [
        makeEvent({ ...base, type: "llm_reasoning_delta", timestamp: "2026-04-20T12:00:00.000Z", data: { content: "Let me", snapshot: "Let me", iteration: 0 } }),
        makeEvent({ ...base, type: "llm_reasoning_delta", timestamp: "2026-04-20T12:00:01.000Z", data: { content: " plan.", snapshot: "Let me plan.", iteration: 0 } }),
        makeEvent({ ...base, type: "client_reasoning", timestamp: "2026-04-20T12:00:02.000Z", data: { reasoning: "Let me plan. Done.", iteration: 0 } }),
      ],
      "queen-dm",
      "Alexandra",
    );
    const reasoning = restored.filter((m) => m.type === "reasoning");
    expect(reasoning).toHaveLength(1);
    expect(reasoning[0].content).toBe("Let me plan. Done.");
  });
});

// ---------------------------------------------------------------------------
// formatAgentDisplayName
// ---------------------------------------------------------------------------

describe("formatAgentDisplayName", () => {
  it("converts underscored agent name to title case", () => {
    expect(formatAgentDisplayName("competitive_intel_agent")).toBe("Competitive Intel Agent");
  });

  it("strips -graph suffix", () => {
    expect(formatAgentDisplayName("competitive_intel_agent-graph")).toBe("Competitive Intel Agent");
  });

  it("strips _graph suffix", () => {
    expect(formatAgentDisplayName("my_agent_graph")).toBe("My Agent");
  });

  it("converts hyphenated names to title case", () => {
    expect(formatAgentDisplayName("inbox-management")).toBe("Inbox Management");
  });

  it("takes the last path segment", () => {
    expect(formatAgentDisplayName("examples/templates/job_hunter")).toBe("Job Hunter");
  });

  it("handles a single word", () => {
    expect(formatAgentDisplayName("agent")).toBe("Agent");
  });
});

// ---------------------------------------------------------------------------
// extractLastPhase
// ---------------------------------------------------------------------------

describe("extractLastPhase", () => {
  it("returns the most recent valid phase from queen_phase_changed events", () => {
    expect(
      extractLastPhase([
        makeEvent({
          type: "queen_phase_changed",
          data: { phase: "independent" },
        }),
        makeEvent({
          type: "queen_phase_changed",
          data: { phase: "colony" },
        }),
      ]),
    ).toBe("colony");
  });

  it("reads phase metadata from node loop iterations", () => {
    expect(
      extractLastPhase([
        makeEvent({
          type: "node_loop_iteration",
          data: { phase: "colony" },
        }),
      ]),
    ).toBe("colony");
  });
});

// ---------------------------------------------------------------------------
// client_input_committed — a steer injected mid-iteration must SPLIT the
// queen's per-iteration bubble so the post-steer reply renders as its own
// bubble BELOW the steer, instead of folding into the pre-steer narration
// (which is pinned at the iteration's start, above the steer). Also re-stamps
// the user bubble to its true injection time. Guards the fix for both DM and
// colony (both restore through replayEventsToMessages).
// ---------------------------------------------------------------------------
describe("client_input_committed splits the steered iteration bubble", () => {
  const at = (s: number) =>
    new Date(Date.UTC(2026, 0, 1, 0, 0, s)).toISOString();

  // One queen loop iteration (78) spanning a steer: it starts long before the
  // steer ("tacos…" at t=10), the user steers (received t=31, drained/committed
  // t=35), and the queen's reaction streams after ("Ramen it is" at t=39). All
  // three deltas share iteration=78 — the merge-by-iteration is exactly what
  // collapses them into one bubble without the fix.
  const buildEvents = (committed: AgentEvent | null): AgentEvent[] => {
    const early = makeEvent({
      type: "client_output_delta",
      stream_id: "queen",
      node_id: "queen",
      execution_id: "exec1",
      timestamp: at(10),
      data: { snapshot: "Pulling the best taco spots…", iteration: 78, inner_turn: 0 },
    });
    const received = makeEvent({
      type: "client_input_received",
      stream_id: "queen",
      execution_id: "exec1",
      correlation_id: "corr-ramen",
      timestamp: at(31),
      data: { content: "no i meant ramen" },
    });
    const reaction = makeEvent({
      type: "client_output_delta",
      stream_id: "queen",
      node_id: "queen",
      execution_id: "exec1",
      timestamp: at(39),
      data: { snapshot: "Ramen it is. Let me pivot.", iteration: 78, inner_turn: 16 },
    });
    // Disk/emission order: early delta → received → committed → reaction.
    return committed ? [early, received, committed, reaction] : [early, received, reaction];
  };

  const queenBubbles = (msgs: ChatMessageLike[]) =>
    msgs.filter((m) => m.role === "queen" && !m.type);
  type ChatMessageLike = { role?: string; type?: string; content?: string; createdAt?: number };
  const idxOf = (msgs: ChatMessageLike[], pred: (m: ChatMessageLike) => boolean) =>
    msgs.findIndex(pred);

  it("splits into two bubbles so the reply sorts below the steer", () => {
    const committed = makeEvent({
      type: "client_input_committed",
      stream_id: "queen",
      execution_id: "exec1",
      correlation_id: "corr-ramen",
      timestamp: at(35),
      data: { seq: 58 },
    });
    const msgs = replayEventsToMessages(buildEvents(committed), "thread", undefined, "Eleanor") as ChatMessageLike[];

    // Two distinct queen bubbles — pre-steer and post-steer.
    const bubbles = queenBubbles(msgs);
    expect(bubbles).toHaveLength(2);

    const taco = idxOf(msgs, (m) => (m.content ?? "").includes("taco"));
    const ramen = idxOf(msgs, (m) => (m.content ?? "").includes("Ramen it is"));
    const user = idxOf(msgs, (m) => m.type === "user");
    // Order: taco narration → steer → ramen reply.
    expect(taco).toBeLessThan(user);
    expect(user).toBeLessThan(ramen);
    // Bubbles are not cross-contaminated.
    expect(msgs[taco].content).not.toContain("Ramen it is");
    expect(msgs[ramen].content).not.toContain("taco");
    // User bubble adopted the committed (true injection) time.
    expect(msgs[user].createdAt).toBe(Date.parse(at(35)));
  });

  it("without the committed event the whole iteration merges above the steer (the bug)", () => {
    const msgs = replayEventsToMessages(buildEvents(null), "thread", undefined, "Eleanor") as ChatMessageLike[];
    // One merged bubble carrying BOTH texts, pinned at the iteration start…
    const bubbles = queenBubbles(msgs);
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0].content).toContain("taco");
    expect(bubbles[0].content).toContain("Ramen it is");
    // …so the reply wrongly sits ABOVE the steer.
    const ramen = idxOf(msgs, (m) => (m.content ?? "").includes("Ramen it is"));
    const user = idxOf(msgs, (m) => m.type === "user");
    expect(ramen).toBeLessThan(user);
  });

  it("segments independently of event order (delta seen before its drain)", () => {
    const committed = makeEvent({
      type: "client_input_committed",
      stream_id: "queen",
      execution_id: "exec1",
      correlation_id: "corr-ramen",
      timestamp: at(35),
      data: { seq: 58 },
    });
    // Pathological order: the post-steer reaction delta is delivered BEFORE
    // the committed event. The pre-pass over committed times must still place
    // it in the post-steer segment.
    const ev = buildEvents(committed);
    const reordered = [ev[0], ev[1], ev[3], ev[2]]; // early, received, reaction, committed
    const msgs = replayEventsToMessages(reordered, "thread", undefined, "Eleanor") as ChatMessageLike[];
    expect(queenBubbles(msgs)).toHaveLength(2);
  });
});
