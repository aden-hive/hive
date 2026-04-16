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
 * Format a message timestamp Slack-style: time-of-day for messages from today,
 * date + time for older messages.
 */
export function formatMessageTime(createdAt: number): string {
  const d = new Date(createdAt);
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  const time = d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  if (sameDay) return time;
  const sameYear = d.getFullYear() === now.getFullYear();
  const date = d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
  return `${date}, ${time}`;
}

/**
 * Format the label shown on a day-separator divider. Always absolute date + time
 * (no "Today" / "Yesterday") so the user can see exactly when activity resumed.
 */
export function formatDayDividerLabel(createdAt: number): string {
  const d = new Date(createdAt);
  const now = new Date();
  const sameYear = d.getFullYear() === now.getFullYear();
  const date = d.toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
  const time = d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${date}, ${time}`;
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
      if (!snapshot.trim()) return null;
      return {
        id: `stream-${iterIdKey}${innerSuffix}-${event.node_id}`,
        agent: agentDisplayName || event.node_id || "Agent",
        agentColor: "",
        content: snapshot,
        timestamp: "",
        role: "worker",
        thread,
        createdAt,
        nodeId: event.node_id || undefined,
        executionId: event.execution_id || undefined,
      };
    }

    case "client_input_requested":
      // Handled explicitly in handleSSEEvent (workspace.tsx) for queen input widgets.
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
      if (!snapshot.trim()) return null;
      return {
        id: `stream-${idKey}${llmInnerSuffix}-${event.node_id}`,
        agent: event.node_id || "Agent",
        agentColor: "",
        content: snapshot,
        timestamp: "",
        role: "worker",
        thread,
        createdAt,
        nodeId: event.node_id || undefined,
        executionId: event.execution_id || undefined,
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

// ---------------------------------------------------------------------------
// Stateful event replay — produces tool_status pills + regular messages
// ---------------------------------------------------------------------------

/**
 * State maintained while replaying an event stream. Tracks per-stream turn
 * counters, the set of active tool calls (so tool_status pill content
 * reflects "tool A done, tool B running" correctly), and a tool_use_id →
 * pill_msg_id map so deferred `tool_call_completed` events can find the
 * pill they belong to after the turn counter moves on.
 */
export interface ReplayState {
  turnCounters: Record<string, number>;
  activeToolCalls: Record<
    string,
    { name: string; done: boolean; streamId: string }
  >;
  toolUseToPill: Record<string, { msgId: string; name: string }>;
}

export function newReplayState(): ReplayState {
  return { turnCounters: {}, activeToolCalls: {}, toolUseToPill: {} };
}

/**
 * Process a single event and emit zero or more ChatMessage upserts.
 *
 * Why this exists: `sseEventToChatMessage` is stateless — one event in, at
 * most one message out. But the chat's tool_status pill is a SYNTHESIZED
 * message: each tool_call_started adds to an accumulating pill, and each
 * tool_call_completed flips one of its tools from running to done. Live
 * SSE handlers in colony-chat and queen-dm already do this synthesis
 * against React refs. Cold-restore from events.jsonl used to skip
 * tool_call_* events entirely, so refreshed sessions looked completely
 * different from live ones — no tool activity visible, just prose.
 *
 * This function centralizes the synthesis so cold-restore and live paths
 * can use the exact same state machine. The caller treats the returned
 * messages as upserts (by id) — a later event in the same replay may
 * emit the same pill id with updated content, which should REPLACE the
 * earlier row in the caller's message list.
 */
export function replayEvent(
  state: ReplayState,
  event: AgentEvent,
  thread: string,
  agentDisplayName: string | undefined,
): ChatMessage[] {
  const streamId = event.stream_id;
  const isQueen = streamId === "queen";
  const role: "queen" | "worker" = isQueen ? "queen" : "worker";
  const turnKey = streamId;
  const currentTurn = state.turnCounters[turnKey] ?? 0;
  const eventCreatedAt = event.timestamp
    ? new Date(event.timestamp).getTime()
    : Date.now();

  const out: ChatMessage[] = [];

  // Update state machine BEFORE the generic converter runs so the
  // regular message emitted for this event sees the post-update
  // counter (matches live handler ordering at colony-chat.tsx:525).
  switch (event.type) {
    case "execution_started":
      state.turnCounters[turnKey] = currentTurn + 1;
      // New execution for a worker resets its active tools, mirroring
      // the live handler's setAgentState at colony-chat.tsx:566.
      if (!isQueen) {
        const keepActive: typeof state.activeToolCalls = {};
        for (const [k, v] of Object.entries(state.activeToolCalls)) {
          if (v.streamId !== streamId) keepActive[k] = v;
        }
        state.activeToolCalls = keepActive;
      }
      break;
    case "llm_turn_complete":
      state.turnCounters[turnKey] = currentTurn + 1;
      break;
    case "tool_call_started": {
      if (!event.node_id) break;
      const toolName = (event.data?.tool_name as string) || "unknown";
      const toolUseId = (event.data?.tool_use_id as string) || "";
      state.activeToolCalls[toolUseId] = {
        name: toolName,
        done: false,
        streamId,
      };
      const pillId = `tool-pill-${streamId}-${event.execution_id || "exec"}-${currentTurn}`;
      if (toolUseId) {
        state.toolUseToPill[toolUseId] = { msgId: pillId, name: toolName };
      }
      const tools = Object.values(state.activeToolCalls)
        .filter((t) => t.streamId === streamId)
        .map((t) => ({ name: t.name, done: t.done }));
      const allDone = tools.length > 0 && tools.every((t) => t.done);
      out.push({
        id: pillId,
        agent: agentDisplayName || event.node_id || "Agent",
        agentColor: "",
        content: JSON.stringify({ tools, allDone }),
        timestamp: "",
        type: "tool_status",
        role,
        thread,
        createdAt: eventCreatedAt,
        nodeId: event.node_id || undefined,
        executionId: event.execution_id || undefined,
      });
      break;
    }
    case "tool_call_completed": {
      if (!event.node_id) break;
      const toolUseId = (event.data?.tool_use_id as string) || "";
      const tracked = state.toolUseToPill[toolUseId];
      if (toolUseId) delete state.toolUseToPill[toolUseId];
      if (toolUseId && state.activeToolCalls[toolUseId]) {
        state.activeToolCalls[toolUseId].done = true;
      }
      if (!tracked) break;
      const tools = Object.values(state.activeToolCalls)
        .filter((t) => t.streamId === streamId)
        .map((t) => ({ name: t.name, done: t.done }));
      const allDone = tools.length > 0 && tools.every((t) => t.done);
      // Re-emit the SAME pill id with updated content. Caller upserts
      // by id, so this replaces the row from tool_call_started.
      out.push({
        id: tracked.msgId,
        agent: agentDisplayName || event.node_id || "Agent",
        agentColor: "",
        content: JSON.stringify({ tools, allDone }),
        timestamp: "",
        type: "tool_status",
        role,
        thread,
        createdAt: eventCreatedAt,
        nodeId: event.node_id || undefined,
        executionId: event.execution_id || undefined,
      });
      break;
    }
  }

  // Regular stateless conversion (prose, user input, system notes).
  const msg = sseEventToChatMessage(
    event,
    thread,
    agentDisplayName,
    state.turnCounters[turnKey] ?? 0,
  );
  if (msg) {
    if (isQueen) msg.role = "queen";
    out.push(msg);
  }

  return out;
}

/**
 * Replay an entire event array and return a deduplicated, chronologically
 * sorted ChatMessage list. Used by cold-restore paths so refreshed
 * sessions match the live stream exactly.
 */
export function replayEventsToMessages(
  events: AgentEvent[],
  thread: string,
  agentDisplayName: string | undefined,
): ChatMessage[] {
  const state = newReplayState();
  // Upsert by id — later emissions for the same pill replace earlier ones.
  const byId = new Map<string, ChatMessage>();
  for (const evt of events) {
    for (const m of replayEvent(state, evt, thread, agentDisplayName)) {
      byId.set(m.id, m);
    }
  }
  return Array.from(byId.values()).sort(
    (a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0),
  );
}

type QueenPhase = "planning" | "building" | "staging" | "running" | "independent";
const VALID_PHASES = new Set<string>(["planning", "building", "staging", "running", "independent"]);

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
