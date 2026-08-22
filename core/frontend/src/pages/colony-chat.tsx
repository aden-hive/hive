import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useParams, useLocation, useNavigate } from "react-router-dom";
import { Loader2, WifiOff, KeyRound, X, Component, Cloud } from "lucide-react";
import type { GraphNode, NodeStatus } from "@/components/graph-types";
import ChatPanel, { type ChatMessage, type ImageContent } from "@/components/ChatPanel";
import CredentialsModal, {
  type Credential,
  clearCredentialCache,
} from "@/components/CredentialsModal";
import AgentCredentialForm from "@/components/AgentCredentialForm";
import type { AgentCredentialFormRequest } from "@/api/credentials";
import { executionApi } from "@/api/execution";
import { workersApi } from "@/api/workers";
import { sessionsApi, colonySessionsApi } from "@/api/sessions";
import { type SseConnectionState, useMultiSSE } from "@/hooks/use-sse";
import { usePendingQueue } from "@/hooks/use-pending-queue";
import type { LiveSession, AgentEvent } from "@/api/types";
import {
  EVENTS_PAGE_SIZE,
  formatAgentDisplayName,
  newReplayState,
  replayEvent,
  replayEventsToMessages,
  replayOlderEvents,
  shouldSkipForDedupe,
  type OlderCursor,
  type ReplayState,
} from "@/lib/chat-helpers";
import {
  resolveInitialColonyPhase,
  shouldUsePrefetchedColonyRestore,
} from "@/lib/colony-session-restore";
import { cronToLabel } from "@/lib/graphUtils";
import { api, ApiError } from "@/api/client";
import { useColony } from "@/context/ColonyContext";
import { useHeaderActions } from "@/context/HeaderActionsContext";
import SessionReportAction from "@/components/SessionReportAction";
import { Tooltip } from "@/components/Tooltip";
import { useColonyWorkers } from "@/context/ColonyWorkersContext";
import { useMe, canMakeLLMCalls } from "@/lib/me";
import { useSessionUsage } from "@/context/SessionUsageContext";
import { agentSlug, getQueenForAgent, slugToColonyId } from "@/lib/colony-registry";
import { useDebugState } from "@/components/DebugStateContext";

const makeId = () => Math.random().toString(36).slice(2, 9);

function fmtLogTs(ts: string): string {
  try {
    const d = new Date(ts);
    return `[${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}]`;
  } catch {
    return "[--:--:--]";
  }
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "..." : s;
}

// ── Session restore ──────────────────────────────────────────────────────────

type SessionRestoreResult = {
  messages: ChatMessage[];
  replayState: ReplayState;
  restoredPhase: "independent" | "colony" | null;
  /** Cursor for fetching the session's older pages, or null when the session
   *  has no events / fully fit in the first page. */
  cursor: OlderCursor | null;
  /** The queen's outstanding ask_user questions, if the transcript ends on an
   *  unanswered `client_input_requested` — so a restored session re-renders the
   *  interactive question widget (not just a read-only bubble). Null otherwise. */
  pendingQuestions: { id: string; prompt: string; options?: string[] }[] | null;
};

async function restoreSessionMessages(
  sessionId: string,
  thread: string,
  agentDisplayName: string,
  queenDisplayName?: string,
): Promise<SessionRestoreResult> {
  try {
    const { events, start_offset, start_index, has_more_older } =
      await sessionsApi.eventsHistory(sessionId, { limit: EVENTS_PAGE_SIZE });
    if (events.length > 0) {
      // Walk events twice:
      //   1. Extract the trailing queen phase (unchanged logic).
      //   2. Run the full state-machine replay so tool_status pills
      //      are synthesized just like the live SSE handler does.
      // Without (2), refreshed sessions showed zero tool activity
      // because tool_call_started/completed events are ignored by
      // the stateless converter.
      let runningPhase: ChatMessage["phase"] = undefined;
      // Track the queen's outstanding ask_user questions: set on the last
      // `client_input_requested`, cleared once the user answers (a later
      // `client_input_received`/`_committed`). Whatever survives to the end is
      // still pending — used to re-render the interactive question widget.
      let pendingQuestions:
        | { id: string; prompt: string; options?: string[] }[]
        | null = null;
      for (const evt of events) {
        const p =
          evt.type === "queen_phase_changed"
            ? (evt.data?.phase as string)
            : evt.type === "node_loop_iteration"
              ? (evt.data?.phase as string | undefined)
              : undefined;
        if (p && ["independent", "colony"].includes(p)) {
          runningPhase = p as ChatMessage["phase"];
        }
        if (evt.type === "client_input_requested") {
          const qs = evt.data?.questions;
          if (Array.isArray(qs) && qs.length > 0) {
            pendingQuestions = qs
              .filter((q): q is Record<string, unknown> => !!q && typeof q === "object")
              .map((q) => ({
                id: String(q.id ?? ""),
                prompt: String(q.prompt ?? q.question ?? ""),
                options: Array.isArray(q.options) ? (q.options as string[]) : undefined,
              }))
              .filter((q) => q.prompt);
          }
        } else if (
          evt.type === "client_input_received" ||
          evt.type === "client_input_committed"
        ) {
          pendingQuestions = null;
        }
      }

      const replayState = newReplayState();
      const messages = replayEventsToMessages(
        events,
        thread,
        agentDisplayName,
        queenDisplayName,
        replayState,
      );
      // Stamp the latest phase on every queen message so the UI's
      // phase-badge rendering matches what the live path would have
      // displayed at the time of the refresh.
      if (runningPhase) {
        for (const m of messages) {
          if (m.role === "queen") m.phase = runningPhase;
        }
      }

      // Older events beyond this first page are no longer dropped — they're
      // fetched lazily as the user scrolls up (see fetchOlderPage). The cursor
      // points at the page boundary; `has_more_older` gates the indicator.
      return {
        messages,
        replayState,
        restoredPhase: runningPhase ?? null,
        cursor: {
          startOffset: start_offset,
          startIndex: start_index,
          hasMoreOlder: has_more_older,
        },
        pendingQuestions,
      };
    }
  } catch {
    // Event log not available
  }
  return {
    messages: [],
    replayState: newReplayState(),
    restoredPhase: null,
    cursor: null,
    pendingQuestions: null,
  };
}

// ── Agent backend state ──────────────────────────────────────────────────────

interface AgentState {
  sessionId: string | null;
  /** Colony directory name (e.g. ``linkedin_honeycomb_messaging``) —
   *  the value used for the colony-scoped progress + data endpoints.
   *  Comes from ``LiveSession.colony_id`` (the legacy field name; it's
   *  the on-disk directory under ``~/.hive/colonies/``). Distinct from
   *  the URL's ``colonyId`` route param, which is a display-mangled
   *  slug. Null for queen-DM sessions not bound to a colony. */
  colonyDirName: string | null;
  loading: boolean;
  ready: boolean;
  queenReady: boolean;
  error: string | null;
  displayName: string | null;
  awaitingInput: boolean;
  workerInputMessageId: string | null;
  queenPhase: "independent" | "colony";
  agentPath: string | null;
  currentRunId: string | null;
  nodeLogs: Record<string, string[]>;
  nodeActionPlans: Record<string, string>;
  subagentReports: {
    subagent_id: string;
    message: string;
    data?: Record<string, unknown>;
    timestamp: string;
  }[];
  isStreaming: boolean;
  // The agent loop's authoritative top-level state (mirrors backend
  // LoopActivity). Sole writers: the `loop_state_changed` event handler
  // and the `session_snapshot` handler — no other event touches these.
  // Backend `_set_activity` is the single source of truth.
  activity: "executing" | "awaiting_user" | "interrupted" | null;
  parkReason: string | null;
  interruptCause: string | null;
  llmSnapshots: Record<string, string>;
  pendingQuestions: { id: string; prompt: string; options?: string[] }[] | null;
  pendingQuestionSource: "queen" | null;
  contextUsage: Record<
    string,
    {
      usagePct: number;
      messageCount: number;
      estimatedTokens: number;
      maxTokens: number;
      at: number;
    }
  >;
  queenSupportsImages: boolean;
}

function defaultAgentState(): AgentState {
  return {
    sessionId: null,
    colonyDirName: null,
    loading: true,
    ready: false,
    queenReady: false,
    error: null,
    displayName: null,
    awaitingInput: false,
    workerInputMessageId: null,
    queenPhase: "independent",
    agentPath: null,
    currentRunId: null,
    nodeLogs: {},
    nodeActionPlans: {},
    subagentReports: [],
    isStreaming: false,
    activity: null,
    parkReason: null,
    interruptCause: null,
    llmSnapshots: {},
    pendingQuestions: null,
    pendingQuestionSource: null,
    contextUsage: {},
    queenSupportsImages: true,
  };
}

// ── Component ────────────────────────────────────────────────────────────────

