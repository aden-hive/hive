import { describe, it, expect } from "vitest";
import { backendMessageToChatMessage, sseEventToChatMessage, formatAgentDisplayName } from "./chat-helpers";
import type { AgentEvent, Message } from "@/api/types";

// ---------------------------------------------------------------------------
// backendMessageToChatMessage
// ---------------------------------------------------------------------------

describe("backendMessageToChatMessage", () => {
  it("converts a user message", () => {
    const msg: Message = { seq: 1, role: "user", content: "hello", _node_id: "chat" };
    const result = backendMessageToChatMessage(msg, "inbox-management");
    expect(result.type).toBe("user");
    expect(result.agent).toBe("You");
    expect(result.role).toBeUndefined();
    expect(result.content).toBe("hello");
    expect(result.thread).toBe("inbox-management");
  });

  it("converts an assistant message with node_id as agent", () => {
    const msg: Message = { seq: 2, role: "assistant", content: "hi", _node_id: "intake" };
    const result = backendMessageToChatMessage(msg, "inbox-management");
    expect(result.agent).toBe("intake");
    expect(result.role).toBe("worker");
    expect(result.type).toBeUndefined();
  });

  it("defaults agent to 'Agent' when _node_id is empty", () => {
    const msg: Message = { seq: 3, role: "assistant", content: "ok", _node_id: "" };
    const result = backendMessageToChatMessage(msg, "inbox-management");
    expect(result.agent).toBe("Agent");
  });

  it("produces deterministic ID from seq", () => {
    const msg: Message = { seq: 42, role: "user", content: "test", _node_id: "x" };
    const result = backendMessageToChatMessage(msg, "thread");
    expect(result.id).toBe("backend-42");
  });

  it("passes through the thread parameter", () => {
    const msg: Message = { seq: 1, role: "user", content: "hi", _node_id: "x" };
    const result = backendMessageToChatMessage(msg, "my-thread");
    expect(result.thread).toBe("my-thread");
  });

  it("uses agentDisplayName instead of node_id when provided", () => {
    const msg: Message = { seq: 2, role: "assistant", content: "hi", _node_id: "intake" };
    const result = backendMessageToChatMessage(msg, "thread", "Competitive Intel Agent");
    expect(result.agent).toBe("Competitive Intel Agent");
  });

  it("still shows 'You' for user messages even when agentDisplayName is provided", () => {
    const msg: Message = { seq: 1, role: "user", content: "hello", _node_id: "chat" };
    const result = backendMessageToChatMessage(msg, "thread", "My Agent");
    expect(result.agent).toBe("You");
  });
});

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
    graph_id: null,
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

  it("converts client_input_requested with prompt to message", () => {
    const event = makeEvent({
      type: "client_input_requested",
      node_id: "chat",
      execution_id: "abc",
      data: { prompt: "What next?" },
    });
    const result = sseEventToChatMessage(event, "t");
    expect(result).not.toBeNull();
    expect(result!.content).toBe("What next?");
    expect(result!.role).toBe("worker");
  });

  it("returns null for client_input_requested without prompt", () => {
    const event = makeEvent({
      type: "client_input_requested",
      node_id: "chat",
      execution_id: "abc",
      data: { prompt: "" },
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
