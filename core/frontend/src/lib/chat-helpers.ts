/**
 * Pure functions for converting SSE events into ChatMessage objects.
 * No React dependencies — just JSON in, object out.
 */

import type { ChatMessage, ImageContent } from "@/components/ChatPanel";
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
 * the colony worker id — the same identifier the Colony sidebar uses
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

    case "client_input_requested": {
      // Surface the question(s) as a queen bubble in the chat history so the
      // transcript records what was asked alongside the user's answer. The
      // input widget at the bottom of the panel still drives the actual
      // answer flow — this bubble is read-only context.
      const rawQuestions = event.data?.questions;
      if (!Array.isArray(rawQuestions) || rawQuestions.length === 0) return null;
      const prompts: string[] = [];
      for (const q of rawQuestions) {
        if (!q || typeof q !== "object") continue;
        const qo = q as Record<string, unknown>;
        const prompt =
          typeof qo.prompt === "string"
            ? qo.prompt
            : typeof qo.question === "string"
              ? (qo.question as string)
              : null;
        if (prompt) prompts.push(prompt);
      }
      if (prompts.length === 0) return null;
      const content =
        prompts.length === 1
          ? prompts[0]
          : prompts.map((p, i) => `${i + 1}. ${p}`).join("\n");
      return {
        // Stable per-request id so live + replay paths upsert the same row.
        id: `ask-user-${event.execution_id ?? ""}-${event.timestamp ?? createdAt}`,
        agent: agentDisplayName || event.node_id || "Agent",
        agentColor: "",
        content,
        timestamp: "",
        // Default to worker; the replayEvent wrapper upgrades to "queen"
        // when stream_id === "queen". Mirrors llm_text_delta's pattern.
        role: "worker",
        thread,
        createdAt,
        nodeId: event.node_id || undefined,
        executionId: event.execution_id || undefined,
        streamId: event.stream_id || undefined,
      };
    }

    case "client_input_received": {
      const userContent = (event.data?.content as string) || "";
      const imagePaths = event.data?.image_paths as string[] | undefined;
      // Internal directives the backend injects through the user-input
      // channel (e.g. the fork kickoff prompt) are tagged with this
      // marker. The queen acts on them, but they are NOT user-authored —
      // never render them as a "You" bubble.
      if (userContent.startsWith("<hive-internal>")) return null;
      // Allow image-only messages (no text but has attachments)
      if (!userContent && (!imagePaths || imagePaths.length === 0)) return null;
      // Reconstruct images from saved attachment paths.
      //
      // When a PDF is uploaded the desktop ships one base64 page image
      // per PDF page in the chat payload so the LLM can "see" the doc.
      // The backend writes every one of those alongside the original
      // PDF in the session's attachments/ directory, using a stable
      // naming scheme:
      //   1777589697032_0.pdf            ← original upload
      //   1777589697032_0_p0.png  ─┐
      //   1777589697032_0_p1.png   ├─ rendered pages, same prefix + _p<N>
      //   1777589697032_0_p7.png  ─┘
      // All of these come back in image_paths on restore. Without
      // filtering we'd render the PDF chip + N thumbnails and open the
      // image carousel. Match the `_p<digits>.<ext>` suffix pattern and
      // drop those siblings — leaves real user-uploaded images alone.
      const pageRender = /_p\d+\.[a-z0-9]+$/i;
      const filtered = imagePaths
        ? imagePaths.filter((p) => !pageRender.test(p))
        : imagePaths;
      const images: ImageContent[] | undefined =
        filtered && filtered.length > 0
          ? filtered.map((p) => {
              // Layer F2: emit canonical `hive-attachment://<rel_path>`.
              // AttachmentChip's resolveAttachmentUrl handles the basename
              // → /api/sessions/{sid}/attachment/{name} mapping at render
              // time, and tolerates both legacy ("attachments/X") and
              // current ("data/attachments/X") prefixes via split('/').pop().
              const filename = p.split("/").pop() ?? p;
              return {
                type: "image_url" as const,
                image_url: { url: `hive-attachment://${p}` },
                _fileName: filename,
              };
            })
          : undefined;
      return {
        id: `user-input-${event.timestamp}`,
        agent: "You",
        agentColor: "",
        content: userContent,
        timestamp: "",
        type: "user",
        thread,
        createdAt,
        images,
        // Carrying execution_id here lets the optimistic-message reconciler
        // distinguish server-echoed user bubbles from still-unflushed ones.
        executionId: event.execution_id || undefined,
        streamId: event.stream_id || undefined,
        // Tie this bubble to the later client_input_committed event, which
        // re-stamps createdAt to the true injection time.
        correlationId: event.correlation_id || undefined,
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
/**
 * Per-tool-call state inside a turn's pill.
 *
 * For terminal_* tools we additionally retain the arguments (from
 * tool_call_started) and result envelope (from tool_call_completed) so
 * the chat panel can render an inline command + output preview without
 * re-querying the runtime. Other tools omit these fields to keep the
 * tool_status content payload small (catalogs are pill-only).
 */
type ToolEntry = {
  name: string;
  done: boolean;
  /** opaque per-call id surfaced to the UI; used to key React rows */
  callKey?: string;
  /** ms epoch when tool_call_started fired — drives running-pill elapsed
   * counters and per-call timestamps in the expanded detail panel. */
  startedAt?: number;
  /** ms epoch when tool_call_completed fired — present iff `done`. Lets
   * the renderer compute duration without needing the result envelope
   * (terminal_* tools also have `runtime_ms` in `result`, but we want
   * a uniform timing for non-terminal pills too). */
  endedAt?: number;
  /** Set when the tool was forcibly marked done because the session
   * ended without a tool_call_completed (runtime crash, killed, or
   * not auto-resumed). The renderer treats it as a terminal "we
   * don't know what happened" state — visually muted, distinct from
   * a clean done. */
  isInterrupted?: boolean;
  /** present only for tools whose name starts with terminal_ */
  args?: unknown;
  result?: unknown;
  isError?: boolean;
};

/**
 * Names whose detail (command + output, or chart spec + file_url) we
 * surface in the chat. Other tools stay pill-only — keeping their
 * args/results out of the message content avoids ballooning the chat
 * history with tool catalogs, file blobs, etc.
 */
function shouldRetainDetail(toolName: string): boolean {
  return toolName.startsWith("terminal_") || toolName.startsWith("chart_");
}

/**
 * Per-call tracker. One per `tool_call_started` event; stays in
 * `state.toolTrackers` until either `tool_call_completed` arrives
 * (which mutates `entry.done = true` and re-emits the message) or
 * `finalizeOpenToolRows` flips it to interrupted at end of replay.
 */
type ToolTracker = {
  msgId: string;
  streamId: string;
  thread: string;
  agentName: string;
  role: "queen" | "worker";
  entry: ToolEntry;
  createdAt: number;
};

export interface ReplayState {
  turnCounters: Record<string, number>;
  /**
   * Worker streams (`worker:<uuid>`) we have already emitted a bubble anchor
   * for. A worker's bubble must exist as soon as ANY of its events lands —
   * we cannot key off one specific type, because a spawned worker never emits
   * `execution_started` (its loop announces itself with `node_loop_started`,
   * and a worker stopped while still queued only ever emits a synthesized
   * `subagent_report`). Anchoring on the first event of any type, once per
   * stream, is what keeps the bubble's `createdAt` stable.
   */
  workerAnchored: Set<string>;
  /**
   * Live trackers keyed by `(streamId, executionId, toolUseId)` for
   * matched lookups, or `anon:<msgId>` for tool calls that arrived
   * without a tool_use_id (rare but possible). Removed on
   * tool_call_completed; surviving entries at end-of-replay get
   * marked `isInterrupted` by `finalizeOpenToolRows`.
   */
  toolTrackers: Record<string, ToolTracker>;
  queenIterText: Record<string, Record<number, string>>;
  /** Parallel to `queenIterText`: the (first-seen) timestamp of each inner
   *  turn, so a merged bubble can expose a per-span time for hover tooltips
   *  on its timeline nodes. */
  queenIterTimes: Record<string, Record<number, number>>;
  /** Per-execution injection (drain) timestamps for steered/queued user
   *  messages, from `client_input_committed`, keyed by conversation seq (for
   *  idempotence). A single queen loop `iteration` can span many inner-turns;
   *  the renderer normally merges them into ONE bubble. When the user steers
   *  mid-iteration, we split that bubble into segments so the steer's reply
   *  lands in a NEW bubble that sorts AFTER the steer instead of folding into
   *  the pre-steer narration. A queen delta's segment = how many injections
   *  occurred before it (by timestamp) — order-independent, so disk-restore
   *  and live SSE assign the same bubble id. See `queenSegmentFor`. */
  queenInjections: Record<string, Map<number, number>>;
  /** Queue of `attach_file` chip URLs published per execution_id but not
   * yet attached to a queen bubble. Drained into the FIRST new queen
   * text bubble that appears after each tool_call_completed — we can't
   * just key by iteration because `tool_call_completed` events carry
   * no iteration field (defaults to 0) while the queen's response can
   * land at any iter. */
  queenPendingChips: Record<string, { url: string; filename?: string; credits?: number; generated?: boolean }[]>;
  /** Per-bubble snapshot of which chips landed on a given queen msg.id.
   * Keeps streaming-delta upserts consistent: each new COD for the
   * same bubble re-reads the already-applied chip list instead of
   * stealing more from the pending queue. */
  queenChipsAppliedByMsgId: Record<string, { url: string; filename?: string; credits?: number; generated?: boolean }[]>;
  /** Metadata for queen-generated images, keyed by output-file basename.
   * Captured from `image_generate` / `collect_result` results and matched to
   * the `attach_file` chip by filename so a generated image renders as a
   * confident "Generated image" card (vs a plain attachment) and shows the
   * credits it cost (when the proxy injected `usage.credits`). A key's
   * presence marks the file as generated even when the cost is unknown. */
  imageGenMeta: Record<string, { credits?: number }>;
  /** Dedupe keys (`<timestamp>|<seq>`) of events already processed.
   * Lets the live SSE replay path skip events that the disk
   * eventsHistory fetch or a ring-buffer resubscribe already
   * delivered. The SSE handler replays a wide event set
   * (TOOL_CALL_STARTED/COMPLETED, EXECUTION_COMPLETED, etc.) so
   * dedupe is mandatory — without it tool pills would render twice.
   * Keyed via `eventDedupeKey`; see there for why bare `seq` is unsafe. */
  seenEventKeys: Set<string>;
  /** Monotonic counter from the most recent session_snapshot we've
   * applied. Used to ignore events whose underlying publish
   * predates the snapshot but whose state is already reflected
   * in current_tool_calls / awaiting_input. Anything with
   * `seq <= snapshotSeq` is treated as historical only — dispatched
   * for transcript replay but not for "is the queen busy right now"
   * inference. */
  snapshotSeq: number;
  /** Epoch-ms of the most recent session_snapshot event. `seq` restarts
   * at 1 on every runtime run, so a low `seq <= snapshotSeq` is only
   * genuinely "historical" when the event was *also* published at or
   * before the snapshot — a fresh run's live events have low seqs too,
   * but a later timestamp. 0 until a snapshot lands. */
  snapshotAt: number;
  /** Display name of the queen that authored the CURRENT run, captured
   * from the `queen_identity_selected` event that opens each run. Used to
   * label queen bubbles with their true per-run author instead of the
   * colony's currently-linked queen — otherwise a colony that swapped
   * queens relabels every historical bubble to the current one. Undefined
   * until the first identity event; queen bubbles then fall back to the
   * page-level `queenDisplayName`. */
  queenIdentityName?: string;
  /** First-seen epoch-ms per reasoning bubble id. Streaming upserts replace
   * the message wholesale, so ordering needs the bubble's original time,
   * not the latest snapshot's. */
  reasoningStartedAt: Record<string, number>;
  /** Bubble ids whose final client_reasoning block has been applied. A
   * coalesced llm_reasoning_delta can be flushed to disk AFTER the final
   * block (tool-only turns flush at llm_turn_complete); its stale
   * tail-capped snapshot must not overwrite the full text on replay. */
  reasoningFinal: Set<string>;
}

export function newReplayState(): ReplayState {
  return {
    turnCounters: {},
    workerAnchored: new Set<string>(),
    toolTrackers: {},
    queenIterText: {},
    queenIterTimes: {},
    queenInjections: {},
    queenPendingChips: {},
    queenChipsAppliedByMsgId: {},
    imageGenMeta: {},
    seenEventKeys: new Set<string>(),
    snapshotSeq: 0,
    snapshotAt: 0,
    reasoningStartedAt: {},
    reasoningFinal: new Set<string>(),
  };
}

/**
 * Stable, run-independent dedupe key for an AgentEvent.
 *
 * `event.seq` alone is NOT unique. The runtime restarts its seq counter
 * at 1 on every new run (each run opens with a `queen_identity_selected`),
 * so a long-lived session's events.jsonl — and a long-lived SSE
 * connection — accumulate many events sharing low seq values. Keying
 * dedupe on bare `seq` makes a fresh run's events collide with an earlier
 * run's and silently drop the entire job ("latest messages swallowed").
 * Pairing `seq` with the event's own timestamp restores uniqueness
 * across runs while still matching a genuinely redelivered event — the
 * SSE ring-buffer replay re-sends the identical timestamp+seq.
 *
 * Returns null when there's no usable seq; those events fall back to the
 * id-based upsert dedupe in the message list.
 */
export function eventDedupeKey(event: AgentEvent): string | null {
  const seq = event.seq;
  if (typeof seq !== "number" || seq <= 0) return null;
  return `${event.timestamp ?? ""}|${seq}`;
}

/** Returns true when this event has already been processed in this
 * replay state. Events with no seq (legacy or synthesised on the
 * renderer) always pass through — falling back to the existing
 * id-based upsert dedupe in the message list. */
export function shouldSkipForDedupe(state: ReplayState, event: AgentEvent): boolean {
  const key = eventDedupeKey(event);
  if (key === null) return false;
  if (state.seenEventKeys.has(key)) return true;
  state.seenEventKeys.add(key);
  // Bound the set so a long-lived session doesn't grow unboundedly.
  // 10k events covers ~hours of busy queen activity; older entries
  // can never be replayed again because the server-side ring buffer
  // is also bounded.
  if (state.seenEventKeys.size > 10_000) {
    const trimmed = Array.from(state.seenEventKeys).slice(-8000);
    state.seenEventKeys.clear();
    for (const k of trimmed) state.seenEventKeys.add(k);
  }
  return false;
}

function toolLookupKey(
  streamId: string,
  executionId: string | null | undefined,
  toolUseId: string,
): string {
  return `${streamId}:${executionId || "exec"}:${toolUseId}`;
}

/**
 * Walk every tracker still in the state and mark its entry as
 * interrupted. Used at the end of disk replay so an undone tool from
 * a session that crashed/was killed without firing
 * tool_call_completed renders as terminal-but-unknown rather than
 * forever-running. Live SSE redelivery overwrites by id if the tool
 * is in fact still alive.
 */
function finalizeOpenToolRows(
  state: ReplayState,
  thread: string,
  agentDisplayName: string | undefined,
  queenDisplayName: string | undefined,
): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const tracker of Object.values(state.toolTrackers)) {
    if (tracker.entry.done) continue;
    tracker.entry.done = true;
    tracker.entry.isInterrupted = true;
    out.push(trackerToMessage(tracker, thread, agentDisplayName, queenDisplayName));
  }
  state.toolTrackers = {};
  return out;
}

