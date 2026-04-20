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

function makeEvent(overrides: Partial<AgentEvent>): AgentEvent {
  return {
    type: "execution_started",
    stream_id: "s1",
    node_id: null,
    execution_id: null,
    data: {},
    timestamp: "2026-01-01T00:00:00Z",
    correlation_id: null,
    colony_id: null,
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

  it("returns null for client_input_requested (handled in workspace.tsx)", () => {
    const event = makeEvent({
      type: "client_input_requested",
      node_id: "chat",
      execution_id: "abc",
      data: { prompt: "What next?" },
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
    expect(queenMessages[0].id).toBe("queen-stream-session-1-0");
    expect(queenMessages[0].content).toBe(
      "I will create the ERD.\nSaved to `database_erd.md`.",
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
  it("keeps incubating as a valid queen phase", () => {
    expect(
      extractLastPhase([
        makeEvent({
          type: "queen_phase_changed",
          data: { phase: "independent" },
        }),
        makeEvent({
          type: "queen_phase_changed",
          data: { phase: "incubating" },
        }),
      ]),
    ).toBe("incubating");
  });

  it("reads phase metadata from node loop iterations", () => {
    expect(
      extractLastPhase([
        makeEvent({
          type: "node_loop_iteration",
          data: { phase: "working" },
        }),
      ]),
    ).toBe("working");
  });
});
