import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useParams, useLocation } from "react-router-dom";
import { Loader2, WifiOff, KeyRound, FolderOpen, X, Users } from "lucide-react";
import type { GraphNode, NodeStatus } from "@/components/graph-types";
import ChatPanel, { type ChatMessage, type ImageContent } from "@/components/ChatPanel";
import CredentialsModal, {
  type Credential,
  clearCredentialCache,
} from "@/components/CredentialsModal";
import { executionApi } from "@/api/execution";
import { sessionsApi } from "@/api/sessions";
import { useMultiSSE } from "@/hooks/use-sse";
import type { LiveSession, AgentEvent } from "@/api/types";
import {
  sseEventToChatMessage,
  formatAgentDisplayName,
  replayEventsToMessages,
} from "@/lib/chat-helpers";
import {
  resolveInitialColonyPhase,
  shouldUsePrefetchedColonyRestore,
} from "@/lib/colony-session-restore";
import { cronToLabel } from "@/lib/graphUtils";
import { ApiError } from "@/api/client";
import { useColony } from "@/context/ColonyContext";
import { useHeaderActions } from "@/context/HeaderActionsContext";
import { useColonyWorkers } from "@/context/ColonyWorkersContext";
import { agentSlug, getQueenForAgent } from "@/lib/colony-registry";
import BrowserStatusBadge from "@/components/BrowserStatusBadge";

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
  restoredPhase: "independent" | "incubating" | "working" | "reviewing" | null;
  truncated: boolean;
  droppedCount: number;
};

