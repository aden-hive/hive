import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Plus, KeyRound, Loader2, WifiOff, X, FolderOpen } from "lucide-react";
import type { GraphNode, NodeStatus } from "@/components/graph-types";
import DraftGraph from "@/components/DraftGraph";
import ChatPanel, { type ChatMessage } from "@/components/ChatPanel";
import TopBar from "@/components/TopBar";
import { TAB_STORAGE_KEY, loadPersistedTabs, savePersistedTabs, type PersistedTabState } from "@/lib/tab-persistence";
import NodeDetailPanel from "@/components/NodeDetailPanel";
import CredentialsModal, { type Credential, createFreshCredentials, cloneCredentials, allRequiredCredentialsMet, clearCredentialCache } from "@/components/CredentialsModal";
import { executionApi } from "@/api/execution";
import { graphsApi } from "@/api/graphs";
import { sessionsApi } from "@/api/sessions";
import { useMultiSSE } from "@/hooks/use-sse";
import type { LiveSession, AgentEvent, NodeSpec, DraftGraph as DraftGraphData } from "@/api/types";
import { sseEventToChatMessage, formatAgentDisplayName } from "@/lib/chat-helpers";
import { topologyToGraphNodes } from "@/lib/graph-converter";
import { cronToLabel } from "@/lib/graphUtils";
import { ApiError } from "@/api/client";

const makeId = () => Math.random().toString(36).slice(2, 9);

/**
 * Strip the instance suffix added when multiple tabs share the same agentType.
 * e.g. "exports/deep_research::abc123" → "exports/deep_research"
 * First-instance keys (no "::") are returned unchanged.
 */
const baseAgentType = (key: string): string => key.split("::")[0];

