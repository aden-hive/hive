/**
 * Pure functions for converting backend messages and SSE events into ChatMessage objects.
 * No React dependencies — just JSON in, object out.
 */

import type { ChatMessage } from "@/components/ChatPanel";
import type { AgentEvent, Message } from "@/api/types";

/**
 * Derive a human-readable display name from a raw agent identifier.
 *
 * Examples:
 *   "competitive_intel_agent"       → "Competitive Intel Agent"
 *   "competitive_intel_agent-graph" → "Competitive Intel Agent"
 *   "inbox-management"              → "Inbox Management"
 *   "job_hunter"                    → "Job Hunter"
 */
export function formatAgentDisplayName(raw: string): string {
  // Take the last path segment (in case it's a path like "examples/templates/foo")
  const base = raw.split("/").pop() || raw;
  // Strip common suffixes like "-graph" or "_graph"
  const stripped = base.replace(/[-_]graph$/, "");
  // Replace underscores and hyphens with spaces, then title-case each word
  return stripped
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

/**
 * Convert a backend Message (from sessionsApi.messages()) into a ChatMessage.
 * When agentDisplayName is provided, it is used as the sender for all agent
 * messages instead of the raw node_id.
 */
export function backendMessageToChatMessage(
  msg: Message,
  thread: string,
  agentDisplayName?: string,
): ChatMessage {
  return {
    id: `backend-${msg.seq}`,
    agent: msg.role === "user" ? "You" : agentDisplayName || msg._node_id || "Agent",
    agentColor: "",
    content: msg.content,
    timestamp: "",
    type: msg.role === "user" ? "user" : undefined,
    role: msg.role === "user" ? undefined : "worker",
    thread,
  };
}

/**
 * Convert an SSE AgentEvent into a ChatMessage, or null if the event
 * doesn't produce a visible chat message.
 * When agentDisplayName is provided, it is used as the sender for all agent
 * messages instead of the raw node_id.
 */
export function sseEventToChatMessage(
  event: AgentEvent,
  thread: string,
  agentDisplayName?: string,
  turnId?: number,
): ChatMessage | null {
  // turnId disambiguates messages across response turns.  Within a single
  // turn the ID stays stable so the upsert logic can replace the previous
  // snapshot (streaming).  Across turns, different turnIds produce different
  // IDs so each response gets its own bubble.
  const idKey = turnId != null ? String(turnId) : (event.execution_id ?? "0");

  switch (event.type) {
    case "client_output_delta": {
      const snapshot = (event.data?.snapshot as string) || (event.data?.content as string) || "";
      if (!snapshot) return null;
      return {
        id: `stream-${idKey}-${event.node_id}`,
        agent: agentDisplayName || event.node_id || "Agent",
        agentColor: "",
        content: snapshot,
        timestamp: "",
        role: "worker",
        thread,
      };
    }

    case "client_input_requested": {
      const prompt = (event.data?.prompt as string) || "";
      if (!prompt) return null;
      return {
        id: `input-req-${idKey}-${event.node_id}`,
        agent: agentDisplayName || event.node_id || "Agent",
        agentColor: "",
        content: prompt,
        timestamp: "",
        role: "worker",
        thread,
      };
    }

    case "llm_text_delta": {
      const snapshot = (event.data?.snapshot as string) || (event.data?.content as string) || "";
      if (!snapshot) return null;
      return {
        id: `stream-${idKey}-${event.node_id}`,
        agent: event.node_id || "Agent",
        agentColor: "",
        content: snapshot,
        timestamp: "",
        role: "worker",
        thread,
      };
    }

    case "execution_failed": {
      const error = (event.data?.error as string) || "Execution failed";
      return {
        id: `error-${event.execution_id}`,
        agent: "System",
        agentColor: "",
        content: `Error: ${error}`,
        timestamp: "",
        type: "system",
        thread,
      };
    }

    default:
      return null;
  }
}
