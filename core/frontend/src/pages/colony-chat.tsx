import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useParams, useLocation } from "react-router-dom";
import { Loader2, WifiOff, KeyRound, FolderOpen, X } from "lucide-react";
import type { GraphNode, NodeStatus } from "@/components/graph-types";
import TriggersPanel from "@/components/TriggersPanel";
import TriggerDetailPanel from "@/components/TriggerDetailPanel";
import ChatPanel, { type ChatMessage, type ImageContent } from "@/components/ChatPanel";
import CredentialsModal, {
  type Credential,
  clearCredentialCache,
} from "@/components/CredentialsModal";
import { executionApi } from "@/api/execution";
import { sessionsApi } from "@/api/sessions";
import { useMultiSSE } from "@/hooks/use-sse";
import type { LiveSession, AgentEvent } from "@/api/types";
import { sseEventToChatMessage, formatAgentDisplayName } from "@/lib/chat-helpers";
import { cronToLabel } from "@/lib/graphUtils";
import { ApiError } from "@/api/client";
import { useColony } from "@/context/ColonyContext";
import { useHeaderActions } from "@/context/HeaderActionsContext";
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
  restoredPhase: "planning" | "building" | "staging" | "running" | "independent" | null;
};

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
      for (const evt of events) {
        const p =
          evt.type === "queen_phase_changed"
            ? (evt.data?.phase as string)
            : evt.type === "node_loop_iteration"
            ? (evt.data?.phase as string | undefined)
            : undefined;
        if (p && ["planning", "building", "staging", "running"].includes(p)) {
          runningPhase = p as ChatMessage["phase"];
        }
        const msg = sseEventToChatMessage(evt, thread, agentDisplayName);
        if (!msg) continue;
        if (evt.stream_id === "queen") {
          msg.role = "queen";
          msg.phase = runningPhase;
        }
        messages.push(msg);
      }
      return { messages, restoredPhase: runningPhase ?? null };
    }
  } catch {
    // Event log not available
  }
  return { messages: [], restoredPhase: null };
}

// ── Agent backend state ──────────────────────────────────────────────────────