async function restoreSessionMessages(
  sessionId: string,
  thread: string,
  agentDisplayName: string,
  queenDisplayName?: string,
): Promise<SessionRestoreResult> {
  try {
    const { events, truncated, total, returned } =
      await sessionsApi.eventsHistory(sessionId);
    if (events.length > 0) {
      // Walk events twice:
      //   1. Extract the trailing queen phase (unchanged logic).
      //   2. Run the full state-machine replay so tool_status pills
      //      are synthesized just like the live SSE handler does.
      // Without (2), refreshed sessions showed zero tool activity
      // because tool_call_started/completed events are ignored by
      // the stateless converter.
      let runningPhase: ChatMessage["phase"] = undefined;
      for (const evt of events) {
        const p =
          evt.type === "queen_phase_changed"
            ? (evt.data?.phase as string)
            : evt.type === "node_loop_iteration"
              ? (evt.data?.phase as string | undefined)
              : undefined;
        if (p && ["independent", "working", "reviewing"].includes(p)) {
          runningPhase = p as ChatMessage["phase"];
        }
      }

      const messages = replayEventsToMessages(events, thread, agentDisplayName, queenDisplayName);
      // Stamp the latest phase on every queen message so the UI's
      // phase-badge rendering matches what the live path would have
      // displayed at the time of the refresh.
      if (runningPhase) {
        for (const m of messages) {
          if (m.role === "queen") m.phase = runningPhase;
        }
      }

      // Prepend a run_divider banner when the server truncated older
      // events so the user knows how many are hidden.
      const droppedCount = Math.max(0, total - returned);
      if (truncated && droppedCount > 0) {
        const firstTs = events[0]?.timestamp;
        const bannerCreatedAt = firstTs ? new Date(firstTs).getTime() - 1 : 0;
        messages.unshift({
          id: `restore-truncated-${sessionId}`,
          agent: "System",
          agentColor: "",
          type: "run_divider",
          content: `${droppedCount.toLocaleString()} older event${droppedCount === 1 ? "" : "s"} not shown (showing last ${returned.toLocaleString()})`,
          timestamp: firstTs ?? new Date().toISOString(),
          thread,
          createdAt: bannerCreatedAt,
        });
      }
      return {
        messages,
        restoredPhase: runningPhase ?? null,
        truncated,
        droppedCount,
      };
    }
  } catch {
    // Event log not available
  }
  return { messages: [], restoredPhase: null, truncated: false, droppedCount: 0 };
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
  queenPhase: "independent" | "incubating" | "working" | "reviewing";
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
  isTyping: boolean;
  isStreaming: boolean;
  queenIsTyping: boolean;
  workerIsTyping: boolean;
  llmSnapshots: Record<string, string>;
  activeToolCalls: Record<string, { name: string; done: boolean; streamId: string }>;
  pendingQuestion: string | null;
  pendingOptions: string[] | null;
  pendingQuestions: { id: string; prompt: string; options?: string[] }[] | null;
  pendingQuestionSource: "queen" | null;
  contextUsage: Record<
    string,
    { usagePct: number; messageCount: number; estimatedTokens: number; maxTokens: number }
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
    isTyping: false,
    isStreaming: false,
    queenIsTyping: false,
    workerIsTyping: false,
    llmSnapshots: {},
    activeToolCalls: {},
    pendingQuestion: null,
    pendingOptions: null,
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
  const { setActions } = useHeaderActions();
  const { toggleColonyWorkers } = useColonyWorkers();

  // Route state from home page (new chat flow)
  const routeState = (location.state || {}) as {
    prompt?: string;
    agentPath?: string;
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
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [credentials] = useState<Credential[]>([]);
  const [agentState, setAgentState] = useState<AgentState>(defaultAgentState);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [credentialAgentPath, setCredentialAgentPath] = useState<string | null>(null);
  const [dismissedBanner, setDismissedBanner] = useState<string | null>(null);

  // ── Header actions (Credentials, Data, Browser) ─────────────────────────
  useEffect(() => {
    setActions(
      <>
        <button
          onClick={() => setCredentialsOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
        >
          <KeyRound className="w-3.5 h-3.5" />
          Credentials
        </button>
        {agentState.sessionId && (
          <button
            onClick={() => sessionsApi.revealFolder(agentState.sessionId!).catch(() => {})}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
            title="Open session data folder"
          >
            <FolderOpen className="w-3.5 h-3.5" />
            Data
          </button>
        )}
        {agentState.sessionId && (
          <button
            onClick={() => toggleColonyWorkers()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
            title="Show / hide the colony workers panel"
          >
            <Users className="w-3.5 h-3.5" />
            Workers
          </button>
        )}
        <BrowserStatusBadge />
      </>,
    );
    return () => setActions(null);
  }, [agentState.sessionId, setActions, toggleColonyWorkers]);

  // Refs for SSE callback stability
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const agentStateRef = useRef(agentState);
  agentStateRef.current = agentState;

  const turnCounterRef = useRef<Record<string, number>>({});
  // Timestamp of the latest restored message — SSE events older than this
  // are duplicates from the ring-buffer replay and should be skipped.
  const restoreCutoffRef = useRef<number>(0);
  // Maps tool_use_id → the pill message ID and tool name that was created for it.
  // Survives turn counter resets so deferred completions (e.g. ask_user) can
  // find and update the correct pill even after the counter changes.
  const toolUseToPillRef = useRef<
    Record<string, { msgId: string; name: string }>
  >({});
  const queenPhaseRef = useRef<string>("independent");
  const queenIterTextRef = useRef<Record<string, Record<number, string>>>({});
  const suppressIntroRef = useRef(false);
  const loadingRef = useRef(false);

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
          // Match by content + timestamp across the whole list (not just
          // the last slot) so a queued user message still reconciles
          // even when the queen's previous reply slotted in between.
          // Also drops the "queued" indicator since the backend has
          // now confirmed receipt.
          const incomingTs = chatMsg.createdAt ?? Date.now();
          const matchIdx = prev.findIndex(
            (m) =>
              m.type === "user" &&
              m.content === chatMsg.content &&
              Math.abs(incomingTs - (m.createdAt ?? incomingTs)) <= 15000,
          );
          if (matchIdx !== -1) {
            return prev.map((m, i) =>
              i === matchIdx ? { ...m, id: chatMsg.id, queued: undefined } : m,
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
    // For new chats without an agent, create a queen-only session
    if (!agentPath && isNewChat) {
      loadingRef.current = true;
      updateState({ loading: true, error: null, ready: false, sessionId: null });
      try {
        const session = await sessionsApi.create(
          undefined, undefined, undefined,
          routeState.prompt || undefined,
        );
        updateState({
          sessionId: session.session_id,
          displayName: "New Chat",
          queenPhase: "independent",
          loading: false,
          ready: true,
        });
      } catch (err: unknown) {
        updateState({ loading: false, error: String(err) });
      } finally {
        loadingRef.current = false;
      }
      return;
    }
    if (!agentPath) return;
    loadingRef.current = true;
    updateState({ loading: true, error: null, ready: false, sessionId: null });

    try {
      let liveSession: LiveSession | undefined;
      let isResumedSession = false;
      let coldRestoreId: string | undefined;
      let prefetchedRestore: SessionRestoreResult | null = null;

      // Check for existing live session for this agent
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

      // Check cold history if no live session
      if (!liveSession) {
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

      let restoredPhase: "independent" | "incubating" | "working" | "reviewing" | null = null;

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

        // Create new session (pass coldRestoreId for resume)
        liveSession = await sessionsApi.create(agentPath, undefined, undefined, undefined, coldRestoreId ?? undefined);
      }

      const session = liveSession!;
      const displayName = formatAgentDisplayName(session.colony_name || agentPath);
      let restoredMessages: ChatMessage[] = [];
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
        restoredPhase = restored.restoredPhase;
      } else if (prefetchedRestore) {
        if (reusePrefetchedRestore) {
          restoredMessages = prefetchedRestore.messages;
          restoredPhase = prefetchedRestore.restoredPhase;
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
          restoredPhase = restored.restoredPhase;
        }
      }

      if (restoredMessages.length > 0) {
        restoredMessages.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
        setMessages(restoredMessages);
        // Record the latest restored timestamp so SSE replay duplicates are skipped
        const maxTs = Math.max(...restoredMessages.map((m) => m.createdAt ?? 0));
        restoreCutoffRef.current = maxTs;
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

      updateState({
        sessionId: session.session_id,
        colonyDirName: session.colony_id,
        displayName,
        queenPhase: initialPhase,
        queenSupportsImages: session.queen_supports_images !== false,
        ready: true,
        loading: false,
        queenReady: hasRestoredContent,
      });
    } catch (err: unknown) {
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
  }, [agentPath, isNewChat, routeState.prompt, updateState]);

  // Load session on mount or when agent path changes
  useEffect(() => {
    if (agentPath || isNewChat) {
      // Reset state for new colony
      setMessages([]);
      setGraphNodes([]);
      setAgentState(defaultAgentState());
      turnCounterRef.current = {};
      toolUseToPillRef.current = {};
      queenPhaseRef.current = "independent";
      queenIterTextRef.current = {};
      suppressIntroRef.current = false;
      restoreCutoffRef.current = 0;
      loadingRef.current = false;
      loadSession();
    }
  }, [agentPath, isNewChat]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── SSE event handler ──────────────────────────────────────────────────

  const handleSSEEvent = useCallback(
    (_agentType: string, event: AgentEvent) => {
      const streamId = event.stream_id;
      const isQueen = streamId === "queen";
      const suppressQueenMessages = isQueen && suppressIntroRef.current;
      const state = agentStateRef.current;
      const agentDisplayName = state.displayName;
      const displayName = isQueen ? queenInfo.name : agentDisplayName || undefined;
      const role = isQueen ? ("queen" as const) : ("worker" as const);
      const ts = fmtLogTs(event.timestamp);
      const turnKey = streamId;
      const currentTurn = turnCounterRef.current[turnKey] ?? 0;
      const eventCreatedAt = event.timestamp
        ? new Date(event.timestamp).getTime()
        : Date.now();

      // Skip SSE replay events that were already restored from history
      if (
        restoreCutoffRef.current > 0 &&
        eventCreatedAt <= restoreCutoffRef.current &&
        (event.type === "client_output_delta" || event.type === "llm_text_delta" || event.type === "client_input_received")
      ) {
        return;
      }

      const shouldMarkQueenReady = isQueen && !state.queenReady;

      switch (event.type) {
        case "execution_started":
          if (isQueen) {
            turnCounterRef.current[turnKey] = currentTurn + 1;
            updateState({
              isTyping: true,
              queenIsTyping: true,
              ...(shouldMarkQueenReady && { queenReady: true }),
            });
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
            turnCounterRef.current[turnKey] = currentTurn + 1;
            updateState({
              isTyping: true,
              isStreaming: false,
              workerIsTyping: true,
              awaitingInput: false,
              currentRunId: incomingRunId,
              nodeLogs: {},
              subagentReports: [],
              llmSnapshots: {},
              activeToolCalls: {},
              pendingQuestion: null,
              pendingOptions: null,
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
            markAllNodesAs(["running", "looping", "complete", "error"], "pending");
          }
          break;

        case "execution_completed":
          if (isQueen) {
            suppressIntroRef.current = false;
            updateState({ isTyping: false, queenIsTyping: false });
          } else {
            updateState({
              isTyping: false,
              isStreaming: false,
              workerIsTyping: false,
              awaitingInput: false,
              workerInputMessageId: null,
              llmSnapshots: {},
              pendingQuestion: null,
              pendingOptions: null,
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
            markAllNodesAs(["running", "looping"], "complete");
          }
          break;

        case "execution_paused":
        case "execution_failed":
        case "client_output_delta":
        case "client_input_received":
        case "client_input_requested":
        case "llm_text_delta": {
          const chatMsg = sseEventToChatMessage(event, agentPath, displayName, currentTurn);
          if (chatMsg && !suppressQueenMessages) {
            // Merge queen inner_turns within same iteration
            if (
              isQueen &&
              (event.type === "client_output_delta" || event.type === "llm_text_delta") &&
              event.execution_id
            ) {
              const iter = event.data?.iteration ?? 0;
              const inner = (event.data?.inner_turn as number) ?? 0;
              const iterKey = `${event.execution_id}:${iter}`;
              if (!queenIterTextRef.current[iterKey]) {
                queenIterTextRef.current[iterKey] = {};
              }
              const snapshot =
                (event.data?.snapshot as string) || (event.data?.content as string) || "";
              queenIterTextRef.current[iterKey][inner] = snapshot;
              const parts = queenIterTextRef.current[iterKey];
              const sorted = Object.keys(parts)
                .map(Number)
                .sort((a, b) => a - b);
              chatMsg.content = sorted.map((k) => parts[k]).join("\n");
              chatMsg.id = `queen-stream-${event.execution_id}-${iter}`;
            }
            if (isQueen) {
              chatMsg.role = role;
              chatMsg.phase = queenPhaseRef.current as ChatMessage["phase"];
            }
            upsertMessage(chatMsg, {
              reconcileOptimisticUser: event.type === "client_input_received",
            });
          }

          if (event.type === "llm_text_delta" || event.type === "client_output_delta") {
            updateState({
              isStreaming: true,
              ...(isQueen ? {} : { workerIsTyping: false }),
            });
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
            const rawOptions = event.data?.options;
            const options = Array.isArray(rawOptions) ? (rawOptions as string[]) : null;
            const rawQuestions = event.data?.questions;
            const questions = Array.isArray(rawQuestions)
              ? (rawQuestions as { id: string; prompt: string; options?: string[] }[])
              : null;
            if (isQueen) {
              const prompt = (event.data?.prompt as string) || "";
              updateState({
                awaitingInput: true,
                isTyping: false,
                isStreaming: false,
                queenIsTyping: false,
                pendingQuestion: prompt || null,
                pendingOptions: options,
                pendingQuestions: questions,
                pendingQuestionSource: "queen",
              });
            }
          }

          if (event.type === "execution_paused") {
            updateState({
              isTyping: false,
              isStreaming: false,
              queenIsTyping: false,
              workerIsTyping: false,
              awaitingInput: false,
              pendingQuestion: null,
              pendingOptions: null,
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
            if (!isQueen) {
              markAllNodesAs(["running", "looping"], "pending");
            }
          }

          if (event.type === "execution_failed") {
            updateState({
              isTyping: false,
              isStreaming: false,
              queenIsTyping: false,
              workerIsTyping: false,
              awaitingInput: false,
              pendingQuestion: null,
              pendingOptions: null,
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

        case "node_loop_started":
          turnCounterRef.current[turnKey] = currentTurn + 1;
          updateState({ isTyping: true, activeToolCalls: {} });
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
          turnCounterRef.current[turnKey] = currentTurn + 1;
          if (isQueen) {
            updateState({
              isStreaming: false,
              activeToolCalls: {},
              awaitingInput: false,
              pendingQuestion: null,
              pendingOptions: null,
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
          } else {
            updateState({
              isStreaming: false,
              workerIsTyping: true,
              activeToolCalls: {},
              awaitingInput: false,
              pendingQuestion: null,
              pendingOptions: null,
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
          }
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

            const toolName = (event.data?.tool_name as string) || "unknown";
            const toolUseId = (event.data?.tool_use_id as string) || "";

            const sid = event.stream_id;
            // Track which pill message this tool belongs to so deferred
            // completions (ask_user) can find it after the turn counter changes.
            toolUseToPillRef.current[toolUseId] = {
              msgId: `tool-pill-${sid}-${event.execution_id || "exec"}-${currentTurn}`,
              name: toolName,
            };
            setAgentState((prev) => {
              const newActive = {
                ...prev.activeToolCalls,
                [toolUseId]: { name: toolName, done: false, streamId: sid },
              };
              const tools = Object.values(newActive)
                .filter((t) => t.streamId === sid)
                .map((t) => ({ name: t.name, done: t.done }));
              const allDone = tools.length > 0 && tools.every((t) => t.done);
              upsertMessage({
                id: `tool-pill-${sid}-${event.execution_id || "exec"}-${currentTurn}`,
                agent: agentDisplayName || event.node_id || "Agent",
                agentColor: "",
                content: JSON.stringify({ tools, allDone }),
                timestamp: "",
                type: "tool_status",
                role,
                thread: agentPath,
                createdAt: eventCreatedAt,
                nodeId: event.node_id || undefined,
                executionId: event.execution_id || undefined,
                streamId: sid || undefined,
              });
              return { ...prev, isStreaming: false, activeToolCalls: newActive };
            });
          }
          break;
        }

        case "tool_call_completed": {
          if (event.node_id) {
            const toolName = (event.data?.tool_name as string) || "unknown";
            const toolUseId = (event.data?.tool_use_id as string) || "";
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

            // Look up the original pill message this tool belongs to.
            // For deferred completions (ask_user), the turn counter and
            // activeToolCalls have already been reset, so we rely on the
            // ref recorded during tool_call_started.
            const tracked = toolUseToPillRef.current[toolUseId];
            delete toolUseToPillRef.current[toolUseId];

            const sid = event.stream_id;

            // Mark done in activeToolCalls if still present (normal case)
            setAgentState((prev) => {
              if (!prev.activeToolCalls[toolUseId]) return prev;
              return {
                ...prev,
                activeToolCalls: {
                  ...prev.activeToolCalls,
                  [toolUseId]: {
                    ...prev.activeToolCalls[toolUseId],
                    done: true,
                  },
                },
              };
            });

            // Determine the correct pill message ID
            const pillMsgId =
              tracked?.msgId ??
              `tool-pill-${sid}-${event.execution_id || "exec"}-${currentTurn}`;
            const trackedName = tracked?.name;

            // Update the pill message content directly
            setMessages((prevMsgs) => {
              const idx = prevMsgs.findIndex((m) => m.id === pillMsgId);
              if (idx < 0) return prevMsgs;

              try {
                const parsed = JSON.parse(prevMsgs[idx].content);
                const tools: { name: string; done: boolean }[] =
                  parsed.tools || [];

                if (trackedName) {
                  let marked = false;
                  for (let i = 0; i < tools.length; i++) {
                    if (
                      tools[i].name === trackedName &&
                      !tools[i].done &&
                      !marked
                    ) {
                      tools[i] = { ...tools[i], done: true };
                      marked = true;
                    }
                  }
                }

                const allDone =
                  tools.length > 0 && tools.every((t) => t.done);
                return prevMsgs.map((m, i) =>
                  i === idx
                    ? {
                        ...m,
                        content: JSON.stringify({ tools, allDone }),
                      }
                    : m,
                );
              } catch {
                return prevMsgs;
              }
            });
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
              [streamKey]: { usagePct, messageCount, estimatedTokens, maxTokens },
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

        case "queen_phase_changed": {
          const rawPhase = event.data?.phase as string;
          const eventAgentPath = (event.data?.agent_path as string) || null;
          const newPhase: AgentState["queenPhase"] =
            rawPhase === "working"
              ? "working"
              : rawPhase === "reviewing"
                ? "reviewing"
                : "independent";
          queenPhaseRef.current = newPhase;
          updateState({
            queenPhase: newPhase,
            ...(eventAgentPath ? { agentPath: eventAgentPath } : {}),
          });
          break;
        }

        case "worker_colony_loaded": {
          const graphName = event.data?.colony_name as string | undefined;
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
          // Available = defined in triggers.json but not running yet.
          // Activated = running (just activated or restored after server
          // restart). Both get surfaced as cards in the TriggersPanel; the
          // only difference is the status.
          const isActive = event.type === "trigger_activated";
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
                    status: (isActive ? "running" : "pending") as NodeStatus,
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
              const computedLabel = _cron
                ? cronToLabel(_cron)
                : _interval
                ? `Every ${_interval >= 60 ? `${_interval / 60}h` : `${_interval}m`}`
                : triggerName;
              const newNode: GraphNode = {
                id: nodeId,
                label: computedLabel,
                status: isActive ? "running" : "pending",
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

        default:
          if (shouldMarkQueenReady) updateState({ queenReady: true });
          break;
      }
    },
    [agentPath, queenInfo.name, updateState, upsertMessage, updateGraphNodeStatus, markAllNodesAs, appendNodeLog, graphNodes],
  );

  // ── SSE subscription ───────────────────────────────────────────────────

  const sseSessions = useMemo(() => {
    if (agentState.sessionId && agentState.ready) {
      return { [agentPath]: agentState.sessionId };
    }
    return {};
  }, [agentPath, agentState.sessionId, agentState.ready]);

  useMultiSSE({ sessions: sseSessions, onEvent: handleSSEEvent });

  // ── Action handlers ────────────────────────────────────────────────────

  const handleCancelQueen = useCallback(async () => {
    if (!agentState.sessionId) return;
    try {
      await executionApi.cancelQueen(agentState.sessionId);
      updateState({ isTyping: false, isStreaming: false, queenIsTyping: false });
    } catch {
      // fire-and-forget
    }
  }, [agentState.sessionId, updateState]);

  const handleSend = useCallback(
    (text: string, _thread: string, images?: ImageContent[]) => {
      if (agentState.pendingQuestionSource === "queen") {
        updateState({
          pendingQuestion: null,
          pendingOptions: null,
          pendingQuestions: null,
          pendingQuestionSource: null,
        });
      }

      const userMsg: ChatMessage = {
        id: makeId(),
        agent: "You",
        agentColor: "",
        content: text,
        timestamp: "",
        type: "user",
        thread: agentPath,
        createdAt: Date.now(),
        images,
      };
      setMessages((prev) => [...prev, userMsg]);
      suppressIntroRef.current = false;
      updateState({ isTyping: true, queenIsTyping: true });

      if (agentState.sessionId && agentState.ready) {
        executionApi.chat(agentState.sessionId, text, images).catch((err: unknown) => {
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
          updateState({ isTyping: false, isStreaming: false, queenIsTyping: false });
        });
      }
    },
    [agentPath, agentState.sessionId, agentState.ready, agentState.pendingQuestionSource, updateState, upsertMessage],
  );

  const handleQueenQuestionAnswer = useCallback(
    (answer: string) => {
      updateState({
        pendingQuestion: null,
        pendingOptions: null,
        pendingQuestions: null,
        pendingQuestionSource: null,
      });
      handleSend(answer, agentPath);
    },
    [agentPath, handleSend, updateState],
  );

  const handleMultiQuestionAnswer = useCallback(
    (answers: Record<string, string>) => {
      updateState({
        pendingQuestion: null,
        pendingOptions: null,
        pendingQuestions: null,
        pendingQuestionSource: null,
      });
      const lines = Object.entries(answers).map(([id, answer]) => `[${id}]: ${answer}`);
      handleSend(lines.join("\n"), agentPath);
    },
    [agentPath, handleSend, updateState],
  );

  const handleQuestionDismiss = useCallback(() => {
    if (!agentState.sessionId) return;
    const question = agentState.pendingQuestion || "";
    updateState({
      pendingQuestion: null,
      pendingOptions: null,
      pendingQuestions: null,
      pendingQuestionSource: null,
      awaitingInput: false,
    });
    executionApi
      .chat(agentState.sessionId, `[User dismissed the question: "${question}"]`)
      .catch(() => {});
  }, [agentState.sessionId, agentState.pendingQuestion, updateState]);

  const triggers = useMemo(
    () => graphNodes.filter((n) => n.nodeType === "trigger"),
    [graphNodes],
  );

  // Mirror live triggers into the shared context so the tabbed
  // ColonyWorkersPanel (rendered at the layout level) can render the
  // Triggers tab without having to re-subscribe to the session SSE.
  const {
    setTriggers: setCtxTriggers,
    setSessionId: setCtxSessionId,
    setColonyName: setCtxColonyName,
  } = useColonyWorkers();
  useEffect(() => {
    setCtxTriggers(triggers);
    return () => setCtxTriggers([]);
  }, [triggers, setCtxTriggers]);

  // Publish the live colony session id to the context. The AppLayout
  // renders ``ColonyWorkersPanel`` whenever this is non-null AND the
  // user hasn't dismissed it (via the X button). Cleanup clears it so
  // the panel closes when we leave the colony room.
  useEffect(() => {
    setCtxSessionId(agentState.sessionId ?? null);
    return () => setCtxSessionId(null);
  }, [agentState.sessionId, setCtxSessionId]);

  // Publish the colony directory name (e.g. ``linkedin_honeycomb_messaging``)
  // alongside the session id. The panel's progress + data tabs route by
  // colony name, not session — one progress.db per colony, independent
  // of which session is open. Comes from ``LiveSession.colony_id`` (the
  // on-disk directory) rather than the URL slug, which is mangled by
  // ``slugToColonyId``.
  useEffect(() => {
    setCtxColonyName(agentState.colonyDirName ?? null);
    return () => setCtxColonyName(null);
  }, [agentState.colonyDirName, setCtxColonyName]);

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
            messages={messages}
            onSend={handleSend}
            onCancel={handleCancelQueen}
            activeThread={agentPath}
            isWaiting={(agentState.queenIsTyping && !agentState.isStreaming) ?? false}
            isWorkerWaiting={(agentState.workerIsTyping && !agentState.isStreaming) ?? false}
            isBusy={agentState.queenIsTyping ?? false}
            disabled={agentState.loading || !agentState.queenReady}
            queenPhase={agentState.queenPhase}
            pendingQuestion={agentState.awaitingInput ? agentState.pendingQuestion : null}
            pendingOptions={agentState.awaitingInput ? agentState.pendingOptions : null}
            pendingQuestions={agentState.awaitingInput ? agentState.pendingQuestions : null}
            onQuestionSubmit={handleQueenQuestionAnswer}
            onMultiQuestionSubmit={handleMultiQuestionAnswer}
            onQuestionDismiss={handleQuestionDismiss}
            contextUsage={agentState.contextUsage}
            supportsImages={agentState.queenSupportsImages}
            queenProfileId={colony?.queenProfileId ?? null}
            queenId={colony?.queenProfileId ?? undefined}
          />
        </div>

        {/* Workers / Triggers / Skills / Tools now live in the tabbed
            ColonyWorkersPanel rendered by AppLayout. Trigger data is
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
    </div>
  );
}