/**
 * Serialize a single tool entry into the `tool_status` content shape.
 * The renderer parses `{tools, allDone}` so the array form is kept
 * even though one tool_status message now always carries exactly one
 * tool — the render-side `tool_status_group` merge concatenates
 * adjacent messages back into a multi-pill row.
 */
function entryContent(entry: ToolEntry): string {
  const out: ToolEntry = { name: entry.name, done: entry.done };
  if (entry.callKey !== undefined) out.callKey = entry.callKey;
  if (entry.startedAt !== undefined) out.startedAt = entry.startedAt;
  if (entry.endedAt !== undefined) out.endedAt = entry.endedAt;
  if (entry.isInterrupted !== undefined) out.isInterrupted = entry.isInterrupted;
  if (shouldRetainDetail(entry.name)) {
    if (entry.args !== undefined) out.args = entry.args;
    if (entry.result !== undefined) out.result = entry.result;
    if (entry.isError !== undefined) out.isError = entry.isError;
  }
  return JSON.stringify({ tools: [out], allDone: entry.done });
}

function trackerToMessage(
  tracker: ToolTracker,
  thread: string,
  agentDisplayName: string | undefined,
  queenDisplayName: string | undefined,
): ChatMessage {
  const isQueen = tracker.streamId === "queen";
  const fallbackName = isQueen
    ? queenDisplayName || agentDisplayName
    : agentDisplayName;
  return {
    id: tracker.msgId,
    agent: tracker.agentName || fallbackName || "Agent",
    agentColor: "",
    content: entryContent(tracker.entry),
    timestamp: "",
    type: "tool_status",
    role: tracker.role,
    thread: tracker.thread || thread,
    createdAt: tracker.createdAt,
    streamId: tracker.streamId || undefined,
  };
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
/** Record a steer/queue injection (drain) time from a client_input_committed
 *  event. Idempotent — keyed by conversation seq, so redelivery (disk restore
 *  + live ring buffer) doesn't double-count. */
export function recordQueenInjection(state: ReplayState, event: AgentEvent): void {
  const exec = event.execution_id;
  const cseq = event.data?.seq as number | undefined;
  if (!exec || typeof cseq !== "number") return;
  const t = event.timestamp ? new Date(event.timestamp).getTime() : 0;
  (state.queenInjections[exec] ??= new Map<number, number>()).set(cseq, t);
}

/** Segment index for a queen text delta = how many injections (steers)
 *  occurred before it, by timestamp. Pre-steer deltas → segment 0, deltas
 *  after the Nth injection → segment N. Order-independent (compares times),
 *  so disk restore and live SSE produce the same bubble id. */
function queenSegmentFor(
  state: ReplayState,
  executionId: string,
  deltaTime: number,
): number {
  const m = state.queenInjections[executionId];
  if (!m || m.size === 0) return 0;
  let seg = 0;
  for (const t of m.values()) if (t < deltaTime) seg += 1;
  return seg;
}

export function replayEvent(
  state: ReplayState,
  event: AgentEvent,
  thread: string,
  agentDisplayName: string | undefined,
  queenDisplayName?: string,
): ChatMessage[] {
  const streamId = event.stream_id;
  const isQueen = streamId === "queen";
  // Prefer the current run's own queen identity (from queen_identity_selected)
  // over the colony's page-level queen name, so bubbles authored by a
  // previously-linked queen keep that queen's name instead of relabeling to
  // whoever is linked now.
  const effectiveName = isQueen
    ? state.queenIdentityName || queenDisplayName || agentDisplayName
    : agentDisplayName;
  const role: "queen" | "worker" = isQueen ? "queen" : "worker";
  const turnKey = streamId;
  const currentTurn = state.turnCounters[turnKey] ?? 0;
  const eventCreatedAt = event.timestamp
    ? new Date(event.timestamp).getTime()
    : Date.now();

  const out: ChatMessage[] = [];

  // Record steer/queue injection boundaries; produces no message itself.
  // Subsequent queen deltas after this drain time fall into a new bubble
  // segment (see queenSegmentFor) so the steer's reply doesn't fold into the
  // pre-steer narration.
  if (event.type === "client_input_committed") {
    recordQueenInjection(state, event);
    return out;
  }

  // A run opens with queen_identity_selected naming the queen that authored
  // it. Capture that per-run identity so subsequent queen bubbles in this run
  // are labeled with their true author. Produces no bubble itself.
  if (event.type === "queen_identity_selected") {
    const name = event.data?.name;
    if (typeof name === "string" && name.trim()) {
      state.queenIdentityName = name;
    }
    return out;
  }

  // Update state machine BEFORE the generic converter runs so regular
  // messages and synthesized tool pills use the same turn counters in
  // both live SSE handling and cold replay.
  // ── Worker bubble anchor ────────────────────────────────────────────────
  // A parallel worker's bubble is seeded by a synthetic, empty-content
  // role:"worker" message rather than by its first text delta — the server no
  // longer streams a worker's chatter unless the user is watching that worker,
  // and everything the bubble displays (task, status, result, task progress)
  // comes from the workers poll. ChatPanel only opens a worker_run span on a
  // role:"worker" message, so without this anchor an unwatched worker renders
  // no bubble at all.
  //
  // Anchor on the FIRST event of any type, not on a chosen one: a spawned
  // worker never emits `execution_started` (checked against a real 80-worker
  // colony log — 62 node_loop_started, 82 subagent_report, zero
  // execution_started), and a worker stopped while still queued emits nothing
  // but a synthesized `subagent_report`. Once-per-stream keeps `createdAt`
  // stable so the bubble doesn't jump around as more of its events arrive.
  if (streamId && workerIdFromStreamId(streamId) && !state.workerAnchored.has(streamId)) {
    state.workerAnchored.add(streamId);
    out.push({
      id: `worker-anchor-${streamId}`,
      agent: agentDisplayName || "Worker",
      agentColor: "",
      content: "",
      timestamp: "",
      role: "worker",
      thread,
      createdAt: eventCreatedAt,
      nodeId: event.node_id || undefined,
      executionId: event.execution_id || undefined,
      streamId,
    });
  }

  switch (event.type) {
    case "execution_started":
      state.turnCounters[turnKey] = currentTurn + 1;
      break;
    case "llm_turn_complete": {
      state.turnCounters[turnKey] = currentTurn + 1;
      // Flush any attach_file chips still queued for this execution. The
      // normal path drains them into the NEXT queen text bubble — but the
      // turn can end without one (or the trailing text delta is dropped
      // under SSE backpressure, being non-critical), and the chips then
      // never rendered live while a refresh (full disk replay) showed
      // them: the exact "attachment invisible until refresh" asymmetry.
      // Stable id (execution-scoped) so live + replay paths dedupe.
      const leftover = event.execution_id
        ? state.queenPendingChips[event.execution_id]
        : undefined;
      if (leftover && leftover.length > 0) {
        const chips = leftover.splice(0);
        const chipMsgId = `chips-${streamId}-${event.execution_id}`;
        state.queenChipsAppliedByMsgId[chipMsgId] = chips;
        out.push({
          id: chipMsgId,
          agent: queenDisplayName || agentDisplayName || "Queen",
          agentColor: "",
          content: "",
          timestamp: "",
          thread,
          createdAt: eventCreatedAt,
          images: chips.map((c) => ({
            type: "image_url" as const,
            image_url: { url: c.url },
            _fileName: c.filename,
            _credits: c.credits,
            _generated: c.generated,
          })),
        });
      }
      break;
    }
    case "llm_reasoning_delta":
    case "client_reasoning": {
      // Live thinking feedback: a thinking model can reason for minutes
      // before its first visible character — without a bubble the session
      // looks dead the whole time. llm_reasoning_delta carries a rolling
      // tail-capped snapshot; the final client_reasoning replaces it with
      // the full consolidated block. Same id → one upserted bubble, in
      // both live SSE and disk replay.
      const rIter = (event.data?.iteration as number | undefined) ?? currentTurn;
      const rInner = (event.data?.inner_turn as number | undefined) ?? 0;
      const rText =
        event.type === "client_reasoning"
          ? (event.data?.reasoning as string) || ""
          : (event.data?.snapshot as string) || (event.data?.content as string) || "";
      if (!rText.trim()) break;
      const rMsgId = `reason-${streamId}-${event.execution_id || "exec"}-${rIter}-t${rInner}`;
      if (event.type === "client_reasoning") {
        state.reasoningFinal.add(rMsgId);
      } else if (state.reasoningFinal.has(rMsgId)) {
        break; // stale rolling snapshot arriving after the final block
      }
      const rStartedAt = state.reasoningStartedAt[rMsgId] ?? eventCreatedAt;
      state.reasoningStartedAt[rMsgId] = rStartedAt;
      out.push({
        id: rMsgId,
        agent: effectiveName || event.node_id || "Agent",
        agentColor: "",
        content: rText,
        timestamp: "",
        type: "reasoning",
        role,
        thread,
        createdAt: rStartedAt,
        nodeId: event.node_id || undefined,
        executionId: event.execution_id || undefined,
        streamId: event.stream_id || undefined,
      });
      break;
    }
    case "tool_call_started": {
      if (!event.node_id) break;
      const toolName = (event.data?.tool_name as string) || "unknown";
      const toolUseId = (event.data?.tool_use_id as string) || "";
      // Path-independent message id. tool_use_id is stamped by the LLM
      // provider and persisted with the event, so the same logical tool
      // call yields the same msgId whether it arrives via disk replay
      // (events.jsonl) or live SSE (ring-buffer resubscribe). That's
      // what dedupes tool_status messages when the user switches away
      // from a session and back. Anonymous calls (no tool_use_id, very
      // rare) fall back to a seq-based id — they won't dedupe across
      // paths but they're short-lived: finalizeOpenToolRows clears them
      // at end-of-replay.
      const msgId = toolUseId
        ? `tool-${streamId}-${event.execution_id || "exec"}-${toolUseId}`
        : `tool-${streamId}-${eventCreatedAt}-${event.seq ?? 0}`;
      const entry: ToolEntry = {
        name: toolName,
        done: false,
        callKey: toolUseId || undefined,
        startedAt: eventCreatedAt,
      };
      if (shouldRetainDetail(toolName)) {
        const toolInput = event.data?.tool_input;
        if (toolInput !== undefined) entry.args = toolInput;
      }
      const tracker: ToolTracker = {
        msgId,
        streamId,
        thread,
        agentName: effectiveName || event.node_id || "Agent",
        role,
        entry,
        createdAt: eventCreatedAt,
      };
      const trackerKey = toolUseId
        ? toolLookupKey(streamId, event.execution_id, toolUseId)
        : `anon:${msgId}`;
      state.toolTrackers[trackerKey] = tracker;
      out.push(trackerToMessage(tracker, thread, agentDisplayName, queenDisplayName));
      break;
    }
    case "tool_call_completed": {
      if (!event.node_id) break;
      const toolUseId = (event.data?.tool_use_id as string) || "";
      if (!toolUseId) break;
      const trackerKey = toolLookupKey(streamId, event.execution_id, toolUseId);
      let tracker = state.toolTrackers[trackerKey];
      if (tracker) {
        delete state.toolTrackers[trackerKey];
      } else {
        // Orphan completion: the matching tool_call_started was
        // truncated out of the event-log tail (eventsHistory only
        // returns the last N events). Synthesize a terminal pill from
        // the completion event alone so the transcript still shows the
        // tool ran with its result — silently dropping it would leave a
        // gap. Mirror image of finalizeOpenToolRows, which handles the
        // opposite truncation (started without completed).
        const toolName = (event.data?.tool_name as string) || "unknown";
        tracker = {
          msgId: `tool-${streamId}-${event.execution_id || "exec"}-${toolUseId}`,
          streamId,
          thread,
          agentName: effectiveName || event.node_id || "Agent",
          role,
          entry: {
            name: toolName,
            done: false,
            callKey: toolUseId,
            startedAt: eventCreatedAt,
          },
          createdAt: eventCreatedAt,
        };
      }
      tracker.entry.done = true;
      tracker.entry.endedAt = eventCreatedAt;
      if (shouldRetainDetail(tracker.entry.name)) {
        const rawResult = event.data?.result;
        if (rawResult !== undefined) {
          // Envelopes arrive as JSON strings; parse so the renderer
          // can pick fields cheaply, falling back to the raw string
          // for unknown shapes.
          let parsed: unknown = rawResult;
          if (typeof rawResult === "string") {
            try {
              parsed = JSON.parse(rawResult);
            } catch {
              parsed = rawResult;
            }
          }
          tracker.entry.result = parsed;
        }
        const isErr = event.data?.is_error;
        if (typeof isErr === "boolean") tracker.entry.isError = isErr;
      }
      // attach_file: harvest hive_attachment_url(s) from the result and
      // queue them under the execution_id. They'll be drained into the
      // next new queen text bubble that appears (see the COD branch).
      //
      // Note: the result string starts with attach_file's JSON summary
      // followed by the inlined text body for text-shaped attachments
      // (the MCP executor concatenates TextContent blocks). Use
      // raw_decode-style parsing — pull just the leading JSON envelope
      // and ignore the trailing text.
      // image_generate runs in the background and is collected via
      // `collect_result`, whose result carries the proxy-injected
      // `usage.credits` and the saved image path(s). (Direct image_generate
      // output is handled too, for non-async configs.) The image is shown to
      // the user via a subsequent attach_file call, so stash the per-image
      // credit cost here (keyed by output filename) and attach it to that chip.
      if (
        isQueen &&
        ((event.data?.tool_name as string) === "image_generate" ||
          (event.data?.tool_name as string) === "collect_result")
      ) {
        const rawResult = event.data?.result;
        if (typeof rawResult === "string") {
          const leading = rawResult.replace(/^\s+/, "");
          if (leading.startsWith("{")) {
            try {
              const parsed = JSON.parse(leading) as {
                images?: { path?: unknown }[];
                usage?: { credits?: unknown };
              };
              const imgs = Array.isArray(parsed.images) ? parsed.images : [];
              const credits =
                typeof parsed.usage?.credits === "number" ? parsed.usage.credits : undefined;
              if (imgs.length > 0) {
                // Record every generated image by basename (this marks it as
                // generated); attach the per-image credit cost when known.
                const per = credits !== undefined ? credits / imgs.length : undefined;
                for (const im of imgs) {
                  const p = (im as { path?: unknown }).path;
                  if (typeof p === "string") {
                    const base = p.split(/[\\/]/).pop();
                    if (base) state.imageGenMeta[base] = { credits: per };
                  }
                }
              }
            } catch {
              /* not JSON; skip */
            }
          }
        }
      }
      if (isQueen && (event.data?.tool_name as string) === "attach_file" && event.execution_id) {
        const rawResult = event.data?.result;
        if (typeof rawResult === "string") {
          const leading = rawResult.replace(/^\s+/, "");
          if (leading.startsWith("{")) {
            // Walk a brace-matched JSON envelope off the front of the
            // string. We can't use JSON.parse(leading) directly because
            // attach_file's trailing inlined file body breaks it.
            let depth = 0;
            let inStr = false;
            let escape = false;
            let end = -1;
            for (let i = 0; i < leading.length; i++) {
              const c = leading[i];
              if (escape) { escape = false; continue; }
              if (c === "\\" && inStr) { escape = true; continue; }
              if (c === "\"") { inStr = !inStr; continue; }
              if (inStr) continue;
              if (c === "{") depth++;
              else if (c === "}") {
                depth--;
                if (depth === 0) { end = i + 1; break; }
              }
            }
            if (end > 0) {
              let parsed: unknown = null;
              try { parsed = JSON.parse(leading.slice(0, end)); } catch { /* not JSON; skip */ }
              const attached = (parsed as { attached?: unknown[] })?.attached;
              if (Array.isArray(attached)) {
                if (!state.queenPendingChips[event.execution_id]) {
                  state.queenPendingChips[event.execution_id] = [];
                }
                for (const entry of attached) {
                  if (!entry || typeof entry !== "object") continue;
                  const url = (entry as { hive_attachment_url?: unknown }).hive_attachment_url;
                  const filename = (entry as { filename?: unknown }).filename;
                  if (typeof url === "string" && url.length > 0) {
                    const fname = typeof filename === "string" ? filename : undefined;
                    const genMeta = fname ? state.imageGenMeta[fname] : undefined;
                    state.queenPendingChips[event.execution_id].push({
                      url,
                      filename: fname,
                      // Mark queen-generated images so they render as a
                      // confident "Generated image" card, with the credit cost.
                      generated: !!genMeta,
                      credits: genMeta?.credits,
                    });
                  }
                }
              }
            }
          }
        }
      }
      out.push(trackerToMessage(tracker, thread, agentDisplayName, queenDisplayName));
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
        // Split a long iteration into segments at each mid-iteration steer so
        // the post-steer reply renders as its own bubble below the steer,
        // instead of folding into the bubble pinned at the iteration's start.
        const seg = queenSegmentFor(state, event.execution_id, eventCreatedAt);
        const iterKey = `${event.execution_id}:${iter}:${seg}`;
        if (!state.queenIterText[iterKey]) {
          state.queenIterText[iterKey] = {};
        }
        (state.queenIterTimes[iterKey] ??= {});
        state.queenIterText[iterKey][inner] = msg.content;
        // Keep the first-seen time for this inner turn (when the step began),
        // not the latest streaming delta's.
        state.queenIterTimes[iterKey][inner] ??= eventCreatedAt;
        const parts = state.queenIterText[iterKey];
        const sorted = Object.keys(parts)
          .map(Number)
          .sort((a, b) => a - b);
        const spans = sorted.map((k) => parts[k]);
        // Join inner-turn spans with a blank line so copied/printed/plain-text
        // forms read as paragraphs. The rendered bubble draws a wider (1.5x
        // paragraph) gap between spans via `innerTurns` (see ChatPanel).
        msg.content = spans.join("\n\n");
        if (spans.length > 1) {
          msg.innerTurns = spans;
          msg.innerTurnTimes = sorted.map((k) => state.queenIterTimes[iterKey][k]);
        }
        msg.id = `queen-stream-${event.execution_id}-${iter}-s${seg}`;
        // Chip-attach policy:
        //   1. If we've already applied chips to THIS bubble (msg.id),
        //      re-attach the same list. Keeps the chip stable across
        //      every streaming delta for the bubble.
        //   2. Otherwise, drain any chips queued for the execution
        //      (pushed by tool_call_completed for attach_file) into
        //      this bubble — it's the first new queen-text bubble to
        //      appear since the tool ran.
        const alreadyApplied = state.queenChipsAppliedByMsgId[msg.id];
        const pending = event.execution_id
          ? state.queenPendingChips[event.execution_id]
          : undefined;
        let chips = alreadyApplied;
        if (!chips && pending && pending.length > 0) {
          chips = pending.splice(0);  // drain
          state.queenChipsAppliedByMsgId[msg.id] = chips;
        }
        if (chips && chips.length > 0) {
          msg.images = chips.map((c) => ({
            type: "image_url" as const,
            image_url: { url: c.url },
            _fileName: c.filename,
            _credits: c.credits,
            _generated: c.generated,
          }));
        }
      }
    }
    out.push(msg);
  }

  return out;
}

