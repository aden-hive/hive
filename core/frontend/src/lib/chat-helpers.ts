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
/**
 * Extract the colony worker uuid from a parallel-worker ``streamId``.
 *
 * Worker messages tag their ``streamId`` as either ``"worker"`` (single-worker
 * legacy case) or ``"worker:{uuid}"`` (parallel fan-out). The uuid half is
 * the colony worker id — the same identifier the Colony Workers sidebar uses
 * to key its Sessions cards. Returns null for the legacy single-worker case
 * or any other stream kind.
 */
export function workerIdFromStreamId(
  streamId: string | null | undefined,
): string | null {
  if (!streamId) return null;
  const m = /^worker:(.+)$/.exec(streamId);
  return m ? m[1] : null;
}

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
        streamId: event.stream_id || undefined,
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
        // Carrying execution_id here lets the optimistic-message reconciler
        // distinguish server-echoed user bubbles from still-unflushed ones.
        executionId: event.execution_id || undefined,
        streamId: event.stream_id || undefined,
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
        streamId: event.stream_id || undefined,
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
        streamId: event.stream_id || undefined,
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
        streamId: event.stream_id || undefined,
      };
    }

    case "trigger_fired": {
      // Surface each scheduler/webhook fire as a banner in the chat, so the
      // user can see exactly when the queen was invoked by a trigger vs. by
      // a typed message. The banner sits at the start of the turn the queen
      // is about to run in response.
      const triggerId = event.data?.trigger_id as string | undefined;
      if (!triggerId) return null;
      const payload = {
        trigger_id: triggerId,
        trigger_type: event.data?.trigger_type as string | undefined,
        name: event.data?.name as string | undefined,
        task: event.data?.task as string | undefined,
        fire_count: event.data?.fire_count as number | undefined,
        last_fired_at: event.data?.last_fired_at as number | undefined,
      };
      return {
        id: `trigger-${triggerId}-${payload.last_fired_at ?? event.timestamp}`,
        agent: "Trigger",
        agentColor: "",
        content: JSON.stringify(payload),
        timestamp: "",
        type: "trigger",
        thread,
        createdAt,
        streamId: event.stream_id || undefined,
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
 * counters, materialized tool rows, and a pending tool_use_id → row map so
 * deferred `tool_call_completed` events can find the exact pill they belong
 * to after the turn counter moves on.
 */
type ToolRowState = {
  streamId: string;
  executionId: string;
  tools: Record<string, { name: string; done: boolean }>;
};

export interface ReplayState {
  turnCounters: Record<string, number>;
  toolRows: Record<string, ToolRowState>;
  toolUseToPill: Record<
    string,
    { msgId: string; toolKey: string; name: string }
  >;
  queenIterText: Record<string, Record<number, string>>;
}

export function newReplayState(): ReplayState {
  return {
    turnCounters: {},
    toolRows: {},
    toolUseToPill: {},
    queenIterText: {},
  };
}

function toolLookupKey(
  streamId: string,
  executionId: string | null | undefined,
  toolUseId: string,
): string {
  return `${streamId}:${executionId || "exec"}:${toolUseId}`;
}

function toolRowContent(row: ToolRowState): string {
  const tools = Object.values(row.tools).map((t) => ({
    name: t.name,
    done: t.done,
  }));
  const allDone = tools.length > 0 && tools.every((t) => t.done);
  return JSON.stringify({ tools, allDone });
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
  queenDisplayName?: string,
): ChatMessage[] {
  const streamId = event.stream_id;
  const isQueen = streamId === "queen";
  const effectiveName = isQueen ? (queenDisplayName || agentDisplayName) : agentDisplayName;
  const role: "queen" | "worker" = isQueen ? "queen" : "worker";
  const turnKey = streamId;
  const currentTurn = state.turnCounters[turnKey] ?? 0;
  const eventCreatedAt = event.timestamp
    ? new Date(event.timestamp).getTime()
    : Date.now();

  const out: ChatMessage[] = [];

  // Update state machine BEFORE the generic converter runs so regular
  // messages and synthesized tool pills use the same turn counters in
  // both live SSE handling and cold replay.
  switch (event.type) {
    case "execution_started":
      state.turnCounters[turnKey] = currentTurn + 1;
      break;
    case "llm_turn_complete":
      state.turnCounters[turnKey] = currentTurn + 1;
      break;
    case "tool_call_started": {
      if (!event.node_id) break;
      const toolName = (event.data?.tool_name as string) || "unknown";
      const toolUseId = (event.data?.tool_use_id as string) || "";
      const pillId = `tool-pill-${streamId}-${event.execution_id || "exec"}-${currentTurn}`;
      const row =
        state.toolRows[pillId] ||
        (state.toolRows[pillId] = {
          streamId,
          executionId: event.execution_id || "exec",
          tools: {},
        });
      const toolKey = toolUseId || `anonymous-${Object.keys(row.tools).length}`;
      row.tools[toolKey] = {
        name: toolName,
        done: false,
      };
      if (toolUseId) {
        state.toolUseToPill[toolLookupKey(streamId, event.execution_id, toolUseId)] = {
          msgId: pillId,
          toolKey,
          name: toolName,
        };
      }
      out.push({
        id: pillId,
        agent: effectiveName || event.node_id || "Agent",
        agentColor: "",
        content: toolRowContent(row),
        timestamp: "",
        type: "tool_status",
        role,
        thread,
        createdAt: eventCreatedAt,
        nodeId: event.node_id || undefined,
        executionId: event.execution_id || undefined,
        streamId: streamId || undefined,
      });
      break;
    }
    case "tool_call_completed": {
      if (!event.node_id) break;
      const toolUseId = (event.data?.tool_use_id as string) || "";
      const lookupKey = toolLookupKey(streamId, event.execution_id, toolUseId);
      const tracked = state.toolUseToPill[lookupKey];
      if (toolUseId) delete state.toolUseToPill[lookupKey];
      if (!tracked) break;
      const row = state.toolRows[tracked.msgId];
      if (!row) break;
      row.tools[tracked.toolKey] = {
        name: row.tools[tracked.toolKey]?.name || tracked.name,
        done: true,
      };
      out.push({
        id: tracked.msgId,
        agent: effectiveName || event.node_id || "Agent",
        agentColor: "",
        content: toolRowContent(row),
        timestamp: "",
        type: "tool_status",
        role,
        thread,
        createdAt: eventCreatedAt,
        nodeId: event.node_id || undefined,
        executionId: event.execution_id || undefined,
        streamId: streamId || undefined,
      });
      break;
    }
  }

  // Regular stateless conversion (prose, user input, system notes).
  const msg = sseEventToChatMessage(
    event,
    thread,
    effectiveName,
    state.turnCounters[turnKey] ?? 0,
  );
  if (msg) {
    if (isQueen) {
      msg.role = "queen";
      if (
        event.execution_id &&
        (event.type === "client_output_delta" || event.type === "llm_text_delta")
      ) {
        const iter = (event.data?.iteration as number | undefined) ?? 0;
        const inner = (event.data?.inner_turn as number | undefined) ?? 0;
        const iterKey = `${event.execution_id}:${iter}`;
        if (!state.queenIterText[iterKey]) {
          state.queenIterText[iterKey] = {};
        }
        state.queenIterText[iterKey][inner] = msg.content;
        const parts = state.queenIterText[iterKey];
        const sorted = Object.keys(parts)
          .map(Number)
          .sort((a, b) => a - b);
        msg.content = sorted.map((k) => parts[k]).join("\n");
        msg.id = `queen-stream-${event.execution_id}-${iter}`;
      }
    }
    out.push(msg);
  }

  return out;
}

/**
 * Replay an entire event array and return a deduplicated, chronologically
 * sorted ChatMessage list. Used by cold-restore paths so refreshed
 * sessions match the live stream exactly.
 *
 * If the events stream contains a ``colony_fork_marker`` event (emitted
 * by ``fork_session_into_colony`` after compacting the parent transcript),
 * every message produced from events PRECEDING the marker is folded into
 * a single ``inherited_block`` ChatMessage. The colony page renders that
 * block as a collapsible widget so the inherited DM history is one click
 * away without dominating the colony's own chat.
 */
export function replayEventsToMessages(
  events: AgentEvent[],
  thread: string,
  agentDisplayName: string | undefined,
  queenDisplayName?: string,
  state: ReplayState = newReplayState(),
): ChatMessage[] {
  // Upsert by id — later emissions for the same pill replace earlier ones.
  const byId = new Map<string, ChatMessage>();

  // Track the marker (if any) and which message ids belong to the
  // inherited prefix. A single fork can only happen once per session so
  // we only need to remember the first marker we encounter.
  let markerEvent: AgentEvent | null = null;
  let markerCreatedAt: number | null = null;
  const inheritedIds = new Set<string>();

  for (const evt of events) {
    if (evt.type === "colony_fork_marker") {
      if (markerEvent === null) {
        markerEvent = evt;
        markerCreatedAt = evt.timestamp
          ? new Date(evt.timestamp).getTime()
          : Date.now();
        // Snapshot every id seen so far — those are the ones to fold
        // into the inherited block.
        for (const id of byId.keys()) inheritedIds.add(id);
      }
      continue;
    }
    for (const m of replayEvent(state, evt, thread, agentDisplayName, queenDisplayName)) {
      const previous = byId.get(m.id);
      byId.set(
        m.id,
        previous ? { ...m, createdAt: previous.createdAt ?? m.createdAt } : m,
      );
    }
  }

  const all = Array.from(byId.values()).sort(
    (a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0),
  );

  if (markerEvent === null || inheritedIds.size === 0) return all;

  const inherited: ChatMessage[] = [];
  const native: ChatMessage[] = [];
  for (const msg of all) {
    if (inheritedIds.has(msg.id)) inherited.push(msg);
    else native.push(msg);
  }
  if (inherited.length === 0) return all;

  const markerData = markerEvent.data || {};
  const block: ChatMessage = {
    id: `inherited-block-${markerEvent.timestamp || "fork"}`,
    agent: "System",
    agentColor: "",
    type: "inherited_block",
    content: JSON.stringify({
      parent_session_id: markerData.parent_session_id ?? null,
      fork_time: markerData.fork_time ?? markerEvent.timestamp ?? null,
      summary_preview: markerData.summary_preview ?? "",
      inherited_message_count:
        typeof markerData.inherited_message_count === "number"
          ? markerData.inherited_message_count
          : inherited.length,
      messages: inherited,
    }),
    timestamp: markerEvent.timestamp || "",
    thread,
    // Place the block at the marker's timestamp so it sorts immediately
    // before the first native message (the marker is always written
    // AFTER the inherited content).
    createdAt: markerCreatedAt ?? inherited[inherited.length - 1].createdAt ?? 0,
  };

  return [block, ...native];
}

type QueenPhase = "independent" | "incubating" | "working" | "reviewing";
const VALID_PHASES = new Set<string>([
  "independent",
  "incubating",
  "working",
  "reviewing",
]);

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
