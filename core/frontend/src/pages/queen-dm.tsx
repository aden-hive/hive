import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChevronRight, ListTodo, Loader2, Plus } from "lucide-react";
import TaskListPanel, { type PreviousSessionInfo } from "@/components/TaskListPanel";
import { tasksApi, type TaskRecord } from "@/api/tasks";
import ChatPanel, {
  type ChatMessage,
  type ImageContent,
} from "@/components/ChatPanel";
import QueenSessionSwitcher from "@/components/QueenSessionSwitcher";
import { api } from "@/api/client";
import { executionApi } from "@/api/execution";
import { sessionsApi } from "@/api/sessions";
import { queensApi, type PortraitDescriptor } from "@/api/queens";
import AgentCredentialForm from "@/components/AgentCredentialForm";
import type { AgentCredentialFormRequest } from "@/api/credentials";
import { useMultiSSE } from "@/hooks/use-sse";
import { usePendingQueue } from "@/hooks/use-pending-queue";
import type { AgentEvent, HistorySession } from "@/api/types";
import {
  EVENTS_PAGE_SIZE,
  eventDedupeKey,
  mergeChatMessages,
  newReplayState,
  replayEvent,
  replayEventsToMessages,
  replayOlderEvents,
  type OlderCursor,
} from "@/lib/chat-helpers";
import {
  beginLoad,
  TRACE_ENABLED,
  msgSummary,
  trace as traceLoad,
} from "@/lib/session-load-trace";
import { useColony } from "@/context/ColonyContext";
import { useColonyWorkers } from "@/context/ColonyWorkersContext";
import { useHeaderActions } from "@/context/HeaderActionsContext";
import SessionReportAction from "@/components/SessionReportAction";
import { useDebugState } from "@/components/DebugStateContext";
import { useMe, canMakeLLMCalls } from "@/lib/me";
import { useSessionUsage } from "@/context/SessionUsageContext";
import { getQueenForAgent, slugToColonyId } from "@/lib/colony-registry";
import { userStorage } from "@/lib/userStorage";
import {
  clearComposerHandoff,
  peekComposerHandoff,
  type ComposerHandoff,
} from "@/lib/composerHandoff";

const makeId = () => Math.random().toString(36).slice(2, 9);

// Remembers the last session the user had open in each queen DM so that
// navigating away (e.g. to another queen) and back lands on the session
// they were just in, instead of whichever session the server picks.
// Scoped per-user via userStorage so two accounts don't see each other's
// last-session pointers.
const lastSessionKey = (queenId: string) => `queen:${queenId}:lastSession`;
const readLastSession = (queenId: string): string | null =>
  userStorage.get<string | null>(lastSessionKey(queenId), null);
const writeLastSession = (queenId: string, sessionId: string) =>
  userStorage.set(lastSessionKey(queenId), sessionId);
const clearLastSession = (queenId: string) =>
  userStorage.remove(lastSessionKey(queenId));

// Maximum time the full-screen loading overlay may stay up waiting for the
// on-disk history restore on a session switch. The restore is normally
// sub-100ms, so in the common case it wins this race and the conversation
// appears fully populated with no flicker. But when the runtime is busy
// (mid-LLM-stream, parallel colony workers) the events/history read can be
// starved for up to its 20s server-side timeout — far too long to pin the
// whole switch UX behind a spinner. After this budget we drop the overlay and
// reveal whatever the live SSE replay has rendered; `restoreMessages` keeps
// running and *merges* the disk history in when it finally lands (it never
// replaces, and is cancel-guarded), so nothing is lost.
const HISTORY_OVERLAY_BUDGET_MS = 2_500;
const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

// Optimistic "fake-sent" messages from the out-of-credit flow. Persisted
// per-user, per-queen so navigating away and back keeps the bubbles
// visible — without this, `resetViewState()` wipes them on every queenId
// change. Cleared the moment we commit to a real bootstrap (credits
// returned), at which point the real session takes over the transcript.
const noCreditMsgsKey = (queenId: string) => `queen:${queenId}:noCreditMsgs`;
const readNoCreditMsgs = (queenId: string): ChatMessage[] =>
  userStorage.get<ChatMessage[]>(noCreditMsgsKey(queenId), []);
const appendNoCreditMsg = (queenId: string, msg: ChatMessage): void => {
  const existing = readNoCreditMsgs(queenId);
  userStorage.set(noCreditMsgsKey(queenId), [...existing, msg]);
};
const clearNoCreditMsgs = (queenId: string): void =>
  userStorage.remove(noCreditMsgsKey(queenId));