/**
 * Combine two ChatMessage entries that share an id. tool_status pills
 * carry their accumulated tools[] in JSON content, so a naive
 * "restored overwrites prev" merge silently drops tools that one side
 * saw but the other didn't — common when the user switches back to a
 * mid-streaming session: the disk events.jsonl write lags the SSE
 * ring buffer by a few hundred ms, so disk's pill is missing the
 * just-streamed tool. This helper unions the tools by callKey,
 * preferring the more-complete entry (done > running, has-result >
 * no-result), so neither side's events are lost in the merge.
 *
 * Non-tool_status messages and unparseable content fall through to
 * "restored wins" (the existing behaviour) — they're idempotent
 * across replays and don't need merging.
 */
export function mergeChatMessages(prev: ChatMessage, restored: ChatMessage): ChatMessage {
  if (prev.type !== "tool_status" || restored.type !== "tool_status") {
    return restored;
  }
  let prevData: { tools?: ToolEntry[]; allDone?: boolean };
  let restoredData: { tools?: ToolEntry[]; allDone?: boolean };
  try {
    prevData = JSON.parse(prev.content);
    restoredData = JSON.parse(restored.content);
  } catch {
    return restored;
  }
  const byKey = new Map<string, ToolEntry>();
  const order: string[] = [];
  let anonCount = 0;
  const ingest = (t: ToolEntry) => {
    const key = t.callKey ?? `__anon-${anonCount++}`;
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, t);
      order.push(key);
      return;
    }
    // Prefer the more-complete entry: done wins over running; preserve
    // result/args/isError from whichever side captured them.
    const merged: ToolEntry = {
      name: existing.name || t.name,
      done: existing.done || t.done,
      callKey: existing.callKey ?? t.callKey,
    };
    if (t.args !== undefined) merged.args = t.args;
    else if (existing.args !== undefined) merged.args = existing.args;
    if (t.result !== undefined) merged.result = t.result;
    else if (existing.result !== undefined) merged.result = existing.result;
    if (t.isError !== undefined) merged.isError = t.isError;
    else if (existing.isError !== undefined) merged.isError = existing.isError;
    byKey.set(key, merged);
  };
  for (const t of prevData.tools ?? []) ingest(t);
  for (const t of restoredData.tools ?? []) ingest(t);
  const tools = order.map((k) => byKey.get(k)!);
  const allDone = tools.length > 0 && tools.every((t) => t.done);
  return {
    ...restored,
    content: JSON.stringify({ tools, allDone }),
    createdAt: Math.max(prev.createdAt ?? 0, restored.createdAt ?? 0),
  };
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

  // Pre-pass: record every steer/queue injection time up front so the
  // queen-bubble segmentation in the main loop is independent of event
  // ordering (a delta streamed before its drain still segments correctly).
  for (const evt of events) {
    if (evt.type === "client_input_committed") recordQueenInjection(state, evt);
  }

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
    if (evt.type === "client_input_committed") {
      // Re-stamp the user bubble (created earlier by client_input_received)
      // to its true injection time, so a revisit/replay orders it exactly
      // like the live transcript — after the in-flight turn, not at receive
      // time. Matched by correlation id. Idempotent if seen twice.
      const committedAt = evt.timestamp
        ? new Date(evt.timestamp).getTime()
        : null;
      const corr = evt.correlation_id || undefined;
      if (committedAt && corr) {
        for (const [id, m] of byId) {
          if (m.type === "user" && m.correlationId === corr) {
            byId.set(id, { ...m, createdAt: committedAt });
            break;
          }
        }
      }
      continue;
    }
    // Dedupe by seq before delegating to the per-event state machine.
    // Without this, the same event delivered via both eventsHistory
    // (disk) and the live SSE replay (ring buffer) would render its
    // tool pill twice on revisit.
    if (shouldSkipForDedupe(state, evt)) continue;
    for (const m of replayEvent(state, evt, thread, agentDisplayName, queenDisplayName)) {
      const previous = byId.get(m.id);
      byId.set(
        m.id,
        previous ? { ...m, createdAt: previous.createdAt ?? m.createdAt } : m,
      );
    }
  }

  // After processing all events, any tool row still "open" had at
  // least one call without a corresponding tool_call_completed —
  // typically because the session ended (runtime crashed/killed/not
  // auto-resumed) mid-tool. Mark those entries as interrupted so the
  // renderer can show them as a terminal "didn't finish" state
  // instead of perpetually green/running. Live SSE redelivery (if
  // the runtime is in fact still running the tool) will overwrite
  // this via upsertMessage on the same deterministic pillId.
  for (const m of finalizeOpenToolRows(state, thread, agentDisplayName, queenDisplayName)) {
    const previous = byId.get(m.id);
    byId.set(
      m.id,
      previous ? { ...m, content: m.content, createdAt: previous.createdAt ?? m.createdAt } : m,
    );
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

/** How many events each backward page fetches (infinite scroll). The render
 *  window reveals messages 30 at a time; this is the network-fetch
 *  granularity. */
export const EVENTS_PAGE_SIZE = 500;

/** Backward-paging cursor for a session's event log. Seeded from the first
 *  (newest) page and advanced as older pages are fetched on scroll-up. */
export type OlderCursor = {
  /** Byte offset of the first held event's line — pass as `beforeOffset`. */
  startOffset: number;
  /** Absolute 1-based line-index of the first held event — pass as
   *  `beforeIndex`. */
  startIndex: number;
  /** True while older events remain on disk. */
  hasMoreOlder: boolean;
};

/**
 * Replay a session's OLDER paged events into messages.
 *
 * Used by the infinite-scroll paging path: the newest page seeds the live
 * transcript, and as the user scrolls up earlier pages are fetched and
 * prepended to a separate oldest-first accumulator. This re-runs the full
 * accumulator through `replayEventsToMessages` with a FRESH `ReplayState`
 * every call — a fresh state each time is mandatory because the replay is a
 * stateful oldest→newest walk (tool spans, turn counters, chip-attach
 * draining, the fork-marker fold all cross page boundaries), so re-deriving
 * from the whole accumulator is the only way to stay correct as pages land.
 * It must NOT share state with the live SSE `replayStateRef`.
 *
 * Idempotent: the backend renumbers `seq` to the absolute file line-index, so
 * message ids (keyed on tool_use_id / execution_id+iteration) are stable
 * across re-runs and merge cleanly at the boundary with the live transcript.
 */
export function replayOlderEvents(
  olderEvents: AgentEvent[],
  thread: string,
  agentDisplayName: string | undefined,
  queenDisplayName?: string,
): ChatMessage[] {
  return replayEventsToMessages(
    olderEvents,
    thread,
    agentDisplayName,
    queenDisplayName,
    newReplayState(),
  );
}

type QueenPhase = "independent" | "colony";
const VALID_PHASES = new Set<string>(["independent", "colony"]);

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
