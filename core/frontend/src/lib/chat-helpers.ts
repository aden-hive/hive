/**
 * Pure functions for converting SSE events into ChatMessage objects.
 * No React dependencies — just JSON in, object out.
 */

import type { ChatMessage } from "@/components/ChatPanel";
import type { AgentEvent } from "@/api/types";

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
  // Use the backend event timestamp for message ordering
  const createdAt = event.timestamp ? new Date(event.timestamp).getTime() : Date.now();

  switch (event.type) {
    case "client_output_delta": {
      // Prefer backend-provided iteration (reliable, embedded in event data)
      // over frontend turnCounter (can desync when SSE queue drops events).
      const iter = event.data?.iteration;
      const iterTid = iter != null ? String(iter) : tid;
      const iterIdKey = eid && iterTid ? `${eid}-${iterTid}` : eid || iterTid || `t-${Date.now()}`;

      // Distinguish multiple LLM calls within the same iteration (inner tool loop).
      // inner_turn=0 (or absent) produces no suffix for backward compat.
      const innerTurn = event.data?.inner_turn as number | undefined;
      const innerSuffix = innerTurn != null && innerTurn > 0 ? `-t${innerTurn}` : "";

      const snapshot = (event.data?.snapshot as string) || (event.data?.content as string) || "";
      if (!snapshot) return null;
      return {
        id: `stream-${iterIdKey}${innerSuffix}-${event.node_id}`,
        agent: agentDisplayName || event.node_id || "Agent",
        agentColor: "",
        content: snapshot,
        timestamp: "",
        role: "worker",
        thread,
        createdAt,
      };
    }

    case "client_input_requested":
      // Handled explicitly in handleSSEEvent (workspace.tsx) so it can
      // create a worker_input_request message and set awaitingInput state.
      return null;

    case "client_input_received": {
      const userContent = (event.data?.content as string) || "";
      if (!userContent) return null;
      return {
        id: `user-input-${event.timestamp}`,
        agent: "You",
        agentColor: "",
        content: userContent,
        timestamp: "",
        type: "user",
        thread,
        createdAt,
      };
    }

    case "llm_text_delta": {
      const llmInnerTurn = event.data?.inner_turn as number | undefined;
      const llmInnerSuffix = llmInnerTurn != null && llmInnerTurn > 0 ? `-t${llmInnerTurn}` : "";

      const snapshot = (event.data?.snapshot as string) || (event.data?.content as string) || "";
      if (!snapshot) return null;
      return {
        id: `stream-${idKey}${llmInnerSuffix}-${event.node_id}`,
        agent: event.node_id || "Agent",
        agentColor: "",
        content: snapshot,
        timestamp: "",
        role: "worker",
        thread,
        createdAt,
      };
    }

    case "execution_paused": {
      return {
        id: `paused-${event.execution_id}`,
        agent: "System",
        agentColor: "",
        content:
          (event.data?.reason as string) || "Execution paused",
        timestamp: "",
        type: "system",
        thread,
        createdAt,
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
        createdAt,
      };
    }

    default:
      return null;
  }
}

type QueenPhase = "planning" | "building" | "staging" | "running";
const VALID_PHASES = new Set<string>(["planning", "building", "staging", "running"]);

/**
 * Scan an array of persisted events and return the last queen phase seen,
 * or null if no phase event exists.  Reads both `queen_phase_changed` events
 * and the per-iteration `phase` metadata on `node_loop_iteration` events.
 */
export function extractLastPhase(events: AgentEvent[]): QueenPhase | null {
  let last: QueenPhase | null = null;
  for (const evt of events) {
    const phase =
      evt.type === "queen_phase_changed" ? (evt.data?.phase as string) :
      evt.type === "node_loop_iteration" ? (evt.data?.phase as string | undefined) :
      undefined;
    if (phase && VALID_PHASES.has(phase)) {
      last = phase as QueenPhase;
    }
  }
  return last;
}
