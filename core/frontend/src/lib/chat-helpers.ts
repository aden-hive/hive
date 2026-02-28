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
  // Combine execution_id (unique per execution) with turnId (increments per
  // loop iteration) so each iteration gets its own bubble while streaming
  // deltas within one iteration still share the same ID for upsert.
  const eid = event.execution_id ?? "";
  const tid = turnId != null ? String(turnId) : "";
  const idKey = eid && tid ? `${eid}-${tid}` : eid || tid || `t-${Date.now()}`;

  switch (event.type) {
    case "client_output_delta": {
      // Prefer backend-provided iteration (reliable, embedded in event data)
      // over frontend turnCounter (can desync when SSE queue drops events).
      const iter = event.data?.iteration;
      const iterTid = iter != null ? String(iter) : tid;
      const iterIdKey = eid && iterTid ? `${eid}-${iterTid}` : eid || iterTid || `t-${Date.now()}`;

      const snapshot = (event.data?.snapshot as string) || (event.data?.content as string) || "";
      if (!snapshot) return null;
      return {
        id: `stream-${iterIdKey}-${event.node_id}`,
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

    case "execution_paused": {
      return {
        id: `paused-${event.execution_id}`,
        agent: "System",
        agentColor: "",
        content: "Execution paused by user",
        timestamp: "",
        type: "system",
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