export default function QueenDM() {
  const { queenId } = useParams<{ queenId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { queens, queenProfiles, refresh } = useColony();
  const { setActions } = useHeaderActions();
  const { me, noteCreditSpend } = useMe();
  const { addUsage } = useSessionUsage();
  const llmReady = canMakeLLMCalls(me);
  // Tracks the case where we entered the room without enough credits to
  // bootstrap a real session. Once credits return, a follow-up effect
  // creates the session lazily (no initial_prompt — the user sends what's
  // in their composer). Reset whenever the route changes so a stale flag
  // can't leak between queens / between bootstrap and resume modes.
  const deferredBootstrapRef = useRef(false);
  const profileQueen = queenProfiles.find((q) => q.id === queenId);
  const colonyQueen = queens.find((q) => q.id === queenId);
  const queenInfo = getQueenForAgent(queenId || "");
  // Prefer the onboarding-chosen lead from /v1/me when the user configured an
  // override for this specific queen — surfaces "Anna Wintour" (etc.)
  // immediately even when the local queen profile patch hasn't landed yet.
  // Name AND portrait read from this single override so the two never diverge;
  // sourcing name from preferences but portrait from the (stale) runtime profile
  // is exactly what showed a new lead's name over the old persona's face. Title
  // stays with the runtime profile — `t` is an org affiliation ("LVMH").
  const preferredLead =
    (queenId && me?.preferences?.queens?.[queenId]) || null;
  const queenName =
    preferredLead?.n ?? profileQueen?.name ?? colonyQueen?.name ?? queenInfo.name;
  const queenTitle =
    profileQueen?.title ?? colonyQueen?.role ?? queenInfo.role;
  const queenPortraitOverride =
    (preferredLead?.p as PortraitDescriptor | undefined) ?? null;
  const selectedSessionParam = searchParams.get("session");
  const newSessionFlag = searchParams.get("new");
  // Both CRM doors land here: `crm-setup=1` from the not-configured prompt and
  // `crm-continue=1` from the Configure dialog. Both open a conversation about
  // the CRM's shape, which is what the runtime needs told — it cannot infer it
  // from the queen id, since the CRM's host queen is also the default queen.
  const crmSetupFlag =
    searchParams.get("crm-setup") === "1" || searchParams.get("crm-continue") === "1";

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [queenReady, setQueenReady] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  // SSE connection state surfaced to the user. "reconnecting" appears
  // while the main-side bridge is sleeping between attempts; "closed"
  // is terminal and rare. Anything else: "live".
  const [sseState, setSseState] = useState<"live" | "reconnecting" | "closed">("live");
  // Wall-clock of the most recent live SSE event for this queen. Drives
  // the "last activity Xs ago" display and the "Working… (no events
  // for 30s)" stuck-queen warning. Reset on session switch.
  const [lastEventAt, setLastEventAt] = useState<number>(() => Date.now());
  const [pendingQuestions, setPendingQuestions] = useState<
    { id: string; prompt: string; options?: string[] }[] | null
  >(null);
  const [awaitingInput, setAwaitingInput] = useState(false);
  // Why the loop is parked (ParkReason value) — tracked live off the
  // client_input_requested event so the debug panel reflects it in
  // realtime, not only on the periodic session_snapshot rehydrate.
  const [parkReason, setParkReason] = useState<string | null>(null);
  // INTERRUPTED — the loop is not moving and it is NOT a deliberate
  // end-of-turn (broken park, stream stall, crash). Mutually exclusive
  // with awaitingInput; both are driven off the LOOP_STATE_CHANGED event.
  const [interrupted, setInterrupted] = useState(false);
  const [interruptCause, setInterruptCause] = useState<string | null>(null);
  // Mirror of the queen's task list, polled for the Ctrl+Shift+D debug panel.
  const [debugTasks, setDebugTasks] = useState<TaskRecord[]>([]);
  // True while a compaction pass is running (between
  // context_compaction_started and context_compacted). On a heavily
  // over-budget conversation this can stretch into minutes — the
  // DebugPanel exposes it so a "looks frozen" queen is recognisable
  // as "compacting" instead of "stuck".
  const [isCompacting, setIsCompacting] = useState(false);
  const [lastCompaction, setLastCompaction] = useState<{
    before: number;
    after: number;
    at: number;
  } | null>(null);
  // Real-time context-usage snapshot, updated on every
  // ``context_usage_updated`` event (which fires after each individual
  // tool call). Mirrored to ``__hive_debug_state`` for DebugPanel.
  const [contextUsage, setContextUsage] = useState<{
    usagePct: number;
    estimatedTokens: number;
    maxContextTokens: number;
    messageCount: number;
    trigger: string;
    conversationChars: number;
    systemChars: number;
    toolDefsChars: number;
    imageBlocks: number;
    at: number;
  } | null>(null);
  // Recent ReminderHub injections (idle nudge, tool-budget advisory,
  // stream-stall continue-nudge, lifecycle blocks) — surfaced in the
  // DebugPanel's Reminder Hub section. Newest first, capped at 15.
  const [reminders, setReminders] = useState<
    {
      source: string;
      detail: string;
      nudgeCount: number | null;
      cap: number | null;
      at: number;
    }[]
  >([]);
  // True when this queen is loaded into the runtime (we have a session
  // and SSE hasn't terminally closed). Derived rather than tracked as
  // its own state. Combined with `isStreaming` and `awaitingInput`,
  // describes everything the UI needs: queen unloaded → nothing;
  // queen loaded → streaming text, awaiting input, or the
  // typing-dots fallback (queen working but nothing visible yet).
  // Open tools are surfaced inline as tool_status pills rather than
  // a separate state field.
  const active = sessionId !== null && sseState !== "closed";
  const [tokenUsage, setTokenUsage] = useState<{
    input: number;
    output: number;
    cached: number;
    cacheCreated: number;
    costUsd: number;
    credits: number | null;
    requests: number;
  }>({
    input: 0,
    output: 0,
    cached: 0,
    cacheCreated: 0,
    costUsd: 0,
    credits: null,
    requests: 0,
  });
  // Live turns also feed the app-wide accumulator behind the PlanBadge
  // popover (addUsage / noteCreditSpend in the llm_turn_complete handler).
  // Unlike `tokenUsage` — which seeds from history on resume and backs the
  // bottom-right strip — that accumulator counts live turns only, so the
  // header tracks what this app run actually spent across pages.
  const [historySessions, setHistorySessions] = useState<HistorySession[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [switchingSessionId, setSwitchingSessionId] = useState<string | null>(
    null,
  );
  const [creatingNewSession, setCreatingNewSession] = useState(false);
  const [initialDraft, setInitialDraft] = useState<string | null>(null);
  // A draft composed on another screen (with files it had no session to upload
  // into) and handed here to be sent through the real composer. See
  // lib/composerHandoff.
  const [handoff, setHandoff] = useState<ComposerHandoff | null>(null);
  const [actionPlanOpen, setActionPlanOpen] = useState(false);
  const [expandedHistoryDays, setExpandedHistoryDays] = useState<Set<string>>(new Set());
  // Sessions whose inline content is currently expanded under the history
  // timeline. Separate from `expandedHistoryDays` (which gates the day-level
  // group) and from `sessionId` (the active session). Clicking a session row
  // toggles inline expansion only — it does not switch the active session.
  const [expandedHistorySessions, setExpandedHistorySessions] = useState<Set<string>>(
    new Set(),
  );
  // Cache of replayed messages per expanded historical session. Populated
  // lazily on first expand by fetching `eventsHistory(sid)`. `undefined`
  // means "not loaded yet" so the panel can show a loading hint.
  const [historySessionMessages, setHistorySessionMessages] = useState<
    Record<string, ChatMessage[]>
  >({});
  // ── Older-page paging (infinite scroll) ──────────────────────────────────
  // CURRENT session: the newest page seeds `messages` (live SSE keeps
  // appending); older pages accumulate oldest-first here and re-replay with a
  // fresh state into `olderMessages`, kept STRICTLY separate from the live
  // transcript / replay state and concatenated ahead only at render time.
  const olderEventsRef = useRef<AgentEvent[]>([]);
  const olderCursorRef = useRef<OlderCursor | null>(null);
  const [olderMessages, setOlderMessages] = useState<ChatMessage[]>([]);
  const olderPageInFlightRef = useRef(false);
  const [currentSessionHasMoreOlder, setCurrentSessionHasMoreOlder] =
    useState(false);
  // PREVIOUS (history) sessions: per-session raw-event accumulators + cursors
  // so each previous session can be paged fully on scroll-up before the next
  // older session is revealed. `historySessionMessages` (above) holds each
  // session's replayed messages; these refs drive its paging.
  const historySessionEventsRef = useRef<Record<string, AgentEvent[]>>({});
  const historySessionCursorsRef = useRef<Record<string, OlderCursor>>({});
  // Bumped whenever a history-session cursor flips so ChatPanel/the window
  // re-evaluate `historySessionHasMoreOlder` (refs alone don't re-render).
  const [, setHistoryCursorTick] = useState(0);
  const historySessionPageInFlightRef = useRef(false);
  const [cloneDialogOpen, setCloneDialogOpen] = useState(false);
  // Secure credential form the queen popped via credentials(action="collect").
  const [credentialForm, setCredentialForm] = useState<AgentCredentialFormRequest | null>(null);
  const [cloneColonyName, setCloneColonyName] = useState("");
  const [cloneGoal, setCloneGoal] = useState("");
  const [cloneHandover, setCloneHandover] = useState("");
  // Colony-spawned lock state. Once a colony has been spawned from this DM
  // and the user clicked into it, /chat is rejected server-side and the
  // composer is replaced with a "compact + new session" button. Hydrated
  // from the session detail and updated optimistically on click.
  const [colonySpawned, setColonySpawned] = useState(false);
  const [spawnedColonyName, setSpawnedColonyName] = useState<string | null>(
    null,
  );
  const [compactingAndForking, setCompactingAndForking] = useState(false);
  const [initError, setInitError] = useState<string | null>(null);

  const replayStateRef = useRef(newReplayState());
  const debug = useDebugState();
  // `queenName` is derived from async sources (useMe, useColony) and flips
  // value 1–2 times during the first ~second after mount. Stashing it in a
  // ref lets `restoreMessages` stay identity-stable so it doesn't churn
  // the main bootstrap effect's deps list — without this, the effect
  // tears itself down (cancelled=true) and the in-flight getOrCreateSession
  // is dropped, leaving sessionId=null forever on a first visit.
  const queenNameRef = useRef(queenName);
  queenNameRef.current = queenName;

  // ----- DEBUG INSTRUMENTATION (remove after first-visit-hang is fixed) -----
  const bootstrapRunRef = useRef(0);
  const renderCountRef = useRef(0);
  renderCountRef.current += 1;
  console.log(
    `[queen-dm:render #${renderCountRef.current}] queenId=${queenId} sessionId=${sessionId} ` +
      `loading=${loading} queenReady=${queenReady} queenName="${queenName}" ` +
      `selectedSessionParam=${selectedSessionParam} newSessionFlag=${newSessionFlag} ` +
      `llmReady=${llmReady}`,
  );
  // -------------------------------------------------------------------------
  // Snapshot fields captured from the latest session_snapshot SSE
  // frame so the debug panel can display server-side state.
  const snapStateRef = useRef<Record<string, unknown>>({});
  // Flipped true by the auto-flush path; consumed by the next empty-prompt
  // client_input_requested so we don't flicker the typing bubble off while
  // the queen is about to resume on the flushed input.
  const queenAboutToResumeRef = useRef(false);
  // Question bubble for an ask_user that's actively awaiting an answer. We
  // stash it here instead of pushing it into messages so the user only sees
  // ONE copy of the question (the popup widget) while answering. Committed
  // to the transcript on client_input_received so the bubble lands right
  // above the user's answer for scroll-back context.
  const pendingAskUserBubbleRef = useRef<ChatMessage | null>(null);
  const [queenPhase, setQueenPhase] = useState<"independent" | "colony">(
    "independent",
  );
  // When the queen calls suggest_colony (DM) or task_create(new_colony=true)
  // (colony pivot), the backend emits COLONY_SUGGESTION_REQUESTED and
  // parks her on _input_ready. Stash the payload here so the dialog
  // Cancel handler knows what to do (chat-message dismiss for DM,
  // dedicated dismiss-colony-pivot POST for colony pivot, or just close
  // for the manual header path).
  //
  // ``sourcePhase``:
  //   - "independent" | undefined → DM suggest_colony path. Slug is
  //     queen-proposed; user-typed goal + handover go into the colony
  //     queen's seed prompt. Dismiss injects a chat message.
  //   - "colony" → colony-pivot path. Slug starts blank for the user;
  //     goal + handoff are queen-authored and shown read-only; backend
  //     already has the rich payload stashed on session.pending_colony_pivot
  //     so accept only needs colonyId + sourceSessionId. Dismiss POSTs
  //     to /api/sessions/{id}/dismiss-colony-pivot.
  const [cloneSuggestion, setCloneSuggestion] = useState<
    {
      colonyName: string;
      reason: string | null;
      sourcePhase?: "independent" | "colony";
      goal?: string | null;
      handoff?: string | null;
      taskCount?: number | null;
    } | null
  >(null);
  const [cloneSubmitting, setCloneSubmitting] = useState(false);
  const [cloneError, setCloneError] = useState<string | null>(null);

  // Publish the active session id into the shared workers/tasks context
  // so AppLayout's right-rail TaskListPanel can attach to it. The colony
  // workers panel itself stays hidden in queen-DM because we don't set
  // colonyName (AppLayout requires both — see LayoutShell).
  const { setSessionId: setCtxSessionId } = useColonyWorkers();
  useEffect(() => {
    setCtxSessionId(sessionId ?? null);
    return () => setCtxSessionId(null);
  }, [sessionId, setCtxSessionId]);

  // Tell the backend the user (re-)entered this chat — lifts an explicit
  // user-stop so a stopped agent un-freezes (it resumes via the normal idle
  // nudge, not instantly). Fire-and-forget; a no-op when not stopped.
  useEffect(() => {
    if (sessionId) executionApi.markPresence(sessionId).catch(() => {});
  }, [sessionId]);

  // Auto-open the Action Plan drawer on session load when the existing
  // task list already has more than one visible task. Live-stream events
  // (`task_created` / `node_action_plan`) handle the in-flight case
  // separately; this covers reopening a session that was previously
  // populated.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    tasksApi
      .getList(sessionId)
      .then((snap) => {
        if (cancelled || !snap) return;
        const visible = snap.tasks.filter(
          (t) => !(t.metadata as { _internal?: boolean })._internal,
        );
        if (visible.length > 1) setActionPlanOpen(true);
      })
      .catch(() => {
        /* 404 / network — leave the drawer closed */
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const resetViewState = useCallback(() => {
    traceLoad("view", "resetViewState — clearing messages[] + replayState");
    setSessionId(null);
    setMessages([]);
    setQueenReady(false);
    setIsStreaming(false);
    setPendingQuestions(null);
    setAwaitingInput(false);
    setParkReason(null);
    setInterrupted(false);
    setInterruptCause(null);
    setQueenPhase("independent");
    setTokenUsage({
      input: 0,
      output: 0,
      cached: 0,
      cacheCreated: 0,
      costUsd: 0,
      credits: null,
      requests: 0,
    });
    setInitialDraft(null);
    setColonySpawned(false);
    setSpawnedColonyName(null);
    setCompactingAndForking(false);
    setInitError(null);
    replayStateRef.current = newReplayState();
    // Drop the current session's older-page accumulator/cursor so the next
    // session never renders the previous session's history above its
    // transcript. History-session paging caches survive intentionally — they
    // belong to the timeline, not the active session.
    olderEventsRef.current = [];
    setOlderMessages([]);
    olderCursorRef.current = null;
    olderPageInFlightRef.current = false;
    setCurrentSessionHasMoreOlder(false);
  }, []);

  // Fetch the CURRENT session's next older page (scroll-up infinite scroll).
  // Prepends raw events to `olderEventsRef` and re-replays the whole
  // accumulator with a fresh state — never touching the live replay state.
  const fetchOlderPage = useCallback(async () => {
    const sid = sessionId;
    const cursor = olderCursorRef.current;
    if (!sid || !cursor?.hasMoreOlder || olderPageInFlightRef.current) return;
    olderPageInFlightRef.current = true;
    try {
      const res = await sessionsApi.eventsHistory(sid, {
        limit: EVENTS_PAGE_SIZE,
        beforeOffset: cursor.startOffset,
        beforeIndex: cursor.startIndex,
      });
      if (res.events.length > 0) {
        olderEventsRef.current = [...res.events, ...olderEventsRef.current];
        setOlderMessages(
          replayOlderEvents(
            olderEventsRef.current,
            "queen-dm",
            queenNameRef.current,
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
  }, [sessionId]);

  // Whether an already-loaded history session still has older pages on disk.
  const historySessionHasMoreOlder = useCallback(
    (sid: string) =>
      historySessionCursorsRef.current[sid]?.hasMoreOlder ?? false,
    [],
  );

  // Fetch the next older page of an already-loaded history (previous) session.
  // Mirrors fetchOlderPage but keyed per session; serialized across all
  // history sessions so the cascade pages one at a time.
  const fetchOlderPageForSession = useCallback(async (sid: string) => {
    const cursor = historySessionCursorsRef.current[sid];
    if (!cursor?.hasMoreOlder || historySessionPageInFlightRef.current) return;
    historySessionPageInFlightRef.current = true;
    try {
      const res = await sessionsApi.eventsHistory(sid, {
        limit: EVENTS_PAGE_SIZE,
        beforeOffset: cursor.startOffset,
        beforeIndex: cursor.startIndex,
      });
      if (res.events.length > 0) {
        const acc = [
          ...res.events,
          ...(historySessionEventsRef.current[sid] ?? []),
        ];
        historySessionEventsRef.current[sid] = acc;
        const replayed = replayOlderEvents(acc, "queen-dm", queenNameRef.current);
        setHistorySessionMessages((c) => ({ ...c, [sid]: replayed }));
      }
      historySessionCursorsRef.current[sid] = {
        startOffset: res.start_offset,
        startIndex: res.start_index,
        hasMoreOlder: res.has_more_older,
      };
      setHistoryCursorTick((t) => t + 1);
    } catch {
      // Leave the cursor as-is; a later scroll retries.
    } finally {
      historySessionPageInFlightRef.current = false;
    }
  }, []);

  // Concatenate older paged messages AHEAD of the live transcript; the live
  // message wins at the id boundary. ChatPanel's createdAt sort is the final
  // arbiter (older events sort strictly earlier).
  const combinedMessages = useMemo(() => {
    if (olderMessages.length === 0) return messages;
    const liveIds = new Set(messages.map((m) => m.id));
    return [...olderMessages.filter((m) => !liveIds.has(m.id)), ...messages];
  }, [olderMessages, messages]);

  // TRACE: every change to the messages array, with a compact summary
  // (count + first/last createdAt + the calendar days covered). This is
  // the line that makes a mid-resume message-loss obvious — the count
  // drops or `days` shrinks to just the most recent day.
  //
  // TRACE_ENABLED guard is load-bearing: traceLoad() no-ops when tracing
  // is off, but its ARGUMENTS were still evaluated eagerly — msgSummary()
  // walks the entire transcript, so every streaming delta paid an O(n)
  // scan that grew with the session and starved router transitions.
  useEffect(() => {
    if (!TRACE_ENABLED) return;
    traceLoad("messages", "messages[] changed", {
      sessionId,
      ...msgSummary(messages),
    });
  }, [messages, sessionId]);

  // Out-of-credit "fake send" — the common path for both the New Chat
  // bootstrap (auto-replays the prompt the user typed on /home) and the
  // Switch-to-existing-queen flow (user clicks send themselves). We
  // optimistically render their message, show the queen's typing dots,
  // and pop the upgrade modal ~2s later so the moment doesn't feel like
  // a hard wall — the user gets to "send" their first thought, see the
  // queen react, then learn about the gate.
  //
  // No backend call is made: the modal handles the credit purchase, and
  // when credits return the bootstrap effect's recovery path picks up
  // the still-stashed `queenFirstMessage` as a real `initial_prompt`.
  const noCreditTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const triggerNoCreditPreview = useCallback(
    (
      text: string,
      images?: ImageContent[],
      displayMessage?: string,
      displayImages?: ImageContent[],
    ) => {
      if (!queenId) return;
      if (noCreditTimerRef.current) {
        clearTimeout(noCreditTimerRef.current);
        noCreditTimerRef.current = null;
      }
      const userMsg: ChatMessage = {
        id: makeId(),
        agent: "You",
        agentColor: "",
        content: displayMessage || text,
        timestamp: "",
        type: "user",
        thread: "queen-dm",
        createdAt: Date.now(),
        images: displayImages || images,
      };
      setMessages((prev) => [...prev, userMsg]);
      // Persist so navigating away and back doesn't lose the bubble.
      // Cleared the moment we boot a real session.
      appendNoCreditMsg(queenId, userMsg);
    },
    [queenId],
  );

  // Cancel any pending no-credit timer when the route changes or the
  // component unmounts so we don't fire the upgrade modal after the user
  // has navigated away.
  useEffect(() => {
    return () => {
      if (noCreditTimerRef.current) {
        clearTimeout(noCreditTimerRef.current);
        noCreditTimerRef.current = null;
      }
    };
  }, [queenId]);

  const upsertMessage = useCallback(
    (chatMsg: ChatMessage, options?: { reconcileOptimisticUser?: boolean }) => {
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === chatMsg.id);
        traceLoad("upsertMessage", idx >= 0 ? "update" : "insert", {
          id: chatMsg.id,
          type: chatMsg.type ?? "(text)",
          createdAt:
            typeof chatMsg.createdAt === "number"
              ? new Date(chatMsg.createdAt).toISOString()
              : null,
          prevLen: prev.length,
        });
        if (idx >= 0) {
          const existing = prev[idx];
          // Tool pills jump to the latest tool event timestamp so the
          // pill always anchors at the position of the most recent
          // tool in its batch. Without this, batched pills (a single
          // pillId shared across consecutive same-name tools) stay
          // pinned at the first tool's index — buried above whatever
          // queen text streamed between batch entries — and new
          // tool starts/completions look invisible to the user.
          const existingCreatedAt = existing.createdAt ?? 0;
          if (chatMsg.type === "tool_status") {
            const createdAt = Math.max(existingCreatedAt, chatMsg.createdAt ?? 0);
            const updated = { ...chatMsg, createdAt };
            // Re-position only when the timestamp actually advanced; an
            // upsert that doesn't move createdAt forward (e.g. a duplicate
            // SSE replay event) shouldn't shuffle messages around.
            if (createdAt > existingCreatedAt) {
              const without = prev.slice(0, idx).concat(prev.slice(idx + 1));
              let insertIdx = without.length - 1;
              while (
                insertIdx >= 0 &&
                (without[insertIdx].createdAt ?? 0) > createdAt
              ) {
                insertIdx--;
              }
              if (insertIdx === -1 || insertIdx === without.length - 1) {
                return [...without, updated];
              }
              const next = [...without];
              next.splice(insertIdx + 1, 0, updated);
              return next;
            }
            return prev.map((m, i) => (i === idx ? updated : m));
          }
          const updated = {
            ...chatMsg,
            createdAt: existing.createdAt ?? chatMsg.createdAt,
          };
          return prev.map((m, i) => (i === idx ? updated : m));
        }
        if (options?.reconcileOptimisticUser && chatMsg.type === "user") {
          const incomingTs = chatMsg.createdAt ?? Date.now();
          // Fall back to _reconcileContent so optimistic bubbles with a
          // short display message (e.g. "[document.pdf]") still match the
          // server's full-extracted-text echo.
          const matchIdx = prev.findIndex(
            (m) =>
              m.type === "user" &&
              (m.content === chatMsg.content ||
                (m._reconcileContent !== undefined &&
                  m._reconcileContent === chatMsg.content)) &&
              Math.abs(incomingTs - (m.createdAt ?? incomingTs)) <= 15000,
          );
          if (matchIdx !== -1) {
            // Adopt the server echo's createdAt — it's the authoritative
            // injection time (CLIENT_INPUT_RECEIVED), so the live transcript
            // sorts this bubble exactly where a reload/replay would place it
            // from the same event. The optimistic createdAt was only a
            // placeholder (re-stamped to send time on steer/flush).
            return prev.map((m, i) =>
              i === matchIdx
                ? {
                    ...m,
                    id: chatMsg.id,
                    queued: undefined,
                    createdAt: chatMsg.createdAt ?? m.createdAt,
                    // Adopt the correlation id so the upcoming
                    // client_input_committed event can find and re-stamp this
                    // bubble to its true injection time.
                    correlationId: chatMsg.correlationId ?? m.correlationId,
                  }
                : m,
            );
          }
        }

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

  const restoreMessages = useCallback(
    async (sid: string, cancelled: () => boolean, loadId?: string) => {
      const tr = (event: string, data?: unknown) =>
        traceLoad("restoreMessages", event, data, loadId);
      tr("ENTER", { sid });
      try {
        const { events, start_offset, start_index, has_more_older } =
          await sessionsApi.eventsHistory(sid, { limit: EVENTS_PAGE_SIZE });
        tr("eventsHistory resolved", {
          sid,
          eventsLen: events.length,
          hasMoreOlder: has_more_older,
          firstTs: events[0]?.timestamp ?? null,
          lastTs: events[events.length - 1]?.timestamp ?? null,
        });
        if (cancelled()) {
          tr("BAIL cancelled after eventsHistory", { sid });
          return;
        }

        // Use a *fresh* replayState for the disk-history pass.
        //
        // We deliberately do NOT share ``replayStateRef.current`` with
        // the SSE replay. The ``seq`` field on AgentEvent restarts at 1
        // on every runtime run — the events.jsonl file accumulates
        // events across many runs. The dedupe key (``eventDedupeKey``)
        // pairs seq with the event timestamp so it's run-independent,
        // but the disk pass still gets its own state so its keys can't
        // pre-empt the live SSE replay. The merge-by-id at the
        // message-list level below handles real duplicates safely.
        const replayState = newReplayState();
        const restored = replayEventsToMessages(
          events,
          "queen-dm",
          queenNameRef.current,
          undefined,
          replayState,
        );
        tr("replayEventsToMessages → restored", msgSummary(restored));

        // Sum historical llm_turn_complete events so usage carries over
        // across resume. SSE does not replay llm_turn_complete, so no
        // double-count risk. ``credits`` is null when no historical
        // event carried it (pre-Hive-aliased turns or direct provider
        // models) — distinguished from zero on purpose.
        const seed = {
          input: 0,
          output: 0,
          cached: 0,
          cacheCreated: 0,
          costUsd: 0,
          credits: null as number | null,
          requests: 0,
        };
        for (const evt of events) {
          if (evt.type !== "llm_turn_complete" || !evt.data) continue;
          const d = evt.data as Record<string, unknown>;
          seed.input += (d.input_tokens as number) || 0;
          seed.output += (d.output_tokens as number) || 0;
          seed.cached += (d.cached_tokens as number) || 0;
          seed.cacheCreated += (d.cache_creation_tokens as number) || 0;
          seed.costUsd += (d.cost_usd as number) || 0;
          seed.requests += 1;
          if (typeof d.credits === "number") {
            seed.credits = (seed.credits ?? 0) + d.credits;
          }
        }
        if (!cancelled()) {
          setTokenUsage((prev) => ({
            input: prev.input + seed.input,
            output: prev.output + seed.output,
            cached: prev.cached + seed.cached,
            cacheCreated: prev.cacheCreated + seed.cacheCreated,
            costUsd: prev.costUsd + seed.costUsd,
            credits:
              seed.credits === null
                ? prev.credits
                : (prev.credits ?? 0) + seed.credits,
            requests: prev.requests + seed.requests,
          }));
        }

        // Older events beyond this first page are fetched lazily on scroll-up
        // (see fetchOlderPage) — no truncation banner. Seed the cursor unless
        // a newer restore for a different session has cancelled this one.
        if (!cancelled()) {
          olderEventsRef.current = [];
          setOlderMessages([]);
          olderPageInFlightRef.current = false;
          olderCursorRef.current = {
            startOffset: start_offset,
            startIndex: start_index,
            hasMoreOlder: has_more_older,
          };
          setCurrentSessionHasMoreOlder(has_more_older);
          // Carry steer-injection boundaries from the disk restore into the
          // live replay state (queen-dm uses a separate ReplayState for SSE).
          // Without this, an in-progress steered iteration would re-segment
          // its queen bubble differently live vs restored and duplicate it.
          replayStateRef.current.queenInjections = replayState.queenInjections;
        }
        if (restored.length === 0) {
          tr("SKIP merge — restored is empty", { sid });
        } else if (cancelled()) {
          tr("SKIP merge — cancelled before merge", {
            sid,
            restoredCount: restored.length,
          });
        }
        if (restored.length > 0 && !cancelled()) {
          // Merge restored history into whatever's already on screen
          // instead of replacing wholesale. The live SSE replay (which
          // races us, see the race comment above) may already have
          // rendered the latest messages; setMessages(restored) used
          // to wipe those because eventsHistory only goes up to the
          // last disk flush.
          //
          // Strategy: build a Map from existing messages by id, layer
          // restored messages on top (disk history wins on id
          // collisions because tool-pill state may have been refined
          // as later events arrived during the same restore pass).
          // Tool-status pills go through ``mergeChatMessages`` so the
          // disk vs live merge unions both tools[] sets — without it,
          // a switch-back during active streaming silently drops
          // tools that the live SSE just rendered but the disk
          // events.jsonl write hasn't flushed yet. Anything
          // live-only (id not in restored) survives.
          setMessages((prev) => {
            const byId = new Map<string, ChatMessage>();
            for (const m of prev) byId.set(m.id, m);
            for (const m of restored) {
              const existing = byId.get(m.id);
              byId.set(m.id, existing ? mergeChatMessages(existing, m) : m);
            }
            const merged = Array.from(byId.values());
            merged.sort(
              (a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0),
            );
            tr("MERGE restored into messages", {
              sid,
              prev: msgSummary(prev),
              restored: msgSummary(restored),
              merged: msgSummary(merged),
            });
            return merged;
          });
          // Only clear typing if the history contains a completed execution;
          // during bootstrap the queen is still processing.
          const hasCompleted = events.some(
            (e: AgentEvent) => e.type === "execution_completed",
          );
          if (hasCompleted) {
          }
        }
        tr("DONE", { sid });
      } catch (err) {
        tr("FAILED", { sid, error: err instanceof Error ? err.message : String(err) });
        if (!cancelled()) {
          console.warn("[queen-dm] restoreMessages failed:", err);
        }
      }
    },
    [],
  );

  // ----- DEBUG INSTRUMENTATION: track which bootstrap-effect dep flipped --
  const depsTrackerRef = useRef<{
    queenId: string | undefined;
    selectedSessionParam: string | null;
    newSessionFlag: string | null;
    llmReady: boolean;
    restoreMessages: unknown;
    refresh: unknown;
    resetViewState: unknown;
    setSearchParams: unknown;
    triggerNoCreditPreview: unknown;
  } | null>(null);
  {
    const prev = depsTrackerRef.current;
    const next = {
      queenId,
      selectedSessionParam,
      newSessionFlag,
      llmReady,
      restoreMessages,
      refresh,
      resetViewState,
      setSearchParams,
      triggerNoCreditPreview,
    };
    if (prev) {
      const changed: string[] = [];
      if (prev.queenId !== next.queenId) changed.push("queenId");
      if (prev.selectedSessionParam !== next.selectedSessionParam) changed.push("selectedSessionParam");
      if (prev.newSessionFlag !== next.newSessionFlag) changed.push("newSessionFlag");
      if (prev.llmReady !== next.llmReady) changed.push("llmReady");
      if (prev.restoreMessages !== next.restoreMessages) changed.push("restoreMessages");
      if (prev.refresh !== next.refresh) changed.push("refresh");
      if (prev.resetViewState !== next.resetViewState) changed.push("resetViewState");
      if (prev.setSearchParams !== next.setSearchParams) changed.push("setSearchParams");
      if (prev.triggerNoCreditPreview !== next.triggerNoCreditPreview) changed.push("triggerNoCreditPreview");
      if (changed.length) {
        console.log(`[queen-dm:deps] changed=${changed.join(",")}`);
      }
    }
    depsTrackerRef.current = next;
  }
  // -----------------------------------------------------------------------

  useEffect(() => {
    const runId = ++bootstrapRunRef.current;
    // Open a fresh trace-log file for this resume flow. Every `log()` call
    // below is mirrored into it; async work (restoreMessages) carries this
    // same loadId so its records can't leak into a superseding run's file.
    const loadId = beginLoad(`bootstrap-${runId}`, {
      queenId,
      selectedSessionParam,
      newSessionFlag,
      llmReady,
    });
    const log = (msg: string, extra?: Record<string, unknown>) => {
      console.log(
        `[queen-dm:bootstrap #${runId}] ${msg}`,
        extra ?? "",
      );
      traceLoad("bootstrap", msg, extra, loadId);
    };

    log("ENTER", {
      queenId,
      selectedSessionParam,
      newSessionFlag,
      llmReady,
    });

    if (!queenId) {
      log("EXIT no queenId");
      return;
    }

    // If we arrived without an explicit session in the URL and aren't
    // bootstrapping a new one, redirect to the last session the user had
    // open for this queen.
    if (!selectedSessionParam && newSessionFlag !== "1") {
      const stored = readLastSession(queenId);
      log("checked readLastSession", { stored });
      if (stored && stored.startsWith("session_")) {
        log("REDIRECT to stored session, returning early", { stored });
        setSearchParams({ session: stored }, { replace: true });
        return;
      }
    }

    log("resetViewState + setLoading(true)");
    resetViewState();
    setLoading(true);
    // Any handoff belongs to the session load that claimed it. Dropping it here
    // means switching sessions can't hand a stale draft to a remounted composer
    // and send it a second time; the branch below re-sets it when this load is
    // the one delivering it.
    setHandoff(null);

    let cancelled = false;
    const isBootstrap = newSessionFlag === "1";
    // Read the pending first message up-front. We only *consume* it (remove
    // from session storage) once we've committed to a real bootstrap below;
    // the no-credit branch leaves it in place so the credit-recovery
    // rerun can use it as the queen's `initial_prompt`.
    const pendingFirstMessage = isBootstrap
      ? userStorage.session.get<string | null>(`queenFirstMessage:${queenId}`, null)
      : null;
    // A staged handoff is delivered as a real message through the composer
    // (that's the only path that can upload its files), never as the session's
    // `initial_prompt` — so the bootstrap below deliberately starts the session
    // with no prompt and lets the auto-send do the talking.
    const pendingHandoff = isBootstrap ? peekComposerHandoff(queenId) : null;

    // No-credit branch: we want the queen room to feel alive. Render the
    // greeting; if the user arrived with a prompt from /home, replay it
    // through `triggerNoCreditPreview` (user bubble + 2s typing dots →
    // upgrade modal). If they switched in via the sidebar with no pending
    // prompt, stay silent — the modal pops the moment they hit send (see
    // `handleSend`). Either way, no session is created here:
    // `assertSubscriptionActive` would 402, and even a successful create
    // can flow into LLM work.
    if (!llmReady) {
      log("BRANCH no-credit (llmReady=false), returning");
      deferredBootstrapRef.current = true;
      const greeting: ChatMessage = {
        id: makeId(),
        agent: queenName,
        agentColor: "",
        content: `Hi! I'm ${queenName}${queenTitle ? `, your ${queenTitle}` : ""}. What can I help you with today?`,
        timestamp: "",
        role: "queen",
        thread: "queen-dm",
        createdAt: Date.now(),
      };
      // Replay any optimistic "fake-sent" messages the user typed in a
      // prior visit so the transcript looks unchanged across navigation.
      const stored = readNoCreditMsgs(queenId);
      setMessages([greeting, ...stored]);
      setLoading(false);
      // Unlock the send button so the user can attempt their first
      // message — `triggerNoCreditPreview` (via handleSend) handles it
      // gracefully without ever calling the backend. Without this,
      // `sendLocked={loading || !queenReady}` would keep the composer
      // greyed out and the user couldn't send anything.
      setQueenReady(true);
      if (pendingFirstMessage) {
        triggerNoCreditPreview(pendingFirstMessage);
      }
      return () => {
        cancelled = true;
      };
    }
    // We're committing to a real bootstrap — consume the pending message
    // now so a URL rewrite or browser refresh won't replay it. Drop any
    // optimistic no-credit bubbles too: the real session takes over the
    // transcript from here on, and the queen will respond to the
    // pending-first-message via its `initial_prompt`.
    if (isBootstrap && pendingFirstMessage !== null) {
      userStorage.session.remove(`queenFirstMessage:${queenId}`);
    }
    // Same commit point for the handoff: hand it to the composer and drop the
    // staged copy, so a remount can't replay the send.
    if (pendingHandoff) {
      clearComposerHandoff(queenId);
      setInitialDraft(pendingHandoff.text);
      setHandoff(pendingHandoff);
    }
    clearNoCreditMsgs(queenId);
    deferredBootstrapRef.current = false;

    log("starting async block", { isBootstrap });
    (async () => {
      try {
        let bootstrapSessionId: string | null = null;
        // The session the backend actually resolves onto. selectSession
        // follows the fork chain, so selecting a forked-away (e.g. root)
        // session resolves forward to its latest live descendant.
        let resolvedSessionId: string | null = null;
        if (isBootstrap) {
          log("calling createNewSession");
          const bootstrapResult = await queensApi.createNewSession(
            queenId,
            // A handoff owns the first message; seeding it here too would send
            // it twice — once without its attachments.
            pendingHandoff ? undefined : pendingFirstMessage ?? undefined,
            "independent",
            crmSetupFlag,
          );
          log("createNewSession resolved", {
            cancelled,
            session_id: bootstrapResult.session_id,
          });
          bootstrapSessionId = bootstrapResult.session_id;
        } else if (selectedSessionParam) {
          log("calling selectSession (preflight)", { selectedSessionParam });
          const preflight = await queensApi.selectSession(
            queenId,
            selectedSessionParam,
          );
          if (preflight.status === "colony" && preflight.colony_id) {
            // Colony overseer session — the DM page never hosts these.
            // Drop the stored last-session pointer so re-opening this
            // queen's DM doesn't bounce through the redirect again, then
            // land on the colony page, which owns the resume.
            log("REDIRECT colony session → colony page", {
              sessionId: preflight.session_id,
              colonyId: preflight.colony_id,
            });
            if (readLastSession(queenId) === selectedSessionParam) {
              clearLastSession(queenId);
            }
            if (!cancelled) {
              navigate(`/colony/${slugToColonyId(preflight.colony_id)}`, {
                replace: true,
              });
            }
            return;
          }
          resolvedSessionId = preflight.session_id;
          log("selectSession (preflight) resolved", {
            cancelled,
            requested: selectedSessionParam,
            resolved: resolvedSessionId,
          });
        }
        if (cancelled) {
          log("EARLY RETURN after preflight: cancelled=true");
          return;
        }
        let sid: string;

        // Fast path: the preflight selectSession above already resolved
        // (and fork-corrected) the target — no extra API call needed, we
        // just adopt its result. When the clicked session had been forked
        // away from, `resolvedSessionId` is its latest live descendant,
        // not the raw URL param; rewrite the URL so the user lands on (and
        // a refresh rehydrates) the live session, not the dead root.
        if (
          selectedSessionParam &&
          selectedSessionParam.startsWith("session_")
        ) {
          sid = resolvedSessionId ?? selectedSessionParam;
          log("BRANCH fast-path: setSessionId", {
            requested: selectedSessionParam,
            sid,
          });
          setSessionId(sid);
          setQueenReady(true);
          if (selectedSessionParam !== sid) {
            // Fork-corrected: the clicked session had been forked away
            // from, so `sid` is its latest live descendant. Rewrite the
            // URL so a refresh rehydrates the live session; the effect
            // re-runs on the new param, but we still restore `sid` below
            // so this run paints without waiting on the re-run.
            // (cancelled re-check: a bootstrap resolving after the user
            // navigated away must not drag the router back here — this
            // was the "click Home, revive, but stay in the session" bug.)
            if (!cancelled) setSearchParams({ session: sid }, { replace: true });
          }
          // Don't hold the overlay hostage to the disk restore. Race it
          // against a short budget: if history lands fast (common case) the
          // user still sees the complete conversation appear at once — no
          // flicker. If the runtime is busy and the events/history read is
          // starved, drop the overlay after the budget and let the restore
          // *merge* in the background instead of pinning the switch on a
          // spinner for up to the 20s server timeout. The merge is
          // cancel-guarded and idempotent, so a late landing is safe.
          const restore = restoreMessages(sid, () => cancelled, loadId);
          await Promise.race([restore, delay(HISTORY_OVERLAY_BUDGET_MS)]);
          if (cancelled) return;
          refresh();
          return;
        }

        if (selectedSessionParam) {
          log("BRANCH historical session resume");
          const result = await queensApi.selectSession(
            queenId,
            selectedSessionParam,
          );
          log("selectSession resolved", { cancelled, session_id: result.session_id });
          if (cancelled) {
            log("EARLY RETURN after selectSession: cancelled=true");
            return;
          }
          sid = result.session_id;
          log("setSessionId (historical)", { sid });
          setSessionId(sid);
          setQueenReady(true);

          if (selectedSessionParam !== sid && !cancelled) {
            setSearchParams({ session: sid }, { replace: true });
          }
        } else {
          log("BRANCH no-URL-param", { has_bootstrap_sid: Boolean(bootstrapSessionId) });
          if (bootstrapSessionId) {
            sid = bootstrapSessionId;
          } else {
            log("calling getOrCreateSession");
            const result = await queensApi.getOrCreateSession(
              queenId,
              undefined,
              "independent",
            );
            log("getOrCreateSession resolved", {
              cancelled,
              session_id: result.session_id,
              status: result.status,
            });
            if (cancelled) {
              log("EARLY RETURN after getOrCreateSession: cancelled=true (SESSION DROPPED!)");
              return;
            }
            sid = result.session_id;
          }
          log("setSessionId (no-URL-param)", { sid });
          setSessionId(sid);
          setQueenReady(true);

          if (isBootstrap && !cancelled) {
            // Swap ?new=1 for ?session={sid} so a browser refresh rehydrates
            // this session instead of creating another new one.
            setSearchParams({ session: sid }, { replace: true });

            // Message was passed as initial_prompt so the queen is already
            // processing it. Show the optimistic user bubble; live SSE
            // events drive the four explicit signals from there.
            if (pendingFirstMessage && !cancelled) {
              const userMsg: ChatMessage = {
                id: makeId(),
                agent: "You",
                agentColor: "",
                content: pendingFirstMessage,
                timestamp: "",
                type: "user",
                thread: "queen-dm",
                createdAt: Date.now(),
              };
              setMessages((prev) => [...prev, userMsg]);
            }
          }

          if (!isBootstrap && selectedSessionParam && selectedSessionParam !== sid && !cancelled) {
            setSearchParams({ session: sid }, { replace: true });
          }
        }

        log("about to restoreMessages", { sid, cancelled });
        // Same overlay-budget race as the fast path above: never pin the
        // switch on a slow/starved history read — merge it in the background.
        const restore = restoreMessages(sid, () => cancelled, loadId);
        await Promise.race([restore, delay(HISTORY_OVERLAY_BUDGET_MS)]);
        log("restore done or overlay budget elapsed; calling refresh");
        refresh();
      } catch (err) {
        log("CAUGHT error in async block", { err: String(err), cancelled });
        // Stale-pointer recovery: the URL session came from our own
        // `readLastSession` redirect on run #1, and the backend just told
        // us it doesn't belong to this queen (session forked / deleted /
        // re-homed out of band). Wipe the cached pointer AND strip the
        // URL param so the effect reruns clean and picks up or creates a
        // real session — surfacing an error wall here would force the
        // user to click out of a problem we can fix ourselves.
        const wasStaleStored = Boolean(
          queenId &&
            selectedSessionParam &&
            selectedSessionParam === readLastSession(queenId),
        );
        if (wasStaleStored && queenId) {
          clearLastSession(queenId);
        }
        if (!cancelled) {
          if (wasStaleStored) {
            log("RECOVER from stale lastSession pointer: clearing ?session");
            setSearchParams({}, { replace: true });
          } else {
            const message =
              err instanceof Error ? err.message : String(err);
            setInitError(
              `Could not connect to session: ${message}`,
            );
          }
        }
      } finally {
        log("FINALLY", { cancelled });
        if (!cancelled) {
          setLoading(false);
          setSwitchingSessionId(null);
          setCreatingNewSession(false);
        }
      }
    })();

    return () => {
      log("CLEANUP firing → cancelled=true");
      cancelled = true;
    };
  }, [
    queenId,
    selectedSessionParam,
    newSessionFlag,
    crmSetupFlag,
    llmReady,
    restoreMessages,
    refresh,
    resetViewState,
    setSearchParams,
    triggerNoCreditPreview,
  ]);

  // Remember the session the user is currently viewing so switching queens
  // and coming back lands on it instead of whatever the server picks.
  useEffect(() => {
    if (!queenId || !sessionId) {
      console.log("[queen-dm:writeLastSession] SKIP", { queenId, sessionId });
      return;
    }
    console.log("[queen-dm:writeLastSession] WRITE", { queenId, sessionId });
    writeLastSession(queenId, sessionId);
  }, [queenId, sessionId]);

  useEffect(() => {
    if (!queenId) return;
    let cancelled = false;
    setHistoryLoading(true);

    sessionsApi
      .history()
      .then(({ sessions }) => {
        if (cancelled) return;
        const filtered = sessions
          .filter((session) => session.queen_id === queenId)
          // Newest-created first. `session_id` (session_YYYYMMDD_HHMMSS_<hash>)
          // is a total, deterministic creation-time tiebreak for the rare
          // case of equal `created_at` values.
          .sort(
            (a, b) =>
              b.created_at - a.created_at ||
              b.session_id.localeCompare(a.session_id),
          );
        // Populate the history-timeline navigator at the top of the chat,
        // but do NOT merge other sessions' events into the chat panel.
        // Cross-session aggregation made the chat show weeks-old April
        // messages no matter which session was active — the user expects
        // clicking a session to scope the visible chat to that session.
        setHistorySessions(filtered);
      })
      .catch(() => {
        if (!cancelled) setHistorySessions([]);
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [queenId, sessionId]);

  // Hydrate the colony-spawned lock + queen phase from the session detail
  // whenever the session ID changes. /sessions/{id} carries both flags
  // (and the cold-info path returns colony_spawned after a server restart),
  // so this single fetch covers live, page-reload, and post-restart states.
  // Without seeding queen_phase here the badge starts at the useState
  // default ("independent") and only updates when a fresh
  // QUEEN_PHASE_CHANGED SSE event fires — a reload mid-incubation would
  // briefly mis-render.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    sessionsApi
      .get(sessionId)
      .then((data) => {
        if (cancelled) return;
        const detail = data as {
          colony_spawned?: boolean;
          spawned_colony_id?: string | null;
          queen_phase?: "independent" | "colony";
        };
        setColonySpawned(Boolean(detail.colony_spawned));
        setSpawnedColonyName(detail.spawned_colony_id ?? null);
        if (
          detail.queen_phase === "independent" ||
          detail.queen_phase === "colony"
        ) {
          setQueenPhase(detail.queen_phase);
        }
      })
      .catch(() => {
        // Non-fatal — lock + phase simply won't activate until a fresh
        // SSE event arrives.
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const handleColonyLinkClick = useCallback(
    (colonyName: string) => {
      if (!sessionId || !colonyName) return;
      // Optimistically lock so the textarea swaps to the button before the
      // user navigates back. Backend persists the same flag in meta.json so
      // a refresh would re-hydrate the locked state anyway.
      setColonySpawned(true);
      setSpawnedColonyName(colonyName);
      executionApi.markColonySpawned(sessionId, colonyName).catch(() => {
        // Revert on failure so the user isn't stranded with no composer.
        setColonySpawned(false);
        setSpawnedColonyName(null);
      });
    },
    [sessionId],
  );

  const handleCompactAndFork = useCallback(async () => {
    if (!sessionId || compactingAndForking || !queenId) return;
    setCompactingAndForking(true);
    try {
      const result = await executionApi.compactAndFork(sessionId);
      // Navigate to the freshly-forked session for the same queen. Replacing
      // the URL keeps the back button on the home/history page rather than
      // bouncing back to the now-locked DM.
      setSearchParams({ session: result.new_session_id }, { replace: true });
    } catch {
      setCompactingAndForking(false);
    }
  }, [sessionId, compactingAndForking, queenId, setSearchParams]);

  const handleSelectHistoricalSession = useCallback(
    (nextSessionId: string) => {
      if (!nextSessionId || nextSessionId === sessionId) return;
      setSwitchingSessionId(nextSessionId);
      setSearchParams({ session: nextSessionId });
    },
    [sessionId, setSearchParams],
  );

  // Toggle inline expansion of a historical session under the history
  // timeline. First expand fetches the session's events from disk and
  // replays them into a ChatMessage[]; subsequent expands reuse the
  // cache. Active session is NEVER touched — this is read-only peek.
  const handleToggleHistorySession = useCallback(
    (sid: string) => {
      if (!sid) return;
      setExpandedHistorySessions((prev) => {
        const next = new Set(prev);
        if (next.has(sid)) {
          next.delete(sid);
          return next;
        }
        next.add(sid);
        // Fetch on first expand only — cache survives toggles within
        // the same page visit so collapse/re-expand is instant.
        setHistorySessionMessages((cache) => {
          if (sid in cache) return cache;
          // Mark as "loading" by NOT putting the key yet — the panel
          // detects undefined and shows a loading hint.
          void (async () => {
            try {
              // Load only the newest page; older pages stream in as the user
              // scrolls up within this session (see fetchOlderPageForSession).
              const res = await sessionsApi.eventsHistory(sid, {
                limit: EVENTS_PAGE_SIZE,
              });
              historySessionEventsRef.current[sid] = res.events;
              historySessionCursorsRef.current[sid] = {
                startOffset: res.start_offset,
                startIndex: res.start_index,
                hasMoreOlder: res.has_more_older,
              };
              const replayed = replayOlderEvents(
                res.events,
                "queen-dm",
                queenName,
              );
              setHistorySessionMessages((c) => ({ ...c, [sid]: replayed }));
              setHistoryCursorTick((t) => t + 1);
            } catch (err) {
              console.warn(`[queen-dm] failed to load events for ${sid}:`, err);
              setHistorySessionMessages((c) => ({ ...c, [sid]: [] }));
            }
          })();
          return cache;
        });
        return next;
      });
    },
    [queenName],
  );

  const handleCreateNewSession = useCallback(() => {
    if (!queenId) return;
    // Bounce through the ?new=1 bootstrap path so the chat shell appears
    // immediately with a typing indicator while createNewSession runs in
    // the background. URL is replaced with ?session=<id> when it resolves.
    // Avoids the 5s "nothing happens, then chat appears" dead window.
    setSearchParams({ new: "1" });
  }, [queenId, setSearchParams]);

  // Header action: "Report a problem" once a session exists. (The
  // QueenSessionSwitcher used to live here but the surface was crowded;
  // sessions remain reachable from the history list.)
  useEffect(() => {
    setActions(sessionId ? <SessionReportAction sessionId={sessionId} /> : null);
    return () => setActions(null);
  }, [setActions, sessionId]);

  // SSE handler
  const handleSSEEvent = useCallback(
    (_agentType: string, event: AgentEvent) => {
      // Action Plan panel trigger. Task lifecycle events are emitted at
      // stream_id="primary" (see the runtime's tasks/events.py), NOT
      // "queen", so they must be handled BEFORE the queen-stream guard
      // below — otherwise `task_created` is dropped and the panel never
      // auto-opens. The panel's task data comes from TaskListContext's
      // own SSE subscription (which filters by data.session_id, not
      // stream_id); here we only flip the panel visible.
      if (event.type === "task_created" || event.type === "node_action_plan") {
        setActionPlanOpen(true);
      }

      // Worker streams: let their META events through (execution_started,
      // subagent_report, execution_completed/failed, …). Those are what
      // anchor and fill a worker's bubble — task, status and result all come
      // from the workers poll, so no per-turn chatter is needed here.
      //
      // The server only sends a worker's chatter to a client that explicitly
      // asked to watch that worker (?watch=worker:<id>), and this page never
      // does, so anything arriving on a worker stream is already meta-only.
      // Previously this early-returned on EVERY non-queen event, which meant
      // worker bubbles never appeared live — they only materialised after a
      // reload, once the history replay picked the worker events off disk.
      const isQueen = event.stream_id === "queen";
      const isWorker = (event.stream_id ?? "").startsWith("worker");
      if (!isQueen && !isWorker) return;

      // Drop genuine duplicates — the SSE ring-buffer replay redelivers
      // events on every resubscribe, and the wider replay set (TOOL_CALL_*,
      // EXECUTION_*, LLM_TURN_COMPLETE) would otherwise render tool pills
      // twice and double-count token totals.
      //
      // The dedupe key pairs `seq` with the event timestamp. Bare `seq`
      // is NOT unique: the runtime restarts its seq counter at 1 on every
      // new run, so over a long-lived page mount a fresh job's events
      // (seq 1, 2, 3 …) collide with an earlier run's already-seen seqs
      // and the whole job is dropped — the user watches the latest
      // messages get swallowed and only a force-reload brings them back.
      const dedupeKey = eventDedupeKey(event);
      if (dedupeKey !== null) {
        if (replayStateRef.current.seenEventKeys.has(dedupeKey)) {
          traceLoad("sse", "DEDUP drop", {
            type: event.type,
            seq: event.seq,
            ts: event.timestamp,
            key: dedupeKey,
          });
          return;
        }
        replayStateRef.current.seenEventKeys.add(dedupeKey);
      }
      traceLoad("sse", "event", {
        type: event.type,
        seq: event.seq,
        ts: event.timestamp,
        execId: event.execution_id,
      });

      // Feed the debug panel's event log and replay state snapshot
      debug.pushEvent(event);
      const _pushDebugReplay = () => {
        const rs = replayStateRef.current;
        debug.setReplay({
          turnCounters: { ...rs.turnCounters },
          toolTrackers: Object.keys(rs.toolTrackers).length,
          seenSeqsSize: rs.seenEventKeys.size,
          snapshotSeq: rs.snapshotSeq,
        });
      };

      // session_forked is a navigation-control event — it must switch the
      // URL to the successor session unconditionally. Handle it HERE,
      // ahead of the historical-event guard below: when the queen calls
      // task_create(new_session=true) the old session is retired, the SSE
      // resubscribes, and the ring buffer replays session_forked as a
      // "historical" event (seq <= snapshotSeq). The guard would then
      // return before the `switch` ever runs, so the URL never swaps and
      // the user is stranded on the dead session until a manual refresh.
      // Swapping ?session= re-runs the loading effect (refetches the new
      // session, useMultiSSE reconnects); `replace` keeps the back button
      // off the retired session. Idempotent — swapping to the session
      // you're already on is a no-op.
      if (event.type === "session_forked") {
        const newId = event.data?.new_session_id as string | undefined;
        if (typeof newId === "string" && newId) {
          setSearchParams({ session: newId }, { replace: true });
        }
        return;
      }

      // Synthesised session_snapshot: rehydrate "queen is busy" state
      // from the server's current view of the ring buffer. Sent as
      // the very first frame on every fresh SSE subscribe so the
      // user never sees a "looks dead" window after revisit.
      if (event.type === "session_snapshot") {
        const d = (event.data ?? {}) as {
          snapshot_seq?: number;
          activity?: string | null;
          is_executing?: boolean;
          awaiting_input?: boolean;
          interrupted?: boolean;
          interrupt_cause?: string | null;
          queen_busy_reason?: string | null;
          park_reason?: string | null;
          current_tool_calls?: Array<{ name: string | null; started_at: string | null }>;
          pending_questions?: Array<{ id: string; prompt: string; options?: string[] }> | null;
        };
        if (typeof d.snapshot_seq === "number") {
          replayStateRef.current.snapshotSeq = d.snapshot_seq;
        }
        traceLoad("sse", "session_snapshot", {
          snapshot_seq: d.snapshot_seq,
          is_executing: d.is_executing,
          awaiting_input: d.awaiting_input,
          busy_reason: d.queen_busy_reason,
          ts: event.timestamp,
        });
        // Stamp when this snapshot was published. The `seq <= snapshotSeq`
        // historical guard below pairs with this: a new run resets `seq`
        // to 1, so its live events also have low seqs — only a timestamp
        // at/before the snapshot proves an event is genuinely historical.
        replayStateRef.current.snapshotAt = event.timestamp
          ? new Date(event.timestamp).getTime()
          : Date.now();
        // Mirror snapshot fields into the debug panel
        snapStateRef.current = {
          activity: d.activity ?? null,
          is_executing: d.is_executing,
          awaiting_input: d.awaiting_input,
          interrupted: d.interrupted,
          interrupt_cause: d.interrupt_cause ?? null,
          snapshot_seq: d.snapshot_seq,
          busy_reason: d.queen_busy_reason,
          park_reason: d.park_reason ?? null,
          open_tools: Array.isArray((d as Record<string,unknown>).current_tool_calls)
            ? String(((d as Record<string,unknown>).current_tool_calls as unknown[]).length)
            : "0",
        };
        // INTERRUPTED — the loop is not moving and it is NOT a deliberate
        // end-of-turn (broken park, stream stall, crash). Mutually
        // exclusive with awaiting_input; rehydrate it before that check.
        setInterrupted(!!d.interrupted);
        setInterruptCause(d.interrupted ? (d.interrupt_cause ?? null) : null);
        if (d.interrupted) {
          setAwaitingInput(false);
          setParkReason(d.park_reason ?? null);
          setQueenReady(true);
          setIsStreaming(false);
          return;
        }
        // Awaiting-input is the strongest signal: queen is paused on
        // the user, not working. Show the modal, keep the typing dot
        // off, clear any stale tool indicator. The backend's snapshot
        // already suppresses is_executing when awaiting_input=true,
        // but defend against older runtimes by checking here too.
        if (d.awaiting_input) {
          setAwaitingInput(true);
          setParkReason(d.park_reason ?? null);
          setQueenReady(true);
          setIsStreaming(false);
          // CRITICAL: seed pendingQuestions from the snapshot. Without
          // this, replayed CLIENT_INPUT_REQUESTED events fall under
          // the past-event guard (seq <= snapshotSeq) and never reach
          // the switch case that populates pendingQuestions, so the
          // modal can't render and the user has no way to answer the
          // queen.
          if (Array.isArray(d.pending_questions) && d.pending_questions.length > 0) {
            setPendingQuestions(d.pending_questions);
          }
          return;
        }
        // Snapshot is authoritative in BOTH directions. The old
        // "only flip ON from positive signals" stance assumed live
        // events would always clear isStreaming on the way out — but
        // the clearing events (llm_turn_complete etc.) could be
        // dropped under backpressure, and every reconnect then
        // re-seeded isStreaming=true with nothing ever clearing it:
        // the composer queued messages forever until a page refresh.
        setQueenReady(true);
        // "tool" busy_reason means a tool from an in-flight LLM turn is
        // still running — the queen is still mid-LLM-loop, so the typing
        // indicator belongs on. Only "llm"/"tool" (i.e. is_executing &&
        // !awaiting_input) qualify; null means idle.
        if (d.queen_busy_reason === "llm" || d.queen_busy_reason === "tool") {
          setIsStreaming(true);
        } else {
          // Server says idle — reconcile the stuck-streaming case and
          // deliver anything the closed gate accumulated.
          setIsStreaming(false);
          flushNextPendingRef.current?.();
        }
        // The in-flight tool surface is the inline tool_status pill
        // (one per tool_use_id, deduped across replay paths). The SSE
        // ring buffer redelivers tool_call_started for any open call,
        // so the pill materializes shortly after the snapshot applies
        // — no separate seed required.
        return;
      }

      // Past events delivered through the SSE ring-buffer replay (seq
      // <= snapshotSeq): their net effect is already captured in the
      // snapshot we just applied. Render their transcript bubbles
      // (pills, text) via replayEvent's emittedMessages, but skip
      // the state-mutation switch below — otherwise execution_started
      // from 5s ago would re-flip active and llm_turn_complete
      // would double-add token usage.
      const emittedMessages = replayEvent(
        replayStateRef.current,
        event,
        "queen-dm",
        queenName,
      );
      const eventPublishedAt = event.timestamp
        ? new Date(event.timestamp).getTime()
        : 0;
      if (
        typeof event.seq === "number" &&
        event.seq > 0 &&
        replayStateRef.current.snapshotSeq > 0 &&
        event.seq <= replayStateRef.current.snapshotSeq &&
        // A low seq is only genuinely "historical" when the event was
        // also published at or before the snapshot. The runtime restarts
        // `seq` at 1 each run, so a fresh job's live execution_started /
        // llm_turn_complete also carry low seqs — but a newer timestamp.
        // Without this check they'd be misread as replayed history: the
        // typing spinner would never light and token usage wouldn't
        // count. Fall back to seq-only when either timestamp is missing.
        (replayStateRef.current.snapshotAt === 0 ||
          eventPublishedAt === 0 ||
          eventPublishedAt <= replayStateRef.current.snapshotAt)
      ) {
        traceLoad("sse", "historical (seq<=snapshotSeq) — upsert only, skip state", {
          type: event.type,
          seq: event.seq,
          emitted: emittedMessages.length,
        });
        for (const msg of emittedMessages) upsertMessage(msg);
        _pushDebugReplay();
        return;
      }

      // Worker meta anchors and fills the worker's bubble — it must never
      // drive the QUEEN's state. The switch below owns queen-level UI (the
      // typing spinner, token totals, the ready flag); letting a worker's
      // execution_started through would light the queen's spinner, and its
      // execution_completed would clear one the queen never started.
      if (isWorker) {
        for (const msg of emittedMessages) upsertMessage(msg);
        _pushDebugReplay();
        return;
      }

      switch (event.type) {
        // ... (switch body unchanged)
        case "execution_started":
          setQueenReady(true);
          // Light up the spinner at the start of every queen turn and keep
          // it lit until `execution_completed` / `awaiting_input` ends the
          // turn. Without this the spinner would only show during text
          // streaming and disappear during tool calls or between LLM
          // hops — the user would see "thinking" gaps that don't match
          // the queen's actual workload.
          setIsStreaming(true);
          // Do NOT clear `queued` on user messages here. The pending queue
          // hook owns that flag — it's cleared on steer / cancel / flush.
          // If the user has queued messages that haven't been flushed yet,
          // the queen starting a new turn (e.g. from a steer or from the
          // flush itself) shouldn't hide the still-queued ones.
          break;

        case "execution_completed":
          setIsStreaming(false);
          break;

        case "llm_turn_complete":
          if (event.data) {
            const inp = (event.data.input_tokens as number) || 0;
            const out = (event.data.output_tokens as number) || 0;
            const cached = (event.data.cached_tokens as number) || 0;
            const cacheCreated = (event.data.cache_creation_tokens as number) || 0;
            const costUsd = (event.data.cost_usd as number) || 0;
            // credits is omitted by the runtime when the turn had no
            // Hive-aliased call carrying upstream usage.credits — keep
            // the prior value (null stays null until at least one turn
            // reports credits).
            const rawCredits = event.data.credits;
            const credits = typeof rawCredits === "number" ? rawCredits : null;
            setTokenUsage((prev) => ({
              input: prev.input + inp,
              output: prev.output + out,
              cached: prev.cached + cached,
              cacheCreated: prev.cacheCreated + cacheCreated,
              costUsd: prev.costUsd + costUsd,
              credits:
                credits === null ? prev.credits : (prev.credits ?? 0) + credits,
              requests: prev.requests + 1,
            }));
            // Live turn (SSE never replays llm_turn_complete): feed the
            // app-wide usage total and tick the header balance down
            // optimistically.
            addUsage({
              input: inp,
              output: out,
              cached,
              cacheCreated,
              costUsd,
              credits,
              requests: 1,
            });
            if (credits !== null) noteCreditSpend(credits);
          }
          // LLM call finished — but the queen may immediately call a tool
          // or loop into another LLM call. Don't clear isStreaming here;
          // the spinner stays lit until `execution_completed` or
          // `awaiting_input` actually ends the turn.
          // Flush one queued message per LLM turn boundary. Skip for
          // cancelled turns: handleCancelQueen already drained one
          // queued message synchronously.
          if (event.data?.stop_reason !== "cancelled") {
            flushNextPendingRef.current();
          }
          break;

        case "client_output_delta":
        case "llm_text_delta": {
          for (const msg of emittedMessages) upsertMessage(msg);
          setIsStreaming(true);
          break;
        }

        case "llm_reasoning_delta":
        case "client_reasoning": {
          // Live thinking bubble — the point is feedback DURING the silent
          // reasoning phase, so these must upsert live, not only on replay.
          for (const msg of emittedMessages) upsertMessage(msg);
          setIsStreaming(true);
          break;
        }

        case "node_loop_started":
        case "node_loop_iteration":
          // Loop entered / iterated — queen is doing work. Some
          // queens never emit ``execution_started`` (auto-park
          // sessions); these are the only signal we get.
          // node_loop_iteration is published immediately before
          // _run_single_turn in agent_loop.py — i.e. it's the
          // definitive "LLM call is about to be made" signal.
          // Flip isStreaming here so the indicator doesn't go dark
          // between a tool_call_completed and the first text delta
          // of the next LLM hop.
          setQueenReady(true);
          setIsStreaming(true);
          break;

        case "client_input_requested": {
          const rawQuestions = event.data?.questions;
          const questions = Array.isArray(rawQuestions)
            ? (rawQuestions as {
                id: string;
                prompt: string;
                options?: string[];
              }[])
            : null;
          // An empty-prompt client_input_requested means the queen parked
          // in auto-wait. If we just auto-flushed a queued message, our
          // inject will unblock her in a moment — skip flipping active
          // off so the thinking bubble doesn't flicker.
          if (queenAboutToResumeRef.current && !questions) {
            queenAboutToResumeRef.current = false;
            break;
          }
          // Stash the question bubble (synthesized by replayEvent) instead
          // of upserting now: while the popup widget is open the user only
          // wants to see ONE copy of the question. We commit the bubble on
          // client_input_received so it lands right above the user's
          // answer in the transcript.
          if (emittedMessages.length > 0) {
            pendingAskUserBubbleRef.current = emittedMessages[0];
          }
          setAwaitingInput(true);
          setParkReason((event.data?.park_reason as string | undefined) ?? null);
          setIsStreaming(false);
          setPendingQuestions(questions);
          break;
        }

        case "client_input_received": {
          // Commit the stashed ask_user bubble first so it appears above
          // the user's reply in scroll-back. Its createdAt predates this
          // event's, so the timestamp-ordered insert in upsertMessage
          // places it correctly.
          if (pendingAskUserBubbleRef.current) {
            upsertMessage(pendingAskUserBubbleRef.current);
            pendingAskUserBubbleRef.current = null;
          }
          for (const msg of emittedMessages) {
            upsertMessage(msg, { reconcileOptimisticUser: true });
          }
          // Clear any pending-question UI state. Idempotent in the
          // live flow (handleSend already cleared it on submit), but
          // critical in the replay flow: without this, an
          // already-resolved client_input_requested would leave the
          // modal stuck open after revisit. The backend also filters
          // resolved requests out of the SSE replay (see
          // collect_resolved_request_seqs in event_bus.py); this is
          // the renderer-side belt to that suspenders.
          setPendingQuestions(null);
          setAwaitingInput(false);
          setParkReason(null);
          setInterrupted(false);
          setInterruptCause(null);
          break;
        }

        case "client_input_committed": {
          // The message was just drained into the conversation. This event's
          // timestamp is the true injection moment — after the in-flight turn
          // that was streaming when the message arrived. Re-stamp the matching
          // user bubble (by correlation id) so it sorts at its real position
          // instead of at receive time (which predates that turn's tail).
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

        case "loop_state_changed": {
          // The agent loop's authoritative top-level state. Set
          // awaitingInput / interrupted / parkReason / interruptCause
          // together from this one event so they stay mutually exclusive.
          const activity = event.data?.activity as string | undefined;
          const pr = (event.data?.park_reason as string | undefined) ?? null;
          const ic = (event.data?.interrupt_cause as string | undefined) ?? null;
          const isAwaiting = activity === "awaiting_user";
          const isInterrupted = activity === "interrupted";
          setAwaitingInput(isAwaiting);
          setInterrupted(isInterrupted);
          setParkReason(isAwaiting || isInterrupted ? pr : null);
          setInterruptCause(isInterrupted ? ic : null);
          if (isAwaiting || isInterrupted) setIsStreaming(false);
          break;
        }

        case "queen_phase_changed": {
          const rawPhase = event.data?.phase as string;
          if (rawPhase === "independent" || rawPhase === "colony") {
            setQueenPhase(rawPhase);
          }
          break;
        }

        case "colony_suggestion_requested": {
          // Two variants share this event:
          //
          // (a) DM suggest_colony — colony_id is queen-proposed; user
          //     authors goal + handover.
          // (b) Colony pivot via task_create(new_colony=true) — colony_id
          //     is empty (user picks the slug); goal + handoff are
          //     queen-authored and shown read-only; backend already has
          //     the rich payload server-side.
          //
          // ``source_phase`` discriminates: "colony" → pivot variant;
          // anything else (incl. absent) → DM variant.
          const data = (event.data ?? {}) as {
            colony_id?: string;
            reason?: string | null;
            source_phase?: string;
            goal?: string | null;
            handoff?: string | null;
            task_count?: number | null;
          };
          const isPivot = data.source_phase === "colony";
          const slug = (data.colony_id || "").toLowerCase().replace(/[^a-z0-9_]/g, "");
          // DM variant requires a queen-proposed slug; the pivot variant
          // intentionally starts blank for the user to fill in.
          if (!slug && !isPivot) break;
          setCloneSuggestion({
            colonyName: slug,
            reason: data.reason?.trim() || null,
            sourcePhase: isPivot ? "colony" : "independent",
            goal: isPivot ? (data.goal?.trim() || null) : null,
            handoff: isPivot ? (data.handoff?.trim() || null) : null,
            taskCount: isPivot ? (typeof data.task_count === "number" ? data.task_count : null) : null,
          });
          setCloneColonyName(slug);
          // Pivot variant: clear goal/handover inputs since the queen
          // authored them and they're shown read-only. DM variant: clear
          // so the user fills them in fresh.
          setCloneGoal("");
          setCloneHandover("");
          setCloneError(null);
          setCloneSubmitting(false);
          setCloneDialogOpen(true);
          break;
        }

        case "client_credential_form_requested": {
          // Queen called credentials(action="collect"): pop a secure form.
          // The queen is parked until the form is submitted or cancelled.
          const data = (event.data ?? {}) as Partial<AgentCredentialFormRequest>;
          if (
            !data.credential_id ||
            !data.correlation_id ||
            !Array.isArray(data.fields) ||
            data.fields.length === 0
          ) {
            break;
          }
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

        case "colony_created": {
          // Queen called create_colony() — surface a clickable system
          // message linking to /colony/{colony_id} so the user can
          // navigate to the new colony immediately.
          const colonyId = (event.data?.colony_id as string) || "";
          const isNew = (event.data?.is_new as boolean) ?? true;
          const skillName = (event.data?.skill_name as string) || "";
          if (!colonyId) break;
          // ColonyContext keys colonies by slugToColonyId(slug), not by the
          // raw snake_case directory name. Apply the same transform so the
          // /colony/:colonyId route lookup in colony-chat.tsx resolves.
          const routeId = slugToColonyId(colonyId);
          const msg: ChatMessage = {
            id: makeId(),
            agent: "System",
            agentColor: "",
            content: JSON.stringify({
              kind: "colony_created",
              colony_id: colonyId,
              is_new: isNew,
              skill_name: skillName,
              href: `/colony/${routeId}`,
            }),
            timestamp: "",
            type: "colony_link",
            thread: "queen-dm",
            createdAt: Date.now(),
          };
          setMessages((prev) => [...prev, msg]);
          // Refresh the sidebar's colony list so the new colony shows up
          // under "Colonies" immediately (without requiring a page
          // reload or the 30s status poll).
          refresh();
          break;
        }

        case "tool_call_started": {
          for (const msg of emittedMessages) upsertMessage(msg);
          setQueenReady(true);
          // Defensive: ensure the spinner is on while a tool is executing.
          // execution_started already raised it for normal turn starts,
          // but the queen can spawn tool calls outside an execution_started
          // (e.g. auto-park sessions). Keep the indicator honest.
          setIsStreaming(true);
          break;
        }

        case "tool_call_completed": {
          for (const msg of emittedMessages) upsertMessage(msg);
          break;
        }

        case "context_compaction_started": {
          setIsCompacting(true);
          break;
        }

        case "context_compacted": {
          const d = (event.data ?? {}) as {
            usage_before?: number;
            usage_after?: number;
          };
          setIsCompacting(false);
          if (typeof d.usage_before === "number" && typeof d.usage_after === "number") {
            setLastCompaction({
              before: d.usage_before,
              after: d.usage_after,
              at: Date.now(),
            });
          }
          break;
        }

        case "context_usage_updated": {
          const d = (event.data ?? {}) as {
            usage_pct?: number;
            estimated_tokens?: number;
            max_context_tokens?: number;
            message_count?: number;
            trigger?: string;
            breakdown?: {
              conversation_chars?: number;
              system_chars?: number;
              tool_defs_chars?: number;
              image_blocks?: number;
            };
          };
          if (typeof d.estimated_tokens === "number") {
            setContextUsage({
              usagePct: d.usage_pct ?? 0,
              estimatedTokens: d.estimated_tokens,
              maxContextTokens: d.max_context_tokens ?? 0,
              messageCount: d.message_count ?? 0,
              trigger: d.trigger ?? "",
              conversationChars: d.breakdown?.conversation_chars ?? 0,
              systemChars: d.breakdown?.system_chars ?? 0,
              toolDefsChars: d.breakdown?.tool_defs_chars ?? 0,
              imageBlocks: d.breakdown?.image_blocks ?? 0,
              at: Date.now(),
            });
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

        default:
          break;
      }
      _pushDebugReplay();
    },
    [queenName, refresh, upsertMessage, setSearchParams, addUsage, noteCreditSpend],
  );

  // ---- Debug state mirroring -----------------------------------------
  // Poll the queen's task list for the debug panel. Light (one localhost
  // GET) and only meaningfully consumed when the panel is open.
  useEffect(() => {
    if (!sessionId) {
      setDebugTasks([]);
      return;
    }
    let cancelled = false;
    const poll = () => {
      tasksApi
        .getList(sessionId)
        .then((snap) => {
          if (!cancelled) setDebugTasks(snap?.tasks ?? []);
        })
        .catch(() => {
          /* 404 / network — leave the last snapshot */
        });
    };
    poll();
    const iv = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [sessionId]);

  // Sync queen state into window.__hive_debug_state so the DebugPanel
  // overlay can display all UI-affecting state in real time.  Replay
  // state is pushed in handleSSEEvent (immediately after each event)
  // to avoid a setState-in-useEffect loop.
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__hive_debug_state = {
      active,
      isStreaming,
      awaitingInput,
      parkReason,
      interrupted,
      interruptCause,
      pendingQuestions,
      tasks: debugTasks,
      queenPhase,
      sseState,
      lastEventAt,
      sessionId,
      isCompacting,
      lastCompaction,
      contextUsage,
      reminders,
      ...snapStateRef.current,
    };
  }, [
    active,
    isStreaming,
    awaitingInput,
    parkReason,
    interrupted,
    interruptCause,
    pendingQuestions,
    debugTasks,
    queenPhase,
    sseState,
    lastEventAt,
    sessionId,
    isCompacting,
    lastCompaction,
    contextUsage,
    reminders,
  ]);

  const sseSessions = useMemo((): Record<string, string> => {
    if (sessionId) return { "queen-dm": sessionId };
    return {};
  }, [sessionId]);

  // Auto-resume nonce — bumped when SSE reports the session id gone
  // (HTTP 404) so useMultiSSE re-mounts after we've re-created the
  // session in the runtime via queen_resume_from. See onSessionGone.
  const [sseResumeNonce, setSseResumeNonce] = useState(0);
  const resumingRef = useRef(false);

  useMultiSSE({
    sessions: sseSessions,
    onEvent: (agentType, event) => {
      // Live event arrived → mark stream as live and bump activity ts.
      // Note: this fires even for replayed events on subscribe, which
      // is the right time to consider the queen "active" — the queue
      // just delivered something.
      setSseState("live");
      setLastEventAt(Date.now());
      handleSSEEvent(agentType, event);
    },
    onConnectionState: (_agentType, state) => {
      setSseState(state);
    },
    onSessionGone: (_agentType, goneSessionId) => {
      // Runtime lost this session — hive-serve was restarted and its
      // in-memory session_manager is empty, but the queen_dir on disk
      // is intact. Recreate the same session id via queen_resume_from
      // so the queen loads from disk; SSE URL stays identical.
      if (resumingRef.current) return;
      resumingRef.current = true;
      void (async () => {
        try {
          await sessionsApi.create({
            queenResumeFrom: goneSessionId,
            queenName: queenId || undefined,
          });
          setSseResumeNonce((n) => n + 1);
        } catch (err) {
          console.error(
            "[queen-dm] auto-resume after session-gone failed:",
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

  // On session switch, reset the activity clock so the prior queen's
  // staleness doesn't carry over.
  useEffect(() => {
    setLastEventAt(Date.now());
    setSseState("live");
  }, [sessionId]);

  // Core backend send — used both for immediate sends and for Steer /
  // auto-flush paths out of the pending queue.
  const sendToBackend = useCallback(
    (text: string, images?: ImageContent[], displayMessage?: string): boolean => {
      // `false` = not accepted — the pending queue keeps its entry and
      // retries on the next flush instead of destroying the message.
      if (!sessionId) return false;
      // Flip isStreaming optimistically so the typing dots / message
      // spinner show the instant the user sends, instead of waiting
      // for the first llm_text_delta (which can lag by a second or
      // more on cold turns). The real SSE flow keeps it accurate
      // afterwards: llm_text_delta reasserts true, llm_turn_complete /
      // terminal events flip it false. .catch() below clears it if
      // the request itself fails before any event arrives.
      setIsStreaming(true);
      executionApi.chat(sessionId, text, images, displayMessage).catch((err) => {
        console.error("[queen-dm] chat failed:", err);
        setIsStreaming(false);
      });
      return true;
    },
    [sessionId],
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
      queenAboutToResumeRef.current = true;
    }, []),
  });

  // ── Stall watchdog ─────────────────────────────────────────────────
  // Self-heal for lost gate events: isStreaming is cleared only by SSE
  // events that can be dropped (backpressure) or never arrive (silently
  // dead TCP). If we look busy but nothing has arrived for 20s, ask the
  // server for its authoritative snapshot and reconcile — clearing the
  // gate and flushing any queued messages instead of waiting for a
  // manual page refresh.
  const lastEventAtRef = useRef(lastEventAt);
  lastEventAtRef.current = lastEventAt;
  const watchdogBusyRef = useRef(false);
  useEffect(() => {
    if (!sessionId || !isStreaming) return;
    const iv = setInterval(async () => {
      if (Date.now() - lastEventAtRef.current < 20_000) return;
      if (watchdogBusyRef.current) return;
      watchdogBusyRef.current = true;
      try {
        const snap = await api.get<{ queen_busy_reason?: string | null }>(
          `/sessions/${sessionId}/snapshot`,
        );
        const busy =
          snap.queen_busy_reason === "llm" || snap.queen_busy_reason === "tool";
        if (!busy) {
          console.warn(
            "[queen-dm] stall watchdog: server idle but isStreaming stuck — reconciling",
          );
          setIsStreaming(false);
          flushNextPendingRef.current?.();
        } else {
          // Server really is busy; the stream is just quiet. Reset the
          // clock so we don't hammer the endpoint every 5s.
          setLastEventAt(Date.now());
        }
      } catch {
        // 404 (session being recycled) / transient network — leave state
        // alone; the session-gone path handles real disappearance.
      } finally {
        watchdogBusyRef.current = false;
      }
    }, 5_000);
    return () => clearInterval(iv);
  }, [sessionId, isStreaming]);

  // Reset the queue whenever we navigate to a different queen. The hook
  // outlives the route change (same component instance), so without this,
  // a message queued for Queen A would auto-flush into Queen B's session
  // on B's next execution_completed.
  useEffect(() => {
    clearPendingQueue();
  }, [queenId, clearPendingQueue]);

  // Send handler. Queues when the queen is mid-turn (unless the user is
  // answering an ask_user prompt, which must send immediately to unblock
  // the loop). Queued messages are held locally until Steer, Cancel, or
  // the next `execution_completed` auto-flush.
  const handleSend = useCallback(
    (text: string, _thread: string, images?: ImageContent[], displayMessage?: string, displayImages?: ImageContent[]) => {
      // Out-of-credit path: render the user's message, fake-type for
      // ~2s, then pop the upgrade modal. No session, no backend call —
      // see `triggerNoCreditPreview`. This is the same flow used by the
      // /home → queen bootstrap when the user lands here with a stashed
      // prompt; both end up in the same helper so the experience is
      // consistent regardless of how the user got here.
      if (!llmReady) {
        triggerNoCreditPreview(text, images, displayMessage, displayImages);
        return;
      }

      const answeringQuestion = awaitingInput;
      if (answeringQuestion) {
        setAwaitingInput(false);
        setPendingQuestions(null);
      }

      // Queue while the queen has visible work in flight — streaming
      // text or any open tool tracker. Anything else (truly idle,
      // parked, thinking-between-events) sends through immediately;
      // the backend serializes if it lands mid-turn.
      const hasOpenTool = Object.values(
        replayStateRef.current.toolTrackers,
      ).some((t) => t.streamId === "queen" && !t.entry.done);
      const shouldQueue =
        !answeringQuestion && (isStreaming || hasOpenTool);

      const msgId = makeId();
      const userMsg: ChatMessage = {
        id: msgId,
        agent: "You",
        agentColor: "",
        // Show the display message in the chat bubble, not the full extracted content
        content: displayMessage || text,
        timestamp: "",
        type: "user",
        thread: "queen-dm",
        createdAt: Date.now(),
        // Show display images (with file chips) in the bubble, fall back to LLM images
        images: displayImages || images,
        queued: shouldQueue,
        // Server echoes carry the full extracted text — stash the original
        // for the content-based reconciler so the chip bubble survives.
        _reconcileContent: displayMessage ? text : undefined,
      };
      setMessages((prev) => [...prev, userMsg]);

      if (shouldQueue) {
        enqueuePending(msgId, { text, images, displayMessage });
        return;
      }

      sendToBackend(text, images, displayMessage);
    },
    [llmReady, triggerNoCreditPreview, awaitingInput, isStreaming, sendToBackend, enqueuePending],
  );

  const resetCloneDialogFields = useCallback(() => {
    setCloneColonyName("");
    setCloneGoal("");
    setCloneHandover("");
    setCloneError(null);
    setCloneSubmitting(false);
  }, []);

  // Close the dialog without creating the colony. Three paths:
  //
  // - Suggested DM path (source_phase=independent or absent): queen is
  //   parked on _input_ready after a synthetic suggest_colony intercept;
  //   inject a chat message to unblock her tool call and continue the chat.
  // - Colony-pivot path (source_phase=colony): queen is parked the same
  //   way after the task_create(new_colony=true) intercept, but the
  //   wake-up happens via a dedicated POST to dismiss-colony-pivot —
  //   that endpoint clears pending_colony_pivot AND injects a synthetic
  //   message telling the queen to call ask_user for explicit direction.
  // - Manual path (no suggestion — header button opened the dialog):
  //   no pending tool call, just close.
  const handleCloneDialogClose = useCallback(() => {
    const suggestion = cloneSuggestion;
    setCloneDialogOpen(false);
    setCloneSuggestion(null);
    resetCloneDialogFields();
    if (!suggestion || !sessionId) return;
    if (suggestion.sourcePhase === "colony") {
      sessionsApi.dismissColonyPivot(sessionId).catch(() => {
        /* best-effort — UI is already closed */
      });
    } else {
      const dismissMsg = `[Dismissed colony suggestion for '${suggestion.colonyName}'. Continue working in this chat.]`;
      executionApi.chat(sessionId, dismissMsg, undefined, "").catch(() => {
        /* best-effort — UI is already closed */
      });
    }
  }, [cloneSuggestion, sessionId, resetCloneDialogFields]);

  const handleColonySpawn = useCallback(async () => {
    if (cloneSubmitting) return;
    const colony = cloneColonyName.trim();
    if (!colony || !sessionId) return;

    setCloneError(null);
    setCloneSubmitting(true);
    try {
      // Two backends:
      //
      // - Pivot variant (sourcePhase === "colony"): the backend has the
      //   queen-authored {goal, handoff, tasks} stashed on
      //   session.pending_colony_pivot. We POST only colonyId +
      //   sourceSessionId — the backend's _create_sibling_colony_from_colony
      //   reads the lean handoff server-side and seeds the new colony.
      //   No initialPrompt is needed (and the seed message is built
      //   from the handoff, not from initial_prompt).
      //
      // - DM/manual variant: user authored goal + handover in the
      //   dialog inputs; combine them into the colony queen's first
      //   user message (sent as initial_prompt).
      const isPivot = cloneSuggestion?.sourcePhase === "colony";
      let initialPrompt = "";
      if (!isPivot) {
        const goal = cloneGoal.trim();
        const handover = cloneHandover.trim();
        initialPrompt = [
          goal && `Goal: ${goal}`,
          handover && `Knowledge to carry over from the previous chat:\n${handover}`,
        ]
          .filter(Boolean)
          .join("\n\n");
      }
      const live = await sessionsApi.create({
        colonyId: colony,
        colonyGoal: initialPrompt || undefined,
        sourceSessionId: sessionId,
        // Backend's ``queen_name`` body field is actually the queen
        // profile id (resolves to ``QUEENS_DIR/<id>/profile.yaml``).
        // Send the route's ``queenId`` — the display ``queenName`` would
        // 404 for any user with a custom display override.
        queenName: queenId || undefined,
        initialPhase: "colony",
      });
      // Backend's _create_colony_from_source (DM source) and
      // _create_sibling_colony_from_colony (colony source) both inject
      // an unblock message into the source session after the fork.
      setCloneDialogOpen(false);
      setCloneSuggestion(null);
      resetCloneDialogFields();
      // Carry an ``initialGoal`` into the new colony page so its mount
      // flips queenIsTyping=true optimistically — the colony queen
      // starts processing the seed before the SSE connection opens
      // post-navigation, and without this hint the user sees a blank
      // chat with no spinner until the first text delta lands. For DM
      // suggest_colony this is the user-typed initialPrompt; for the
      // pivot variant it's the queen-authored goal (initialPrompt is
      // empty since the seed is server-side).
      const initialGoal =
        initialPrompt || (isPivot ? cloneSuggestion?.goal || "" : "");
      navigate(`/colony/${slugToColonyId(live.colony_id || colony)}`, {
        state: initialGoal ? { initialGoal } : undefined,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to create colony";
      setCloneError(msg);
      setCloneSubmitting(false);
    }
  }, [
    cloneColonyName,
    cloneGoal,
    cloneHandover,
    cloneSubmitting,
    cloneSuggestion,
    navigate,
    queenId,
    resetCloneDialogFields,
    sessionId,
  ]);

  const handleQuestionAnswer = useCallback(
    (answers: Record<string, string>) => {
      const questions = pendingQuestions;
      setAwaitingInput(false);
      setPendingQuestions(null);
      // For a single question, send just the answer text. For a batch,
      // send `"prompt"="answer"` pairs so the agent can map replies back.
      const entries = Object.entries(answers);
      const promptFor = (id: string) =>
        questions?.find((q) => q.id === id)?.prompt ?? id;
      const formatted =
        entries.length === 1
          ? entries[0][1]
          : entries
              .map(([id, val]) => `"${promptFor(id)}"="${val}"`)
              .join("\n");
      handleSend(formatted, "queen-dm");
    },
    [handleSend, pendingQuestions],
  );

  const handleCancelQueen = useCallback(async () => {
    if (!sessionId) return;
    try {
      await executionApi.cancelQueen(sessionId);
      setIsStreaming(false);
      replayStateRef.current = newReplayState();
      // After cancelling the current turn, immediately send the oldest
      // queued message (if any). The remaining queued messages stay put
      // so the user can review them or Steer/Cancel individually.
      flushNextPending();
    } catch {
      // ignore
    }
  }, [sessionId, flushNextPending]);

  // Group all sessions (except current) by date for the history timeline.
  // Kept above the `!queenId` early return so the hook order stays stable
  // when the user navigates between queens (otherwise React errors with
  // "Rendered fewer hooks than expected").
  const historyByDay = useMemo(() => {
    const otherSessions = historySessions.filter((s) => s.session_id !== sessionId);
    if (otherSessions.length === 0) return [];
    const dayMap = new Map<string, typeof otherSessions>();
    for (const s of otherSessions) {
      const d = new Date(s.created_at * 1000);
      const dk = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const arr = dayMap.get(dk) || [];
      arr.push(s);
      dayMap.set(dk, arr);
    }
    return [...dayMap.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([dk, sessions]) => ({
        key: dk,
        label: (() => {
          const d = new Date(dk + "T12:00:00");
          const now = new Date();
          const today = now.toISOString().slice(0, 10);
          const yest = new Date(now.getTime() - 86400000).toISOString().slice(0, 10);
          if (dk === today) return "Today";
          if (dk === yest) return "Yesterday";
          return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
        })(),
        sessions: sessions.sort((a, b) => a.created_at - b.created_at),
      }));
  }, [historySessions, sessionId]);

  // Sessions are PARALLEL conversations — one queen can serve several
  // concurrent chats (different counterparts, long-lived threads) — not a
  // linear timeline. Rendering the other sessions as scrollback "previous
  // sessions" above the active chat misreads them, so the inline timeline
  // stays off; navigation lives in the header QueenSessionSwitcher.
  // (`historyByDay` is intentionally unused now but kept computed so the
  // grouping logic stays exercised for a future opt-in timeline.)
  const historyTimelineForPanel = undefined;
  void historyByDay;

  // Prior sessions of this queen, newest first, for the Action Plan's
  // "Previous sessions" fold. After a session fork the just-left session
  // lands here automatically — historySessions refetches on sessionId
  // change — so the old plan stays reachable without crowding the new one.
  const previousSessionPlans = useMemo<PreviousSessionInfo[]>(
    () =>
      historySessions
        .filter((s) => s.session_id !== sessionId)
        .map((s) => ({
          sessionId: s.session_id,
          // Seconds included — forked sessions can be minutes (or less)
          // apart, so minute precision alone makes them indistinguishable.
          label: new Date(s.created_at * 1000).toLocaleString(undefined, {
            month: "short",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
            second: "2-digit",
          }),
        })),
    [historySessions, sessionId],
  );

  if (!queenId) {
    return (
      <div className="flex items-center justify-center h-full bg-background">
        <p className="text-sm text-muted-foreground">No queen selected.</p>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 flex flex-col">
      {/* Chat */}
      <div className="flex-1 min-h-0 relative">
        <ChatPanel
          messages={combinedMessages}
          currentSessionHasMoreOlder={currentSessionHasMoreOlder}
          onFetchOlderPage={fetchOlderPage}
          historySessionHasMoreOlder={historySessionHasMoreOlder}
          onFetchOlderPageForSession={fetchOlderPageForSession}
          onSend={handleSend}
          onCancel={handleCancelQueen}
          onSteer={handleSteer}
          onCancelQueued={handleCancelQueued}
          activeThread="queen-dm"
          isWaiting={isStreaming}
          isBusy={isStreaming}
          // Keep the textarea typable while the queen is warming up so the
          // user can compose a follow-up immediately. Send stays locked
          // until the session is live and the queen is ready.
          //
          // Out-of-credit users intentionally see the *normal* send
          // button — clicking it routes through `handleSend` →
          // `triggerNoCreditPreview` (optimistic bubble + 2s typing dots
          // + upgrade modal), which feels like a real send instead of a
          // hard wall. ChatPanel's `paymentLocked` lock-icon mode is
          // unused here for that reason.
          sendLocked={loading || !queenReady}
          queenPhase={queenPhase}
          showQueenPhaseBadge
          queenTitle={queenTitle}
          pendingQuestions={awaitingInput ? pendingQuestions : null}
          onQuestionSubmit={handleQuestionAnswer}
          onQuestionDismiss={() => {
            setAwaitingInput(false);
            setPendingQuestions(null);
          }}
          supportsImages={true}
          sessionId={sessionId}
          historyTimeline={historyTimelineForPanel}
          expandedHistoryDays={expandedHistoryDays}
          onToggleHistoryDay={(dk) => setExpandedHistoryDays((prev) => {
            const next = new Set(prev);
            if (next.has(dk)) next.delete(dk);
            else next.add(dk);
            return next;
          })}
          onSelectHistorySession={handleSelectHistoricalSession}
          expandedHistorySessions={expandedHistorySessions}
          onToggleHistorySession={handleToggleHistorySession}
          historySessionMessages={historySessionMessages}
          initialDraft={initialDraft}
          initialAttachments={handoff?.files ?? null}
          autoSendToken={handoff?.token ?? null}
          queenProfileId={queenId ?? null}
          queenId={queenId}
          onColonyLinkClick={handleColonyLinkClick}
          colonySpawned={colonySpawned}
          spawnedColonyName={spawnedColonyName}
          queenDisplayName={queenName}
          queenPortraitOverride={queenPortraitOverride}
          onCompactAndFork={handleCompactAndFork}
          compactingAndForking={compactingAndForking}
          onStartNewSession={handleCreateNewSession}
          startingNewSession={creatingNewSession}
          tokenUsage={tokenUsage}
          sseState={sseState}
          lastEventAt={lastEventAt}
          headerAction={
            <div className="flex items-center gap-1.5">
              <QueenSessionSwitcher
                sessions={historySessions}
                currentSessionId={sessionId}
                loading={historyLoading}
                creatingNew={creatingNewSession}
                onSelect={(sid) => setSearchParams({ session: sid })}
                onCreateNew={handleCreateNewSession}
              />
              <button
                onClick={() => setActionPlanOpen((open) => !open)}
                disabled={!sessionId}
                title={
                  actionPlanOpen
                    ? "Hide the Action Plan panel"
                    : "Show the Action Plan panel"
                }
                className={
                  "flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors disabled:opacity-40 " +
                  (actionPlanOpen
                    ? "bg-primary/10 text-primary"
                    : "text-primary hover:bg-primary/10")
                }
              >
                <ListTodo className="w-3 h-3" />
                Action Plan
              </button>
              <button
                onClick={() => setCloneDialogOpen(true)}
                disabled={!sessionId}
                className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium text-primary hover:bg-primary/10 transition-colors disabled:opacity-40"
              >
                <Plus className="w-3 h-3" />
                Start Colony
              </button>
            </div>
          }
        />
        {/* Loading overlay — covers the chat until the session's history
            has been restored, so the conversation is revealed fully
            populated rather than assembled live in front of the user.
            The parent div is `relative`; this sits opaque on top. */}
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background">
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground/60" />
          </div>
        )}
      </div>

      {credentialForm && sessionId && (
        <AgentCredentialForm
          sessionId={sessionId}
          request={credentialForm}
          onClose={() => setCredentialForm(null)}
        />
      )}

      {cloneDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => {
              if (!cloneSubmitting) handleCloneDialogClose();
            }}
          />
          <div className="relative flex w-full max-w-lg h-[min(560px,88vh)] flex-col overflow-hidden rounded-xl border border-border/60 bg-card shadow-2xl">
            <div className="px-6 pt-5 pb-3 space-y-1">
              <h2 className="text-sm font-semibold text-foreground">
                {cloneSuggestion?.sourcePhase === "colony"
                  ? "Spawn a new colony for this work?"
                  : cloneSuggestion
                  ? `Create colony '${cloneSuggestion.colonyName}'?`
                  : "Set Up a Colony"}
              </h2>
              <p className="text-[11px] text-muted-foreground">
                {cloneSuggestion?.sourcePhase === "colony"
                  ? "The current colony's queen has identified this work as off-goal for this colony and wants to spawn a fresh sibling colony for it. The current colony stays alive and untouched."
                  : cloneSuggestion
                  ? "The queen suggested creating a colony for this work. Confirm the name (you can edit) and create — this chat will be compacted into the new colony's queen seed."
                  : "Confirm the name and any optional brief. The new colony's queen picks up from a compacted copy of this conversation."}
              </p>
              {cloneSuggestion?.reason && (
                <p className="mt-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-[11px] text-foreground">
                  <span className="font-medium">Queen's reason: </span>
                  {cloneSuggestion.reason}
                </p>
              )}
            </div>
            <div className="flex-1 overflow-y-auto px-6 pb-4 space-y-3">
              {cloneSuggestion?.sourcePhase === "colony" && cloneSuggestion?.goal && (
                <div>
                  <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                    New colony's goal <span className="text-muted-foreground/40">(authored by the queen)</span>
                  </label>
                  <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm text-foreground whitespace-pre-wrap">
                    {cloneSuggestion.goal}
                  </div>
                </div>
              )}
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                  Colony name
                  {cloneSuggestion?.sourcePhase === "colony" && (
                    <span className="text-muted-foreground/40"> (you choose — slug)</span>
                  )}
                </label>
                <input
                  type="text"
                  value={cloneColonyName}
                  onChange={(e) =>
                    setCloneColonyName(
                      e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""),
                    )
                  }
                  placeholder={
                    cloneSuggestion?.sourcePhase === "colony"
                      ? "e.g. uber_eats_research"
                      : "e.g. research_team"
                  }
                  className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary"
                  autoFocus
                />
              </div>
              {cloneSuggestion?.sourcePhase === "colony" ? (
                <>
                  {cloneSuggestion?.handoff && (
                    <div>
                      <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                        Handover to new colony's queen
                        <span className="text-muted-foreground/40"> (authored by the queen, read-only)</span>
                      </label>
                      <div className="max-h-48 overflow-y-auto rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-[12px] text-foreground whitespace-pre-wrap leading-relaxed">
                        {cloneSuggestion.handoff}
                      </div>
                    </div>
                  )}
                  {typeof cloneSuggestion?.taskCount === "number" && cloneSuggestion.taskCount > 0 && (
                    <p className="text-[11px] text-muted-foreground">
                      {cloneSuggestion.taskCount === 1
                        ? "1 task will be seeded in the new colony."
                        : `${cloneSuggestion.taskCount} tasks will be seeded in the new colony.`}
                    </p>
                  )}
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                      Goal <span className="text-muted-foreground/40">(optional)</span>
                    </label>
                    <textarea
                      value={cloneGoal}
                      onChange={(e) => setCloneGoal(e.target.value)}
                      placeholder="Describe what this colony should work on"
                      rows={3}
                      className="w-full resize-none rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                      Knowledge to hand over <span className="text-muted-foreground/40">(optional)</span>
                    </label>
                    <textarea
                      value={cloneHandover}
                      onChange={(e) => setCloneHandover(e.target.value)}
                      placeholder="Anything the new colony queen should know from this chat — decisions, constraints, who to contact, etc."
                      rows={4}
                      className="w-full resize-none rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                </>
              )}
            </div>
            {cloneError && (
              <div className="border-t border-destructive/30 bg-destructive/10 px-6 py-2 text-[11px] text-destructive">
                {cloneError}
              </div>
            )}
            <div className="mt-auto flex justify-end gap-2 border-t border-border/50 px-6 py-4">
              <button
                onClick={handleCloneDialogClose}
                disabled={cloneSubmitting}
                className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors disabled:opacity-50"
              >
                {cloneSuggestion ? "Dismiss" : "Cancel"}
              </button>
              <button
                onClick={handleColonySpawn}
                disabled={!cloneColonyName.trim() || cloneSubmitting}
                className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {cloneSubmitting ? "Creating…" : "Create Colony"}
              </button>
            </div>
          </div>
        </div>
      )}
      </div>

      {/* Action Plan rail — renders the queen's session task list. Driven
          by `actionPlanOpen`, which auto-opens on task_created /
          node_action_plan SSE events and on session load (see the
          effects above). */}
      {actionPlanOpen && sessionId && (
        <TaskListPanel
          variant="rail"
          title="Action Plan"
          sessionId={sessionId}
          previousSessions={previousSessionPlans}
          onClose={() => setActionPlanOpen(false)}
        />
      )}
    </div>
  );
}