/** Format seconds into a compact countdown string. */
function formatCountdown(totalSecs: number): string {
  const h = Math.floor(totalSecs / 3600);
  const m = Math.floor((totalSecs % 3600) / 60);
  const s = Math.floor(totalSecs % 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

/** Live countdown from an initial seconds value, ticking every second. */
function TimerCountdown({ initialSeconds }: { initialSeconds: number }) {
  const [remaining, setRemaining] = useState(Math.max(0, Math.round(initialSeconds)));
  const startRef = useRef({ wallTime: Date.now(), initial: Math.max(0, Math.round(initialSeconds)) });

  useEffect(() => {
    startRef.current = { wallTime: Date.now(), initial: Math.max(0, Math.round(initialSeconds)) };
    setRemaining(Math.max(0, Math.round(initialSeconds)));
  }, [initialSeconds]);

  useEffect(() => {
    const id = setInterval(() => {
      const elapsed = (Date.now() - startRef.current.wallTime) / 1000;
      setRemaining(Math.max(0, Math.round(startRef.current.initial - elapsed)));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  if (remaining <= 0) return <span className="text-amber-400/80">firing...</span>;
  return <span>{formatCountdown(remaining)}</span>;
}

// --- Session types ---
interface Session {
  id: string;
  agentType: string;
  /** The key used in sessionsByAgent / agentStates for this specific tab instance.
   * Equals agentType for the first tab; equals "agentType::frontendSessionId" for
   * additional tabs opened for the same agent so each gets its own isolated slot. */
  tabKey?: string;
  label: string;
  messages: ChatMessage[];
  graphNodes: GraphNode[];
  credentials: Credential[];
  backendSessionId?: string;
  /** The cold history session ID this tab was originally opened from (if any).
   * Used to detect "already open" even after backendSessionId is updated to a
   * new live session ID when the cold session is revived. */
  historySourceId?: string;
}

function createSession(agentType: string, label: string, existingCredentials?: Credential[]): Session {
  return {
    id: makeId(),
    agentType,
    label,
    messages: [],
    graphNodes: [],
    credentials: existingCredentials ? cloneCredentials(existingCredentials) : createFreshCredentials(agentType),
  };
}

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

type SessionRestoreResult = {
  messages: ChatMessage[];
  restoredPhase: "planning" | "building" | "staging" | "running" | null;
  /** Last flowchart map from events — used to restore flowchart overlay on cold resume. */
  flowchartMap: Record<string, string[]> | null;
  /** Last original draft from events — used to restore flowchart overlay on cold resume. */
  originalDraft: DraftGraphData | null;
};

/**
 * Restore session messages from the persisted event log.
 * Returns an empty result if no event log exists.
 */
async function restoreSessionMessages(
  sessionId: string,
  thread: string,
  agentDisplayName: string,
): Promise<SessionRestoreResult> {
  try {
    const { events } = await sessionsApi.eventsHistory(sessionId);
    if (events.length > 0) {
      const messages: ChatMessage[] = [];
      let runningPhase: ChatMessage["phase"] = undefined;
      let flowchartMap: Record<string, string[]> | null = null;
      let originalDraft: DraftGraphData | null = null;
      for (const evt of events) {
        // Track phase transitions so each message gets the phase it was created in
        const p = evt.type === "queen_phase_changed" ? evt.data?.phase as string
          : evt.type === "node_loop_iteration" ? evt.data?.phase as string | undefined
          : undefined;
        if (p && ["planning", "building", "staging", "running"].includes(p)) {
          runningPhase = p as ChatMessage["phase"];
        }
        // Track last flowchart state for cold restore
        if (evt.type === "flowchart_map_updated" && evt.data) {
          const mapData = evt.data as { map?: Record<string, string[]>; original_draft?: DraftGraphData };
          flowchartMap = mapData.map ?? null;
          originalDraft = mapData.original_draft ?? null;
        }
        const msg = sseEventToChatMessage(evt, thread, agentDisplayName);
        if (!msg) continue;
        if (evt.stream_id === "queen") {
          msg.role = "queen";
          msg.phase = runningPhase;
        }
        messages.push(msg);
      }
      return { messages, restoredPhase: runningPhase ?? null, flowchartMap, originalDraft };
    }
  } catch {
    // Event log not available — session will start fresh.
  }
  return { messages: [], restoredPhase: null, flowchartMap: null, originalDraft: null };
}

// --- Per-agent backend state (consolidated) ---
interface AgentBackendState {
  sessionId: string | null;
  loading: boolean;
  ready: boolean;
  queenReady: boolean;
  error: string | null;
  displayName: string | null;
  graphId: string | null;
  nodeSpecs: NodeSpec[];
  awaitingInput: boolean;
  /** The message ID of the current worker input request (for inline reply box) */
  workerInputMessageId: string | null;
  queenBuilding: boolean;
  /** Queen operating phase — "planning" (design), "building" (coding), "staging" (loaded), or "running" (executing) */
  queenPhase: "planning" | "building" | "staging" | "running";
  /** Draft graph from planning phase (before code generation) */
  draftGraph: DraftGraphData | null;
  /** Original draft (pre-dissolution) for flowchart display during runtime */
  originalDraft: DraftGraphData | null;
  /** Runtime node ID → list of original draft node IDs it absorbed */
  flowchartMap: Record<string, string[]> | null;
  workerRunState: "idle" | "deploying" | "running";
  currentExecutionId: string | null;
  currentRunId: string | null;
  nodeLogs: Record<string, string[]>;
  nodeActionPlans: Record<string, string>;
  subagentReports: { subagent_id: string; message: string; data?: Record<string, unknown>; timestamp: string }[];
  isTyping: boolean;
  isStreaming: boolean;
  /** True only when the queen's LLM is actively processing (not worker) */
  queenIsTyping: boolean;
  /** True only when a worker's LLM is actively processing (not queen) */
  workerIsTyping: boolean;
  llmSnapshots: Record<string, string>;
  activeToolCalls: Record<string, { name: string; done: boolean; streamId: string }>;
  /** True while save_agent_draft tool is running (between tool_call_started and draft_graph_updated) */
  designingDraft: boolean;
  /** Agent folder path — set after scaffolding, used for credential queries */
  agentPath: string | null;
  /** Structured question text from ask_user with options */
  pendingQuestion: string | null;
  /** Predefined choices from ask_user (1-3 items); UI appends "Other" */
  pendingOptions: string[] | null;
  /** Multiple questions from ask_user_multiple */
  pendingQuestions: { id: string; prompt: string; options?: string[] }[] | null;
  /** Whether the pending question came from the queen interaction flow */
  pendingQuestionSource: "queen" | null;
  /** Per-node context window usage (from context_usage_updated events) */
  contextUsage: Record<string, { usagePct: number; messageCount: number; estimatedTokens: number; maxTokens: number }>;
  /** Whether the queen's LLM supports image content — false disables the attach button */
  queenSupportsImages: boolean;
}

function defaultAgentState(): AgentBackendState {
  return {
    sessionId: null,
    loading: true,
    ready: false,
    queenReady: false,
    error: null,
    displayName: null,
    graphId: null,
    nodeSpecs: [],
    awaitingInput: false,
    workerInputMessageId: null,
    queenBuilding: false,
    queenPhase: "planning",
    designingDraft: false,
    draftGraph: null,
    originalDraft: null,
    flowchartMap: null,
    agentPath: null,
    workerRunState: "idle",
    currentExecutionId: null,
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

export default function Workspace() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rawAgent = searchParams.get("agent") || "new-agent";
  const hasExplicitAgent = searchParams.has("agent");
  const initialPrompt = searchParams.get("prompt") || "";
  // ?session= param: when navigating from the home history sidebar, this
  // carries the backendSessionId to open as a tab on mount.
  const initialSessionId = searchParams.get("session") || "";

  // When submitting a new prompt from home for "new-agent", use a unique key
  // so each prompt gets its own tab instead of overwriting the previous one.
  const [initialAgent] = useState(() =>
    initialPrompt && hasExplicitAgent && rawAgent === "new-agent"
      ? `new-agent-${makeId()}`
      : rawAgent
  );

  // Sessions grouped by agent type — restore from localStorage if available
  const [sessionsByAgent, setSessionsByAgent] = useState<Record<string, Session[]>>(() => {
    const persisted = loadPersistedTabs();
    const initial: Record<string, Session[]> = {};

    if (persisted) {
      for (const tab of persisted.tabs) {
        // tabKey is the actual key used in sessionsByAgent (may contain "::" suffix).
        // Fall back to agentType for tabs persisted before this field was added.
        const tabKey = tab.tabKey || tab.agentType;
        // New-agent tabs each have a unique key (e.g. "new-agent-abc123"),
        // so they never collide with the incoming tab — always restore them.
        if (!initial[tabKey]) initial[tabKey] = [];
        const session = createSession(tab.agentType, tab.label);
        session.id = tab.id;
        session.backendSessionId = tab.backendSessionId;
        session.tabKey = tab.tabKey; // restore so future persistence uses correct key
        session.historySourceId = tab.historySourceId;
        // Restore messages and graph from localStorage (up to 50 messages).
        // If the backend session is still alive, loadAgentForType may
        // append additional messages fetched from the server.
        const cached = persisted.sessions?.[tab.id];
        if (cached) {
          session.messages = cached.messages || [];
          session.graphNodes = cached.graphNodes || [];
        }
        initial[tabKey].push(session);
      }
    }

    // If persisted tabs were restored and user didn't explicitly request
    // a different agent via URL, return restored tabs as-is.
    if (persisted && Object.keys(initial).length > 0 && !hasExplicitAgent) {
      return initial;
    }

    // If there are already persisted tabs for this agent type, don't create
    // a new one — the post-mount effect will call handleHistoryOpen if needed
    // (for ?session= params coming from the home page sidebar).
    if (initial[initialAgent]?.length) {
      return initial;
    }
    // Also check for existing tabs with instance suffixes (e.g. "agentType::instanceId")
    const existingKey = Object.keys(initial).find(
      k => baseAgentType(k) === initialAgent && initial[k]?.length > 0
    );
    if (existingKey && !initialPrompt) {
      return initial;
    }

    // If the user submitted a new prompt from the home page, always create
    // a fresh session so the prompt isn't lost into an existing session.
    // initialAgent is already a unique key (e.g. "new-agent-abc123") when
    // coming from home, so the new tab won't overwrite existing ones.
    if (initialPrompt && hasExplicitAgent) {
      const rawLabel = initialAgent.startsWith("new-agent")
        ? "New Agent"
        : formatAgentDisplayName(initialAgent);
      const existingNewAgentCount = Object.keys(initial).filter(
        k => (k === "new-agent" || k.startsWith("new-agent-")) && (initial[k] || []).length > 0
      ).length;
      const label = existingNewAgentCount === 0 ? rawLabel : `${rawLabel} #${existingNewAgentCount + 1}`;
      const newSession = createSession(initialAgent, label);
      initial[initialAgent] = [newSession];
      return initial;
    }

    // Only create a fresh default tab when there are no persisted tabs at all.
    // If ?session= was passed we intentionally do NOT create a tab here —
    // handleHistoryOpen is called post-mount and does proper dedup.
    if (initialAgent === "new-agent") {
      const s = createSession("new-agent", "New Agent");
      initial["new-agent"] = [...(initial["new-agent"] || []), s];
    } else if (!initialSessionId) {
      // Only auto-create an agent tab if there's no session to restore
      const s = createSession(initialAgent, formatAgentDisplayName(initialAgent));
      initial[initialAgent] = [...(initial[initialAgent] || []), s];
    }

    return initial;
  });

  const [activeSessionByAgent, setActiveSessionByAgent] = useState<Record<string, string>>(() => {
    const persisted = loadPersistedTabs();
    // If initialSessionId maps to an already-restored tab, activate that tab
    if (initialSessionId) {
      for (const [tabKey, sessions] of Object.entries(sessionsByAgent)) {
        const match = sessions.find(
          s => s.backendSessionId === initialSessionId || s.historySourceId === initialSessionId,
        );
        if (match) {
          return { ...(persisted?.activeSessionByAgent ?? {}), [tabKey]: match.id };
        }
      }
    }
    if (persisted) {
      let restored = { ...persisted.activeSessionByAgent };
      // Remove stale new-agent-* entries when starting fresh from home
      if (initialPrompt && hasExplicitAgent) {
        restored = Object.fromEntries(
          Object.entries(restored).filter(([key]) =>
            key !== "new-agent" && !key.startsWith("new-agent-")
          )
        );
      }
      const urlSessions = sessionsByAgent[initialAgent];
      if (urlSessions?.length) {
        // When a prompt was submitted from home, activate the newly created
        // session (last in array) instead of the previously active one.
        if (initialPrompt && hasExplicitAgent) {
          restored[initialAgent] = urlSessions[urlSessions.length - 1].id;
        } else if (!restored[initialAgent]) {
          restored[initialAgent] = urlSessions[0].id;
        }
      }
      return restored;
    }
    const sessions = sessionsByAgent[initialAgent];
    return sessions ? { [initialAgent]: sessions[0].id } : {};
  });

  const [activeWorker, setActiveWorker] = useState(() => {
    // If initialSessionId maps to an already-restored tab, activate that key
    if (initialSessionId) {
      for (const [tabKey, sessions] of Object.entries(sessionsByAgent)) {
        if (sessions.some(
          s => s.backendSessionId === initialSessionId || s.historySourceId === initialSessionId,
        )) return tabKey;
      }
    }
    if (!hasExplicitAgent) {
      const persisted = loadPersistedTabs();
      if (persisted?.activeWorker) return persisted.activeWorker;
    }
    return initialAgent;
  });

  // Clear URL params after mount — they're consumed during initialization
  // and leaving them causes confusion (stale ?agent= after tab switches, etc.)
  useEffect(() => {
    navigate("/workspace", { replace: true });
  }, []);

  // Post-mount: if the URL carried a ?session= param (from the home page history
  // sidebar), open it via handleHistoryOpen instead of creating a tab in init state.
  // This is the single canonical path — it has robust dedup (checks backendSessionId
  // AND historySourceId across all in-memory tabs) and is safe to call after persisted
  // state has been hydrated.
  // We capture initialSessionId and related URL params in stable refs so the effect
  // only fires once on mount, regardless of re-renders.
  const initialSessionIdRef = useRef(initialSessionId);
  const initialAgentRef = useRef(initialAgent);
  const mountedRef = useRef(false);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  // Explicit agent path for the credentials modal — set from 424 responses
  // when activeWorker doesn't match the actual agent (e.g. "new-agent" tab).
  const [credentialAgentPath, setCredentialAgentPath] = useState<string | null>(null);
  const [dismissedBanner, setDismissedBanner] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [triggerTaskDraft, setTriggerTaskDraft] = useState("");
  const [triggerCronDraft, setTriggerCronDraft] = useState("");
  const [triggerTaskSaving, setTriggerTaskSaving] = useState(false);
  const [triggerScheduleSaving, setTriggerScheduleSaving] = useState(false);
  const [triggerCronSaved, setTriggerCronSaved] = useState(false);
  const [triggerTaskSaved, setTriggerTaskSaved] = useState(false);
  const [graphPanelPct, setGraphPanelPct] = useState(30);
  const savedGraphPanelPct = useRef(30);
  const resizing = useRef(false);

  // Drag-to-resize the graph panel
  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!resizing.current) return;
      const pct = (e.clientX / window.innerWidth) * 100;
      setGraphPanelPct(Math.max(15, Math.min(50, pct)));
    };
    const onMouseUp = () => {
      resizing.current = false;
      document.body.style.cursor = "";
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  // Shrink graph panel when node detail opens, restore when it closes
  const nodeIsSelected = selectedNode !== null;
  useEffect(() => {
    if (nodeIsSelected) {
      savedGraphPanelPct.current = graphPanelPct;
      setGraphPanelPct(prev => Math.min(prev, 30));
    } else {
      setGraphPanelPct(savedGraphPanelPct.current);
    }
  }, [nodeIsSelected]); // eslint-disable-line react-hooks/exhaustive-deps

  // Ref mirror of sessionsByAgent so SSE callback can read current graph
  // state without adding sessionsByAgent to its dependency array.
  const sessionsRef = useRef(sessionsByAgent);
  sessionsRef.current = sessionsByAgent;

  // Ref mirror of activeSessionByAgent so setSessionsByAgent updater
  // functions always read the *current* active session id, avoiding stale
  // closures that can silently drop messages / graph updates.
  const activeSessionRef = useRef(activeSessionByAgent);
  activeSessionRef.current = activeSessionByAgent;

  // Synchronous per-agent turn counter for SSE message IDs.
  // Using a ref avoids stale-closure bugs when multiple SSE events
  // arrive in the same React batch.
  const turnCounterRef = useRef<Record<string, number>>({});
  // Per-agent queen phase ref — used to stamp each message with the phase
  // it was created in (avoids stale-closure when phase change and message
  // events arrive in the same React batch).
  const queenPhaseRef = useRef<Record<string, string>>({});
  // Accumulated queen text across inner_turns within the same iteration.
  // Key: `${agentType}:${execution_id}:${iteration}`, value: { [inner_turn]: snapshot }.
  // This lets us merge all inner_turn text into one chat bubble per iteration.
  const queenIterTextRef = useRef<Record<string, Record<number, string>>>({});
  // Timestamp when designingDraft was set — used to enforce minimum spinner duration.
  const designingDraftSinceRef = useRef<Record<string, number>>({});
  const designingDraftTimerRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // Synchronous ref to suppress the queen's auto-intro SSE messages
  // after a cold-restore (where we already restored the conversation from disk).
  // Using a ref avoids the race condition where sessionId is set in agentState
  // (opening SSE) before the suppressQueenIntro flag can be committed.
  const suppressIntroRef = useRef(new Set<string>());

  // --- Consolidated per-agent backend state ---
  const [agentStates, setAgentStates] = useState<Record<string, AgentBackendState>>({});

  const updateAgentState = useCallback((agentType: string, patch: Partial<AgentBackendState>) => {
    setAgentStates(prev => ({
      ...prev,
      [agentType]: { ...(prev[agentType] || defaultAgentState()), ...patch },
    }));
  }, []);

  // Derive active agent's backend state
  const activeAgentState = agentStates[activeWorker];

  // Reset dismissed banner when the error clears so it re-appears if the same error returns
  const currentError = activeAgentState?.error;
  useEffect(() => { if (!currentError) setDismissedBanner(null); }, [currentError]);

  // Persist tab metadata + session data to localStorage on every relevant change
  useEffect(() => {
    const tabs: PersistedTabState["tabs"] = [];
    const sessions: Record<string, { messages: ChatMessage[]; graphNodes: GraphNode[] }> = {};
    for (const agentSessions of Object.values(sessionsByAgent)) {
      for (const s of agentSessions) {
        const tKey = s.tabKey || s.agentType;
        tabs.push({
          id: s.id,
          agentType: s.agentType,
          tabKey: s.tabKey,
          label: s.label,
          // agentStates is keyed by tabKey (unique per tab), not by base agentType
          backendSessionId: s.backendSessionId || agentStates[tKey]?.sessionId || undefined,
          ...(s.historySourceId ? { historySourceId: s.historySourceId } : {}),
        });
        sessions[s.id] = { messages: s.messages, graphNodes: s.graphNodes };
      }
    }
    if (tabs.length > 0) {
      savePersistedTabs({ tabs, activeSessionByAgent, activeWorker, sessions });
    } else {
      localStorage.removeItem(TAB_STORAGE_KEY);
    }
  }, [sessionsByAgent, activeSessionByAgent, activeWorker, agentStates]);

  const handleRun = useCallback(async () => {
    const state = agentStates[activeWorker];
    if (!state?.sessionId || !state?.ready) return;
    // Reset dismissed banner so a repeated 424 re-shows it
    setDismissedBanner(null);
    try {
      updateAgentState(activeWorker, { workerRunState: "deploying" });
      const result = await executionApi.trigger(state.sessionId, "default", {});
      updateAgentState(activeWorker, { currentExecutionId: result.execution_id });
    } catch (err) {
      // 424 = credentials required — open the credentials modal
      if (err instanceof ApiError && err.status === 424) {
        const errBody = (err as ApiError).body as Record<string, unknown>;
        const credPath = (errBody?.agent_path as string) || null;
        if (credPath) setCredentialAgentPath(credPath);
        updateAgentState(activeWorker, { workerRunState: "idle", error: "credentials_required" });
        setCredentialsOpen(true);
        return;
      }

      const errMsg = err instanceof Error ? err.message : String(err);
      setSessionsByAgent((prev) => {
        const sessions = prev[activeWorker] || [];
        const activeId = activeSessionRef.current[activeWorker] || sessions[0]?.id;
        return {
          ...prev,
          [activeWorker]: sessions.map((s) => {
            if (s.id !== activeId) return s;
            const errorMsg: ChatMessage = {
              id: makeId(), agent: "System", agentColor: "",
              content: `Failed to trigger run: ${errMsg}`,
              timestamp: "", type: "system", thread: activeWorker, createdAt: Date.now(),
            };
            return { ...s, messages: [...s.messages, errorMsg] };
          }),
        };
      });
      updateAgentState(activeWorker, { workerRunState: "idle" });
    }
  }, [agentStates, activeWorker, updateAgentState]);


  // --- Agent loading: loadAgentForType ---
  const loadingRef = useRef(new Set<string>());
  const loadAgentForType = useCallback(async (agentType: string) => {
    // agentType may be a unique composite key ("exports/foo::sessionId") for additional
    // tabs — extract the real agent path for selector checks and API calls.
    const agentPath = baseAgentType(agentType);
    // Ref-based guard: prevents double-load from React StrictMode (must be first check)
    if (loadingRef.current.has(agentType)) return;
    loadingRef.current.add(agentType);

    if (agentPath === "new-agent" || agentType.startsWith("new-agent-")) {
      // Create a queen-only session (no worker) for agent building
      updateAgentState(agentType, { loading: true, error: null, ready: false, sessionId: null });
      try {
        const prompt = initialPrompt || undefined;
        let liveSession: LiveSession | undefined;

        // Find the active session for this agent type
        const activeId = activeSessionRef.current[agentType];
        const activeSess = sessionsRef.current[agentType]?.find(s => s.id === activeId)
          || sessionsRef.current[agentType]?.[0];

        // Try to reconnect to stored backend session (e.g., after browser refresh)
        const storedId = activeSess?.backendSessionId;
        // When the server restarts the session is "cold" — conversation files
        // survive on disk but there is no live runtime.  Track the old ID so
        // we can restore message history after creating a new session.
        let coldRestoreId: string | undefined;

        if (storedId) {
          try {
            const sessionData = await sessionsApi.get(storedId);
            if (sessionData.cold) {
              // Server restarted — files on disk, no live runtime
              coldRestoreId = storedId;
            } else {
              liveSession = sessionData;
            }
          } catch {
            // Session gone entirely (no disk files either)
          }
        }

        let restoredMessageCount = 0;

        // Before creating a new session, check if there's already a live backend
        // session for this queen-only agent that no open tab owns.
        // Skip this search when the tab has a prompt — it's a fresh agent from
        // home and must always get its own session.
        if (!liveSession && !coldRestoreId && !prompt) {
          try {
            const { sessions: allLive } = await sessionsApi.list();
            const existing = allLive.find(s => !s.has_worker && !s.agent_path);
            if (existing) {
              const alreadyOwned = Object.values(sessionsRef.current).flat()
                .some(s => s.backendSessionId === existing.session_id);
              if (!alreadyOwned) {
                liveSession = existing;
              }
            }
          } catch { /* proceed to create */ }

          // If no live session, check history for a cold queen-only session
          if (!liveSession) {
            try {
              const { sessions: allHistory } = await sessionsApi.history();
              const coldMatch = allHistory.find(
                s => !s.agent_path && s.has_messages
              );
              if (coldMatch) {
                coldRestoreId = coldMatch.session_id;
              }
            } catch { /* proceed to create fresh */ }
          }
        }

        let restoredPhase: "planning" | "building" | "staging" | "running" | null = null;
        let restoredFlowchartMap: Record<string, string[]> | null = null;
        let restoredOriginalDraft: DraftGraphData | null = null;
        if (!liveSession) {
          // Fetch conversation history from disk BEFORE creating the new session.
          // SKIP if messages were already pre-populated by handleHistoryOpen.
          const restoreFrom = coldRestoreId ?? storedId;
          const preRestoredMsgs: ChatMessage[] = [];
          const alreadyHasMessages = (activeSess?.messages?.length ?? 0) > 0;
          if (restoreFrom && !alreadyHasMessages) {
            try {
              const restored = await restoreSessionMessages(restoreFrom, agentType, "Queen Bee");
              preRestoredMsgs.push(...restored.messages);
              restoredPhase = restored.restoredPhase;
              restoredFlowchartMap = restored.flowchartMap;
              restoredOriginalDraft = restored.originalDraft;
            } catch {
              // Not available — will start fresh
            }
          } else if (restoreFrom && alreadyHasMessages) {
            // Messages already cached in localStorage — still fetch events for
            // non-message state (phase, flowchart) that isn't cached.
            try {
              const restored = await restoreSessionMessages(restoreFrom, agentType, "Queen Bee");
              restoredPhase = restored.restoredPhase;
              restoredFlowchartMap = restored.flowchartMap;
              restoredOriginalDraft = restored.originalDraft;
            } catch {
              // Not critical — UI will still show cached messages
            }
          }

          // Suppress the queen's intro cycle whenever we are about to restore a
          // previous conversation, or whenever we have a stored session ID.
          const willRestore = !!(restoreFrom);
          if (willRestore || preRestoredMsgs.length > 0) suppressIntroRef.current.add(agentType);

          // Pass coldRestoreId as queenResumeFrom so the backend writes queen
          // messages into the ORIGINAL session's directory.
          liveSession = await sessionsApi.create(undefined, undefined, undefined, prompt, coldRestoreId ?? undefined);

          if (preRestoredMsgs.length > 0) {
            preRestoredMsgs.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
            if (activeId) {
              setSessionsByAgent(prev => ({
                ...prev,
                [agentType]: (prev[agentType] || []).map(s =>
                  s.id === activeId ? { ...s, messages: preRestoredMsgs, graphNodes: [] } : s,
                ),
              }));
            }
            restoredMessageCount = preRestoredMsgs.length;
          } else if (restoreFrom && activeId && !alreadyHasMessages) {
            // We had a stored session but no messages on disk — wipe stale localStorage cache
            setSessionsByAgent(prev => ({
              ...prev,
              [agentType]: (prev[agentType] || []).map(s =>
                s.id === activeId ? { ...s, messages: [], graphNodes: [] } : s,
              ),
            }));
          }

          // Show the initial prompt as a user message only on a truly fresh session
          if (prompt && restoredMessageCount === 0 && activeId) {
            const userMsg: ChatMessage = {
              id: makeId(), agent: "You", agentColor: "",
              content: prompt, timestamp: "", type: "user", thread: agentType, createdAt: Date.now(),
            };
            setSessionsByAgent(prev => ({
              ...prev,
              [agentType]: (prev[agentType] || []).map(s =>
                s.id === activeId ? { ...s, messages: [...s.messages, userMsg] } : s,
              ),
            }));
          }
        }

        // Store backendSessionId on the Session object for persistence.
        // Also set historySourceId so the sidebar "already-open" check works
        // even after cold-revive changes backendSessionId to a new live session ID.
        if (activeId) {
          setSessionsByAgent(prev => ({
            ...prev,
            [agentType]: (prev[agentType] || []).map(s =>
              s.id === activeId ? {
                ...s,
                backendSessionId: liveSession!.session_id,
                historySourceId: s.historySourceId || coldRestoreId || undefined,
              } : s,
            ),
          }));
        }

        // If no messages were actually restored, lift the intro suppression
        if (restoredMessageCount === 0) suppressIntroRef.current.delete(agentType);

        const qPhase = restoredPhase || liveSession.queen_phase || "planning";
        queenPhaseRef.current[agentType] = qPhase;
        updateAgentState(agentType, {
          sessionId: liveSession.session_id,
          displayName: "Queen Bee",
          ready: true,
          loading: false,
          queenReady: true,
          queenPhase: qPhase,
          queenBuilding: qPhase === "building",
          queenSupportsImages: liveSession.queen_supports_images !== false,
          // Restore flowchart overlay from persisted events
          ...(restoredFlowchartMap ? { flowchartMap: restoredFlowchartMap } : {}),
          ...(restoredOriginalDraft ? { originalDraft: restoredOriginalDraft, draftGraph: null } : {}),
        });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        updateAgentState(agentType, { error: msg, loading: false });
      }
      return;
    }

    updateAgentState(agentType, { loading: true, error: null, ready: false, sessionId: null });

    try {
      let liveSession: LiveSession | undefined;
      let isResumedSession = false;
      // Set when the stored session is cold (server restarted) so we can restore
      // messages from the old session files after creating a new live session.
      let coldRestoreId: string | undefined;

      // Try to reconnect to an existing backend session (e.g., after browser refresh).
      // The backendSessionId is persisted in localStorage per tab.
      // Also check historySourceId — handleHistoryOpen populates this with the
      // original session ID from the sidebar. Use it as a fallback for stored ID.
      const historySourceId = sessionsRef.current[agentType]?.[0]?.historySourceId;
      const storedSessionId = sessionsRef.current[agentType]?.[0]?.backendSessionId
        || historySourceId;
      if (storedSessionId) {
        try {
          const sessionData = await sessionsApi.get(storedSessionId);
          if (sessionData.cold) {
            // Server restarted — conversation files survive on disk, no live runtime.
            coldRestoreId = storedSessionId;
          } else {
            liveSession = sessionData;
            isResumedSession = true;
          }
        } catch {
          // 404: session was explicitly stopped (via closeAgentTab) but conversation
          // files likely still exist on disk. Treat it as cold so we can restore.
          coldRestoreId = historySourceId || storedSessionId;
        }
      }

      // No stored session — check for a live or cold session for this agent
      // that we can reuse (e.g., tab was closed but backend session survived,
      // or server restarted with conversation files on disk).
      if (!liveSession && !coldRestoreId) {
        try {
          const { sessions: allLive } = await sessionsApi.list();
          const existingLive = allLive.find(s => s.agent_path.endsWith(agentPath));
          if (existingLive) {
            const alreadyOwned = Object.values(sessionsRef.current).flat()
              .some(s => s.backendSessionId === existingLive.session_id);
            if (!alreadyOwned) {
              liveSession = existingLive;
              isResumedSession = true;
            }
          }
        } catch { /* proceed */ }

        // If no live session, check history for a cold session to restore
        if (!liveSession) {
          try {
            const { sessions: allHistory } = await sessionsApi.history();
            const coldMatch = allHistory.find(
              s => s.agent_path?.endsWith(agentPath) && s.has_messages
            );
            if (coldMatch) {
              coldRestoreId = coldMatch.session_id;
            }
          } catch { /* proceed to create fresh */ }
        }
      }

      // Track the last queen phase seen in the event log for cold restore
      let restoredPhase: "planning" | "building" | "staging" | "running" | null = null;
      let restoredFlowchartMap: Record<string, string[]> | null = null;
      let restoredOriginalDraft: DraftGraphData | null = null;

      if (!liveSession) {
        // Reconnect failed — clear stale cached messages from localStorage restore.
        // NEVER wipe when: (a) doing a cold restore (we'll restore from disk) or
        // (b) handleHistoryOpen already pre-populated messages (alreadyHasMessages).
        const alreadyHasMessages = (sessionsRef.current[agentType] || [])[0]?.messages?.length > 0;
        if (storedSessionId && !coldRestoreId && !alreadyHasMessages) {
          setSessionsByAgent(prev => ({
            ...prev,
            [agentType]: (prev[agentType] || []).map((s, i) =>
              i === 0 ? { ...s, messages: [], graphNodes: [] } : s,
            ),
          }));
        }

        // CRITICAL: Pre-fetch queen messages from the old session directory BEFORE
        // creating the new session. When queen_resume_from is set the new session writes
        // to the SAME directory, so if we fetch after creation we risk capturing the
        // new queen's greeting in the restored history.
        // SKIP if messages were already pre-populated by handleHistoryOpen (avoids
        // double-fetch and greeting leakage).
        let preQueenMsgs: ChatMessage[] = [];
        if (coldRestoreId && !alreadyHasMessages) {
          const displayNameTemp = formatAgentDisplayName(agentPath);
          const restored = await restoreSessionMessages(coldRestoreId, agentType, displayNameTemp);
          preQueenMsgs = restored.messages;
          restoredPhase = restored.restoredPhase;
          restoredFlowchartMap = restored.flowchartMap;
          restoredOriginalDraft = restored.originalDraft;
        } else if (coldRestoreId && alreadyHasMessages) {
          // Messages already cached — still fetch events for non-message state (phase, flowchart)
          try {
            const displayNameTemp = formatAgentDisplayName(agentPath);
            const restored = await restoreSessionMessages(coldRestoreId, agentType, displayNameTemp);
            restoredPhase = restored.restoredPhase;
            restoredFlowchartMap = restored.flowchartMap;
            restoredOriginalDraft = restored.originalDraft;
          } catch {
            // Not critical — UI will still show cached messages
          }
        }

        // Suppress intro whenever we are about to restore a previous conversation.
        // The user never expects a greeting when reopening a session.
        if (coldRestoreId) suppressIntroRef.current.add(agentType);

        try {
          // Pass coldRestoreId as queenResumeFrom so the backend writes queen
          // messages into the ORIGINAL session's directory — all conversation
          // history accumulates in one place across server restarts.
          liveSession = await sessionsApi.create(agentPath, undefined, undefined, undefined, coldRestoreId ?? undefined);
        } catch (loadErr: unknown) {
          // 424 = credentials required — open the credentials modal
          if (loadErr instanceof ApiError && loadErr.status === 424) {
            const errBody = loadErr.body as Record<string, unknown>;
            const credPath = (errBody.agent_path as string) || null;
            if (credPath) setCredentialAgentPath(credPath);
            updateAgentState(agentType, { loading: false, error: "credentials_required" });
            setCredentialsOpen(true);
            return;
          }

          if (!(loadErr instanceof ApiError) || loadErr.status !== 409) {
            throw loadErr;
          }

          const body = loadErr.body as Record<string, unknown>;
          const existingSessionId = body.session_id as string | undefined;
          if (!existingSessionId) throw loadErr;

          isResumedSession = true;
          if (body.loading) {
            liveSession = await (async () => {
              const maxAttempts = 30;
              const delay = 1000;
              for (let i = 0; i < maxAttempts; i++) {
                await new Promise((r) => setTimeout(r, delay));
                try {
                  const result = await sessionsApi.get(existingSessionId);
                  if (result.loading) continue;
                  return result as LiveSession;
                } catch (pollErr) {
                  // 404 = agent failed to load and was cleaned up — stop immediately
                  if (pollErr instanceof ApiError && pollErr.status === 404) {
                    throw new Error("Agent failed to load");
                  }
                  if (i === maxAttempts - 1) throw loadErr;
                }
              }
              throw loadErr;
            })();
          } else {
            liveSession = body as unknown as LiveSession;
          }
        }

        // If we pre-fetched messages for a cold restore, populate the UI immediately.
        // This happens before the SSE connection opens so no greeting can slip through.
        if (preQueenMsgs.length > 0) {
          preQueenMsgs.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
          setSessionsByAgent(prev => ({
            ...prev,
            [agentType]: (prev[agentType] || []).map((s, i) =>
              i === 0 ? { ...s, messages: preQueenMsgs, graphNodes: [] } : s,
            ),
          }));
        }
      }

      // At this point liveSession is guaranteed set — if both reconnect and create
      // failed, the throw inside the catch exits the outer try block.
      const session = liveSession!;
      const displayName = formatAgentDisplayName(session.graph_name || agentType);
      const initialPhase = restoredPhase || session.queen_phase || (session.has_worker ? "staging" : "planning");
      queenPhaseRef.current[agentType] = initialPhase;
      updateAgentState(agentType, {
        sessionId: session.session_id,
        displayName,
        queenPhase: initialPhase,
        queenBuilding: initialPhase === "building",
        queenSupportsImages: session.queen_supports_images !== false,
        // Restore flowchart overlay from persisted events
        ...(restoredFlowchartMap ? { flowchartMap: restoredFlowchartMap } : {}),
        ...(restoredOriginalDraft ? { originalDraft: restoredOriginalDraft, draftGraph: null } : {}),
      });

      // Update the session label + backendSessionId.  Also set historySourceId
      // so the sidebar "already-open" check works even after cold-revive changes
      // backendSessionId to a new live session ID.
      setSessionsByAgent((prev) => {
        const sessions = prev[agentType] || [];
        if (!sessions.length) return prev;
        return {
          ...prev,
          [agentType]: sessions.map((s, i) =>
            i === 0 ? {
              ...s,
              // Preserve existing label if it was already set with a #N suffix by
              // handleHistoryOpen. Only overwrite with the bare
              // displayName when the label doesn't match the resolved display name.
              label: s.label.startsWith(displayName) ? s.label : displayName,
              backendSessionId: session.session_id,
              // Preserve existing historySourceId; set it from coldRestoreId if missing
              historySourceId: s.historySourceId || coldRestoreId || undefined,
            } : s,
          ),
        };
      });

      // Restore messages when rejoining an existing session OR cold-restoring from disk.
      const restoredMsgs: ChatMessage[] = [];
      // For cold-restore, use the old session ID. For live resume, use current session.
      const historyId = coldRestoreId ?? (isResumedSession ? session.session_id : undefined);

      // For LIVE resume (not cold restore), fetch event log + worker status now.
      // For cold restore they were already pre-fetched above (before create) so we skip to avoid
      // double-restoring and to avoid capturing the new greeting.
      if (historyId && !coldRestoreId) {
        const restored = await restoreSessionMessages(historyId, agentType, displayName);
        restoredMsgs.push(...restored.messages);
        // Use flowchart from event log if not already set
        if (restored.flowchartMap && !restoredFlowchartMap) {
          restoredFlowchartMap = restored.flowchartMap;
          restoredOriginalDraft = restored.originalDraft;
        }
      }

      // Merge messages in chronological order (only for live resume; cold restore
      // was already applied above before create).
      if (restoredMsgs.length > 0) {
        restoredMsgs.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
        setSessionsByAgent((prev) => ({
          ...prev,
          [agentType]: (prev[agentType] || []).map((s, i) =>
            i === 0 ? { ...s, messages: [...restoredMsgs, ...s.messages] } : s,
          ),
        }));
      }

      // If no messages were actually restored, lift the intro suppression gate
      if (restoredMsgs.length === 0 && !coldRestoreId) suppressIntroRef.current.delete(agentType);

      // Mark queenReady immediately only when resuming a session that already
      // has messages (live resume or cold restore).  For a fresh session the
      // queen still needs to process the thinking hook before its first
      // response, so leave queenReady false and let the SSE handler flip it
      // on the first queen event — this keeps the "Connecting to queen..."
      // loading indicator visible until the queen actually responds.
      const hasRestoredContent = restoredMsgs.length > 0 || !!coldRestoreId;
      updateAgentState(agentType, {
        sessionId: session.session_id,
        displayName,
        ready: true,
        loading: false,
        queenReady: !!(isResumedSession || hasRestoredContent),
        // Restore flowchart overlay from persisted events
        ...(restoredFlowchartMap ? { flowchartMap: restoredFlowchartMap } : {}),
        ...(restoredOriginalDraft ? { originalDraft: restoredOriginalDraft, draftGraph: null } : {}),
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      updateAgentState(agentType, { error: msg, loading: false });
    } finally {
      loadingRef.current.delete(agentType);
    }
  }, [updateAgentState, initialPrompt]);

  // Auto-load agents when new tabs appear in sessionsByAgent.
  // Only eagerly load the active tab — background tabs are deferred until the
  // user switches to them to avoid creating duplicate backend sessions on mount.
  useEffect(() => {
    for (const agentType of Object.keys(sessionsByAgent)) {
      if (agentStates[agentType]?.sessionId || agentStates[agentType]?.loading || agentStates[agentType]?.error) continue;
      if (agentType !== activeWorker) continue;
      loadAgentForType(agentType);
    }
  }, [sessionsByAgent, agentStates, loadAgentForType, updateAgentState, activeWorker]);

  // --- Fetch graph topology when a session becomes ready ---
  const fetchGraphForAgent = useCallback(async (agentType: string, sessionId: string, knownGraphId?: string) => {
    try {
      let graphId = knownGraphId;
      if (!graphId) {
        const { graphs } = await sessionsApi.graphs(sessionId);
        if (!graphs.length) return;
        graphId = graphs[0];
      }
      const topology = await graphsApi.nodes(sessionId, graphId);

      updateAgentState(agentType, { graphId, nodeSpecs: topology.nodes });

      const graphNodes = topologyToGraphNodes(topology);
      if (graphNodes.length === 0) return;

      setSessionsByAgent((prev) => {
        const sessions = prev[agentType] || [];
        if (!sessions.length) return prev;
        return {
          ...prev,
          [agentType]: sessions.map((s, i) =>
            i === 0 ? { ...s, graphNodes } : s,
          ),
        };
      });
    } catch {
      // Graph fetch failed — keep using empty data
    }
  }, [updateAgentState]);

  // Track which sessions already have an in-flight or completed graph fetch
  // to prevent the flood of duplicate API calls.  agentStates changes on every
  // SSE event (text delta, tool_call, etc.) which re-triggers this effect
  // before the first response has returned.
  const fetchedGraphSessionsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const [agentType, state] of Object.entries(agentStates)) {
      if (!state.sessionId || !state.ready || state.nodeSpecs.length > 0 || state.graphId) continue;
      if (fetchedGraphSessionsRef.current.has(state.sessionId)) continue;
      fetchedGraphSessionsRef.current.add(state.sessionId);
      fetchGraphForAgent(agentType, state.sessionId);
    }
  }, [agentStates, fetchGraphForAgent]);

  // --- Fetch draft graph when a session is in planning phase ---
  // Covers initial load, tab switches, reconnects, and cold restores.
  const fetchedDraftSessionsRef = useRef<Set<string>>(new Set());
  const fetchedFlowchartMapSessionsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const [agentType, state] of Object.entries(agentStates)) {
      if (!state.sessionId || !state.ready) continue;

      if (state.queenPhase === "planning") {
        // Fetch draft graph for planning phase
        if (state.draftGraph) continue;
        if (fetchedDraftSessionsRef.current.has(state.sessionId)) continue;
        fetchedDraftSessionsRef.current.add(state.sessionId);
        graphsApi.draftGraph(state.sessionId).then(({ draft }) => {
          if (draft) updateAgentState(agentType, { draftGraph: draft });
        }).catch(() => {});
      } else if (state.queenPhase !== "building") {
        // Fetch flowchart map for non-building phases (staging, running)
        if (state.originalDraft) continue; // already have it
        if (fetchedFlowchartMapSessionsRef.current.has(state.sessionId)) continue;
        fetchedFlowchartMapSessionsRef.current.add(state.sessionId);
        graphsApi.flowchartMap(state.sessionId).then(({ map, original_draft }) => {
          if (original_draft) {
            updateAgentState(agentType, {
              flowchartMap: map,
              originalDraft: original_draft,
              draftGraph: null,
            });
          }
        }).catch(() => {});
      }
    }
  }, [agentStates, updateAgentState]);

  // Poll entry points every second to keep next_fire_in countdowns fresh
  // and discover dynamically created triggers (via set_trigger).
  useEffect(() => {
    const id = setInterval(async () => {
      for (const [agentType, sessions] of Object.entries(sessionsByAgent)) {
        const session = sessions[0];
        if (!session) continue;
        const state = agentStates[agentType];
        if (!state?.sessionId) continue;
        try {
          const { entry_points } = await sessionsApi.entryPoints(state.sessionId);
          // Skip non-manual triggers only
          const triggerEps = entry_points.filter(ep => ep.trigger_type !== "manual");
          if (triggerEps.length === 0) continue;

          const fireMap = new Map<string, number>();
          const taskMap = new Map<string, string>();
          const labelMap = new Map<string, string>();
          const targetMap = new Map<string, string>();
          for (const ep of triggerEps) {
            const nodeId = `__trigger_${ep.id}`;
            if (ep.next_fire_in != null) {
              fireMap.set(nodeId, ep.next_fire_in);
            }
            if (ep.task != null) {
              taskMap.set(nodeId, ep.task);
            }
            const cron = ep.trigger_config?.cron as string | undefined;
            const interval = ep.trigger_config?.interval_minutes as number | undefined;
            const epLabel = cron
              ? cronToLabel(cron)
              : interval
                ? `Every ${interval >= 60 ? `${interval / 60}h` : `${interval}m`}`
                : ep.name || undefined;
            if (epLabel) {
              labelMap.set(nodeId, epLabel);
            }
            if (ep.entry_node) {
              targetMap.set(nodeId, ep.entry_node);
            }
          }

          setSessionsByAgent((prev) => {
            const ss = prev[agentType];
            if (!ss?.length) return prev;
            const existingIds = new Set(ss[0].graphNodes.map(n => n.id));

            // Update existing trigger nodes (countdown, task, label, target)
            let updated = ss[0].graphNodes.map((n) => {
              if (n.nodeType !== "trigger") return n;
              const nfi = fireMap.get(n.id);
              const task = taskMap.get(n.id);
              const label = labelMap.get(n.id);
              const target = targetMap.get(n.id);
              if (nfi == null && task == null && !label && !target) return n;
              return {
                ...n,
                ...(label && label !== n.label ? { label } : {}),
                ...(target ? { next: [target] } : {}),
                triggerConfig: {
                  ...n.triggerConfig,
                  ...(nfi != null ? { next_fire_in: nfi } : {}),
                  ...(task != null ? { task } : {}),
                },
              };
            });

            // Discover new triggers not yet in the graph
            const fallbackEntry = ss[0].graphNodes.find(n => n.nodeType !== "trigger")?.id;
            const newNodes: GraphNode[] = [];
            for (const ep of triggerEps) {
              const nodeId = `__trigger_${ep.id}`;
              if (existingIds.has(nodeId)) continue;
              const target = ep.entry_node || fallbackEntry;
              newNodes.push({
                id: nodeId,
                label: labelMap.get(nodeId) || ep.name || ep.id,
                status: "pending",
                nodeType: "trigger",
                triggerType: ep.trigger_type,
                triggerConfig: {
                  ...ep.trigger_config,
                  ...(ep.next_fire_in != null ? { next_fire_in: ep.next_fire_in } : {}),
                  ...(ep.task ? { task: ep.task } : {}),
                },
                ...(target ? { next: [target] } : {}),
              });
            }
            if (newNodes.length > 0) {
              updated = [...newNodes, ...updated];
            }

            // Skip update if nothing changed
            if (newNodes.length === 0 && updated.every((n, idx) => n === ss[0].graphNodes[idx])) return prev;
            return {
              ...prev,
              [agentType]: ss.map((s, i) => (i === 0 ? { ...s, graphNodes: updated } : s)),
            };
          });
        } catch {
          // Entry points fetch failed — skip this tick
        }
      }
    }, 1_000);
    return () => clearInterval(id);
  }, [sessionsByAgent, agentStates]);

  // --- Graph node status helpers (now accept agentType) ---
  const updateGraphNodeStatus = useCallback(
    (agentType: string, nodeId: string, status: NodeStatus, extra?: Partial<GraphNode>) => {
      setSessionsByAgent((prev) => {
        const sessions = prev[agentType] || [];
        const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
        return {
          ...prev,
          [agentType]: sessions.map((s) => {
            if (s.id !== activeId) return s;
            return {
              ...s,
              graphNodes: s.graphNodes.map((n) =>
                n.id === nodeId ? { ...n, status, ...extra } : n
              ),
            };
          }),
        };
      });
    },
    [],
  );

  const markAllNodesAs = useCallback(
    (agentType: string, fromStatus: NodeStatus | NodeStatus[], toStatus: NodeStatus) => {
      const fromArr = Array.isArray(fromStatus) ? fromStatus : [fromStatus];
      setSessionsByAgent((prev) => {
        const sessions = prev[agentType] || [];
        const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
        return {
          ...prev,
          [agentType]: sessions.map((s) => {
            if (s.id !== activeId) return s;
            return {
              ...s,
              graphNodes: s.graphNodes.map((n) =>
                fromArr.includes(n.status) ? { ...n, status: toStatus } : n
              ),
            };
          }),
        };
      });
    },
    [],
  );

  const handlePause = useCallback(async () => {
    const state = agentStates[activeWorker];
    if (!state?.sessionId) return;

    // If we don't have an execution ID, the UI is stale — just reset state
    if (!state.currentExecutionId) {
      updateAgentState(activeWorker, { workerRunState: "idle", currentExecutionId: null });
      markAllNodesAs(activeWorker, ["running", "looping"], "pending");
      return;
    }

    try {
      const result = await executionApi.pause(state.sessionId, state.currentExecutionId);
      // If the backend says "not found", the execution already finished —
      // reset UI state instead of showing an error.
      if (result && !result.stopped) {
        updateAgentState(activeWorker, { workerRunState: "idle", currentExecutionId: null });
        markAllNodesAs(activeWorker, ["running", "looping"], "pending");
        return;
      }
      updateAgentState(activeWorker, { workerRunState: "idle", currentExecutionId: null });
      markAllNodesAs(activeWorker, ["running", "looping"], "pending");
    } catch (err) {
      // Network errors or non-2xx responses — still reset the UI since
      // the execution is likely gone, but also surface the error.
      updateAgentState(activeWorker, { workerRunState: "idle", currentExecutionId: null });
      markAllNodesAs(activeWorker, ["running", "looping"], "pending");
      const errMsg = err instanceof Error ? err.message : String(err);
      setSessionsByAgent((prev) => {
        const sessions = prev[activeWorker] || [];
        const activeId = activeSessionRef.current[activeWorker] || sessions[0]?.id;
        return {
          ...prev,
          [activeWorker]: sessions.map((s) => {
            if (s.id !== activeId) return s;
            const errorMsg: ChatMessage = {
              id: makeId(), agent: "System", agentColor: "",
              content: `Failed to pause: ${errMsg}`,
              timestamp: "", type: "system", thread: activeWorker, createdAt: Date.now(),
            };
            return { ...s, messages: [...s.messages, errorMsg] };
          }),
        };
      });
    }
  }, [agentStates, activeWorker, markAllNodesAs, updateAgentState]);

  const handleCancelQueen = useCallback(async () => {
    const state = agentStates[activeWorker];
    if (!state?.sessionId) return;
    try {
      await executionApi.cancelQueen(state.sessionId);
    } catch {
      // Best-effort — queen may have already finished
    }
    updateAgentState(activeWorker, { isTyping: false, isStreaming: false, queenIsTyping: false, workerIsTyping: false });
  }, [agentStates, activeWorker, updateAgentState]);

  // --- Node log helper (writes into agentStates) ---
  const appendNodeLog = useCallback((agentType: string, nodeId: string, line: string) => {
    setAgentStates((prev) => {
      const state = prev[agentType];
      if (!state) return prev;
      const existing = state.nodeLogs[nodeId] || [];
      return {
        ...prev,
        [agentType]: {
          ...state,
          nodeLogs: {
            ...state.nodeLogs,
            [nodeId]: [...existing, line].slice(-200),
          },
        },
      };
    });
  }, []);

  // --- SSE event handler ---
  const upsertChatMessage = useCallback(
    (agentType: string, chatMsg: ChatMessage, options?: { reconcileOptimisticUser?: boolean }) => {
      setSessionsByAgent((prev) => {
        const sessions = prev[agentType] || [];
        const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
        return {
          ...prev,
          [agentType]: sessions.map((s) => {
            if (s.id !== activeId) return s;
            const idx = s.messages.findIndex((m) => m.id === chatMsg.id);
            let newMessages: ChatMessage[];
            if (idx >= 0) {
              // Update existing message in place, preserve position
              newMessages = s.messages.map((m, i) =>
                i === idx ? { ...chatMsg, createdAt: m.createdAt ?? chatMsg.createdAt } : m,
              );
            } else {
              const shouldReconcileOptimisticUser =
                !!options?.reconcileOptimisticUser && chatMsg.type === "user" && s.messages.length > 0;
              if (shouldReconcileOptimisticUser) {
                const lastIdx = s.messages.length - 1;
                const lastMsg = s.messages[lastIdx];
                const incomingTs = chatMsg.createdAt ?? Date.now();
                const lastTs = lastMsg.createdAt ?? incomingTs;
                const sameMessage =
                  lastMsg.type === "user"
                  && lastMsg.content === chatMsg.content
                  && Math.abs(incomingTs - lastTs) <= 15000;
                if (sameMessage) {
                  newMessages = s.messages.map((m, i) =>
                    i === lastIdx ? { ...m, id: chatMsg.id } : m,
                  );
                  return { ...s, messages: newMessages };
                }
              }

              // Append — SSE events arrive in server-timestamp order via the
              // shared EventBus, so arrival order already interleaves queen
              // and worker correctly.  Local user messages are always created
              // before their server responses, so append is safe there too.
              newMessages = [...s.messages, chatMsg];
            }
            return { ...s, messages: newMessages };
          }),
        };
      });
    },
    [],
  );

  const handleSSEEvent = useCallback(
    (agentType: string, event: AgentEvent) => {
      const streamId = event.stream_id;
      const isQueen = streamId === "queen";
      if (isQueen) console.log('[QUEEN] handleSSEEvent:', event.type, 'agentType:', agentType);
      // Drop queen message content while suppressing the auto-intro after a cold-restore.
      // Uses a synchronous ref to avoid race conditions with React state batching.
      const suppressQueenMessages = isQueen && suppressIntroRef.current.has(agentType);
      const agentDisplayName = agentStates[agentType]?.displayName;
      const displayName = isQueen ? "Queen Bee" : (agentDisplayName || undefined);
      const role = isQueen ? "queen" as const : "worker" as const;
      const ts = fmtLogTs(event.timestamp);
      // Turn counter is per-stream so queen and worker tool pills don't
      // interfere.  A worker node_loop_iteration no longer increments
      // the queen's turn counter (which would cause pill ID mismatches
      // between tool_call_started and tool_call_completed).
      const turnKey = `${agentType}:${streamId}`;
      const currentTurn = turnCounterRef.current[turnKey] ?? 0;
      // Backend event timestamp for correct queen/worker message ordering
      const eventCreatedAt = event.timestamp ? new Date(event.timestamp).getTime() : Date.now();

      // Mark queen as ready on the first queen SSE event.
      // Deferred to individual event handlers below so we can batch it with
      // other state updates (e.g. queenIsTyping) and avoid a flash frame
      // where queenReady=true but queenIsTyping=false.
      const shouldMarkQueenReady = isQueen && !agentStates[agentType]?.queenReady;

      switch (event.type) {
        case "execution_started":
          if (isQueen) {
            turnCounterRef.current[turnKey] = currentTurn + 1;
            updateAgentState(agentType, { isTyping: true, queenIsTyping: true, ...(shouldMarkQueenReady && { queenReady: true }) });
          } else {
            // Warn if prior LLM snapshots are being dropped (edge case: execution_completed never arrived)
            const priorSnapshots = agentStates[agentType]?.llmSnapshots || {};
            if (Object.keys(priorSnapshots).length > 0) {
              console.debug(`[hive] execution_started: dropping ${Object.keys(priorSnapshots).length} unflushed LLM snapshot(s)`);
            }
            // Insert a run divider when a new run_id is detected
            const incomingRunId = event.run_id || null;
            const prevRunId = agentStates[agentType]?.currentRunId;
            if (incomingRunId && incomingRunId !== prevRunId) {
              const dividerMsg: ChatMessage = {
                id: `run-divider-${incomingRunId}`,
                agent: "",
                agentColor: "",
                content: prevRunId ? "New Run" : "Run Started",
                timestamp: ts,
                type: "run_divider",
                role: "worker",
                thread: agentType,
                createdAt: eventCreatedAt,
              };
              upsertChatMessage(agentType, dividerMsg);
            }
            turnCounterRef.current[turnKey] = currentTurn + 1;
            updateAgentState(agentType, {
              isTyping: true,
              isStreaming: false,
              workerIsTyping: true,
              awaitingInput: false,
              workerRunState: "running",
              currentExecutionId: event.execution_id || agentStates[agentType]?.currentExecutionId || null,
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
            markAllNodesAs(agentType, ["running", "looping", "complete", "error"], "pending");
          }
          break;

        case "execution_completed":
          if (isQueen) {
            suppressIntroRef.current.delete(agentType);
            updateAgentState(agentType, { isTyping: false, queenIsTyping: false });
          } else {
            // Flush any remaining LLM snapshots before clearing state
            const completedSnapshots = agentStates[agentType]?.llmSnapshots || {};
            for (const [nid, text] of Object.entries(completedSnapshots)) {
              if (text?.trim()) {
                appendNodeLog(agentType, nid, `${ts} INFO  LLM: ${truncate(text.trim(), 300)}`);
              }
            }
            updateAgentState(agentType, {
              isTyping: false,
              isStreaming: false,
              workerIsTyping: false,
              awaitingInput: false,
              workerInputMessageId: null,
              workerRunState: "idle",
              currentExecutionId: null,
              llmSnapshots: {},
              pendingQuestion: null,
              pendingOptions: null,
              pendingQuestions: null,
              pendingQuestionSource: null,
            });
            markAllNodesAs(agentType, ["running", "looping"], "complete");

            // Re-fetch graph topology so timer countdowns refresh
            const sid = agentStates[agentType]?.sessionId;
            const gid = agentStates[agentType]?.graphId;
            if (sid) fetchGraphForAgent(agentType, sid, gid || undefined);
          }
          break;

        case "execution_paused":
        case "execution_failed":
        case "client_output_delta":
        case "client_input_received":
        case "client_input_requested":
        case "llm_text_delta": {
          const chatMsg = sseEventToChatMessage(event, agentType, displayName, currentTurn);
          if (isQueen) console.log('[QUEEN] chatMsg:', chatMsg?.id, chatMsg?.content?.slice(0, 50), 'turn:', currentTurn);
          if (chatMsg && !suppressQueenMessages) {
            // Queen emits multiple client_output_delta / llm_text_delta snapshots
            // across iterations and inner tool-loop turns.  Merge all inner_turns
            // within the same iteration into ONE bubble so the queen's multi-step
            // tool loop (text → tool → text → tool → text) appears as one cohesive
            // message rather than many small fragments.
            if (isQueen && (event.type === "client_output_delta" || event.type === "llm_text_delta") && event.execution_id) {
              const iter = event.data?.iteration ?? 0;
              const inner = (event.data?.inner_turn as number) ?? 0;
              const iterKey = `${agentType}:${event.execution_id}:${iter}`;

              // Store the latest snapshot for this inner_turn
              if (!queenIterTextRef.current[iterKey]) {
                queenIterTextRef.current[iterKey] = {};
              }
              const snapshot = (event.data?.snapshot as string) || (event.data?.content as string) || "";
              queenIterTextRef.current[iterKey][inner] = snapshot;

              // Concatenate all inner_turn snapshots in order
              const parts = queenIterTextRef.current[iterKey];
              const sortedInners = Object.keys(parts).map(Number).sort((a, b) => a - b);
              chatMsg.content = sortedInners.map(k => parts[k]).join("\n");

              // Single ID per iteration — no inner_turn in the ID
              chatMsg.id = `queen-stream-${event.execution_id}-${iter}`;
            }
            if (isQueen) {
              chatMsg.role = role;
              chatMsg.phase = queenPhaseRef.current[agentType] as ChatMessage["phase"];
            }
            upsertChatMessage(agentType, chatMsg, {
              reconcileOptimisticUser: event.type === "client_input_received",
            });
          }

          // Mark streaming when LLM text is actively arriving
          if (event.type === "llm_text_delta" || event.type === "client_output_delta") {
            updateAgentState(agentType, { isStreaming: true, ...(isQueen ? {} : { workerIsTyping: false }) });
          }

          if (event.type === "llm_text_delta" && !isQueen && event.node_id) {
            const snapshot = (event.data?.snapshot as string) || "";
            if (snapshot) {
              setAgentStates(prev => {
                const state = prev[agentType];
                if (!state) return prev;
                return {
                  ...prev,
                  [agentType]: {
                    ...state,
                    llmSnapshots: { ...state.llmSnapshots, [event.node_id!]: snapshot },
                  },
                };
              });
            }
          }

          if (event.type === "client_input_requested") {
            console.log('[CLIENT_INPUT_REQ] stream_id:', streamId, 'isQueen:', isQueen, 'node_id:', event.node_id, 'prompt:', (event.data?.prompt as string)?.slice(0, 80), 'agentType:', agentType);
            const rawOptions = event.data?.options;
            const options = Array.isArray(rawOptions) ? (rawOptions as string[]) : null;
            const rawQuestions = event.data?.questions;
            const questions = Array.isArray(rawQuestions)
              ? (rawQuestions as { id: string; prompt: string; options?: string[] }[])
              : null;
            if (isQueen) {
              const prompt = (event.data?.prompt as string) || "";
              setAgentStates(prev => {
                const cur = prev[agentType] || defaultAgentState();
                return {
                  ...prev, [agentType]: {
                    ...cur,
                    awaitingInput: true,
                    isTyping: false,
                    isStreaming: false,
                    queenIsTyping: false,
                    queenBuilding: false,
                    pendingQuestion: prompt || null,
                    pendingOptions: options,
                    pendingQuestions: questions,
                    pendingQuestionSource: "queen",
                  }
                };
              });
            } else {
              console.warn(
                "[CLIENT_INPUT_REQ] ignoring non-queen client_input_requested event",
                streamId,
                event.node_id,
              );
            }
          }
          if (event.type === "execution_paused") {
            updateAgentState(agentType, { isTyping: false, isStreaming: false, queenIsTyping: false, workerIsTyping: false, awaitingInput: false, workerInputMessageId: null, pendingQuestion: null, pendingOptions: null, pendingQuestions: null, pendingQuestionSource: null });
            if (!isQueen) {
              updateAgentState(agentType, { workerRunState: "idle", currentExecutionId: null });
              markAllNodesAs(agentType, ["running", "looping"], "pending");
            }
          }
          if (event.type === "execution_failed") {
            updateAgentState(agentType, { isTyping: false, isStreaming: false, queenIsTyping: false, workerIsTyping: false, awaitingInput: false, workerInputMessageId: null, pendingQuestion: null, pendingOptions: null, pendingQuestions: null, pendingQuestionSource: null });
            if (!isQueen) {
              updateAgentState(agentType, { workerRunState: "idle", currentExecutionId: null });
              if (event.node_id) {
                updateGraphNodeStatus(agentType, event.node_id, "error");
                const errMsg = (event.data?.error as string) || "unknown error";
                appendNodeLog(agentType, event.node_id, `${ts} ERROR Execution failed: ${errMsg}`);
              }
              markAllNodesAs(agentType, ["running", "looping"], "pending");
            }
          }
          break;
        }

        case "node_loop_started":
          turnCounterRef.current[turnKey] = currentTurn + 1;
          updateAgentState(agentType, { isTyping: true, activeToolCalls: {} });
          if (!isQueen && event.node_id) {
            const sessions = sessionsRef.current[agentType] || [];
            const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
            const session = sessions.find((s) => s.id === activeId);
            const existing = session?.graphNodes.find((n) => n.id === event.node_id);
            const isRevisit = existing?.status === "complete";
            updateGraphNodeStatus(agentType, event.node_id, isRevisit ? "looping" : "running", {
              maxIterations: (event.data?.max_iterations as number) ?? undefined,
            });
            appendNodeLog(agentType, event.node_id, `${ts} INFO  Node started`);
          }
          break;

        case "node_loop_iteration":
          turnCounterRef.current[turnKey] = currentTurn + 1;
          if (isQueen) {
            updateAgentState(agentType, { isStreaming: false, activeToolCalls: {}, awaitingInput: false, pendingQuestion: null, pendingOptions: null, pendingQuestions: null, pendingQuestionSource: null });
          } else {
            updateAgentState(agentType, { isStreaming: false, workerIsTyping: true, activeToolCalls: {}, awaitingInput: false, pendingQuestion: null, pendingOptions: null, pendingQuestions: null, pendingQuestionSource: null });
          }
          if (!isQueen && event.node_id) {
            const pendingText = agentStates[agentType]?.llmSnapshots[event.node_id];
            if (pendingText?.trim()) {
              appendNodeLog(agentType, event.node_id, `${ts} INFO  LLM: ${truncate(pendingText.trim(), 300)}`);
              setAgentStates(prev => {
                const state = prev[agentType];
                if (!state) return prev;
                const { [event.node_id!]: _, ...rest } = state.llmSnapshots;
                return { ...prev, [agentType]: { ...state, llmSnapshots: rest } };
              });
            }
            const iter = (event.data?.iteration as number) ?? undefined;
            updateGraphNodeStatus(agentType, event.node_id, "looping", { iterations: iter });
            appendNodeLog(agentType, event.node_id, `${ts} INFO  Iteration ${iter ?? "?"}`);
          }
          break;

        case "node_loop_completed":
          if (!isQueen && event.node_id) {
            const pendingText = agentStates[agentType]?.llmSnapshots[event.node_id];
            if (pendingText?.trim()) {
              appendNodeLog(agentType, event.node_id, `${ts} INFO  LLM: ${truncate(pendingText.trim(), 300)}`);
              setAgentStates(prev => {
                const state = prev[agentType];
                if (!state) return prev;
                const { [event.node_id!]: _, ...rest } = state.llmSnapshots;
                return { ...prev, [agentType]: { ...state, llmSnapshots: rest } };
              });
            }
            updateGraphNodeStatus(agentType, event.node_id, "complete");
            appendNodeLog(agentType, event.node_id, `${ts} INFO  Node completed`);
          }
          break;

        case "edge_traversed": {
          if (!isQueen) {
            const sourceNode = event.data?.source_node as string | undefined;
            const targetNode = event.data?.target_node as string | undefined;
            if (sourceNode) updateGraphNodeStatus(agentType, sourceNode, "complete");
            if (targetNode) updateGraphNodeStatus(agentType, targetNode, "running");
          }
          break;
        }

        case "tool_call_started": {
          console.log('[TOOL_PILL] tool_call_started received:', { isQueen, nodeId: event.node_id, streamId: event.stream_id, agentType, executionId: event.execution_id, toolName: event.data?.tool_name });

          // queenBuilding is now driven by queen_phase_changed events

          if (event.node_id) {
            if (!isQueen) {
              const pendingText = agentStates[agentType]?.llmSnapshots[event.node_id];
              if (pendingText?.trim()) {
                appendNodeLog(agentType, event.node_id, `${ts} INFO  LLM: ${truncate(pendingText.trim(), 300)}`);
                setAgentStates(prev => {
                  const state = prev[agentType];
                  if (!state) return prev;
                  const { [event.node_id!]: _, ...rest } = state.llmSnapshots;
                  return { ...prev, [agentType]: { ...state, llmSnapshots: rest } };
                });
              }
              appendNodeLog(agentType, event.node_id, `${ts} INFO  Calling ${(event.data?.tool_name as string) || "unknown"}(${event.data?.tool_input ? truncate(JSON.stringify(event.data.tool_input), 200) : ""})`);

              // Track subagent delegation start
              if ((event.data?.tool_name as string) === "delegate_to_sub_agent") {
                const saInput = event.data?.tool_input as Record<string, unknown> | undefined;
                const saId = (saInput?.agent_id as string) || "";
                if (saId) {
                  setAgentStates(prev => {
                    const state = prev[agentType];
                    if (!state) return prev;
                    return {
                      ...prev,
                      [agentType]: {
                        ...state,
                        subagentReports: [
                          ...state.subagentReports,
                          { subagent_id: saId, message: "Delegating...", timestamp: event.timestamp, status: "running" as const },
                        ],
                      },
                    };
                  });
                }
              }
            }

            const toolName = (event.data?.tool_name as string) || "unknown";
            const toolUseId = (event.data?.tool_use_id as string) || "";

            // Flag when the queen starts designing/updating the flowchart
            if (isQueen && toolName === "save_agent_draft") {
              designingDraftSinceRef.current[agentType] = Date.now();
              // Clear any pending delayed-clear timer from a previous call
              const prev = designingDraftTimerRef.current[agentType];
              if (prev) clearTimeout(prev);
              updateAgentState(agentType, { designingDraft: true });
            }

            // Track active (in-flight) tools and upsert activity row into chat
            const sid = event.stream_id;
            setAgentStates(prev => {
              const state = prev[agentType];
              if (!state) return prev;
              const newActive = { ...state.activeToolCalls, [toolUseId]: { name: toolName, done: false, streamId: sid } };
              // Only include tools from this stream in the pill
              const tools = Object.values(newActive).filter(t => t.streamId === sid).map(t => ({ name: t.name, done: t.done }));
              const allDone = tools.length > 0 && tools.every(t => t.done);
              upsertChatMessage(agentType, {
                id: `tool-pill-${sid}-${event.execution_id || "exec"}-${currentTurn}`,
                agent: agentDisplayName || event.node_id || "Agent",
                agentColor: "",
                content: JSON.stringify({ tools, allDone }),
                timestamp: "",
                type: "tool_status",
                role,
                thread: agentType,
                createdAt: eventCreatedAt,
                nodeId: event.node_id || undefined,
                executionId: event.execution_id || undefined,
              });
              return {
                ...prev,
                [agentType]: { ...state, isStreaming: false, activeToolCalls: newActive },
              };
            });
          } else {
            console.log('[TOOL_PILL] SKIPPED: no node_id', event.node_id);
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
              appendNodeLog(agentType, event.node_id, `${ts} ERROR ${toolName} failed: ${truncate(result || "unknown error", 200)}`);
            } else {
              const resultStr = result ? ` (${truncate(result, 200)})` : "";
              appendNodeLog(agentType, event.node_id, `${ts} INFO  ${toolName} done${resultStr}`);
            }

            // Track subagent delegation completion
            if (toolName === "delegate_to_sub_agent" && result) {
              try {
                const parsed = JSON.parse(result);
                const saId = (parsed?.metadata?.agent_id as string) || "";
                const success = parsed?.metadata?.success as boolean;
                if (saId) {
                  setAgentStates(prev => {
                    const state = prev[agentType];
                    if (!state) return prev;
                    return {
                      ...prev,
                      [agentType]: {
                        ...state,
                        subagentReports: [
                          ...state.subagentReports,
                          { subagent_id: saId, message: success ? "Completed" : "Failed", timestamp: event.timestamp, status: success ? "complete" as const : "error" as const },
                        ],
                      },
                    };
                  });
                }
              } catch { /* ignore parse errors */ }
            }

            // Mark tool as done and update activity row
            const sid = event.stream_id;
            setAgentStates(prev => {
              const state = prev[agentType];
              if (!state) return prev;
              const updated = { ...state.activeToolCalls };
              if (updated[toolUseId]) {
                updated[toolUseId] = { ...updated[toolUseId], done: true };
              }
              const tools = Object.values(updated).filter(t => t.streamId === sid).map(t => ({ name: t.name, done: t.done }));
              const allDone = tools.length > 0 && tools.every(t => t.done);
              upsertChatMessage(agentType, {
                id: `tool-pill-${sid}-${event.execution_id || "exec"}-${currentTurn}`,
                agent: agentDisplayName || event.node_id || "Agent",
                agentColor: "",
                content: JSON.stringify({ tools, allDone }),
                timestamp: "",
                type: "tool_status",
                role,
                thread: agentType,
                createdAt: eventCreatedAt,
                nodeId: event.node_id || undefined,
                executionId: event.execution_id || undefined,
              });
              return {
                ...prev,
                [agentType]: { ...state, activeToolCalls: updated },
              };
            });
          }
          break;
        }

        case "node_internal_output":
          if (!isQueen && event.node_id) {
            const content = (event.data?.content as string) || "";
            if (content.trim()) {
              appendNodeLog(agentType, event.node_id, `${ts} INFO  ${content}`);
            }
          }
          break;

        case "subagent_report": {
          if (!isQueen && event.node_id) {
            const subagentId = (event.data?.subagent_id as string) || "";
            const message = (event.data?.message as string) || "";
            const data = event.data?.data as Record<string, unknown> | undefined;
            // Extract parent node ID from "parentNodeId:subagent:agentId" format
            const parentNodeId = event.node_id.split(":subagent:")[0] || event.node_id;
            appendNodeLog(agentType, parentNodeId, `${ts} INFO  [Subagent:${subagentId}] ${truncate(message, 200)}`);
            setAgentStates(prev => {
              const state = prev[agentType];
              if (!state) return prev;
              return {
                ...prev,
                [agentType]: {
                  ...state,
                  subagentReports: [
                    ...state.subagentReports,
                    { subagent_id: subagentId, message, data, timestamp: event.timestamp },
                  ],
                },
              };
            });
          }
          break;
        }

        case "node_stalled":
          if (!isQueen && event.node_id) {
            const reason = (event.data?.reason as string) || "unknown";
            appendNodeLog(agentType, event.node_id, `${ts} WARN  Stalled: ${reason}`);
          }
          break;

        case "node_retry":
          if (!isQueen && event.node_id) {
            const retryCount = (event.data?.retry_count as number) ?? "?";
            const maxRetries = (event.data?.max_retries as number) ?? "?";
            const retryError = (event.data?.error as string) || "";
            appendNodeLog(agentType, event.node_id, `${ts} WARN  Retry ${retryCount}/${maxRetries}${retryError ? `: ${retryError}` : ""}`);
          }
          break;

        case "node_tool_doom_loop":
          if (!isQueen && event.node_id) {
            const description = (event.data?.description as string) || "tool cycle detected";
            appendNodeLog(agentType, event.node_id, `${ts} WARN  Doom loop: ${description}`);
          }
          break;

        case "context_compacted":
          if (!isQueen && event.node_id) {
            const usageBefore = (event.data?.usage_before as number) ?? "?";
            const usageAfter = (event.data?.usage_after as number) ?? "?";
            appendNodeLog(agentType, event.node_id, `${ts} INFO  Context compacted: ${usageBefore}% -> ${usageAfter}%`);
          }
          break;

        case "context_usage_updated": {
            const streamKey = isQueen ? "__queen__" : (event.node_id || streamId);
            const usagePct = (event.data?.usage_pct as number) ?? 0;
            const messageCount = (event.data?.message_count as number) ?? 0;
            const estimatedTokens = (event.data?.estimated_tokens as number) ?? 0;
            const maxTokens = (event.data?.max_context_tokens as number) ?? 0;
            setAgentStates(prev => {
              const state = prev[agentType];
              if (!state) return prev;
              return {
                ...prev,
                [agentType]: {
                  ...state,
                  contextUsage: {
                    ...state.contextUsage,
                    [streamKey]: { usagePct, messageCount, estimatedTokens, maxTokens },
                  },
                },
              };
            });
          }
          break;

        case "node_action_plan":
          if (!isQueen && event.node_id) {
            const plan = (event.data?.plan as string) || "";
            if (plan.trim()) {
              setAgentStates(prev => {
                const state = prev[agentType];
                if (!state) return prev;
                return {
                  ...prev,
                  [agentType]: {
                    ...state,
                    nodeActionPlans: { ...state.nodeActionPlans, [event.node_id!]: plan },
                  },
                };
              });
            }
          }
          break;

        case "credentials_required": {
          updateAgentState(agentType, { workerRunState: "idle", error: "credentials_required" });
          const credAgentPath = event.data?.agent_path as string | undefined;
          if (credAgentPath) setCredentialAgentPath(credAgentPath);
          setCredentialsOpen(true);
          break;
        }

        case "queen_phase_changed": {
          const rawPhase = event.data?.phase as string;
          const eventAgentPath = (event.data?.agent_path as string) || null;
          const newPhase: "planning" | "building" | "staging" | "running" =
            rawPhase === "running" ? "running"
            : rawPhase === "staging" ? "staging"
            : rawPhase === "planning" ? "planning"
            : "building";
          queenPhaseRef.current[agentType] = newPhase;
          updateAgentState(agentType, {
            queenPhase: newPhase,
            queenBuilding: newPhase === "building",
            // Sync workerRunState so the RunButton reflects the phase
            workerRunState: newPhase === "running" ? "running" : "idle",
            // Clear originalDraft/flowchartMap when re-entering planning.
            // draftGraph is cleared later when originalDraft arrives, so the
            // entrance animation has data to render during the handoff.
            ...(newPhase === "planning"
              ? { originalDraft: null, flowchartMap: null }
              : {}),
            // Store agent path for credential queries
            ...(eventAgentPath ? { agentPath: eventAgentPath } : {}),
          });
          {
            const sid = agentStates[agentType]?.sessionId;
            if (sid) {
              if (newPhase !== "planning" && newPhase !== "building") {
                fetchedDraftSessionsRef.current.delete(sid);
                fetchedFlowchartMapSessionsRef.current.delete(sid);
                // Fetch the flowchart map (original draft + dissolution mapping)
                graphsApi.flowchartMap(sid).then(({ map, original_draft }) => {
                  updateAgentState(agentType, {
                    flowchartMap: map,
                    originalDraft: original_draft,
                  });
                }).catch(() => {});
              } else if (newPhase === "planning") {
                // Only clear dedup sets when re-entering planning (not building)
                fetchedDraftSessionsRef.current.delete(sid);
                fetchedFlowchartMapSessionsRef.current.delete(sid);
              }
            }
          }
          break;
        }

        case "draft_graph_updated": {
          // The draft dict is published directly as event.data (not nested under a key)
          const draft = event.data as unknown as DraftGraphData | undefined;
          if (draft?.nodes) {
            // Ensure the "Designing flowchart…" spinner stays visible for a
            // minimum duration so users see feedback before the draft appears.
            const MIN_SPINNER_MS = 600;
            const since = designingDraftSinceRef.current[agentType] || 0;
            const elapsed = Date.now() - since;
            const remaining = Math.max(0, MIN_SPINNER_MS - elapsed);

            const applyDraft = () => {
              delete designingDraftTimerRef.current[agentType];
              updateAgentState(agentType, { draftGraph: draft, designingDraft: false });
            };

            if (remaining > 0 && since > 0) {
              // Update draftGraph now (so data is ready) but keep spinner visible
              updateAgentState(agentType, { draftGraph: draft });
              designingDraftTimerRef.current[agentType] = setTimeout(() => {
                updateAgentState(agentType, { designingDraft: false });
                delete designingDraftTimerRef.current[agentType];
              }, remaining);
            } else {
              applyDraft();
            }
          }
          break;
        }

        case "flowchart_map_updated": {
          const mapData = event.data as { map?: Record<string, string[]>; original_draft?: DraftGraphData } | undefined;
          if (mapData) {
            updateAgentState(agentType, {
              flowchartMap: mapData.map ?? null,
              originalDraft: mapData.original_draft ?? null,
              draftGraph: null,
            });
          }
          break;
        }

        case "worker_graph_loaded": {
          const graphName = event.data?.graph_name as string | undefined;
          const agentPathFromEvent = event.data?.agent_path as string | undefined;
          const displayName = formatAgentDisplayName(graphName || baseAgentType(agentType));

          // Invalidate cached credential requirements so the modal fetches
          // fresh data the next time it opens (the new agent may have
          // different credential needs than the previous one).
          clearCredentialCache(agentPathFromEvent);
          clearCredentialCache(baseAgentType(agentType));

          // Update agent state: new display name, reset graph so topology refetch triggers
          updateAgentState(agentType, {
            displayName,
            queenBuilding: false,
            workerRunState: "idle",
            graphId: null,
            nodeSpecs: [],
          });

          // Update ONLY the active session's label + graph nodes — never touch
          // sessions belonging to a different tab sharing the same agentType key.
          // Also clear worker messages so the fresh worker starts with a clean slate.
          const activeId = activeSessionRef.current[agentType];
          setSessionsByAgent(prev => ({
            ...prev,
            [agentType]: (prev[agentType] || []).map(s =>
              s.id === activeId || (!activeId && prev[agentType]?.[0]?.id === s.id)
                ? { ...s, label: displayName, graphNodes: [], messages: s.messages.filter(m => m.role !== "worker") }
                : s
            ),
          }));

          // Explicitly fetch graph topology for the newly loaded worker
          // (don't rely solely on the effect — state may already be null/empty)
          const sessionId = agentStates[agentType]?.sessionId;
          if (sessionId) {
            fetchGraphForAgent(agentType, sessionId);
          }

          break;
        }

        case "trigger_activated": {
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            const nodeId = `__trigger_${triggerId}`;
            // If the trigger node doesn't exist yet (dynamically created via set_trigger),
            // synthesize it before updating status.
            setSessionsByAgent(prev => {
              const sessions = prev[agentType] || [];
              const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
              return {
                ...prev,
                [agentType]: sessions.map(s => {
                  if (s.id !== activeId) return s;
                  const exists = s.graphNodes.some(n => n.id === nodeId);
                  if (exists) {
                    return {
                      ...s,
                      graphNodes: s.graphNodes.map(n =>
                        n.id === nodeId ? { ...n, status: "running" as const } : n,
                      ),
                    };
                  }
                  // Synthesize new trigger node at the front of the graph
                  const triggerType = (event.data?.trigger_type as string) || "timer";
                  const triggerConfig = (event.data?.trigger_config as Record<string, unknown>) || {};
                  const entryNode = (event.data?.entry_node as string) || s.graphNodes.find(n => n.nodeType !== "trigger")?.id;
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
                    status: "running",
                    nodeType: "trigger",
                    triggerType,
                    triggerConfig,
                    ...(entryNode ? { next: [entryNode] } : {}),
                  };
                  return { ...s, graphNodes: [newNode, ...s.graphNodes] };
                }),
              };
            });
          }
          break;
        }

        case "trigger_deactivated": {
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            // Clear next_fire_in so countdown hides when inactive
            setSessionsByAgent(prev => {
              const sessions = prev[agentType] || [];
              const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
              return {
                ...prev,
                [agentType]: sessions.map(s => {
                  if (s.id !== activeId) return s;
                  return {
                    ...s,
                    graphNodes: s.graphNodes.map(n => {
                      if (n.id !== `__trigger_${triggerId}`) return n;
                      const { next_fire_in: _, ...restConfig } = (n.triggerConfig || {}) as Record<string, unknown> & { next_fire_in?: unknown };
                      return { ...n, status: "pending" as const, triggerConfig: restConfig };
                    }),
                  };
                }),
              };
            });
          }
          break;
        }

        case "trigger_fired": {
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            const nodeId = `__trigger_${triggerId}`;
            updateGraphNodeStatus(agentType, nodeId, "complete");
            setTimeout(() => updateGraphNodeStatus(agentType, nodeId, "running"), 1500);
          }
          break;
        }

        case "trigger_available": {
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            const nodeId = `__trigger_${triggerId}`;
            setSessionsByAgent(prev => {
              const sessions = prev[agentType] || [];
              const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
              return {
                ...prev,
                [agentType]: sessions.map(s => {
                  if (s.id !== activeId) return s;
                  if (s.graphNodes.some(n => n.id === nodeId)) return s;
                  const triggerType = (event.data?.trigger_type as string) || "timer";
                  const triggerConfig = (event.data?.trigger_config as Record<string, unknown>) || {};
                  const entryNode = (event.data?.entry_node as string) || s.graphNodes.find(n => n.nodeType !== "trigger")?.id;
                  const triggerName = (event.data?.name as string) || triggerId;
                  const _cron2 = triggerConfig.cron as string | undefined;
                  const _interval2 = triggerConfig.interval_minutes as number | undefined;
                  const computedLabel2 = _cron2
                    ? cronToLabel(_cron2)
                    : _interval2
                      ? `Every ${_interval2 >= 60 ? `${_interval2 / 60}h` : `${_interval2}m`}`
                      : triggerName;
                  const newNode: GraphNode = {
                    id: nodeId,
                    label: computedLabel2,
                    status: "pending",
                    nodeType: "trigger",
                    triggerType,
                    triggerConfig,
                    ...(entryNode ? { next: [entryNode] } : {}),
                  };
                  return { ...s, graphNodes: [newNode, ...s.graphNodes] };
                }),
              };
            });
          }
          break;
        }

        case "trigger_updated": {
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            const nodeId = `__trigger_${triggerId}`;
            const triggerConfig = (event.data?.trigger_config as Record<string, unknown>) || {};
            const cron = triggerConfig.cron as string | undefined;
            const interval = triggerConfig.interval_minutes as number | undefined;
            const newLabel = cron
              ? cronToLabel(cron)
              : interval
                ? `Every ${interval >= 60 ? `${interval / 60}h` : `${interval}m`}`
                : undefined;
            setSessionsByAgent(prev => {
              const sessions = prev[agentType] || [];
              const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
              return {
                ...prev,
                [agentType]: sessions.map(s => {
                  if (s.id !== activeId) return s;
                  return {
                    ...s,
                    graphNodes: s.graphNodes.map(n => {
                      if (n.id !== nodeId) return n;
                      return {
                        ...n,
                        ...(newLabel ? { label: newLabel } : {}),
                        triggerConfig: { ...n.triggerConfig, ...triggerConfig },
                      };
                    }),
                  };
                }),
              };
            });
          }
          break;
        }

        case "trigger_removed": {
          const triggerId = event.data?.trigger_id as string;
          if (triggerId) {
            const nodeId = `__trigger_${triggerId}`;
            setSessionsByAgent(prev => {
              const sessions = prev[agentType] || [];
              const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
              return {
                ...prev,
                [agentType]: sessions.map(s => {
                  if (s.id !== activeId) return s;
                  return { ...s, graphNodes: s.graphNodes.filter(n => n.id !== nodeId) };
                }),
              };
            });
          }
          break;
        }

        default:
          // Fallback: ensure queenReady is set even for unexpected first events
          if (shouldMarkQueenReady) updateAgentState(agentType, { queenReady: true });
          break;
      }
    },
    [agentStates, updateAgentState, updateGraphNodeStatus, markAllNodesAs, upsertChatMessage, appendNodeLog, fetchGraphForAgent],
  );

  // --- Multi-session SSE subscription ---
  const sseSessions = useMemo(() => {
    const map: Record<string, string> = {};
    for (const [agentType, state] of Object.entries(agentStates)) {
      if (state.sessionId && state.ready) {
        map[agentType] = state.sessionId;
      }
    }
    return map;
  }, [agentStates]);

  useMultiSSE({ sessions: sseSessions, onEvent: handleSSEEvent });

  const currentSessions = sessionsByAgent[activeWorker] || [];
  const activeSessionId = activeSessionByAgent[activeWorker] || currentSessions[0]?.id;
  const activeSession = currentSessions.find(s => s.id === activeSessionId) || currentSessions[0];

  const currentGraph = activeSession
    ? { nodes: activeSession.graphNodes, title: activeAgentState?.displayName || formatAgentDisplayName(baseAgentType(activeWorker)) }
    : { nodes: [] as GraphNode[], title: "" };

  // Keep selectedNode in sync with live graphNodes (trigger status updates via SSE)
  const liveSelectedNode = selectedNode && currentGraph.nodes.find(n => n.id === selectedNode.id);
  const resolvedSelectedNode = liveSelectedNode || selectedNode;

  // Sync trigger drafts when selected trigger node changes
  useEffect(() => {
    if (resolvedSelectedNode?.nodeType === "trigger") {
      const tc = resolvedSelectedNode.triggerConfig as Record<string, unknown> | undefined;
      setTriggerTaskDraft((tc?.task as string) || "");
      setTriggerCronDraft((tc?.cron as string) || "");
    }
  }, [resolvedSelectedNode?.id]);

  const patchTriggerNode = useCallback((agentType: string, triggerNodeId: string, patch: { task?: string; trigger_config?: Record<string, unknown>; label?: string }) => {
    setSessionsByAgent(prev => {
      const sessions = prev[agentType] || [];
      const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
      return {
        ...prev,
        [agentType]: sessions.map(s => {
          if (s.id !== activeId) return s;
          return {
            ...s,
            graphNodes: s.graphNodes.map(n => {
              if (n.id !== triggerNodeId) return n;
              return {
                ...n,
                ...(patch.label !== undefined ? { label: patch.label } : {}),
                triggerConfig: {
                  ...n.triggerConfig,
                  ...(patch.trigger_config || {}),
                  ...(patch.task !== undefined ? { task: patch.task } : {}),
                },
              };
            }),
          };
        }),
      };
    });
  }, []);

  // Build a flat list of all agent-type tabs for the tab bar
  const agentTabs = Object.entries(sessionsByAgent)
    .filter(([, sessions]) => sessions.length > 0)
    .map(([agentType, sessions]) => {
      const activeId = activeSessionByAgent[agentType] || sessions[0]?.id;
      const session = sessions.find(s => s.id === activeId) || sessions[0];
      return {
        agentType,
        sessionId: session.id,
        label: session.label,
        isActive: agentType === activeWorker,
        hasRunning: session.graphNodes.some(n => n.status === "running" || n.status === "looping"),
      };
    });

  // --- handleSend ---
  const handleSend = useCallback((text: string, thread: string, images?: import("@/components/ChatPanel").ImageContent[]) => {
    if (!activeSession) return;
    const state = agentStates[activeWorker];

    if (!allRequiredCredentialsMet(activeSession.credentials)) {
      const userMsg: ChatMessage = {
        id: makeId(), agent: "You", agentColor: "",
        content: text, timestamp: "", type: "user", thread, createdAt: Date.now(),
      };
      const promptMsg: ChatMessage = {
        id: makeId(), agent: "Queen Bee", agentColor: "",
        content: "Before we get started, you'll need to configure your credentials. Click the **Credentials** button in the top bar to connect the required integrations for this agent.",
        timestamp: "", role: "queen" as const, thread, createdAt: Date.now(),
      };
      setSessionsByAgent(prev => ({
        ...prev,
        [activeWorker]: prev[activeWorker].map(s =>
          s.id === activeSession.id ? { ...s, messages: [...s.messages, userMsg, promptMsg] } : s
        ),
      }));
      return;
    }

    // If queen has a pending question widget, dismiss it when user types directly
    if (agentStates[activeWorker]?.pendingQuestionSource === "queen") {
      updateAgentState(activeWorker, { pendingQuestion: null, pendingOptions: null, pendingQuestions: null, pendingQuestionSource: null });
    }

    const userMsg: ChatMessage = {
      id: makeId(), agent: "You", agentColor: "",
      content: text, timestamp: "", type: "user", thread, createdAt: Date.now(),
      images,
    };
    setSessionsByAgent(prev => ({
      ...prev,
      [activeWorker]: prev[activeWorker].map(s =>
        s.id === activeSession.id ? { ...s, messages: [...s.messages, userMsg] } : s
      ),
    }));
    suppressIntroRef.current.delete(activeWorker);
    updateAgentState(activeWorker, { isTyping: true, queenIsTyping: true });

    if (state?.sessionId && state?.ready) {
      executionApi.chat(state.sessionId, text, images).catch((err: unknown) => {
        const errMsg = err instanceof Error ? err.message : String(err);
        const errorChatMsg: ChatMessage = {
          id: makeId(), agent: "System", agentColor: "",
          content: `Failed to send message: ${errMsg}`,
          timestamp: "", type: "system", thread, createdAt: Date.now(),
        };
        setSessionsByAgent(prev => ({
          ...prev,
          [activeWorker]: prev[activeWorker].map(s =>
            s.id === activeSession.id ? { ...s, messages: [...s.messages, errorChatMsg] } : s
          ),
        }));
        updateAgentState(activeWorker, { isTyping: false, isStreaming: false, queenIsTyping: false });
      });
    } else {
      const errorMsg: ChatMessage = {
        id: makeId(), agent: "System", agentColor: "",
        content: "Cannot send message: backend is not connected. Please wait for the agent to load.",
        timestamp: "", type: "system", thread, createdAt: Date.now(),
      };
      setSessionsByAgent(prev => ({
        ...prev,
        [activeWorker]: prev[activeWorker].map(s =>
          s.id === activeSession.id ? { ...s, messages: [...s.messages, errorMsg] } : s
        ),
      }));
      updateAgentState(activeWorker, { isTyping: false, isStreaming: false });
    }
  }, [activeWorker, activeSession, agentStates, updateAgentState]);

  // --- handleQueenQuestionAnswer: submit queen's own question answer via /chat ---
  // The queen asked the question herself, so she already has context — just send the raw answer.
  const handleQueenQuestionAnswer = useCallback((answer: string, _isOther: boolean) => {
    updateAgentState(activeWorker, { pendingQuestion: null, pendingOptions: null, pendingQuestions: null, pendingQuestionSource: null });
    handleSend(answer, activeWorker);
  }, [activeWorker, handleSend, updateAgentState]);

  // --- handleMultiQuestionAnswer: submit answers to ask_user_multiple ---
  const handleMultiQuestionAnswer = useCallback((answers: Record<string, string>) => {
    updateAgentState(activeWorker, {
      pendingQuestion: null, pendingOptions: null,
      pendingQuestions: null, pendingQuestionSource: null,
    });
    // Format as structured text the LLM can parse
    const lines = Object.entries(answers).map(
      ([id, answer]) => `[${id}]: ${answer}`,
    );
    handleSend(lines.join("\n"), activeWorker);
  }, [activeWorker, handleSend, updateAgentState]);

  // --- handleQuestionDismiss: user closed the question widget without answering ---
  const handleQuestionDismiss = useCallback(() => {
    const state = agentStates[activeWorker];
    if (!state?.sessionId) return;
    const question = state.pendingQuestion || "";

    // Clear UI state immediately
    updateAgentState(activeWorker, {
      pendingQuestion: null,
      pendingOptions: null,
      pendingQuestions: null,
      pendingQuestionSource: null,
      awaitingInput: false,
    });

    const dismissMsg = `[User dismissed the question: "${question}"]`;
    executionApi.chat(state.sessionId, dismissMsg).catch(() => { });
  }, [agentStates, activeWorker, updateAgentState]);

  const handleLoadAgent = useCallback(async (agentPath: string) => {
    const state = agentStates[activeWorker];
    if (!state?.sessionId) return;

    try {
      await sessionsApi.loadGraph(state.sessionId, agentPath);
      // Success: worker_graph_loaded SSE event will handle UI updates automatically
    } catch (err) {
      // 424 = credentials required — open the credentials modal
      if (err instanceof ApiError && err.status === 424) {
        const body = err.body as Record<string, unknown>;
        setCredentialAgentPath((body.agent_path as string) || null);
        setCredentialsOpen(true);
        return;
      }

      const errMsg = err instanceof Error ? err.message : String(err);
      const activeId = activeSessionRef.current[activeWorker];
      const errorMsg: ChatMessage = {
        id: makeId(), agent: "System", agentColor: "",
        content: `Failed to load agent: ${errMsg}`,
        timestamp: "", type: "system", thread: activeWorker, createdAt: Date.now(),
      };
      setSessionsByAgent(prev => ({
        ...prev,
        [activeWorker]: (prev[activeWorker] || []).map(s =>
          s.id === activeId ? { ...s, messages: [...s.messages, errorMsg] } : s
        ),
      }));
    }
  }, [activeWorker, agentStates]);
  void handleLoadAgent; // Used by load-agent modal (wired dynamically)

  const closeAgentTab = useCallback((agentType: string) => {
    setSelectedNode(null);
    // Pause worker execution if running (saves checkpoint), then kill the
    // entire backend session so the queen doesn't keep running.
    const state = agentStates[agentType];
    if (state?.sessionId) {
      const pausePromise = (state.currentExecutionId && state.workerRunState === "running")
        ? executionApi.pause(state.sessionId, state.currentExecutionId)
        : Promise.resolve();

      pausePromise
        .catch(() => { })                          // pause failure shouldn't block kill
        .then(() => sessionsApi.stop(state.sessionId!))
        .catch(() => { });                         // fire-and-forget
    }

    const allTypes = Object.keys(sessionsByAgent).filter(k => (sessionsByAgent[k] || []).length > 0);
    const remaining = allTypes.filter(k => k !== agentType);

    setSessionsByAgent(prev => {
      const next = { ...prev };
      delete next[agentType];
      return next;
    });
    setActiveSessionByAgent(prev => {
      const next = { ...prev };
      delete next[agentType];
      return next;
    });
    // Remove per-agent backend state (SSE connection closes automatically)
    setAgentStates(prev => {
      const next = { ...prev };
      delete next[agentType];
      return next;
    });

    if (remaining.length === 0) {
      navigate("/");
    } else if (activeWorker === agentType) {
      setActiveWorker(remaining[0]);
    }
  }, [sessionsByAgent, activeWorker, navigate, agentStates]);

  // Open a history session: switch to its existing tab, or open a new tab.
  // Async so we can pre-fetch messages before creating the tab — this gives
  // instant visual feedback without waiting for loadAgentForType.
  const handleHistoryOpen = useCallback(async (sessionId: string, agentPath?: string | null, agentName?: string | null) => {
    // Already open as a tab — just switch to it.
    for (const [type, sessions] of Object.entries(sessionsByAgent)) {
      for (const s of sessions) {
        if (s.backendSessionId === sessionId || s.historySourceId === sessionId) {
          setActiveWorker(type);
          setActiveSessionByAgent(prev => ({ ...prev, [type]: s.id }));
          if (s.messages.length > 0) {
            suppressIntroRef.current.add(type);
          }
          return;
        }
      }
    }

    // Pre-fetch messages from disk so the tab opens with conversation already shown.
    // Prefer the persisted event log for full UI reconstruction; fall back to parts.
    let prefetchedMessages: ChatMessage[] = [];
    try {
      const resolvedType = agentPath || "new-agent";
      const displayNameTemp = agentName || formatAgentDisplayName(resolvedType);
      const restored = await restoreSessionMessages(sessionId, resolvedType, displayNameTemp);
      prefetchedMessages = restored.messages;
      if (prefetchedMessages.length > 0) {
        prefetchedMessages.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
      }
    } catch {
      // Not available — session will open empty and loadAgentForType will try again
    }

    const resolvedAgentType = agentPath || "new-agent";
    const existingTabCount = Object.keys(sessionsByAgent).filter(
      k => baseAgentType(k) === resolvedAgentType && (sessionsByAgent[k] || []).length > 0
    ).length;
    const rawLabel = agentName ||
      (agentPath ? agentPath.replace(/\/$/, "").split("/").pop()?.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) || agentPath : null) ||
      "New Agent";
    const label = existingTabCount === 0 ? rawLabel : `${rawLabel} #${existingTabCount + 1}`;
    const newSession = createSession(resolvedAgentType, label);
    newSession.backendSessionId = sessionId;
    newSession.historySourceId = sessionId;
    // Pre-populate messages so the chat panel immediately shows the conversation
    if (prefetchedMessages.length > 0) {
      newSession.messages = prefetchedMessages;
    }
    const tabKey = existingTabCount === 0 ? resolvedAgentType : `${resolvedAgentType}::${newSession.id}`;
    if (tabKey !== resolvedAgentType) newSession.tabKey = tabKey;

    // Suppress queen intro BEFORE the tab is created so loadAgentForType
    // never sees an unsuppressed window — the user never expects a greeting on reopen.
    if (prefetchedMessages.length > 0 || sessionId) {
      suppressIntroRef.current.add(tabKey);
    }

    setSessionsByAgent(prev => ({ ...prev, [tabKey]: [newSession] }));
    setActiveSessionByAgent(prev => ({ ...prev, [tabKey]: newSession.id }));
    setActiveWorker(tabKey);
  }, [sessionsByAgent]);

  // Post-mount: open the session from the URL ?session= param via handleHistoryOpen.
  // This runs AFTER persisted tabs are hydrated, so dedup works correctly.
  // Use a ref guard so it fires exactly once even in React StrictMode.
  useEffect(() => {
    if (mountedRef.current) return;
    mountedRef.current = true;
    const sid = initialSessionIdRef.current;
    if (!sid) return;
    // Fetch agent metadata from the backend so handleHistoryOpen gets the right
    // agentPath and agentName (needed to label the tab correctly).
    sessionsApi.history().then(r => {
      const match = r.sessions.find((s: { session_id: string }) => s.session_id === sid);
      handleHistoryOpen(
        sid,
        match?.agent_path ?? initialAgentRef.current !== "new-agent" ? initialAgentRef.current : null,
        match?.agent_name ?? null,
      );
    }).catch(() => {
      // History fetch failed — still open the session with what we know.
      handleHistoryOpen(
        sid,
        initialAgentRef.current !== "new-agent" ? initialAgentRef.current : null,
        null,
      );
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeWorkerLabel = activeAgentState?.displayName || formatAgentDisplayName(baseAgentType(activeWorker));

  return (
    <div className="flex flex-col h-screen bg-background overflow-hidden">
      <TopBar
        tabs={agentTabs}
        onTabClick={(agentType) => {
          const tab = agentTabs.find(t => t.agentType === agentType);
          if (tab) {
            setActiveWorker(agentType);
            setActiveSessionByAgent(prev => ({ ...prev, [agentType]: tab.sessionId }));
            setSelectedNode(null);
          }
        }}
        onCloseTab={closeAgentTab}
        afterTabs={
          <button
            onClick={() => navigate("/")}
            className="flex-shrink-0 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            title="Add tab"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        }
      >
        <button
          onClick={() => setCredentialsOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
        >
          <KeyRound className="w-3.5 h-3.5" />
          Credentials
        </button>
        {activeAgentState?.sessionId && (
          <button
            onClick={() => sessionsApi.revealFolder(activeAgentState.sessionId!).catch(() => {})}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
            title="Open session data folder"
          >
            <FolderOpen className="w-3.5 h-3.5" />
            Data
          </button>
        )}
      </TopBar>

      {/* Main content area */}
      <div className="flex flex-1 min-h-0">

        {/* ── Draft flowchart + chat ─────────────────────────────────── */}
        <div
          className="bg-card/30 flex flex-col border-r border-border/30 relative"
          style={{ width: `${graphPanelPct}%`, minWidth: 240, flexShrink: 0 }}
        >
          <div className="flex-1 min-h-0">
            <DraftGraph
              key={activeWorker}
              draft={activeAgentState?.originalDraft ?? activeAgentState?.draftGraph ?? null}
              originalDraft={activeAgentState?.originalDraft ?? null}
              loadingMessage={
                activeAgentState?.designingDraft
                  ? "Designing flowchart…"
                  : !activeAgentState?.originalDraft && !activeAgentState?.draftGraph && activeAgentState?.queenPhase !== "planning"
                    ? "Loading flowchart…"
                    : null
              }
              building={activeAgentState?.queenBuilding}
              onRun={handleRun}
              onPause={handlePause}
              runState={activeAgentState?.workerRunState ?? "idle"}
              flowchartMap={activeAgentState?.flowchartMap ?? undefined}
              runtimeNodes={currentGraph.nodes}
              onRuntimeNodeClick={(runtimeNodeId) => {
                const node = currentGraph.nodes.find(n => n.id === runtimeNodeId);
                if (node) setSelectedNode(prev => prev?.id === node.id ? null : node);
              }}
            />
          </div>
          {/* Resize handle */}
          <div
            className="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/40 transition-colors z-10"
            onMouseDown={() => { resizing.current = true; document.body.style.cursor = "col-resize"; }}
          />
        </div>
        <div className="flex-1 min-w-0 flex">
          <div className="flex-1 min-w-0 relative">
            {/* Loading overlay */}
            {activeAgentState?.loading && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 backdrop-blur-sm">
                <div className="flex items-center gap-3 text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span className="text-sm">Connecting to agent...</span>
                </div>
              </div>
            )}

            {/* Queen connecting overlay — agent loaded but queen not yet alive */}
            {!activeAgentState?.loading && activeAgentState?.ready && !activeAgentState?.queenReady && (
              <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-background border-b border-primary/20 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-primary/60" />
                <span className="text-xs text-primary/80">Connecting to queen...</span>
              </div>
            )}

            {/* Connection error banner */}
            {activeAgentState?.error && !activeAgentState?.loading && dismissedBanner !== activeAgentState.error && (
              activeAgentState.error === "credentials_required" ? (
                <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-background border-b border-amber-500/30 flex items-center gap-2">
                  <KeyRound className="w-4 h-4 text-amber-600" />
                  <span className="text-xs text-amber-700">Missing credentials — configure them to continue</span>
                  <button
                    onClick={() => setCredentialsOpen(true)}
                    className="ml-auto text-xs font-medium text-primary hover:underline"
                  >
                    Open Credentials
                  </button>
                  <button
                    onClick={() => setDismissedBanner(activeAgentState.error!)}
                    className="p-0.5 rounded text-amber-600 hover:text-amber-800 hover:bg-amber-500/20 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ) : (
                <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-background border-b border-destructive/30 flex items-center gap-2">
                  <WifiOff className="w-4 h-4 text-destructive" />
                  <span className="text-xs text-destructive">Backend unavailable: {activeAgentState.error}</span>
                  <button
                    onClick={() => setDismissedBanner(activeAgentState.error!)}
                    className="ml-auto p-0.5 rounded text-destructive hover:text-destructive hover:bg-destructive/20 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )
            )}

            {activeSession && (
              <ChatPanel
                messages={activeSession.messages}
                onSend={handleSend}
                onCancel={handleCancelQueen}
                activeThread={activeWorker}
                isWaiting={(activeAgentState?.queenIsTyping && !activeAgentState?.isStreaming) ?? false}
                isWorkerWaiting={(activeAgentState?.workerIsTyping && !activeAgentState?.isStreaming) ?? false}
                isBusy={activeAgentState?.queenIsTyping ?? false}
                disabled={
                  (activeAgentState?.loading ?? true) ||
                  !(activeAgentState?.queenReady)
                }
                queenPhase={activeAgentState?.queenPhase ?? "building"}
                pendingQuestion={activeAgentState?.awaitingInput ? activeAgentState.pendingQuestion : null}
                pendingOptions={activeAgentState?.awaitingInput ? activeAgentState.pendingOptions : null}
                pendingQuestions={activeAgentState?.awaitingInput ? activeAgentState.pendingQuestions : null}
                onQuestionSubmit={handleQueenQuestionAnswer}
                onMultiQuestionSubmit={handleMultiQuestionAnswer}
                onQuestionDismiss={handleQuestionDismiss}
                contextUsage={activeAgentState?.contextUsage}
                supportsImages={activeAgentState?.queenSupportsImages ?? true}
              />
            )}
          </div>
          {resolvedSelectedNode && (
            <div className="w-[480px] min-w-[400px] flex-shrink-0">
              {resolvedSelectedNode.nodeType === "trigger" ? (
                <div className="flex flex-col h-full border-l border-border/40 bg-card/20 animate-in slide-in-from-right">
                  <div className="px-4 pt-4 pb-3 border-b border-border/30 flex items-start justify-between gap-2">
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 bg-[hsl(210,40%,55%)]/15 border border-[hsl(210,40%,55%)]/25">
                        <span className="text-sm" style={{ color: "hsl(210,40%,55%)" }}>
                          {{ "webhook": "\u26A1", "timer": "\u23F1", "api": "\u2192", "event": "\u223F" }[resolvedSelectedNode.triggerType || ""] || "\u26A1"}
                        </span>
                      </div>
                      <div className="min-w-0">
                        <h3 className="text-sm font-semibold text-foreground leading-tight">{resolvedSelectedNode.label}</h3>
                        <p className="text-[11px] text-muted-foreground mt-0.5 capitalize flex items-center gap-1.5">
                          {resolvedSelectedNode.triggerType} trigger
                          <span className={`inline-block w-1.5 h-1.5 rounded-full ${
                            resolvedSelectedNode.status === "running" || resolvedSelectedNode.status === "complete"
                              ? "bg-emerald-400" : "bg-muted-foreground/40"
                          }`} />
                          <span className={`text-[10px] ${
                            resolvedSelectedNode.status === "running" || resolvedSelectedNode.status === "complete"
                              ? "text-emerald-400" : "text-muted-foreground/60"
                          }`}>
                            {resolvedSelectedNode.status === "running" || resolvedSelectedNode.status === "complete" ? "active" : "inactive"}
                          </span>
                        </p>
                      </div>
                    </div>
                    <button onClick={() => setSelectedNode(null)} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="px-4 py-4 flex flex-col gap-3">
                    {(() => {
                      const tc = resolvedSelectedNode.triggerConfig as Record<string, unknown> | undefined;
                      const cron = tc?.cron as string | undefined;
                      const interval = tc?.interval_minutes as number | undefined;
                      const eventTypes = tc?.event_types as string[] | undefined;
                      const scheduleLabel = cron
                        ? cronToLabel(cron)
                        : interval
                          ? `Every ${interval >= 60 ? `${interval / 60}h` : `${interval}m`}`
                          : eventTypes?.length
                            ? eventTypes.join(", ")
                            : null;
                      const canEditCron = resolvedSelectedNode.triggerType === "timer";
                      const cronChanged = canEditCron && triggerCronDraft.trim() !== (cron || "");
                      return scheduleLabel || canEditCron ? (
                        <div>
                          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">Schedule</p>
                          {scheduleLabel && (
                            <p className="text-xs text-foreground/80 font-mono bg-muted/30 rounded-lg px-3 py-2 border border-border/20">
                              {scheduleLabel}
                            </p>
                          )}
                          {canEditCron && (
                            <>
                              <input
                                value={triggerCronDraft}
                                onChange={(e) => setTriggerCronDraft(e.target.value)}
                                placeholder="0 5 * * *"
                                className="mt-1.5 w-full text-xs text-foreground/80 bg-muted/30 rounded-lg px-3 py-2 border border-border/20 font-mono focus:outline-none focus:border-primary/40"
                              />
                              <p className="text-[10px] text-muted-foreground/60 mt-1">
                                Edit the cron expression for this timer trigger.
                              </p>
                              {(cronChanged || triggerCronSaved) && (
                                <button
                                  disabled={triggerScheduleSaving || !cronChanged}
                                  onClick={async () => {
                                    const sessionId = activeAgentState?.sessionId;
                                    const triggerId = resolvedSelectedNode.id.replace("__trigger_", "");
                                    const nextCron = triggerCronDraft.trim();
                                    if (!sessionId || !nextCron) return;
                                    const nextTriggerConfig: Record<string, unknown> = { cron: nextCron };
                                    setTriggerScheduleSaving(true);
                                    try {
                                      await sessionsApi.updateTrigger(sessionId, triggerId, {
                                        trigger_config: nextTriggerConfig,
                                      });
                                      patchTriggerNode(activeWorker, resolvedSelectedNode.id, {
                                        trigger_config: nextTriggerConfig,
                                        label: cronToLabel(nextCron),
                                      });
                                      setTriggerCronSaved(true);
                                      setTimeout(() => setTriggerCronSaved(false), 2000);
                                    } finally {
                                      setTriggerScheduleSaving(false);
                                    }
                                  }}
                                  className="mt-1.5 w-full text-[11px] px-3 py-1.5 rounded-lg border border-primary/30 text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
                                >
                                  {triggerScheduleSaving ? "Saving..." : triggerCronSaved ? "Saved" : "Save Cron"}
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      ) : null;
                    })()}
                    {(() => {
                      const nfi = (resolvedSelectedNode.triggerConfig as Record<string, unknown> | undefined)?.next_fire_in as number | undefined;
                      return nfi != null ? (
                        <div>
                          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">Next run</p>
                          <p className="text-xs text-foreground/80 font-mono bg-muted/30 rounded-lg px-3 py-2 border border-border/20">
                            <TimerCountdown initialSeconds={nfi} />
                          </p>
                        </div>
                      ) : null;
                    })()}
                    <div>
                      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">Task</p>
                      <textarea
                        value={triggerTaskDraft}
                        onChange={(e) => setTriggerTaskDraft(e.target.value)}
                        placeholder="Describe what the worker should do when this trigger fires..."
                        className="w-full text-xs text-foreground/80 bg-muted/30 rounded-lg px-3 py-2 border border-border/20 resize-none min-h-[60px] font-mono focus:outline-none focus:border-primary/40"
                        rows={3}
                      />
                      {(() => {
                        const currentTask = (resolvedSelectedNode.triggerConfig as Record<string, unknown> | undefined)?.task as string || "";
                        const hasChanged = triggerTaskDraft !== currentTask;
                        if (!hasChanged && !triggerTaskSaved) return null;
                        return (
                          <button
                            disabled={triggerTaskSaving || !hasChanged}
                            onClick={async () => {
                              const sessionId = activeAgentState?.sessionId;
                              const triggerId = resolvedSelectedNode.id.replace("__trigger_", "");
                              if (!sessionId) return;
                              setTriggerTaskSaving(true);
                              try {
                                await sessionsApi.updateTrigger(sessionId, triggerId, { task: triggerTaskDraft });
                                patchTriggerNode(activeWorker, resolvedSelectedNode.id, { task: triggerTaskDraft });
                                setTriggerTaskSaved(true);
                                setTimeout(() => setTriggerTaskSaved(false), 2000);
                              } finally {
                                setTriggerTaskSaving(false);
                              }
                            }}
                            className="mt-1.5 w-full text-[11px] px-3 py-1.5 rounded-lg border border-primary/30 text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
                          >
                            {triggerTaskSaving ? "Saving..." : triggerTaskSaved ? "Saved" : "Save Task"}
                          </button>
                        );
                      })()}
                      {!triggerTaskDraft && (
                        <p className="text-[10px] text-amber-400/80 mt-1">A task is required before enabling this trigger.</p>
                      )}
                    </div>
                    <div>
                      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">Fires into</p>
                      <p className="text-xs text-foreground/80 font-mono bg-muted/30 rounded-lg px-3 py-2 border border-border/20">
                        {resolvedSelectedNode.next?.[0]?.split("-").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ") || "—"}
                      </p>
                    </div>
                    {activeAgentState?.queenPhase !== "building" && (() => {
                      const triggerIsActive = resolvedSelectedNode.status === "running" || resolvedSelectedNode.status === "complete";
                      const triggerId = resolvedSelectedNode.id.replace("__trigger_", "");
                      const taskMissing = !triggerTaskDraft;
                      return (
                        <div className="pt-1">
                          <button
                            disabled={!triggerIsActive && taskMissing}
                            onClick={async () => {
                              const sessionId = activeAgentState?.sessionId;
                              if (!sessionId) return;
                              const action = triggerIsActive ? "Disable" : "Enable";
                              await executionApi.chat(sessionId, `${action} trigger ${triggerId}`);
                            }}
                            className={`w-full text-xs px-3 py-2 rounded-lg border transition-colors ${
                              triggerIsActive
                                ? "border-red-500/30 text-red-400 hover:bg-red-500/10"
                                : taskMissing
                                  ? "border-border/30 text-muted-foreground/40 cursor-not-allowed"
                                  : "border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
                            }`}
                          >
                            {triggerIsActive ? "Disable Trigger" : "Enable Trigger"}
                          </button>
                          {!triggerIsActive && taskMissing && (
                            <p className="text-[10px] text-muted-foreground/50 mt-1 text-center">Configure a task first</p>
                          )}
                        </div>
                      );
                    })()}
                  </div>
                </div>
              ) : (
                <NodeDetailPanel
                  node={resolvedSelectedNode}
                  nodeSpec={activeAgentState?.nodeSpecs.find(n => n.id === resolvedSelectedNode.id) ?? null}
                  allNodeSpecs={activeAgentState?.nodeSpecs}
                  subagentReports={activeAgentState?.subagentReports}
                  sessionId={activeAgentState?.sessionId || undefined}
                  graphId={activeAgentState?.graphId || undefined}
                  workerSessionId={null}
                  nodeLogs={activeAgentState?.nodeLogs[resolvedSelectedNode.id] || []}
                  actionPlan={activeAgentState?.nodeActionPlans[resolvedSelectedNode.id]}
                  contextUsage={activeAgentState?.contextUsage[resolvedSelectedNode.id]}
                  onClose={() => setSelectedNode(null)}
                />
              )}
            </div>
          )}
        </div>
      </div>

      <CredentialsModal
        agentType={activeWorker}
        agentLabel={activeWorkerLabel}
        agentPath={credentialAgentPath || activeAgentState?.agentPath || (!activeWorker.startsWith("new-agent") ? activeWorker : undefined)}
        open={credentialsOpen}
        onClose={() => {
          setCredentialsOpen(false);
          setCredentialAgentPath(null);
          // Keep credentials_required error set — clearing it here triggers
          // the auto-load effect which retries session creation immediately,
          // causing an infinite modal loop when credentials are still missing.
          // The error is only cleared in onCredentialChange (below) when the
          // user actually saves valid credentials.
        }}
        credentials={activeSession?.credentials || []}
        onCredentialChange={() => {
          // Clear credential error so the auto-load effect retries session creation
          if (agentStates[activeWorker]?.error === "credentials_required") {
            updateAgentState(activeWorker, { error: null });
          }
          if (!activeSession) return;
          setSessionsByAgent(prev => ({
            ...prev,
            [activeWorker]: prev[activeWorker].map(s =>
              s.id === activeSession.id
                ? { ...s, credentials: s.credentials.map(c => ({ ...c, connected: true })) }
                : s
            ),
          }));
        }}
      />
    </div>
  );
}