export default function ColonyChat() {
  const { colonyId } = useParams<{ colonyId: string }>();
  const location = useLocation();
  const { colonies, queenProfiles, markVisited, refresh: refreshColonies } = useColony();
  const { setActions, setLeftActions } = useHeaderActions();
  const {
    toggleColonyWorkers,
    setTriggers: setCtxTriggers,
    setSessionId: setCtxSessionId,
    setColonyName: setCtxColonyName,
    setRequestQueenPrompt,
    workers: ctxWorkers,
  } = useColonyWorkers();
  const { me, noteCreditSpend } = useMe();
  const { addUsage } = useSessionUsage();
  // No credit/billing gate in local mode — LLM calls are always available.
  const llmReady = canMakeLLMCalls(me);

  // Route state from home page (new chat flow) or a colony-create entry point.
  // `prompt` is the queen-DM new-chat seed; `initialGoal` is set by the three
  // colony-create callers (QueenProfilePanel, Sidebar, queen-dm clone) so we
  // know the queen is about to process an auto-posted first user message and
  // should show the typing indicator immediately — no execution_started yet.
  const routeState = (location.state || {}) as {
    prompt?: string;
    agentPath?: string;
    initialGoal?: string;
  };
  const isNewChat = colonyId?.startsWith("new-") ?? false;

  // Find the colony matching this route
  const colony = colonies.find((c) => c.id === colonyId);
  const agentPath = colony?.agentPath ?? routeState.agentPath ?? "";
  const slug = agentPath ? agentSlug(agentPath) : "";
  const fallbackQueenInfo = getQueenForAgent(slug);
  // Resolve queen name from the linked queen profile, falling back to registry
  const linkedQueenProfile = colony?.queenProfileId
    ? queenProfiles.find((q) => q.id === colony.queenProfileId)
    : null;
  const queenInfo = linkedQueenProfile
    ? { name: linkedQueenProfile.name, role: linkedQueenProfile.title }
    : fallbackQueenInfo;
  const colonyName = colony?.name ?? colonyId ?? "Colony";

  // Mark colony as visited when navigating to it
  useEffect(() => {
    if (colonyId) markVisited(colonyId);
  }, [colonyId, markVisited]);

  // When the user navigates to a colony that isn't in the sidebar's
  // cached list yet (e.g. immediately after the queen's create_colony
  // tool emitted COLONY_CREATED and the user clicked the link before
  // the 30s status poll), re-fetch the colony list so agentPath
  // resolves and the session-load effect below can actually run.
  // Without this the page gets stuck at a blank loading state until
  // the user manually refreshes the browser.
  const refreshAttemptedRef = useRef(false);
  useEffect(() => {
    if (!colonyId || isNewChat) return;
    if (colony) return; // already in cache
    if (routeState.agentPath) return; // home-page new-chat flow already has the path
    if (refreshAttemptedRef.current) return; // don't thrash
    refreshAttemptedRef.current = true;
    refreshColonies();
  }, [colonyId, colony, isNewChat, routeState.agentPath, refreshColonies]);

  // ── Core state ───────────────────────────────────────────────────────────

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // Deferred (free-user) colony preview: ensures the greeting/preview runs once
  // per colony; the timer fires the paywall ~1s after the preview renders.
  const deferredHandledRef = useRef(false);
  const deferredTimerRef = useRef<number | null>(null);
  // Bumped when a free-mode colony is created for real after an in-place
  // upgrade ("I've already upgraded — refresh"). Nothing else changes during
  // that handoff (same route, same agentPath), so the load effect depends on
  // this to re-run and bind the freshly created session.
  const [freeUpgradeNonce, setFreeUpgradeNonce] = useState(0);
  // The upgrade handoff's goal, passed OUTSIDE routeState: react-router v7
  // wraps the navigate() location update in startTransition, so the sync
  // nonce bump above commits first and the load effect runs while
  // routeState.initialGoal is still the old (unset) location state — the
  // typing indicator never armed. loadSession reads this ref as the fallback.
  const freeUpgradeGoalRef = useRef<string | null>(null);
  // ── Older-page paging (infinite scroll) ──────────────────────────────────
  // The newest page seeds `messages` (and the live SSE keeps appending to it).
  // Older pages are kept STRICTLY separate from the live transcript / its
  // replay state: raw events accumulate oldest-first in `olderEventsRef`, are
  // re-replayed with a fresh state into `olderMessages`, and are concatenated
  // ahead of `messages` only at render time (see `combinedMessages`).
  const olderEventsRef = useRef<AgentEvent[]>([]);
  const olderCursorRef = useRef<OlderCursor | null>(null);
  const [olderMessages, setOlderMessages] = useState<ChatMessage[]>([]);
  // Network serialization: one older-page fetch in flight at a time.
  const olderPageInFlightRef = useRef(false);
  // Mirror of `olderCursorRef.current?.hasMoreOlder` so ChatPanel re-renders
  // when the cursor flips (refs don't trigger renders).
  const [currentSessionHasMoreOlder, setCurrentSessionHasMoreOlder] =
    useState(false);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [credentials] = useState<Credential[]>([]);
  const [agentState, setAgentState] = useState<AgentState>(defaultAgentState);

  // DebugPanel mirroring — the Ctrl+Shift+D panel reads window.__hive_debug_state
  // and the DebugState event log. queen-dm.tsx feeds both for /queen routes;
  // colony-chat feeds them here so the panel works on /colony routes too.
  const debug = useDebugState();
  const [lastEventAt, setLastEventAt] = useState<number>(() => Date.now());
  // Stream connectivity surfaced to ChatPanel's liveness pill. The colony
  // page previously passed no onConnectionState, so it could never even
  // show "Reconnecting..." while its stream was down.
  const [sseState, setSseState] = useState<SseConnectionState>("live");
  const [reminders, setReminders] = useState<
    {
      source: string;
      detail: string;
      nudgeCount: number | null;
      cap: number | null;
      at: number;
    }[]
  >([]);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [credentialAgentPath, setCredentialAgentPath] = useState<string | null>(null);
  // Secure credential form the queen popped via credentials(action="collect").
  // Set by the client_credential_form_requested SSE handler; the modal POSTs
  // the secret values straight to the store and resumes the parked queen.
  const [credentialForm, setCredentialForm] = useState<AgentCredentialFormRequest | null>(null);
  // The "run this colony on a cloud computer" (workspace VM / noVNC embed)
  // feature was cloud-only and has been removed. Colonies always run locally.
  const [dismissedBanner, setDismissedBanner] = useState<string | null>(null);

  // Colony-pivot popup state. Set by the colony_suggestion_requested
  // SSE handler when this colony's queen calls
  // task_create(new_colony=true) — the queen is parked on
  // _input_ready, the popup lets the user pick a slug + review the
  // queen-authored goal/handoff, then accept (POST /api/sessions →
  // backend lean-handoff path) or dismiss (POST dismiss-colony-pivot →
  // backend wakes the queen with an ask_user nudge).
  const [pivotPopup, setPivotPopup] = useState<{
    goal: string | null;
    handoff: string | null;
    taskCount: number | null;
  } | null>(null);
  const [pivotColonyName, setPivotColonyName] = useState("");
  const [pivotSubmitting, setPivotSubmitting] = useState(false);
  const [pivotError, setPivotError] = useState<string | null>(null);
  const navigate = useNavigate();

  // Workspace heartbeat used to live here as a per-page setInterval —
  // it now runs in the main process (workspace-heartbeat.ts) for the
  // whole signed-in session, so navigating between colonies no longer
  // drops the heartbeat and lets the e2b sandbox auto-pause at its
  // 1h timeout. The renderer only observes state now.

  // ── Header actions (Colony, Browser) ────────────────────────────────────
  // The "Data" link moved into the Colony panel's Data tab (its natural
  // home), removing the top-right button.
  useEffect(() => {
    setActions(
      <>
        {agentState.sessionId && (
          <Tooltip label="Colony panel">
            <button
              onClick={() => toggleColonyWorkers()}
              className="w-7 h-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors flex-shrink-0"
              aria-label="Show or hide the colony panel"
            >
              <Component className="w-4 h-4" />
            </button>
          </Tooltip>
        )}
        {agentState.sessionId && <SessionReportAction sessionId={agentState.sessionId} />}
      </>,
    );
    return () => setActions(null);
  }, [agentState.sessionId, setActions, toggleColonyWorkers]);

  // Refs for SSE callback stability
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const agentStateRef = useRef(agentState);
  agentStateRef.current = agentState;

  const replayStateRef = useRef(newReplayState());
  const queenPhaseRef = useRef<string>("independent");
  // Flipped true by the auto-flush path; consumed by the next empty-prompt
  // client_input_requested so we don't flicker the typing bubble off while
  // the queen is about to resume on the flushed input.
  const queenAboutToResumeRef = useRef(false);
  // Question bubble for an ask_user that's actively awaiting an answer.
  // Stashed instead of pushed into messages so the user only sees ONE copy
  // of the question (the popup widget) while answering. Committed to the
  // transcript on client_input_received so it lands above the user's reply.
  const pendingAskUserBubbleRef = useRef<ChatMessage | null>(null);
  const suppressIntroRef = useRef(false);
  const loadingRef = useRef(false);
  // Monotonic load token. Every loadSession() invocation claims the next
  // token; a switch fires a fresh load which claims a higher one. Any load
  // that finishes with a stale token (a slower in-flight load from the
  // colony we just left) drops its results instead of binding the wrong
  // colony's session/messages under the current URL. Without this, a fast
  // A→B switch could let A's loadSession resolve last and publish A's
  // sessionId/colonyName to ColonyPanel while the user is on B — the Data
  // tab then queries colony B for one of A's tables → "table X doesn't exist".
  const loadSeqRef = useRef(0);

  // ── Helpers ──────────────────────────────────────────────────────────────

  const updateState = useCallback((patch: Partial<AgentState>) => {
    setAgentState((prev) => ({ ...prev, ...patch }));
  }, []);

  const upsertMessage = useCallback(
    (chatMsg: ChatMessage, options?: { reconcileOptimisticUser?: boolean }) => {
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === chatMsg.id);
        if (idx >= 0) {
          return prev.map((m, i) =>
            i === idx ? { ...chatMsg, createdAt: m.createdAt ?? chatMsg.createdAt } : m,
          );
        }
        if (options?.reconcileOptimisticUser && chatMsg.type === "user" && prev.length > 0) {
          // Optimistic user bubbles have no executionId; server echoes do.
          // Match the oldest unreconciled optimistic with the same content —
          // that's the FIFO-correct pick for both auto-flush and Steer.
          // Fall back to the optimistic's hidden _reconcileContent (set when
          // a PDF/CSV is attached and the visible content is the short
          // display name). Otherwise the server's full-extracted-text echo
          // never matches and we end up with two duplicate user bubbles.
          const idx = prev.findIndex(
            (m) =>
              m.type === "user" &&
              !m.executionId &&
              (m.content === chatMsg.content ||
                (m._reconcileContent !== undefined &&
                  m._reconcileContent === chatMsg.content)),
          );
          if (idx !== -1) {
            return prev.map((m, i) =>
              i === idx
                ? {
                    ...m,
                    id: chatMsg.id,
                    executionId: chatMsg.executionId,
                    // Adopt the correlation id so the upcoming
                    // client_input_committed event can find and re-stamp this
                    // bubble to its true injection time.
                    correlationId: chatMsg.correlationId ?? m.correlationId,
                  }
                : m,
            );
          }
        }
        // Insert in sorted position by createdAt so tool pills and queen
        // messages interleave correctly when multiple arrive out of order.
        const ts = chatMsg.createdAt ?? Date.now();
        let insertIdx = prev.length - 1;
        while (insertIdx >= 0 && (prev[insertIdx].createdAt ?? 0) > ts) {
          insertIdx--;
        }
        if (insertIdx === -1 || insertIdx === prev.length - 1) {
          return [...prev, chatMsg];
        }
        const next = [...prev];
        next.splice(insertIdx + 1, 0, chatMsg);
        return next;
      });
    },
    [],
  );

  // Fetch the current session's next older page (scroll-up infinite scroll).
  // Prepends the raw events to `olderEventsRef` (oldest-first) and re-replays
  // the whole accumulator with a fresh state — never touching the live
  // `replayStateRef`/`messages`. Serialized by `olderPageInFlightRef`.
  const fetchOlderPage = useCallback(async () => {
    const sessionId = agentState.sessionId;
    const cursor = olderCursorRef.current;
    if (!sessionId || !cursor?.hasMoreOlder || olderPageInFlightRef.current)
      return;
    olderPageInFlightRef.current = true;
    try {
      const res = await sessionsApi.eventsHistory(sessionId, {
        limit: EVENTS_PAGE_SIZE,
        beforeOffset: cursor.startOffset,
        beforeIndex: cursor.startIndex,
      });
      if (res.events.length > 0) {
        olderEventsRef.current = [...res.events, ...olderEventsRef.current];
        const displayName =
          agentState.displayName ?? formatAgentDisplayName(agentPath);
        setOlderMessages(
          replayOlderEvents(
            olderEventsRef.current,
            agentPath,
            displayName,
            queenInfo.name,
          ),
        );
      }
      olderCursorRef.current = {
        startOffset: res.start_offset,
        startIndex: res.start_index,
        hasMoreOlder: res.has_more_older,
      };
      setCurrentSessionHasMoreOlder(res.has_more_older);
    } catch {
      // Leave the cursor as-is; a later scroll retries.
    } finally {
      olderPageInFlightRef.current = false;
    }
  }, [agentState.sessionId, agentState.displayName, agentPath, queenInfo.name]);

  // Concatenate older paged messages AHEAD of the live transcript. The live
  // message wins at the boundary (it has the freshest tool-pill state), so
  // drop any older message whose id already appears live. ChatPanel's
  // createdAt sort is the final arbiter; older events sort strictly earlier.
  const combinedMessages = useMemo(() => {
    if (olderMessages.length === 0) return messages;
    const liveIds = new Set(messages.map((m) => m.id));
    return [...olderMessages.filter((m) => !liveIds.has(m.id)), ...messages];
  }, [olderMessages, messages]);

  const updateGraphNodeStatus = useCallback(
    (nodeId: string, status: NodeStatus, extra?: Partial<GraphNode>) => {
      setGraphNodes((prev) =>
        prev.map((n) => (n.id === nodeId ? { ...n, status, ...extra } : n)),
      );
    },
    [],
  );

  const markAllNodesAs = useCallback(
    (fromStatuses: NodeStatus[], toStatus: NodeStatus) => {
      setGraphNodes((prev) =>
        prev.map((n) => (fromStatuses.includes(n.status) ? { ...n, status: toStatus } : n)),
      );
    },
    [],
  );

  const appendNodeLog = useCallback((nodeId: string, line: string) => {
    setAgentState((prev) => ({
      ...prev,
      nodeLogs: {
        ...prev.nodeLogs,
        [nodeId]: [...(prev.nodeLogs[nodeId] || []), line].slice(-200),
      },
    }));
  }, []);

  // Reset dismissed banner when the error clears
  useEffect(() => {
    if (!agentState.error) setDismissedBanner(null);
  }, [agentState.error]);

  // ── Session loading ────────────────────────────────────────────────────

  const loadSession = useCallback(async () => {
    if (loadingRef.current) return;
    // Claim a load token; a later load (e.g. after a colony switch) bumps
    // this, and any state-applying write below is gated on the token still
    // being current so a stale in-flight load can't clobber the new colony.
    const token = ++loadSeqRef.current;
    const isStale = () => token !== loadSeqRef.current;
    // For new chats without an agent, create a queen-only session
    if (!agentPath && isNewChat) {
      loadingRef.current = true;
      updateState({ loading: true, error: null, ready: false, sessionId: null });
      try {
        const session = await sessionsApi.create({
          colonyGoal: routeState.prompt || undefined,
        });
        const hasInitialPrompt = Boolean(routeState.prompt);
        if (isStale()) return;
        updateState({
          sessionId: session.session_id,
          displayName: "New Chat",
          queenPhase: "independent",
          loading: false,
          ready: true,
          // Backend auto-posts the prompt as the first user message; arm
          // isStreaming so the typing/stop UI shows until the first event
          // lands. Mirrors queen-dm convention.
          isStreaming: hasInitialPrompt,
        });
      } catch (err: unknown) {
        updateState({ loading: false, error: String(err) });
      } finally {
        loadingRef.current = false;
      }
      return;
    }
    if (!agentPath) {
      // This run is the latest (the token was just bumped) and it is
      // exiting without owning the load — clear any `loading: true` a
      // superseded run left behind, or the "Connecting to agent..."
      // overlay stays up forever with `ready: false` silently gating
      // every send.
      updateState({ loading: false });
      return;
    }
    loadingRef.current = true;
    updateState({ loading: true, error: null, ready: false, sessionId: null });

    try {
      let liveSession: LiveSession | undefined;
      let isResumedSession = false;
      let coldRestoreId: string | undefined;
      let prefetchedRestore: SessionRestoreResult | null = null;

      // Check for existing live session for this agent.
      //
      // IMPORTANT: GET /sessions (bare, no id) doesn't match either
      // routing rule in main/remote-runtime.ts:pathTargetsRemote, so it
      // ALWAYS hits the local runtime. If the user previously chatted
      // this colony locally (before pushing it to the workspace VM),
      // that local session is still listed here — and we'd bind to it
      // forever, sending all subsequent chat to local even though the
      // colony lives on the VM now.
      //
      // Colonies always run locally now (cloud "pushed colony" removed).
      {
        try {
          const { sessions: allLive } = await sessionsApi.list();
          const existing = allLive.find((s) => s.agent_path.endsWith(agentSlug(agentPath)));
          if (existing) {
            liveSession = existing;
            isResumedSession = true;
          }
        } catch {
          // proceed
        }
      }

      // Check cold history if no live session.
      //
      // Two flows here because colonies and queen DMs use different
      // storage trees:
      //
      //   colony click  → /api/colonies/{name}/sessions   (canonical colony tree)
      //   queen-DM new  → /api/sessions/history           (queen DM history)
      //
      // The old code used a single ``endsWith(agentSlug)`` match against
      // queen DM history for both, which silently missed colony sessions
      // (they live under ``colonies/<c>/queens/<q>/sessions/`` and are
      // intentionally filtered out of queen DM history). Clicking a
      // colony then always created a fresh session instead of resuming.
      const isColonyClick = Boolean(colony?.id && colony?.agentPath);
      if (!liveSession) {
        if (isColonyClick) {
          try {
            const colonyDiskName = agentSlug(agentPath);
            const { sessions } = await colonySessionsApi.list(colonyDiskName);
            // list_colony_sessions sorts newest-first; pick the first
            // session that actually has messages.
            const newest = sessions.find((s) => s.has_messages);
            if (newest) coldRestoreId = newest.session_id;
          } catch {
            // proceed
          }
        } else {
          try {
            const { sessions: allHistory } = await sessionsApi.history();
            const coldMatch = allHistory.find(
              (s) => s.agent_path?.endsWith(agentSlug(agentPath)) && s.has_messages,
            );
            if (coldMatch) coldRestoreId = coldMatch.session_id;
          } catch {
            // proceed
          }
        }
      }

      let restoredPhase: "independent" | "colony" | null = null;

      if (!liveSession) {
        if (coldRestoreId) {
          const displayName = formatAgentDisplayName(agentPath);
          prefetchedRestore = await restoreSessionMessages(
            coldRestoreId,
            agentPath,
            displayName,
            queenInfo.name,
          );
        }

        if (coldRestoreId || (prefetchedRestore?.messages.length ?? 0) > 0) {
          suppressIntroRef.current = true;
        }

        // Free user (no credits): render the colony READ-ONLY. Show the saved
        // transcript (already restored above) but never create a session or boot
        // the queen — zero compute, no 402. `sessionId` is the on-disk session so
        // the workers/data panel can read (tasks + leads) too; sending is
        // intercepted in handleSend and pops the paywall.
        if (!llmReady) {
          if (isStale()) return;
          if (prefetchedRestore && prefetchedRestore.messages.length > 0) {
            if (prefetchedRestore.replayState) {
              replayStateRef.current = prefetchedRestore.replayState;
            }
            olderCursorRef.current = prefetchedRestore.cursor;
            setCurrentSessionHasMoreOlder(prefetchedRestore.cursor?.hasMoreOlder ?? false);
            const msgs = [...prefetchedRestore.messages].sort(
              (a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0),
            );
            setMessages(msgs);
            queenPhaseRef.current = prefetchedRestore.restoredPhase ?? "colony";
            updateState({
              sessionId: coldRestoreId,
              colonyDirName: agentSlug(agentPath),
              displayName: formatAgentDisplayName(agentPath),
              queenPhase: prefetchedRestore.restoredPhase ?? "colony",
              ready: true,
              loading: false,
              queenReady: true,
              // Re-render the queen's unanswered ask_user widget so the user can
              // answer it — the answer routes through handleSend and pops the
              // paywall (the free-user conversion hook). `awaitingInput` gates
              // whether the widget is shown (see the ChatPanel props), so it must
              // be set alongside the questions.
              awaitingInput: !!prefetchedRestore.pendingQuestions,
              pendingQuestions: prefetchedRestore.pendingQuestions,
              pendingQuestionSource: prefetchedRestore.pendingQuestions
                ? "queen"
                : null,
            });
          } else {
            // No saved session on disk — nothing to show; render idle.
            updateState({ loading: false, ready: true, queenReady: true });
          }
          return;
        }

        // Create new session (pass coldRestoreId for resume).
        // ``agentPath`` here is the colony slug — pass it as colony_id.
        liveSession = await sessionsApi.create({
          colonyId: agentSlug(agentPath),
          queenResumeFrom: coldRestoreId ?? undefined,
        });
      }

      const session = liveSession!;
      const displayName = formatAgentDisplayName(session.colony_id || agentPath);
      let restoredMessages: ChatMessage[] = [];
      let restoredReplayState: ReplayState | null = null;
      let restoredCursor: OlderCursor | null = null;
      const reusePrefetchedRestore = shouldUsePrefetchedColonyRestore(
        coldRestoreId,
        session.session_id,
      );

      // Restore messages for live resume
      if (isResumedSession) {
        const restored = await restoreSessionMessages(
          session.session_id,
          agentPath,
          displayName,
          queenInfo.name,
        );
        if (restored.messages.length > 0) {
          restoredMessages = restored.messages;
        }
        restoredReplayState = restored.replayState;
        restoredPhase = restored.restoredPhase;
        restoredCursor = restored.cursor;
      } else if (prefetchedRestore) {
        if (reusePrefetchedRestore) {
          restoredMessages = prefetchedRestore.messages;
          restoredReplayState = prefetchedRestore.replayState;
          restoredPhase = prefetchedRestore.restoredPhase;
          restoredCursor = prefetchedRestore.cursor;
        } else {
          // The backend corrected the resume target to the colony's forked
          // session. Reload from that session so the first paint doesn't show
          // the source queen DM or its stale independent phase.
          const restored = await restoreSessionMessages(
            session.session_id,
            agentPath,
            displayName,
            queenInfo.name,
          );
          restoredMessages = restored.messages;
          restoredReplayState = restored.replayState;
          restoredPhase = restored.restoredPhase;
          restoredCursor = restored.cursor;
        }
      }

      // All awaits are done; if a newer load superseded us during them,
      // drop these results rather than binding a stale colony's session.
      if (isStale()) return;

      if (restoredReplayState) {
        replayStateRef.current = restoredReplayState;
      }

      // Seed the older-page cursor from the restored (newest) page so
      // scroll-up can fetch progressively older pages.
      olderCursorRef.current = restoredCursor;
      setCurrentSessionHasMoreOlder(restoredCursor?.hasMoreOlder ?? false);

      if (restoredMessages.length > 0) {
        restoredMessages.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
        setMessages(restoredMessages);
      }

      const initialPhase = resolveInitialColonyPhase({
        prefetchedSessionId: coldRestoreId,
        resolvedSessionId: session.session_id,
        prefetchedPhase: restoredPhase,
        serverPhase: session.queen_phase,
        hasWorker: session.has_worker,
      });
      queenPhaseRef.current = initialPhase;

      const hasRestoredContent = isResumedSession || !!coldRestoreId;
      if (!hasRestoredContent) suppressIntroRef.current = false;

      // When this page was opened by a colony-create caller that supplied a
      // goal, the backend auto-posts that goal as the first user message and
      // the queen will start processing it. Flip the typing flag optimistically
      // so the bubble shows during the gap before her first llm_text_delta
      // streams in. The SSE replay will flip it off naturally if the queen has
      // already parked (`client_input_requested`). We previously gated this on
      // "no queen message in restore," but by the time loadSession fetches
      // eventsHistory the queen has often already emitted a partial llm_text_delta
      // — which the gate misread as "queen done" and suppressed the indicator
      // for the entire pre-stream wait.
      const showInitialTyping = Boolean(
        routeState.initialGoal || freeUpgradeGoalRef.current,
      );
      freeUpgradeGoalRef.current = null;
      updateState({
        sessionId: session.session_id,
        colonyDirName: session.colony_id,
        displayName,
        queenPhase: initialPhase,
        queenSupportsImages: session.queen_supports_images !== false,
        ready: true,
        loading: false,
        queenReady: hasRestoredContent,
        isStreaming: showInitialTyping,
      });
    } catch (err: unknown) {
      // A stale load's failure must not surface on the colony we switched to.
      if (isStale()) return;
      if (err instanceof ApiError && err.status === 424) {
        const errBody = err.body as Record<string, unknown>;
        const credPath = (errBody.agent_path as string) || null;
        if (credPath) setCredentialAgentPath(credPath);
        updateState({ loading: false, error: "credentials_required" });
        setCredentialsOpen(true);
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        updateState({ error: msg, loading: false });
      }
    } finally {
      loadingRef.current = false;
    }
  }, [agentPath, isNewChat, routeState.prompt, routeState.initialGoal, updateState]);

  // Load session on mount or when agent path changes.
  //
  // Also re-runs when this colony's pushed-status flips: if the user is
  // mid-chat on a local session and then pushes the colony to the VM,
  // the existing local session can't migrate — we need to drop it and
  // bind to a fresh remote session. The bootstrap below already does
  // that correctly once it re-runs (it skips the local-only sessions
  // list lookup and creates a new session via POST which routes to
  // remote via main/ipc.ts:bodyMentionsPushedColony).
  // Cloud "pushed colony" workspaces were removed — every colony is local.
  const colonyOnRemote = false;
  useEffect(() => {
    if (!(agentPath || isNewChat)) return;
    // Reset state for the new colony, then boot it.
    setMessages([]);
    // Drop the previous session's older-page accumulator/cursor so a new
    // session never renders the old session's history above its transcript.
    olderEventsRef.current = [];
    setOlderMessages([]);
    olderCursorRef.current = null;
    olderPageInFlightRef.current = false;
    setCurrentSessionHasMoreOlder(false);
    setGraphNodes([]);
    setAgentState(defaultAgentState());
    replayStateRef.current = newReplayState();
    queenPhaseRef.current = "independent";
    suppressIntroRef.current = false;
    loadingRef.current = false;
    loadSession();
  }, [agentPath, isNewChat, colonyOnRemote, llmReady, freeUpgradeNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  // Clear per-colony modal prompts whenever the colony route changes —
  // independent of the session-load gating above (which early-returns for
  // uncached / not-yet-ready / free-mode colonies). Without this, colony A's
  // pivot or credential prompt stays open after a switch and
  // confirming it would act on colony B's session. Deliberately does NOT touch
  // messages/agentState so free-mode preview colonies (owned by the free-mode
  // effect) aren't wiped.
  useEffect(() => {
    setPivotPopup(null);
    setPivotColonyName("");
    setPivotError(null);
    setPivotSubmitting(false);
    setCredentialForm(null);
    setCredentialsOpen(false);
    setCredentialAgentPath(null);
  }, [colonyId]);


  const handleSSEEvent = useCallback(
    (_agentType: string, event: AgentEvent) => {
      const streamId = event.stream_id;
      const isQueen = streamId === "queen";
      const suppressQueenMessages = isQueen && suppressIntroRef.current;
      const state = agentStateRef.current;
      const agentDisplayName = state.displayName;
      const ts = fmtLogTs(event.timestamp);
      const eventCreatedAt = event.timestamp
        ? new Date(event.timestamp).getTime()
        : Date.now();

      // Feed the Ctrl+Shift+D DebugPanel: event log + live "last event" age.
      debug.pushEvent(event);
      setLastEventAt(Date.now());

      // Exactly-once message replay. `restoreSessionMessages` populated
      // `replayStateRef.current.seenEventKeys` with every event applied
      // from the disk eventsHistory restore; the live SSE re-delivers the
      // ring-buffer tail, which overlaps that restore. `shouldSkipForDedupe`
      // keys on `<timestamp>|<seq>` — exact and type-independent, and
      // unlike bare `seq` it survives the runtime restarting its seq
      // counter at 1 on every new run. When an event was already applied
      // we suppress its message emission (the rest of the handler still
      // runs so graph / typing state stays live). Legacy events without a
      // `seq` fall through to the message list's id-based upsert, as before.
      const alreadyApplied = shouldSkipForDedupe(replayStateRef.current, event);

      const shouldMarkQueenReady = isQueen && !state.queenReady;
      const emittedMessages = alreadyApplied
        ? []
        : replayEvent(
            replayStateRef.current,
            event,
            agentPath,
            agentDisplayName || undefined,
            queenInfo.name,
          );

      // A worker's bubble anchor is emitted on that worker's FIRST event of
      // ANY type — in practice `node_loop_started`. The switch below only
      // upserts `emittedMessages` inside its text-delta and tool-call cases,
      // so without this the anchor is computed and then dropped on the floor,
      // and an unwatched worker (whose chatter the server no longer streams)
      // renders no bubble at all until a reload rebuilds it from disk.
      //
      // Upserting by id is idempotent, so it is harmless that the cases below
      // may also upsert this same message when the worker's first event
      // happens to be a delta or a tool call.
      for (const msg of emittedMessages) {
        if (msg.id.startsWith("worker-anchor-")) upsertMessage(msg);
      }

      switch (event.type) {
        case "execution_started":
          if (isQueen) {
            // loop_state_changed drives `activity`; this handler only marks
            // the queen as ready when appropriate.
            if (shouldMarkQueenReady) {
              updateState({ queenReady: true });
            }
          } else {
            const incomingRunId = event.run_id || null;
            const prevRunId = state.currentRunId;
            if (incomingRunId && incomingRunId !== prevRunId) {
              upsertMessage({
                id: `run-divider-${incomingRunId}`,
                agent: "",
                agentColor: "",
                content: prevRunId ? "New Run" : "Run Started",
                timestamp: ts,
                type: "run_divider",
                role: "worker",
                thread: agentPath,
                createdAt: eventCreatedAt,
              });
            }
            updateState({
              awaitingInput: false,
              currentRunId: incomingRunId,
              nodeLogs: {},
              subagentReports: [],
              llmSnapshots: {},
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
            markAllNodesAs(["running", "looping", "complete", "error"], "pending");
          }
          break;

        case "execution_completed":
          if (isQueen) {
            suppressIntroRef.current = false;
            // loop_state_changed will flip activity to awaiting_user / interrupted
            // and clear isStreaming; this handler keeps no derived state.
          } else {
            updateState({
              isStreaming: false,
              awaitingInput: false,
              workerInputMessageId: null,
              llmSnapshots: {},
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
            markAllNodesAs(["running", "looping"], "complete");
          }
          break;

        case "llm_turn_complete":
          // Queen AND worker turns bill credits, so count every stream —
          // but only genuinely live events. `alreadyApplied` events are the
          // ring-buffer tail re-delivered over SSE after the disk restore
          // already covered them; counting those would double-spend the
          // optimistic balance on every colony revisit.
          if (event.data && !alreadyApplied) {
            const d = event.data;
            const rawCredits = d.credits;
            const credits = typeof rawCredits === "number" ? rawCredits : null;
            addUsage({
              input: (d.input_tokens as number) || 0,
              output: (d.output_tokens as number) || 0,
              cached: (d.cached_tokens as number) || 0,
              cacheCreated: (d.cache_creation_tokens as number) || 0,
              costUsd: (d.cost_usd as number) || 0,
              credits,
              requests: 1,
            });
            if (credits !== null) noteCreditSpend(credits);
          }
          // Flush one queued message per queen LLM-turn boundary. Workers'
          // LLM turns don't drain the queen queue. execution_completed
          // fires only at session shutdown (the queen's loop parks in
          // _await_user_input between turns), so this is the real "turn
          // ended" signal. Mid-tool-call boundaries count too.
          // Skip for cancelled turns: handleKillColony already drained
          // one queued message synchronously, so flushing here would
          // skip ahead by two on each user-triggered stop.
          if (isQueen && event.data?.stop_reason !== "cancelled") {
            flushNextPendingRef.current();
          }
          break;

        case "execution_paused":
        case "execution_failed":
        case "client_output_delta":
        case "client_input_received":
        case "client_input_requested":
        // Live thinking bubble — must upsert live, not only on disk replay.
        case "llm_reasoning_delta":
        case "client_reasoning":
        case "llm_text_delta": {
          // Defer the queen's ask_user bubble so it doesn't render alongside
          // the popup widget. Stash on request, commit on receive — see
          // pendingAskUserBubbleRef declaration above for rationale.
          let stashedAskUserBubble: ChatMessage | null = null;
          if (
            event.type === "client_input_requested" &&
            isQueen &&
            emittedMessages.length > 0
          ) {
            const rawQuestions = event.data?.questions;
            if (Array.isArray(rawQuestions) && rawQuestions.length > 0) {
              stashedAskUserBubble = emittedMessages[0];
              pendingAskUserBubbleRef.current = stashedAskUserBubble;
            }
          }
          if (
            event.type === "client_input_received" &&
            pendingAskUserBubbleRef.current &&
            !suppressQueenMessages
          ) {
            // Commit the stashed bubble first; createdAt predates this
            // event so timestamp-ordered insert places it above the answer.
            upsertMessage(pendingAskUserBubbleRef.current);
            pendingAskUserBubbleRef.current = null;
          }
          if (!suppressQueenMessages) {
            for (const msg of emittedMessages) {
              if (msg === stashedAskUserBubble) continue;
              if (isQueen) {
                msg.phase = queenPhaseRef.current as ChatMessage["phase"];
              }
              upsertMessage(msg, {
                reconcileOptimisticUser: event.type === "client_input_received",
              });
            }
          }

          if (
            isQueen &&
            (event.type === "llm_text_delta" ||
              event.type === "client_output_delta" ||
              event.type === "llm_reasoning_delta" ||
              event.type === "client_reasoning")
          ) {
            // isStreaming narrow contract (matches queen-dm): true while the
            // QUEEN is emitting text tokens. Gated on isQueen because workers
            // publish llm_text_delta on this same colony stream — without the
            // guard a busy worker (queen idle/parked) would light the queen's
            // typing indicator and busy/queue gate. Other UI states derive
            // from `activity` via loop_state_changed / session_snapshot.
            updateState({ isStreaming: true });
          }

          if (event.type === "llm_text_delta" && !isQueen && event.node_id) {
            const snapshot = (event.data?.snapshot as string) || "";
            if (snapshot) {
              setAgentState((prev) => ({
                ...prev,
                llmSnapshots: { ...prev.llmSnapshots, [event.node_id!]: snapshot },
              }));
            }
          }

          if (event.type === "client_input_requested") {
            const rawQuestions = event.data?.questions;
            const questions = Array.isArray(rawQuestions)
              ? (rawQuestions as { id: string; prompt: string; options?: string[] }[])
              : null;
            if (isQueen) {
              // An empty-prompt client_input_requested means the queen parked
              // in auto-wait. If we just auto-flushed a queued message, our
              // inject will unblock her in a moment — skip flipping the
              // awaiting/streaming flags off so the indicator doesn't flicker.
              if (queenAboutToResumeRef.current && !questions) {
                queenAboutToResumeRef.current = false;
              } else {
                const pr = (event.data?.park_reason as string | undefined) ?? null;
                updateState({
                  awaitingInput: true,
                  isStreaming: false,
                  parkReason: pr,
                  pendingQuestions: questions,
                  pendingQuestionSource: "queen",
                });
              }
            }
          }

          if (event.type === "execution_paused") {
            updateState({
              isStreaming: false,
              awaitingInput: false,
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
            if (!isQueen) {
              markAllNodesAs(["running", "looping"], "pending");
            }
          }

          if (event.type === "execution_failed") {
            updateState({
              isStreaming: false,
              awaitingInput: false,
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
            if (!isQueen) {
              if (event.node_id) {
                updateGraphNodeStatus(event.node_id, "error");
                const errMsg = (event.data?.error as string) || "unknown error";
                appendNodeLog(event.node_id, `${ts} ERROR Execution failed: ${errMsg}`);
              }
              markAllNodesAs(["running", "looping"], "pending");
            }
          }
          break;
        }

        case "client_input_committed": {
          // The message was just drained into the conversation; this event's
          // timestamp is the true injection moment (after the in-flight turn
          // that was streaming when it arrived). Re-stamp the matching user
          // bubble by correlation id so it sorts at its real position instead
          // of at receive time. Mirrors queen-dm.tsx; the shared replay path
          // (replayEventsToMessages) covers cold restore. Idempotent.
          const committedAt = event.timestamp
            ? new Date(event.timestamp).getTime()
            : 0;
          const corr = event.correlation_id || undefined;
          if (committedAt && corr) {
            setMessages((prev) =>
              prev.map((m) =>
                m.type === "user" && m.correlationId === corr
                  ? { ...m, createdAt: committedAt }
                  : m,
              ),
            );
          }
          break;
        }

        case "node_loop_started":
          // No isStreaming / typing writes here — loop_state_changed owns
          // "is the agent in flight". node_loop_started carries graph/log
          // information only.
          if (!isQueen && event.node_id) {
            const existing = graphNodes.find((n) => n.id === event.node_id);
            const isRevisit = existing?.status === "complete";
            updateGraphNodeStatus(event.node_id, isRevisit ? "looping" : "running", {
              maxIterations: (event.data?.max_iterations as number) ?? undefined,
            });
            appendNodeLog(event.node_id, `${ts} INFO  Node started`);
          }
          break;

        case "node_loop_iteration":
          // No isStreaming / typing writes here — loop_state_changed announces
          // the loop's authoritative state. This handler only clears the
          // awaiting-input scaffolding (questions / source) that ride
          // outside the activity state machine.
          updateState({
            awaitingInput: false,
            pendingQuestions: null,
            pendingQuestionSource: null,
          });
          if (!isQueen && event.node_id) {
            const pendingText = state.llmSnapshots[event.node_id];
            if (pendingText?.trim()) {
              appendNodeLog(event.node_id, `${ts} INFO  LLM: ${truncate(pendingText.trim(), 300)}`);
              setAgentState((prev) => {
                const { [event.node_id!]: _, ...rest } = prev.llmSnapshots;
                return { ...prev, llmSnapshots: rest };
              });
            }
            const iter = (event.data?.iteration as number) ?? undefined;
            updateGraphNodeStatus(event.node_id, "looping", { iterations: iter });
            appendNodeLog(event.node_id, `${ts} INFO  Iteration ${iter ?? "?"}`);
          }
          break;

        case "node_loop_completed":
          if (!isQueen && event.node_id) {
            const pendingText = state.llmSnapshots[event.node_id];
            if (pendingText?.trim()) {
              appendNodeLog(event.node_id, `${ts} INFO  LLM: ${truncate(pendingText.trim(), 300)}`);
              setAgentState((prev) => {
                const { [event.node_id!]: _, ...rest } = prev.llmSnapshots;
                return { ...prev, llmSnapshots: rest };
              });
            }
            updateGraphNodeStatus(event.node_id, "complete");
            appendNodeLog(event.node_id, `${ts} INFO  Node completed`);
          }
          break;

        case "node_retry":
          if (!isQueen) {
            const sourceNode = event.data?.source_node as string | undefined;
            const targetNode = event.data?.target_node as string | undefined;
            if (sourceNode) updateGraphNodeStatus(sourceNode, "complete");
            if (targetNode) updateGraphNodeStatus(targetNode, "running");
          }
          break;

        case "tool_call_started": {
          if (event.node_id) {
            if (!isQueen) {
              const pendingText = state.llmSnapshots[event.node_id];
              if (pendingText?.trim()) {
                appendNodeLog(
                  event.node_id,
                  `${ts} INFO  LLM: ${truncate(pendingText.trim(), 300)}`,
                );
                setAgentState((prev) => {
                  const { [event.node_id!]: _, ...rest } = prev.llmSnapshots;
                  return { ...prev, llmSnapshots: rest };
                });
              }
              appendNodeLog(
                event.node_id,
                `${ts} INFO  Calling ${(event.data?.tool_name as string) || "unknown"}(${
                  event.data?.tool_input ? truncate(JSON.stringify(event.data.tool_input), 200) : ""
                })`,
              );
            }

            for (const msg of emittedMessages) {
              if (msg.role === "queen") {
                msg.phase = queenPhaseRef.current as ChatMessage["phase"];
              }
              upsertMessage(msg);
            }
            // No isStreaming / typing writes — loop_state_changed owns the
            // "in flight" state. Tool calls are mid-EXECUTING; nothing here
            // to mutate on the state-machine side.
          }
          break;
        }

        case "tool_call_completed": {
          if (event.node_id) {
            const toolName = (event.data?.tool_name as string) || "unknown";
            const isError = event.data?.is_error as boolean | undefined;
            const result = event.data?.result as string | undefined;
            if (isError) {
              appendNodeLog(
                event.node_id,
                `${ts} ERROR ${toolName} failed: ${truncate(result || "unknown error", 200)}`,
              );
            } else {
              const resultStr = result ? ` (${truncate(result, 200)})` : "";
              appendNodeLog(event.node_id, `${ts} INFO  ${toolName} done${resultStr}`);
            }

            for (const msg of emittedMessages) {
              if (msg.role === "queen") {
                msg.phase = queenPhaseRef.current as ChatMessage["phase"];
              }
              upsertMessage(msg);
            }
          }
          break;
        }

        case "node_internal_output":
          if (!isQueen && event.node_id) {
            const content = (event.data?.content as string) || "";
            if (content.trim()) appendNodeLog(event.node_id, `${ts} INFO  ${content}`);
          }
          break;

        case "context_usage_updated": {
          const streamKey = isQueen ? "__queen__" : event.node_id || streamId;
          const usagePct = (event.data?.usage_pct as number) ?? 0;
          const messageCount = (event.data?.message_count as number) ?? 0;
          const estimatedTokens = (event.data?.estimated_tokens as number) ?? 0;
          const maxTokens = (event.data?.max_context_tokens as number) ?? 0;
          setAgentState((prev) => ({
            ...prev,
            contextUsage: {
              ...prev.contextUsage,
              [streamKey]: {
                usagePct,
                messageCount,
                estimatedTokens,
                maxTokens,
                at: Date.now(),
              },
            },
          }));
          break;
        }

        case "credentials_required": {
          updateState({ error: "credentials_required" });
          const credAgentPath = event.data?.agent_path as string | undefined;
          if (credAgentPath) setCredentialAgentPath(credAgentPath);
          setCredentialsOpen(true);
          break;
        }

        case "client_credential_form_requested": {
          // The queen called credentials(action="collect"): pop a secure form
          // for the user. The queen is parked until the form is submitted or
          // cancelled (AgentCredentialForm POSTs to /credential-form, which
          // saves the secret and resumes the loop).
          if (!isQueen) break;
          const data = (event.data ?? {}) as Partial<AgentCredentialFormRequest>;
          if (
            !data.credential_id ||
            !data.correlation_id ||
            !Array.isArray(data.fields) ||
            data.fields.length === 0
          ) {
            break;
          }
          updateState({ isStreaming: false });
          setCredentialForm({
            credential_id: data.credential_id,
            account: data.account || "default",
            title: data.title || `Connect ${data.credential_id}`,
            instructions: data.instructions || "",
            fields: data.fields,
            correlation_id: data.correlation_id,
          });
          break;
        }

        case "queen_phase_changed": {
          const rawPhase = event.data?.phase as string;
          const eventAgentPath = (event.data?.agent_path as string) || null;
          const newPhase: AgentState["queenPhase"] =
            rawPhase === "colony" ? "colony" : "independent";
          queenPhaseRef.current = newPhase;
          updateState({
            queenPhase: newPhase,
            ...(eventAgentPath ? { agentPath: eventAgentPath } : {}),
          });
          break;
        }

        case "colony_suggestion_requested": {
          // Colony-phase queen called task_create(new_colony=true) to
          // pivot off-goal work into a fresh sibling colony. The queen
          // is parked on _input_ready after a synthetic intercept;
          // surfacing the popup is what gives the user a way to wake
          // her (either by accepting and spawning, or by dismissing).
          //
          // We only handle the pivot variant here (source_phase=colony).
          // DM-side suggest_colony events are emitted on a queen DM
          // session, which is queen-dm.tsx's territory — they shouldn't
          // arrive here, but if they do (mis-routed) we ignore them
          // because this page has no concept of "compact this colony's
          // chat into a brand-new colony", which is what that variant
          // assumes.
          const data = (event.data ?? {}) as {
            source_phase?: string;
            goal?: string | null;
            handoff?: string | null;
            task_count?: number | null;
          };
          if (data.source_phase !== "colony") break;
          setPivotPopup({
            goal: data.goal?.trim() || null,
            handoff: data.handoff?.trim() || null,
            taskCount: typeof data.task_count === "number" ? data.task_count : null,
          });
          setPivotColonyName("");
          setPivotError(null);
          setPivotSubmitting(false);
          break;
        }

        case "worker_colony_loaded": {
          const graphName = event.data?.colony_id as string | undefined;
          const agentPathFromEvent = event.data?.agent_path as string | undefined;
          const dn = formatAgentDisplayName(graphName || agentSlug(agentPath));
          clearCredentialCache(agentPathFromEvent);
          updateState({ displayName: dn });
          setGraphNodes([]);
          // Remove old worker messages
          setMessages((prev) => prev.filter((m) => m.role !== "worker"));
          break;
        }

        case "trigger_available":
        case "trigger_activated": {
          // Available = defined in triggers.json but ``enabled: false``.
          // Activated = ``enabled: true``. Triggers fire iff the session
          // is loaded (which it must be for these events to arrive) AND
          // the trigger is enabled — there's no separate colony-level
          // gate anymore.
          const isEnabled = event.type === "trigger_activated";
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            const nodeId = `__trigger_${triggerId}`;
            setGraphNodes((prev) => {
              const exists = prev.some((n) => n.id === nodeId);
              if (exists) {
                // Upgrade an existing inactive card to active without
                // clobbering the trigger_config fields the activated event
                // may carry (e.g. next_fire_in).
                return prev.map((n) => {
                  if (n.id !== nodeId) return n;
                  const incomingConfig =
                    (event.data?.trigger_config as Record<string, unknown>) || undefined;
                  return {
                    ...n,
                    // GraphNode.status carries the trigger's own enabled
                    // flag; whether it's actually firing right now is
                    // (status === "running") AND colonyState === "active",
                    // derived at render time from context.
                    status: (isEnabled ? "running" : "pending") as NodeStatus,
                    ...(incomingConfig ? { triggerConfig: incomingConfig } : {}),
                  };
                });
              }
              const triggerType = (event.data?.trigger_type as string) || "timer";
              const triggerConfig = (event.data?.trigger_config as Record<string, unknown>) || {};
              const entryNode =
                (event.data?.entry_node as string) ||
                prev.find((n) => n.nodeType !== "trigger")?.id;
              const triggerName = (event.data?.name as string) || triggerId;
              const _cron = triggerConfig.cron as string | undefined;
              const _interval = triggerConfig.interval_minutes as number | undefined;
              const scheduleLabel = _cron
                ? cronToLabel(_cron)
                : _interval
                ? `Every ${_interval >= 60 ? `${_interval / 60}h` : `${_interval}m`}`
                : triggerName;
              // Prefer the user's name as the card title when it's a real
              // label (user-created schedulers set a description). Queen-made
              // triggers have no description, so name === triggerId — fall
              // back to the schedule, which TriggerCard then shows as the
              // title with no redundant subtitle.
              const hasName = !!event.data?.name && triggerName !== triggerId;
              const computedLabel = hasName ? triggerName : scheduleLabel;
              const newNode: GraphNode = {
                id: nodeId,
                label: computedLabel,
                status: isEnabled ? "running" : "pending",
                nodeType: "trigger",
                triggerType,
                triggerConfig,
                ...(entryNode ? { next: [entryNode] } : {}),
              };
              return [newNode, ...prev];
            });
          }
          break;
        }

        case "trigger_deactivated": {
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            setGraphNodes((prev) =>
              prev.map((n) => {
                if (n.id !== `__trigger_${triggerId}`) return n;
                const {
                  next_fire_in: _nfi,
                  next_fire_at: _nfa,
                  ...restConfig
                } = (n.triggerConfig || {}) as Record<string, unknown> & {
                  next_fire_in?: unknown;
                  next_fire_at?: unknown;
                };
                return { ...n, status: "pending" as NodeStatus, triggerConfig: restConfig };
              }),
            );
          }
          break;
        }

        case "trigger_fired": {
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            const nodeId = `__trigger_${triggerId}`;
            // Merge refreshed fire stats + next-fire anchor into the node's
            // triggerConfig so the countdown re-anchors and the card shows
            // an up-to-date "fired Nx · last 2m ago" badge.
            const fireCount = event.data?.fire_count as number | undefined;
            const lastFiredAt = event.data?.last_fired_at as number | undefined;
            const nextFireAt = event.data?.next_fire_at as number | undefined;
            const nextFireIn = event.data?.next_fire_in as number | undefined;
            setGraphNodes((prev) =>
              prev.map((n) => {
                if (n.id !== nodeId) return n;
                const config = { ...(n.triggerConfig || {}) };
                if (fireCount != null) config.fire_count = fireCount;
                if (lastFiredAt != null) config.last_fired_at = lastFiredAt;
                if (nextFireAt != null) config.next_fire_at = nextFireAt;
                if (nextFireIn != null) config.next_fire_in = nextFireIn;
                return { ...n, triggerConfig: config };
              }),
            );
            updateGraphNodeStatus(nodeId, "complete");
            setTimeout(() => updateGraphNodeStatus(nodeId, "running"), 1500);

            // Render a banner in the chat marking the start of the turn the
            // queen is about to run in response. Matches the replay path in
            // chat-helpers.ts (case "trigger_fired") so live + restore look
            // identical.
            const bannerPayload = {
              trigger_id: triggerId,
              trigger_type: event.data?.trigger_type as string | undefined,
              name: event.data?.name as string | undefined,
              task: event.data?.task as string | undefined,
              fire_count: fireCount,
              last_fired_at: lastFiredAt,
            };
            upsertMessage({
              id: `trigger-${triggerId}-${lastFiredAt ?? event.timestamp}`,
              agent: "Trigger",
              agentColor: "",
              content: JSON.stringify(bannerPayload),
              timestamp: "",
              type: "trigger",
              thread: agentPath,
              createdAt: lastFiredAt ?? Date.now(),
            });
          }
          break;
        }

        case "trigger_removed": {
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            setGraphNodes((prev) => prev.filter((n) => n.id !== `__trigger_${triggerId}`));
          }
          break;
        }

        case "reminder_injected": {
          const d = (event.data ?? {}) as {
            source?: string;
            detail?: string;
            meta?: { nudge_count?: number; cap?: number };
          };
          setReminders((prev) =>
            [
              {
                source: d.source ?? "?",
                detail: d.detail ?? "",
                nudgeCount:
                  typeof d.meta?.nudge_count === "number" ? d.meta.nudge_count : null,
                cap: typeof d.meta?.cap === "number" ? d.meta.cap : null,
                at: Date.now(),
              },
              ...prev,
            ].slice(0, 15),
          );
          break;
        }

        case "loop_state_changed": {
          // Sole writer of `activity` / `parkReason` / `interruptCause`.
          // Mirrors the backend's _set_activity state machine: EXECUTING /
          // AWAITING_USER / INTERRUPTED. No other event handler touches
          // these — the backend is the single source of truth.
          const a = event.data?.activity as string | undefined;
          const activity =
            a === "executing" || a === "awaiting_user" || a === "interrupted" ? a : null;
          const pr = (event.data?.park_reason as string | undefined) ?? null;
          const ic = (event.data?.interrupt_cause as string | undefined) ?? null;
          updateState({
            activity,
            parkReason: activity === "awaiting_user" || activity === "interrupted" ? pr : null,
            interruptCause: activity === "interrupted" ? ic : null,
            awaitingInput: activity === "awaiting_user",
            // Parked/interrupted means no more streaming — clear the flag
            // even if a stale text-delta is still in flight on the wire.
            ...(activity === "awaiting_user" || activity === "interrupted"
              ? { isStreaming: false }
              : {}),
          });
          break;
        }

        case "session_snapshot": {
          // Rehydrate state-machine fields from the snapshot so a cold-
          // restored mid-flight session shows the correct activity
          // immediately, not only after the next live event.
          const d = (event.data ?? {}) as {
            activity?: string | null;
            park_reason?: string | null;
            interrupt_cause?: string | null;
          };
          const activity =
            d.activity === "executing" ||
            d.activity === "awaiting_user" ||
            d.activity === "interrupted"
              ? d.activity
              : null;
          updateState({
            activity,
            parkReason:
              activity === "awaiting_user" || activity === "interrupted"
                ? (d.park_reason ?? null)
                : null,
            interruptCause: activity === "interrupted" ? (d.interrupt_cause ?? null) : null,
            awaitingInput: activity === "awaiting_user",
            // Snapshot is authoritative in both directions: any state
            // that is not "executing" clears isStreaming. Colony's only
            // live clearer (loop_state_changed) is droppable under
            // backpressure, and a reconnect that couldn't clear the flag
            // left the composer queueing messages until a page refresh.
            ...(activity !== "executing" ? { isStreaming: false } : {}),
          });
          if (activity !== "executing") {
            // Deliver anything the closed gate accumulated.
            flushNextPendingRef.current?.();
          }
          break;
        }

        default:
          if (shouldMarkQueenReady) updateState({ queenReady: true });
          break;
      }
    },
    [agentPath, queenInfo.name, updateState, upsertMessage, updateGraphNodeStatus, markAllNodesAs, appendNodeLog, graphNodes, debug, addUsage, noteCreditSpend],
  );

  // ── SSE subscription ───────────────────────────────────────────────────

  const sseSessions = useMemo(() => {
    if (agentState.sessionId && agentState.ready) {
      return { [agentPath]: agentState.sessionId };
    }
    return {};
  }, [agentPath, agentState.sessionId, agentState.ready]);

  // ── Stall watchdog ─────────────────────────────────────────────────
  // Mirror of queen-dm's: colony's isStreaming has a single SSE clearer
  // (loop_state_changed) that can be dropped under backpressure. Reconcile
  // against the server snapshot after 20s of streaming silence.
  const lastEventAtRef = useRef(lastEventAt);
  lastEventAtRef.current = lastEventAt;
  const watchdogBusyRef = useRef(false);
  useEffect(() => {
    const sid = agentState.sessionId;
    if (!sid || !(agentState.isStreaming ?? false)) return;
    const iv = setInterval(async () => {
      if (Date.now() - lastEventAtRef.current < 20_000) return;
      if (watchdogBusyRef.current) return;
      watchdogBusyRef.current = true;
      try {
        const snap = await api.get<{ activity?: string | null }>(
          `/sessions/${sid}/snapshot`,
        );
        if (snap.activity !== "executing") {
          console.warn(
            "[colony-chat] stall watchdog: server idle but isStreaming stuck — reconciling",
          );
          updateState({ isStreaming: false });
          flushNextPendingRef.current?.();
        } else {
          setLastEventAt(Date.now());
        }
      } catch {
        // transient / session recycling — leave state alone
      } finally {
        watchdogBusyRef.current = false;
      }
    }, 5_000);
    return () => clearInterval(iv);
  }, [agentState.sessionId, agentState.isStreaming, updateState]);

  // Auto-resume nonce. Bumped when SSE reports the session id is gone
  // (HTTP 404 on pre-open) so useMultiSSE re-mounts the SSE stream after
  // we've re-created the session in the runtime. See onSessionGone below
  // for the recovery flow.
  const [sseResumeNonce, setSseResumeNonce] = useState(0);
  const resumingRef = useRef(false);

  useMultiSSE({
    sessions: sseSessions,
    onEvent: handleSSEEvent,
    onConnectionState: (_agentType, state) => {
      setSseState(state);
      if (state === "live") setLastEventAt(Date.now());
    },
    onSessionGone: (_agentType, goneSessionId) => {
      // Runtime lost this session (hive-serve restarted or supervisord
      // killed and restarted it). On-disk queen_dir is intact — we can
      // re-load the SAME session id via ``queen_resume_from`` and the
      // SSE URL doesn't need to change. Coalesce: multiple SSE subs on
      // the same session can each fire onSessionGone, but we only need
      // one resume attempt.
      if (resumingRef.current) return;
      resumingRef.current = true;
      void (async () => {
        try {
          await sessionsApi.create({
            colonyId: agentSlug(agentPath),
            queenResumeFrom: goneSessionId,
          });
          // Session is back in the runtime under the same id. Bump the
          // nonce to force useMultiSSE to re-subscribe (sessions map
          // is unchanged, so it wouldn't re-run on its own).
          setSseResumeNonce((n) => n + 1);
        } catch (err) {
          console.error(
            "[colony-chat] auto-resume after session-gone failed:",
            goneSessionId,
            err,
          );
        } finally {
          resumingRef.current = false;
        }
      })();
    },
    resumeNonce: sseResumeNonce,
  });

  // Authoritative trigger seed. Trigger cards must NOT depend on SSE events
  // surviving the bounded event ring buffer — on a busy colony the older
  // triggers' activation events age out, so the SSE-only path showed one card
  // (or none). The durable list lives in the colony folder (triggers.json) and
  // is served by GET /sessions/{id}/triggers; we fetch it on load and route each
  // trigger through the same handler the live SSE deltas use, so cards render
  // from authoritative state. Re-runs when the session becomes ready (covers the
  // cold-restore window where the colony isn't loaded yet). Idempotent — the
  // handler dedupes by trigger_id, so live SSE deltas layer cleanly on top.
  const handleSSEEventRef = useRef(handleSSEEvent);
  handleSSEEventRef.current = handleSSEEvent;
  useEffect(() => {
    const sid = agentState.sessionId;
    if (!sid || isNewChat) return;
    let cancelled = false;
    (async () => {
      try {
        const { triggers } = await sessionsApi.listTriggers(sid);
        if (cancelled || !triggers?.length) return;
        for (const t of triggers) {
          handleSSEEventRef.current("queen", {
            type: t.enabled ? "trigger_activated" : "trigger_available",
            stream_id: "queen",
            node_id: null,
            execution_id: null,
            data: {
              trigger_id: t.trigger_id,
              trigger_type: t.trigger_type,
              trigger_config: t.trigger_config,
              name: t.name,
            },
            timestamp: new Date().toISOString(),
            correlation_id: null,
            colony_id: null,
            seq: 0,
          });
        }
      } catch (err) {
        // Non-fatal: SSE deltas still cover the common case.
        console.warn("[triggers] authoritative seed failed:", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [agentState.sessionId, agentState.ready, isNewChat]);

  // No markPresence on colony: a user-cancelled queen must NOT auto-resume
  // just because the user re-opened the chat. The user-stop persists until
  // they send a real message (inject_event clears it server-side). queen-dm
  // keeps its markPresence — the backend route is shared but we opt out here.

  // Mirror colony agent state into window.__hive_debug_state so the
  // Ctrl+Shift+D DebugPanel's Queen State / Reminder Hub sections work on
  // /colony routes (queen-dm.tsx does the same for /queen routes). Fields
  // the colony view doesn't track are simply omitted — the panel renders
  // its own defaults. contextUsage is taken from the queen stream
  // (``__queen__``); per-worker usage isn't surfaced here.
  useEffect(() => {
    const qu = agentState.contextUsage["__queen__"];
    (window as unknown as Record<string, unknown>).__hive_debug_state = {
      active: agentState.ready && !!agentState.sessionId,
      isStreaming: agentState.isStreaming,
      // Live "Agent Loop State" panel reads camelCase…
      awaitingInput: agentState.activity === "awaiting_user",
      parkReason: agentState.parkReason,
      interrupted: agentState.activity === "interrupted",
      interruptCause: agentState.interruptCause,
      pendingQuestions: agentState.pendingQuestions,
      // …and the "Session Snapshot (latest)" panel reads snake_case (queen-dm
      // populates these via snapStateRef). Colony exposes both shapes off the
      // same agentState so both panels show the loop's authoritative state.
      activity: agentState.activity,
      is_executing: agentState.activity === "executing",
      awaiting_input: agentState.activity === "awaiting_user",
      park_reason: agentState.parkReason,
      interrupt_cause: agentState.interruptCause,
      queenPhase: agentState.queenPhase,
      sessionId: agentState.sessionId,
      messageCount: qu?.messageCount,
      lastEventAt,
      reminders,
      contextUsage: qu
        ? {
            usagePct: qu.usagePct,
            estimatedTokens: qu.estimatedTokens,
            maxContextTokens: qu.maxTokens,
            messageCount: qu.messageCount,
            trigger: "",
            conversationChars: 0,
            systemChars: 0,
            toolDefsChars: 0,
            imageBlocks: 0,
            at: qu.at,
          }
        : null,
    };
  }, [
    agentState.ready,
    agentState.sessionId,
    agentState.isStreaming,
    agentState.activity,
    agentState.parkReason,
    agentState.interruptCause,
    agentState.pendingQuestions,
    agentState.queenPhase,
    agentState.contextUsage,
    lastEventAt,
    reminders,
  ]);

  // ── Action handlers ────────────────────────────────────────────────────

  // Core backend send — bypasses queue logic. Used both for the normal path
  // (agent idle) and for Steer / auto-flush paths.
  // Returns whether the message was actually handed to the HTTP layer:
  // callers (the pending queue in particular) must NOT treat a false return
  // as sent. The old void signature silently swallowed messages whenever
  // `ready` was false — the queue had already deleted its copy, so the
  // user's text was destroyed while the bubble looked delivered.
  const sendToBackend = useCallback(
    (text: string, images?: ImageContent[], displayMessage?: string): boolean => {
      if (!agentState.sessionId || !agentState.ready) {
        console.warn(
          "[colony-chat] send deferred: session not ready",
          { sessionId: agentState.sessionId, ready: agentState.ready },
        );
        return false;
      }
      executionApi.chat(agentState.sessionId, text, images, displayMessage).catch((err: unknown) => {
        const errMsg = err instanceof Error ? err.message : String(err);
        upsertMessage({
          id: makeId(),
          agent: "System",
          agentColor: "",
          content: `Failed to send message: ${errMsg}`,
          timestamp: "",
          type: "system",
          thread: agentPath,
          createdAt: Date.now(),
        });
        updateState({ isStreaming: false });
      });
      return true;
    },
    [agentPath, agentState.sessionId, agentState.ready, updateState, upsertMessage],
  );

  const {
    enqueue: enqueuePending,
    steer: handleSteer,
    cancelQueued: handleCancelQueued,
    flushNext: flushNextPending,
    flushNextRef: flushNextPendingRef,
    clear: clearPendingQueue,
  } = usePendingQueue({
    sendToBackend,
    setMessages,
    onFlushStart: useCallback(() => {
      // Optimistic: a queued message is about to inject; arm isStreaming so
      // the cancel button reappears immediately. The server-echoed
      // loop_state_changed will reconcile activity moments later.
      updateState({ isStreaming: true });
      queenAboutToResumeRef.current = true;
    }, [updateState]),
  });

  // Reset the queue whenever we navigate to a different colony (or to
  // new-chat). The hook outlives the route change, so without this, a
  // message queued in colony A would auto-flush into colony B's next
  // execution_completed.
  useEffect(() => {
    clearPendingQueue();
  }, [agentPath, isNewChat, clearPendingQueue]);

  const handleKillColony = useCallback(async () => {
    const sessionId = agentState.sessionId;
    if (!sessionId) return;
    const reportFailure = (reason: string) => {
      upsertMessage({
        id: makeId(),
        agent: "System",
        agentColor: "",
        content: `Failed to stop: ${reason}`,
        timestamp: "",
        type: "system",
        thread: agentPath,
        createdAt: Date.now(),
      });
    };
    try {
      // Fire both in parallel: cancel-queen already cascades to workers
      // when the queen is active, but we also call stop-all explicitly so
      // the kill switch works even when only workers are running.
      const [queenResult] = await Promise.all([
        executionApi.cancelQueen(sessionId),
        workersApi.stopAllLive(sessionId).catch(() => {}),
      ]);
      if (queenResult.cancelled) {
        updateState({ isStreaming: false });
      }
      flushNextPending();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      reportFailure(msg);
    }
  }, [agentState.sessionId, agentPath, updateState, upsertMessage, flushNextPending]);

  const handleSend = useCallback(
    (
      text: string,
      _thread: string,
      images?: ImageContent[],
      displayMessage?: string,
      displayImages?: ImageContent[],
    ) => {
      const answeringQuestion = agentState.pendingQuestionSource === "queen";
      if (answeringQuestion) {
        updateState({
          pendingQuestions: null,
          pendingQuestionSource: null,
        });
      }

      // Queue when the queen is mid-turn — unless the user is answering an
      // ask_user prompt, in which case we send immediately so the loop can
      // resume. Queued messages are held locally (not sent to the backend)
      // until the user clicks Steer or the queen goes idle. Read isStreaming
      // (mirrors queen-dm's queueing convention).
      // Also queue when we're entitled to send but no session is bound yet
      // (e.g. the free-mode upgrade just kicked off its create) —
      // sendToBackend would silently drop the message otherwise. The queue
      // flushes at the next turn boundary. Free mode (!llmReady) is excluded:
      // its messages are parked below, never queued.
      const sessionMissing = llmReady && !agentState.sessionId;
      const shouldQueue =
        !answeringQuestion && ((agentState.isStreaming ?? false) || sessionMissing);

      const msgId = makeId();
      const userMsg: ChatMessage = {
        id: msgId,
        agent: "You",
        agentColor: "",
        // Show the typed message in the bubble, not the full extracted file content.
        content: displayMessage || text,
        timestamp: "",
        type: "user",
        thread: agentPath,
        createdAt: Date.now(),
        // Show display images (one chip per file) in the bubble; the per-page
        // rendered PDF images go to the LLM only, never to the carousel.
        images: displayImages || images,
        queued: shouldQueue,
        // The server echoes back the full prompt (including extracted file
        // content). Stash it so upsertMessage's content-based reconciler can
        // still match this bubble after a PDF/CSV is attached.
        _reconcileContent: displayMessage ? text : undefined,
      };
      setMessages((prev) => [...prev, userMsg]);
      suppressIntroRef.current = false;

      if (shouldQueue) {
        enqueuePending(msgId, { text, images, displayMessage });
        return;
      }

      // Optimistic isStreaming — the next loop_state_changed will reconcile
      // activity moments later, but this closes the click→roundtrip window.
      updateState({ isStreaming: true });
      if (!sendToBackend(text, images, displayMessage)) {
        // Gate closed after all (load superseded / not ready) — keep the
        // message queued instead of destroying it; the next flush retries.
        updateState({ isStreaming: false });
        setMessages((prev) =>
          prev.map((m) => (m.id === msgId ? { ...m, queued: true } : m)),
        );
        enqueuePending(msgId, { text, images, displayMessage });
      }
    },
    [
      agentPath,
      agentState.isStreaming,
      agentState.pendingQuestionSource,
      agentState.sessionId,
      updateState,
      sendToBackend,
      enqueuePending,
      llmReady,
      colonyId,
    ],
  );

  // Expose handleSend through ColonyWorkersContext so panel surfaces (the
  // Sentinel setup card's "Set this up with the agent" button) can hand the
  // queen a task without the user retyping it. A ref keeps the registered
  // reference stable while handleSend's closure rebinds; the consumer always
  // calls the latest implementation against the current session.
  const handleSendRef = useRef(handleSend);
  useEffect(() => {
    handleSendRef.current = handleSend;
  }, [handleSend]);
  useEffect(() => {
    setRequestQueenPrompt((text: string) => handleSendRef.current(text, agentPath));
    return () => setRequestQueenPrompt(null);
  }, [setRequestQueenPrompt, agentPath]);

  const handleQueenQuestionAnswer = useCallback(
    (answers: Record<string, string>) => {
      const questions = agentState.pendingQuestions;
      updateState({
        pendingQuestions: null,
        pendingQuestionSource: null,
      });
      // For a single question, send just the answer text. For a batch,
      // send `"prompt"="answer"` pairs so the queen can map replies back.
      const entries = Object.entries(answers);
      const promptFor = (id: string) =>
        questions?.find((q) => q.id === id)?.prompt ?? id;
      const payload =
        entries.length === 1
          ? entries[0][1]
          : entries
              .map(([id, val]) => `"${promptFor(id)}"="${val}"`)
              .join("\n");
      handleSend(payload, agentPath);
    },
    [agentPath, agentState.pendingQuestions, handleSend, updateState],
  );

  const handleQuestionDismiss = useCallback(() => {
    // Silent dismiss: clear the widget locally without messaging the queen
    // (matches queen-dm). The queen stays parked until the next real message.
    updateState({
      pendingQuestions: null,
      pendingQuestionSource: null,
      awaitingInput: false,
    });
  }, [updateState]);

  // --- Colony-pivot popup handlers ---
  const handlePivotDismiss = useCallback(() => {
    const sid = agentState.sessionId;
    setPivotPopup(null);
    setPivotColonyName("");
    setPivotError(null);
    setPivotSubmitting(false);
    if (sid) {
      sessionsApi.dismissColonyPivot(sid).catch(() => {
        /* best-effort — UI is already closed */
      });
    }
  }, [agentState.sessionId]);

  const handlePivotConfirm = useCallback(async () => {
    if (pivotSubmitting) return;
    const colony = pivotColonyName.trim();
    if (!colony) {
      setPivotError("Pick a slug for the new colony first.");
      return;
    }
    const sid = agentState.sessionId;
    if (!sid) {
      setPivotError("No session id — cannot create colony.");
      return;
    }
    setPivotError(null);
    setPivotSubmitting(true);
    try {
      // Backend routes to _create_sibling_colony_from_colony (source
      // phase=colony) which reads goal/handoff/tasks from
      // session.pending_colony_pivot — we only need to send
      // colonyId + sourceSessionId.
      const live = await sessionsApi.create({
        colonyId: colony,
        sourceSessionId: sid,
        initialPhase: "colony",
      });
      // Capture the goal BEFORE clearing pivotPopup so we can pass it
      // as routeState.initialGoal on navigation. Without this the new
      // colony's page mounts with showInitialTyping=false and the user
      // stares at a blank chat until the queen's first text delta lands
      // (the SSE connection takes a moment to open after navigation, so
      // the early execution_started event is missed). Passing the goal
      // flips queenIsTyping=true optimistically at mount.
      const pivotGoal = pivotPopup?.goal || null;
      setPivotPopup(null);
      setPivotColonyName("");
      setPivotSubmitting(false);
      navigate(`/colony/${slugToColonyId(live.colony_id || colony)}`, {
        state: pivotGoal ? { initialGoal: pivotGoal } : undefined,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to create colony";
      setPivotError(msg);
      setPivotSubmitting(false);
    }
  }, [agentState.sessionId, navigate, pivotColonyName, pivotPopup, pivotSubmitting]);

  const triggers = useMemo(
    () => graphNodes.filter((n) => n.nodeType === "trigger"),
    [graphNodes],
  );

  // Mirror live triggers into the shared context so the tabbed
  // ColonyPanel (rendered at the layout level) can render the
  // Triggers tab without having to re-subscribe to the session SSE.
  useEffect(() => {
    setCtxTriggers(triggers);
    return () => setCtxTriggers([]);
  }, [triggers, setCtxTriggers]);

  // Publish the live colony session id to the context. The AppLayout
  // renders ``ColonyPanel`` whenever this is non-null AND the
  // user hasn't dismissed it (via the X button). Cleanup clears it so
  // the panel closes when we leave the colony room.
  useEffect(() => {
    setCtxSessionId(agentState.sessionId ?? null);
    return () => setCtxSessionId(null);
  }, [agentState.sessionId, setCtxSessionId]);

  // Publish the colony directory name (e.g. ``linkedin_honeycomb_messaging``)
  // alongside the session id. The panel's progress + data tabs route by
  // colony name, not session — one tracker.db per colony, independent
  // of which session is open. Comes from ``LiveSession.colony_id`` (the
  // on-disk directory) rather than the URL slug, which is mangled by
  // ``slugToColonyId``.
  useEffect(() => {
    setCtxColonyName(agentState.colonyDirName ?? null);
    return () => setCtxColonyName(null);
  }, [agentState.colonyDirName, setCtxColonyName]);

  // Missed-trigger handshake. The backend emits a single ``missed_triggers``
  // SSE event right after session load when any enabled timer trigger had
  // cron/interval ticks while the session was closed. Non-null opens the
  // resolve modal; the user picks fire_latest / skip / reschedule per
  // trigger and we POST /colony/resolve_missed.

  // ── Render ─────────────────────────────────────────────────────────────

  if (!colony && !isNewChat && !agentState.loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-muted-foreground">Colony not found: {colonyId}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* The cloud pill is published into the AppHeader via setLeftActions
          (see the useEffect above) so it sits next to the queen-title
          chip instead of in a duplicate strip here. */}
      <div className="flex flex-1 min-h-0">
        {/* Chat panel */}
        <div className="flex-1 min-w-0 relative">
          {/* Loading overlay */}
          {agentState.loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 backdrop-blur-sm">
              <div className="flex items-center gap-3 text-muted-foreground">
                <Loader2 className="w-5 h-5 animate-spin" />
                <span className="text-sm">Connecting to agent...</span>
              </div>
            </div>
          )}

          {/* Queen connecting overlay */}
          {!agentState.loading && agentState.ready && !agentState.queenReady && (
            <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-background border-b border-primary/20 flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-primary/60" />
              <span className="text-xs text-primary/80">Connecting to {queenInfo.name}...</span>
            </div>
          )}

          {/* Error banner */}
          {agentState.error &&
            !agentState.loading &&
            dismissedBanner !== agentState.error &&
            (agentState.error === "credentials_required" ? (
              <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-background border-b border-amber-500/30 flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-amber-600" />
                <span className="text-xs text-amber-700">
                  Missing credentials — configure them to continue
                </span>
                <button
                  onClick={() => setCredentialsOpen(true)}
                  className="ml-auto text-xs font-medium text-primary hover:underline"
                >
                  Open Credentials
                </button>
                <button
                  onClick={() => setDismissedBanner(agentState.error!)}
                  className="p-0.5 rounded text-amber-600 hover:text-amber-800 hover:bg-amber-500/20 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : (
              <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-background border-b border-destructive/30 flex items-center gap-2">
                <WifiOff className="w-4 h-4 text-destructive" />
                <span className="text-xs text-destructive">
                  Backend unavailable: {agentState.error}
                </span>
                <button
                  onClick={() => setDismissedBanner(agentState.error!)}
                  className="ml-auto p-0.5 rounded text-destructive hover:bg-destructive/20 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}

          <ChatPanel
            messages={combinedMessages}
            currentSessionHasMoreOlder={currentSessionHasMoreOlder}
            onFetchOlderPage={fetchOlderPage}
            onSend={handleSend}
            onCancel={handleKillColony}
            onSteer={handleSteer}
            onCancelQueued={handleCancelQueued}
            activeThread={agentPath}
            // Mirror queen-dm: both gates read isStreaming.
            isWaiting={agentState.isStreaming ?? false}
            isBusy={agentState.isStreaming ?? false}
            colonyActive={
              (agentState.isStreaming ?? false) ||
              ctxWorkers.some((w) => {
                const s = (w.status || "").toLowerCase();
                return s === "pending" || s === "running";
              })
            }
            disabled={agentState.loading || !agentState.queenReady}
            sseState={sseState}
            lastEventAt={lastEventAt}
            queenPhase={agentState.queenPhase}
            queenTitle={queenInfo.role}
            pendingQuestions={agentState.awaitingInput ? agentState.pendingQuestions : null}
            onQuestionSubmit={handleQueenQuestionAnswer}
            onQuestionDismiss={handleQuestionDismiss}
            contextUsage={agentState.contextUsage}
            supportsImages={agentState.queenSupportsImages}
            // Needed so AttachmentChip / ImageCarouselModal can resolve
            // canonical `hive-attachment://` refs to a fetchable
            // /api/sessions/{sid}/attachment/{name} URL. Without it the raw
            // hive-attachment:// URL hits the renderer and CSP refuses it
            // (only `hive:`/127.0.0.1 are allowed). Mirrors queen-dm.
            sessionId={agentState.sessionId}
            queenProfileId={colony?.queenProfileId ?? null}
            queenId={colony?.queenProfileId ?? undefined}
          />
        </div>

        {/* Workers / Triggers / Skills / Tools now live in the tabbed
            ColonyPanel rendered by AppLayout. Trigger data is
            pushed up via ColonyWorkersContext (see the useEffect that
            mirrors `triggers` into context.setTriggers). */}
      </div>

      <CredentialsModal
        agentType={agentPath}
        agentLabel={colonyName}
        agentPath={credentialAgentPath || agentState.agentPath || agentPath}
        open={credentialsOpen}
        onClose={() => {
          setCredentialsOpen(false);
          setCredentialAgentPath(null);
        }}
        credentials={credentials}
        onCredentialChange={() => {
          if (agentState.error === "credentials_required") {
            updateState({ error: null });
            // Retry session loading
            loadSession();
          }
        }}
      />

      {credentialForm && agentState.sessionId && (
        <AgentCredentialForm
          sessionId={agentState.sessionId}
          request={credentialForm}
          onClose={() => setCredentialForm(null)}
        />
      )}

      {pivotPopup && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => {
              if (!pivotSubmitting) handlePivotDismiss();
            }}
          />
          <div className="relative flex w-full max-w-lg h-[min(560px,88vh)] flex-col overflow-hidden rounded-xl border border-border/60 bg-card shadow-2xl">
            <div className="px-6 pt-5 pb-3 space-y-1">
              <h2 className="text-sm font-semibold text-foreground">
                Spawn a new colony for this work?
              </h2>
              <p className="text-[11px] text-muted-foreground">
                This colony's queen has identified the latest request as off-goal for this colony and wants to spawn a fresh sibling colony for it. This colony stays alive and untouched; the new colony's queen takes over the off-goal work.
              </p>
            </div>
            <div className="flex-1 overflow-y-auto px-6 pb-4 space-y-3">
              {pivotPopup.goal && (
                <div>
                  <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                    New colony's goal{" "}
                    <span className="text-muted-foreground/40">(authored by the queen)</span>
                  </label>
                  <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm text-foreground whitespace-pre-wrap">
                    {pivotPopup.goal}
                  </div>
                </div>
              )}
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                  Colony name{" "}
                  <span className="text-muted-foreground/40">(you choose — slug)</span>
                </label>
                <input
                  type="text"
                  value={pivotColonyName}
                  onChange={(e) =>
                    setPivotColonyName(
                      e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""),
                    )
                  }
                  placeholder="e.g. uber_eats_research"
                  className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary"
                  autoFocus
                />
              </div>
              {pivotPopup.handoff && (
                <div>
                  <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                    Handover to new colony's queen{" "}
                    <span className="text-muted-foreground/40">(authored by the queen, read-only)</span>
                  </label>
                  <div className="max-h-48 overflow-y-auto rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-[12px] text-foreground whitespace-pre-wrap leading-relaxed">
                    {pivotPopup.handoff}
                  </div>
                </div>
              )}
              {typeof pivotPopup.taskCount === "number" && pivotPopup.taskCount > 0 && (
                <p className="text-[11px] text-muted-foreground">
                  {pivotPopup.taskCount === 1
                    ? "1 task will be seeded in the new colony."
                    : `${pivotPopup.taskCount} tasks will be seeded in the new colony.`}
                </p>
              )}
            </div>
            {pivotError && (
              <div className="border-t border-destructive/30 bg-destructive/10 px-6 py-2 text-[11px] text-destructive">
                {pivotError}
              </div>
            )}
            <div className="mt-auto flex justify-end gap-2 border-t border-border/50 px-6 py-4">
              <button
                onClick={handlePivotDismiss}
                disabled={pivotSubmitting}
                className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors disabled:opacity-50"
              >
                Dismiss
              </button>
              <button
                onClick={handlePivotConfirm}
                disabled={!pivotColonyName.trim() || pivotSubmitting}
                className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {pivotSubmitting ? "Creating…" : "Create Colony"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