interface AgentState {
  sessionId: string | null;
  loading: boolean;
  ready: boolean;
  queenReady: boolean;
  error: string | null;
  displayName: string | null;
  awaitingInput: boolean;
  queenPhase: "planning" | "building" | "staging" | "running" | "independent";
  agentPath: string | null;
  currentRunId: string | null;
  nodeLogs: Record<string, string[]>;
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
    loading: true,
    ready: false,
    queenReady: false,
    error: null,
    displayName: null,
    awaitingInput: false,
    queenPhase: "planning",
    agentPath: null,
    currentRunId: null,
    nodeLogs: {},
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
  const { colonies, markVisited, refresh: refreshColonies } = useColony();
  const { setActions } = useHeaderActions();

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
  const queenInfo = getQueenForAgent(slug);
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
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

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
        <BrowserStatusBadge />
      </>,
    );
    return () => setActions(null);
  }, [agentState.sessionId, setActions]);

  // Refs for SSE callback stability
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const agentStateRef = useRef(agentState);
  agentStateRef.current = agentState;

  const turnCounterRef = useRef<Record<string, number>>({});
  const queenPhaseRef = useRef<string>("planning");
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
          const lastIdx = prev.length - 1;
          const lastMsg = prev[lastIdx];
          const incomingTs = chatMsg.createdAt ?? Date.now();
          const lastTs = lastMsg.createdAt ?? incomingTs;
          if (
            lastMsg.type === "user" &&
            lastMsg.content === chatMsg.content &&
            Math.abs(incomingTs - lastTs) <= 15000
          ) {
            return prev.map((m, i) => (i === lastIdx ? { ...m, id: chatMsg.id } : m));
          }
        }
        return [...prev, chatMsg];
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
          queenPhase: "planning",
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

      let restoredPhase: "planning" | "building" | "staging" | "running" | "independent" | null = null;

      if (!liveSession) {
        // Pre-fetch messages from cold session
        let preRestoredMsgs: ChatMessage[] = [];
        if (coldRestoreId) {
          const displayName = formatAgentDisplayName(agentPath);
          const restored = await restoreSessionMessages(coldRestoreId, agentPath, displayName);
          preRestoredMsgs = restored.messages;
          restoredPhase = restored.restoredPhase;
        }

        if (coldRestoreId || preRestoredMsgs.length > 0) {
          suppressIntroRef.current = true;
        }

        // Create new session (pass coldRestoreId for resume)
        liveSession = await sessionsApi.create(agentPath, undefined, undefined, undefined, coldRestoreId ?? undefined);

        if (preRestoredMsgs.length > 0) {
          preRestoredMsgs.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
          setMessages(preRestoredMsgs);
        }
      }

      const session = liveSession!;
      const displayName = formatAgentDisplayName(session.colony_name || agentPath);
      const initialPhase =
        restoredPhase || session.queen_phase || (session.has_worker ? "staging" : "planning");
      queenPhaseRef.current = initialPhase;

      updateState({
        sessionId: session.session_id,
        displayName,
        queenPhase: initialPhase,
        queenSupportsImages: session.queen_supports_images !== false,
      });

      // Restore messages for live resume
      if (isResumedSession) {
        const restored = await restoreSessionMessages(
          session.session_id,
          agentPath,
          displayName,
        );
        if (restored.messages.length > 0) {
          restored.messages.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
          setMessages(restored.messages);
        }
      }

      const hasRestoredContent = isResumedSession || !!coldRestoreId;
      if (!hasRestoredContent) suppressIntroRef.current = false;

      updateState({
        sessionId: session.session_id,
        displayName,
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
      queenPhaseRef.current = "planning";
      queenIterTextRef.current = {};
      suppressIntroRef.current = false;
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
      const shouldMarkQueenReady = isQueen && !state.queenReady;

      switch (event.type) {
        case "execution_started":
          if (isQueen) {
            turnCounterRef.current[turnKey] = currentTurn + 1;
            updateState({
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
              isStreaming: false,
              workerIsTyping: true,
              awaitingInput: false,
              currentRunId: incomingRunId,
              nodeLogs: {},
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
            updateState({ queenIsTyping: false });
          } else {
            updateState({
              isStreaming: false,
              workerIsTyping: false,
              awaitingInput: false,
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
          updateState({ activeToolCalls: {} });
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

            const sid = event.stream_id;
            setAgentState((prev) => {
              const updated = { ...prev.activeToolCalls };
              if (updated[toolUseId]) {
                updated[toolUseId] = { ...updated[toolUseId], done: true };
              }
              const tools = Object.values(updated)
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
              });
              return { ...prev, activeToolCalls: updated };
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
            rawPhase === "independent"
              ? "independent"
              : rawPhase === "running"
              ? "running"
              : rawPhase === "staging"
              ? "staging"
              : rawPhase === "planning"
              ? "planning"
              : "building";
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
                const { next_fire_in: _, ...restConfig } = (n.triggerConfig || {}) as Record<
                  string,
                  unknown
                > & { next_fire_in?: unknown };
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
            updateGraphNodeStatus(nodeId, "complete");
            setTimeout(() => updateGraphNodeStatus(nodeId, "running"), 1500);
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
      updateState({ isStreaming: false, queenIsTyping: false });
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
      updateState({ queenIsTyping: true });

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
          updateState({ isStreaming: false, queenIsTyping: false });
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

  // ── Resolved selected node (sync with live graph updates) ──────────────

  const liveSelectedNode = selectedNode && graphNodes.find((n) => n.id === selectedNode.id);
  const resolvedSelectedNode = liveSelectedNode || selectedNode;

  const triggers = useMemo(
    () => graphNodes.filter((n) => n.nodeType === "trigger"),
    [graphNodes],
  );

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
          />
        </div>

        {/* Triggers sidebar — only rendered when the colony actually has triggers */}
        {triggers.length > 0 && (
          <div className="w-[260px] flex-shrink-0">
            <TriggersPanel
              triggers={triggers}
              selectedId={resolvedSelectedNode?.id ?? null}
              onSelect={(trigger) =>
                setSelectedNode((prev) => (prev?.id === trigger.id ? null : trigger))
              }
            />
          </div>
        )}

        {/* Trigger detail panel */}
        {resolvedSelectedNode && resolvedSelectedNode.nodeType === "trigger" && (
          <div className="w-[380px] min-w-[320px] flex-shrink-0">
            <TriggerDetailPanel
              trigger={resolvedSelectedNode}
              sessionId={agentState.sessionId || ""}
              onClose={() => setSelectedNode(null)}
            />
          </div>
        )}
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
