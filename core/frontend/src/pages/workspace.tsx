import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import ReactDOM from "react-dom";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Plus, KeyRound, Sparkles, Layers, ChevronLeft, Bot, Loader2, WifiOff } from "lucide-react";
import AgentGraph, { type GraphNode, type NodeStatus } from "@/components/AgentGraph";
import ChatPanel, { type ChatMessage } from "@/components/ChatPanel";
import TopBar from "@/components/TopBar";
import { TAB_STORAGE_KEY, loadPersistedTabs, savePersistedTabs, type PersistedTabState } from "@/lib/tab-persistence";
import NodeDetailPanel from "@/components/NodeDetailPanel";
import CredentialsModal, { type Credential, createFreshCredentials, cloneCredentials, allRequiredCredentialsMet } from "@/components/CredentialsModal";
import { agentsApi } from "@/api/agents";
import { executionApi } from "@/api/execution";
import { graphsApi } from "@/api/graphs";
import { sessionsApi } from "@/api/sessions";
import { useMultiSSE } from "@/hooks/use-sse";
import type { LiveSession, AgentEvent, DiscoverEntry, Message, NodeSpec } from "@/api/types";
import { backendMessageToChatMessage, sseEventToChatMessage, formatAgentDisplayName } from "@/lib/chat-helpers";
import { topologyToGraphNodes } from "@/lib/graph-converter";

const makeId = () => Math.random().toString(36).slice(2, 9);

// --- Session types ---
interface Session {
  id: string;
  agentType: string;
  label: string;
  messages: ChatMessage[];
  graphNodes: GraphNode[];
  credentials: Credential[];
  backendSessionId?: string;
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

// --- NewTabPopover ---
type PopoverStep = "root" | "new-agent-choice" | "clone-pick";

interface NewTabPopoverProps {
  open: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  activeWorker: string;
  discoverAgents: DiscoverEntry[];
  onFromScratch: () => void;
  onCloneAgent: (agentPath: string, agentName: string) => void;
}

function NewTabPopover({ open, onClose, anchorRef, discoverAgents, onFromScratch, onCloneAgent }: NewTabPopoverProps) {
  const [step, setStep] = useState<PopoverStep>("root");
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => { if (open) setStep("root"); }, [open]);

  // Compute position from anchor button
  useEffect(() => {
    if (open && anchorRef.current) {
      const rect = anchorRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left });
    }
  }, [open, anchorRef]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        ref.current && !ref.current.contains(e.target as Node) &&
        anchorRef.current && !anchorRef.current.contains(e.target as Node)
      ) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, onClose, anchorRef]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open || !pos) return null;

  const optionClass =
    "flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-left transition-colors hover:bg-muted/60 text-foreground";
  const iconWrap =
    "w-7 h-7 rounded-md flex items-center justify-center bg-muted/80 flex-shrink-0";

  return ReactDOM.createPortal(
    <div
      ref={ref}
      style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 9999 }}
      className="w-60 rounded-xl border border-border/60 bg-card shadow-xl shadow-black/30 overflow-hidden"
    >
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/40">
        {step !== "root" && (
          <button
            onClick={() => setStep(step === "clone-pick" ? "new-agent-choice" : "root")}
            className="p-0.5 rounded hover:bg-muted/60 transition-colors text-muted-foreground hover:text-foreground"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
        )}
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          {step === "root" ? "Add Tab" : step === "new-agent-choice" ? "New Agent" : "Open Agent"}
        </span>
      </div>

      <div className="p-1.5">
        {step === "root" && (
          <>
            <button className={optionClass} onClick={() => setStep("clone-pick")}>
              <span className={iconWrap}><Layers className="w-3.5 h-3.5 text-muted-foreground" /></span>
              <div>
                <div className="font-medium leading-tight">Existing agent</div>
                <div className="text-xs text-muted-foreground mt-0.5">Open another agent's workspace</div>
              </div>
            </button>
            <button className={optionClass} onClick={() => setStep("new-agent-choice")}>
              <span className={iconWrap}><Sparkles className="w-3.5 h-3.5 text-primary" /></span>
              <div>
                <div className="font-medium leading-tight">New agent</div>
                <div className="text-xs text-muted-foreground mt-0.5">Build or clone a fresh agent</div>
              </div>
            </button>
          </>
        )}

        {step === "new-agent-choice" && (
          <>
            <button className={optionClass} onClick={() => { onFromScratch(); onClose(); }}>
              <span className={iconWrap}><Sparkles className="w-3.5 h-3.5 text-primary" /></span>
              <div>
                <div className="font-medium leading-tight">From scratch</div>
                <div className="text-xs text-muted-foreground mt-0.5">Empty pipeline + Queen Bee setup</div>
              </div>
            </button>
            <button className={optionClass} onClick={() => setStep("clone-pick")}>
              <span className={iconWrap}><Layers className="w-3.5 h-3.5 text-muted-foreground" /></span>
              <div>
                <div className="font-medium leading-tight">Clone existing</div>
                <div className="text-xs text-muted-foreground mt-0.5">Start from an existing agent</div>
              </div>
            </button>
          </>
        )}

        {step === "clone-pick" && (
          <div className="flex flex-col max-h-64 overflow-y-auto">
            {discoverAgents.map(agent => (
              <button
                key={agent.path}
                onClick={() => { onCloneAgent(agent.path, agent.name); onClose(); }}
                className="flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-left transition-colors hover:bg-muted/60 text-foreground"
              >
                <div className="w-6 h-6 rounded-md bg-muted/80 flex items-center justify-center flex-shrink-0">
                  <Bot className="w-3.5 h-3.5 text-muted-foreground" />
                </div>
                <span className="text-sm font-medium">{agent.name}</span>
              </button>
            ))}
            {discoverAgents.length === 0 && (
              <p className="text-xs text-muted-foreground px-3 py-2">No agents found</p>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}

// --- LoadAgentPopover ---
interface LoadAgentPopoverProps {
  open: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  discoverAgents: DiscoverEntry[];
  onSelect: (agentPath: string) => void;
}

function LoadAgentPopover({ open, onClose, anchorRef, discoverAgents, onSelect }: LoadAgentPopoverProps) {
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && anchorRef.current) {
      const rect = anchorRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
    }
  }, [open, anchorRef]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        ref.current && !ref.current.contains(e.target as Node) &&
        anchorRef.current && !anchorRef.current.contains(e.target as Node)
      ) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, onClose, anchorRef]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open || !pos) return null;

  return ReactDOM.createPortal(
    <div
      ref={ref}
      style={{ position: "fixed", top: pos.top, right: pos.right, zIndex: 9999 }}
      className="w-60 rounded-xl border border-border/60 bg-card shadow-xl shadow-black/30 overflow-hidden"
    >
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/40">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Load Agent
        </span>
      </div>
      <div className="p-1.5 flex flex-col max-h-64 overflow-y-auto">
        {discoverAgents.map(agent => (
          <button
            key={agent.path}
            onClick={() => { onSelect(agent.path); onClose(); }}
            className="flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-left transition-colors hover:bg-muted/60 text-foreground"
          >
            <div className="w-6 h-6 rounded-md bg-muted/80 flex items-center justify-center flex-shrink-0">
              <Bot className="w-3.5 h-3.5 text-muted-foreground" />
            </div>
            <span className="text-sm font-medium">{agent.name}</span>
          </button>
        ))}
        {discoverAgents.length === 0 && (
          <p className="text-xs text-muted-foreground px-3 py-2">No agents found</p>
        )}
      </div>
    </div>,
    document.body
  );
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
  workerRunState: "idle" | "deploying" | "running";
  currentExecutionId: string | null;
  nodeLogs: Record<string, string[]>;
  nodeActionPlans: Record<string, string>;
  isTyping: boolean;
  llmSnapshots: Record<string, string>;
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
    workerRunState: "idle",
    currentExecutionId: null,
    nodeLogs: {},
    nodeActionPlans: {},
    isTyping: false,
    llmSnapshots: {},
  };
}

export default function Workspace() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rawAgent = searchParams.get("agent") || "new-agent";
  const initialAgent = rawAgent;
  const hasExplicitAgent = searchParams.has("agent");
  const initialPrompt = searchParams.get("prompt") || "";

  // Sessions grouped by agent type — restore from localStorage if available
  const [sessionsByAgent, setSessionsByAgent] = useState<Record<string, Session[]>>(() => {
    const persisted = loadPersistedTabs();
    const initial: Record<string, Session[]> = {};

    if (persisted) {
      for (const tab of persisted.tabs) {
        if (!initial[tab.agentType]) initial[tab.agentType] = [];
        const session = createSession(tab.agentType, tab.label);
        session.id = tab.id;
        session.backendSessionId = tab.backendSessionId;
        // Restore messages and graph from localStorage (up to 50 messages).
        // If the backend session is still alive, loadAgentForType may
        // append additional messages fetched from the server.
        const cached = persisted.sessions?.[tab.id];
        if (cached) {
          session.messages = cached.messages || [];
          session.graphNodes = cached.graphNodes || [];
        }
        initial[tab.agentType].push(session);
      }
    }

    // If persisted tabs were restored and user didn't explicitly request
    // a different agent via URL, return restored tabs as-is.
    if (persisted && Object.keys(initial).length > 0 && !hasExplicitAgent) {
      return initial;
    }

    if (initial[initialAgent]?.length) {
      return initial;
    }

    if (initialAgent === "new-agent") {
      initial["new-agent"] = [...(initial["new-agent"] || []), createSession("new-agent", "New Agent")];
    } else {
      initial[initialAgent] = [...(initial[initialAgent] || []),
        createSession(initialAgent, formatAgentDisplayName(initialAgent))];
    }

    return initial;
  });

  const [activeSessionByAgent, setActiveSessionByAgent] = useState<Record<string, string>>(() => {
    const persisted = loadPersistedTabs();
    if (persisted) {
      const restored = { ...persisted.activeSessionByAgent };
      const urlSessions = sessionsByAgent[initialAgent];
      if (urlSessions?.length && !restored[initialAgent]) {
        restored[initialAgent] = urlSessions[0].id;
      }
      return restored;
    }
    const sessions = sessionsByAgent[initialAgent];
    return sessions ? { [initialAgent]: sessions[0].id } : {};
  });

  const [activeWorker, setActiveWorker] = useState(() => {
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

  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [newTabOpen, setNewTabOpen] = useState(false);
  const newTabBtnRef = useRef<HTMLButtonElement>(null);
  const [loadAgentOpen, setLoadAgentOpen] = useState(false);
  const [loadingWorker, setLoadingWorker] = useState(false);
  const loadAgentBtnRef = useRef<HTMLButtonElement>(null);

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

  // Persist tab metadata + session data to localStorage on every relevant change
  useEffect(() => {
    const tabs: PersistedTabState["tabs"] = [];
    const sessions: Record<string, { messages: ChatMessage[]; graphNodes: GraphNode[] }> = {};
    for (const agentSessions of Object.values(sessionsByAgent)) {
      for (const s of agentSessions) {
        tabs.push({
          id: s.id,
          agentType: s.agentType,
          label: s.label,
          backendSessionId: s.backendSessionId || agentStates[s.agentType]?.sessionId || undefined,
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
    try {
      updateAgentState(activeWorker, { workerRunState: "deploying" });
      const result = await executionApi.trigger(state.sessionId, "default", {});
      updateAgentState(activeWorker, { currentExecutionId: result.execution_id });
    } catch (err) {
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
              timestamp: "", type: "system", thread: activeWorker,
            };
            return { ...s, messages: [...s.messages, errorMsg] };
          }),
        };
      });
      updateAgentState(activeWorker, { workerRunState: "idle" });
    }
  }, [agentStates, activeWorker, updateAgentState]);

  // --- Fetch discovered agents for NewTabPopover ---
  const [discoverAgents, setDiscoverAgents] = useState<DiscoverEntry[]>([]);
  useEffect(() => {
    agentsApi.discover().then(result => {
      const { Framework: _fw, ...userFacing } = result;
      const all = Object.values(userFacing).flat();
      setDiscoverAgents(all);
    }).catch(() => {});
  }, []);

  // --- Agent loading: loadAgentForType ---
  const loadingRef = useRef(new Set<string>());
  const loadAgentForType = useCallback(async (agentType: string) => {
    if (agentType === "new-agent") {
      // Create a queen-only session (no worker) for agent building
      updateAgentState(agentType, { loading: true, error: null, ready: false, sessionId: null });
      try {
        const prompt = initialPrompt || undefined;
        let liveSession: LiveSession | undefined;

        // Try to reconnect to stored backend session (e.g., after browser refresh)
        const storedId = sessionsRef.current[agentType]?.[0]?.backendSessionId;
        if (storedId) {
          try {
            liveSession = await sessionsApi.get(storedId);
          } catch {
            // Session gone — fall through to create new
          }
        }

        if (!liveSession) {
          liveSession = await sessionsApi.create(undefined, undefined, undefined, prompt);

          // Show the initial prompt as a user message in chat (only on fresh create)
          if (prompt) {
            const userMsg: ChatMessage = {
              id: makeId(), agent: "You", agentColor: "",
              content: prompt, timestamp: "", type: "user", thread: agentType,
            };
            setSessionsByAgent(prev => ({
              ...prev,
              [agentType]: (prev[agentType] || []).map(s => ({
                ...s, messages: [...s.messages, userMsg],
              })),
            }));
          }
        }

        // Store backendSessionId on the Session object for persistence
        setSessionsByAgent(prev => ({
          ...prev,
          [agentType]: (prev[agentType] || []).map((s, i) =>
            i === 0 ? { ...s, backendSessionId: liveSession!.session_id } : s,
          ),
        }));

        updateAgentState(agentType, {
          sessionId: liveSession.session_id,
          displayName: "Queen Bee",
          ready: true,
          loading: false,
          queenReady: true,
        });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        updateAgentState(agentType, { error: msg, loading: false });
      }
      return;
    }

    // Ref-based guard: prevents double-load from React StrictMode
    if (loadingRef.current.has(agentType)) return;
    loadingRef.current.add(agentType);

    updateAgentState(agentType, { loading: true, error: null, ready: false, sessionId: null });

    try {
      let liveSession: LiveSession | undefined;
      let isResumedSession = false;

      // Try to reconnect to an existing backend session (e.g., after browser refresh).
      // The backendSessionId is persisted in localStorage per tab.
      const storedSessionId = sessionsRef.current[agentType]?.[0]?.backendSessionId;
      if (storedSessionId) {
        try {
          liveSession = await sessionsApi.get(storedSessionId);
          isResumedSession = true;
        } catch {
          // Session gone (server restarted, etc.) — fall through to create new
        }
      }

      if (!liveSession) {
        try {
          liveSession = await sessionsApi.create(agentType);
        } catch (loadErr: unknown) {
          const { ApiError } = await import("@/api/client");

          // 424 = credentials required — open the credentials modal
          if (loadErr instanceof ApiError && loadErr.status === 424) {
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
                } catch {
                  if (i === maxAttempts - 1) throw loadErr;
                }
              }
              throw loadErr;
            })();
          } else {
            liveSession = body as unknown as LiveSession;
          }
        }
      }

      // At this point liveSession is guaranteed set — if both reconnect and create
      // failed, the throw inside the catch exits the outer try block.
      const session = liveSession!;
      const displayName = formatAgentDisplayName(session.worker_name || agentType);
      updateAgentState(agentType, { sessionId: session.session_id, displayName });

      // Update the session label
      setSessionsByAgent((prev) => {
        const sessions = prev[agentType] || [];
        if (!sessions.length) return prev;
        return {
          ...prev,
          [agentType]: sessions.map((s, i) =>
            i === 0 ? { ...s, label: sessions.length === 1 ? displayName : `${displayName} #${i + 1}`, backendSessionId: session.session_id } : s,
          ),
        };
      });

      // Check worker session status (detects running worker).
      // Only restore messages when rejoining an existing backend session.
      let isWorkerRunning = false;
      try {
        const { sessions: workerSessions } = await sessionsApi.workerSessions(session.session_id);
        const resumable = workerSessions.find(
          (s) => s.status === "active" || s.status === "paused",
        );
        isWorkerRunning = resumable?.status === "active";

        if (isResumedSession && resumable) {
          const { messages } = await sessionsApi.messages(session.session_id, resumable.session_id);
          if (messages.length > 0) {
            const chatMsgs = messages.map((m: Message) =>
              backendMessageToChatMessage(m, agentType, displayName),
            );
            setSessionsByAgent((prev) => ({
              ...prev,
              [agentType]: (prev[agentType] || []).map((s, i) =>
                i === 0 ? { ...s, messages: [...s.messages, ...chatMsgs] } : s,
              ),
            }));
          }
        }
      } catch {
        // Worker session listing failed — not critical
      }

      // Restore queen conversation when rejoining an existing session
      if (isResumedSession) {
        try {
          const { messages: queenMsgs } = await sessionsApi.queenMessages(session.session_id);
          if (queenMsgs.length > 0) {
            const chatMsgs = queenMsgs.map((m: Message) => {
              const msg = backendMessageToChatMessage(m, agentType, "Queen Bee");
              if (msg) msg.role = "queen";
              return msg;
            }).filter(Boolean);
            if (chatMsgs.length > 0) {
              setSessionsByAgent((prev) => ({
                ...prev,
                [agentType]: (prev[agentType] || []).map((s, i) =>
                  i === 0 ? { ...s, messages: [...chatMsgs, ...s.messages] } : s,
                ),
              }));
            }
          }
        } catch {
          // Queen messages not available — not critical
        }
      }

      updateAgentState(agentType, {
        ready: true,
        loading: false,
        queenReady: true,
        ...(isWorkerRunning ? { workerRunState: "running" } : {}),
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      updateAgentState(agentType, { error: msg, loading: false });
    } finally {
      loadingRef.current.delete(agentType);
    }
  }, [updateAgentState, initialPrompt]);

  // Auto-load agents when new tabs appear in sessionsByAgent
  useEffect(() => {
    for (const agentType of Object.keys(sessionsByAgent)) {
      if (agentStates[agentType]?.sessionId || agentStates[agentType]?.loading || agentStates[agentType]?.error) continue;
      loadAgentForType(agentType);
    }
  }, [sessionsByAgent, agentStates, loadAgentForType, updateAgentState]);

  // --- Fetch graph topology when a session becomes ready ---
  const fetchGraphForAgent = useCallback(async (agentType: string, sessionId: string) => {
    try {
      const { graphs } = await sessionsApi.graphs(sessionId);
      if (!graphs.length) return;

      const graphId = graphs[0];
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

  useEffect(() => {
    for (const [agentType, state] of Object.entries(agentStates)) {
      if (!state.sessionId || !state.ready || state.nodeSpecs.length > 0 || state.graphId) continue;
      fetchGraphForAgent(agentType, state.sessionId);
    }
  }, [agentStates, fetchGraphForAgent]);

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
              timestamp: "", type: "system", thread: activeWorker,
            };
            return { ...s, messages: [...s.messages, errorMsg] };
          }),
        };
      });
    }
  }, [agentStates, activeWorker, markAllNodesAs, updateAgentState]);

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
    (agentType: string, chatMsg: ChatMessage) => {
      console.log('[UPSERT] agentType:', agentType, 'msgId:', chatMsg.id, 'thread:', chatMsg.thread, 'role:', chatMsg.role, 'content:', chatMsg.content?.slice(0, 40));
      setSessionsByAgent((prev) => {
        const sessions = prev[agentType] || [];
        const activeId = activeSessionRef.current[agentType] || sessions[0]?.id;
        console.log('[UPSERT-inner] sessions:', sessions.length, 'activeId:', activeId, 'sessionIds:', sessions.map(s => s.id));
        return {
          ...prev,
          [agentType]: sessions.map((s) => {
            if (s.id !== activeId) return s;
            const idx = s.messages.findIndex((m) => m.id === chatMsg.id);
            const newMessages =
              idx >= 0
                ? s.messages.map((m, i) => (i === idx ? chatMsg : m))
                : [...s.messages, chatMsg];
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
      if (streamId === "judge") return;

      const isQueen = streamId === "queen";
      if (isQueen) console.log('[QUEEN] handleSSEEvent:', event.type, 'agentType:', agentType);
      const agentDisplayName = agentStates[agentType]?.displayName;
      const displayName = isQueen ? "Queen Bee" : (agentDisplayName || undefined);
      const role = isQueen ? "queen" as const : "worker" as const;
      const ts = fmtLogTs(event.timestamp);
      const currentTurn = turnCounterRef.current[agentType] ?? 0;

      // Mark queen as ready on the first queen SSE event
      if (isQueen && !agentStates[agentType]?.queenReady) {
        updateAgentState(agentType, { queenReady: true });
      }

      switch (event.type) {
        case "execution_started":
          if (isQueen) {
            turnCounterRef.current[agentType] = currentTurn + 1;
            updateAgentState(agentType, { isTyping: true });
          } else {
            // Warn if prior LLM snapshots are being dropped (edge case: execution_completed never arrived)
            const priorSnapshots = agentStates[agentType]?.llmSnapshots || {};
            if (Object.keys(priorSnapshots).length > 0) {
              console.debug(`[hive] execution_started: dropping ${Object.keys(priorSnapshots).length} unflushed LLM snapshot(s)`);
            }
            turnCounterRef.current[agentType] = currentTurn + 1;
            updateAgentState(agentType, {
              isTyping: true,
              awaitingInput: false,
              workerRunState: "running",
              currentExecutionId: event.execution_id || agentStates[agentType]?.currentExecutionId || null,
              nodeLogs: {},
              llmSnapshots: {},
            });
            markAllNodesAs(agentType, ["running", "looping", "complete", "error"], "pending");
          }
          break;

        case "execution_completed":
          if (isQueen) {
            updateAgentState(agentType, { isTyping: false });
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
              awaitingInput: false,
              workerRunState: "idle",
              currentExecutionId: null,
              llmSnapshots: {},
            });
            markAllNodesAs(agentType, ["running", "looping"], "complete");
          }
          break;

        case "execution_paused":
        case "execution_failed":
        case "client_output_delta":
        case "client_input_requested":
        case "llm_text_delta": {
          const chatMsg = sseEventToChatMessage(event, agentType, displayName, currentTurn);
          if (isQueen) console.log('[QUEEN] chatMsg:', chatMsg?.id, chatMsg?.content?.slice(0, 50), 'turn:', currentTurn);
          if (chatMsg) {
            if (isQueen) chatMsg.role = role;
            upsertChatMessage(agentType, chatMsg);
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
            updateAgentState(agentType, { awaitingInput: true, isTyping: false });
          }
          if (event.type === "execution_paused") {
            updateAgentState(agentType, { isTyping: false, awaitingInput: false });
            if (!isQueen) {
              updateAgentState(agentType, { workerRunState: "idle", currentExecutionId: null });
              markAllNodesAs(agentType, ["running", "looping"], "pending");
            }
          }
          if (event.type === "execution_failed") {
            updateAgentState(agentType, { isTyping: false, awaitingInput: false });
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
          turnCounterRef.current[agentType] = currentTurn + 1;
          updateAgentState(agentType, { isTyping: true });
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
          turnCounterRef.current[agentType] = currentTurn + 1;
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

        case "tool_call_started":
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
            const toolName = (event.data?.tool_name as string) || "unknown";
            const toolInput = event.data?.tool_input;
            const argsStr = toolInput ? truncate(JSON.stringify(toolInput), 200) : "";
            appendNodeLog(agentType, event.node_id, `${ts} INFO  Calling ${toolName}(${argsStr})`);
          }
          break;

        case "tool_call_completed":
          if (!isQueen && event.node_id) {
            const toolName = (event.data?.tool_name as string) || "unknown";
            const isError = event.data?.is_error as boolean | undefined;
            const result = event.data?.result as string | undefined;
            if (isError) {
              appendNodeLog(agentType, event.node_id, `${ts} ERROR ${toolName} failed: ${truncate(result || "unknown error", 200)}`);
            } else {
              const resultStr = result ? ` (${truncate(result, 200)})` : "";
              appendNodeLog(agentType, event.node_id, `${ts} INFO  ${toolName} done${resultStr}`);
            }
          }
          break;

        case "node_internal_output":
          if (!isQueen && event.node_id) {
            const content = (event.data?.content as string) || "";
            if (content.trim()) {
              appendNodeLog(agentType, event.node_id, `${ts} INFO  ${content}`);
            }
          }
          break;

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

        case "worker_loaded": {
          const workerName = event.data?.worker_name as string | undefined;
          const displayName = formatAgentDisplayName(workerName || agentType);

          // Update agent state: new display name, reset graph so topology refetch triggers
          updateAgentState(agentType, {
            displayName,
            workerRunState: "idle",
            graphId: null,
            nodeSpecs: [],
          });

          // Update session label (tab name) and clear graph nodes for fresh fetch
          setSessionsByAgent(prev => ({
            ...prev,
            [agentType]: (prev[agentType] || []).map(s => ({
              ...s,
              label: displayName,
              graphNodes: [],
            })),
          }));

          // Explicitly fetch graph topology for the newly loaded worker
          // (don't rely solely on the effect — state may already be null/empty)
          const sessionId = agentStates[agentType]?.sessionId;
          if (sessionId) {
            fetchGraphForAgent(agentType, sessionId);
          }

          break;
        }

        default:
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
    ? { nodes: activeSession.graphNodes, title: activeAgentState?.displayName || formatAgentDisplayName(activeWorker) }
    : { nodes: [] as GraphNode[], title: "" };

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
  const handleSend = useCallback((text: string, thread: string) => {
    if (!activeSession) return;
    const state = agentStates[activeWorker];

    if (!allRequiredCredentialsMet(activeSession.credentials)) {
      const userMsg: ChatMessage = {
        id: makeId(), agent: "You", agentColor: "",
        content: text, timestamp: "", type: "user", thread,
      };
      const promptMsg: ChatMessage = {
        id: makeId(), agent: "Queen Bee", agentColor: "",
        content: "Before we get started, you'll need to configure your credentials. Click the **Credentials** button in the top bar to connect the required integrations for this agent.",
        timestamp: "", role: "queen" as const, thread,
      };
      setSessionsByAgent(prev => ({
        ...prev,
        [activeWorker]: prev[activeWorker].map(s =>
          s.id === activeSession.id ? { ...s, messages: [...s.messages, userMsg, promptMsg] } : s
        ),
      }));
      return;
    }

    const userMsg: ChatMessage = {
      id: makeId(), agent: "You", agentColor: "",
      content: text, timestamp: "", type: "user", thread,
    };
    setSessionsByAgent(prev => ({
      ...prev,
      [activeWorker]: prev[activeWorker].map(s =>
        s.id === activeSession.id ? { ...s, messages: [...s.messages, userMsg] } : s
      ),
    }));
    updateAgentState(activeWorker, { isTyping: true });

    if (state?.sessionId && state?.ready) {
      executionApi.chat(state.sessionId, text).then((result) => {
        if (result.status === "started") {
          // Queen wasn't ready — backend triggered worker directly
          updateAgentState(activeWorker, {
            currentExecutionId: result.execution_id || null,
            workerRunState: "running",
          });
          const notice: ChatMessage = {
            id: makeId(), agent: "System", agentColor: "",
            content: "The queen wasn't ready yet — your message triggered an agent run directly.",
            timestamp: "", type: "system", thread,
          };
          setSessionsByAgent(prev => ({
            ...prev,
            [activeWorker]: prev[activeWorker].map(s =>
              s.id === activeSession.id ? { ...s, messages: [...s.messages, notice] } : s
            ),
          }));
        }
      }).catch((err: unknown) => {
        const errMsg = err instanceof Error ? err.message : String(err);
        const errorChatMsg: ChatMessage = {
          id: makeId(), agent: "System", agentColor: "",
          content: `Failed to send message: ${errMsg}`,
          timestamp: "", type: "system", thread,
        };
        setSessionsByAgent(prev => ({
          ...prev,
          [activeWorker]: prev[activeWorker].map(s =>
            s.id === activeSession.id ? { ...s, messages: [...s.messages, errorChatMsg] } : s
          ),
        }));
        updateAgentState(activeWorker, { isTyping: false });
      });
    } else {
      const errorMsg: ChatMessage = {
        id: makeId(), agent: "System", agentColor: "",
        content: "Cannot send message: backend is not connected. Please wait for the agent to load.",
        timestamp: "", type: "system", thread,
      };
      setSessionsByAgent(prev => ({
        ...prev,
        [activeWorker]: prev[activeWorker].map(s =>
          s.id === activeSession.id ? { ...s, messages: [...s.messages, errorMsg] } : s
        ),
      }));
      updateAgentState(activeWorker, { isTyping: false });
    }
  }, [activeWorker, activeSession, agentStates, updateAgentState]);

  const handleLoadAgent = useCallback(async (agentPath: string) => {
    const state = agentStates[activeWorker];
    if (!state?.sessionId) return;

    setLoadingWorker(true);
    try {
      await sessionsApi.loadWorker(state.sessionId, agentPath);
      // Success: worker_loaded SSE event will handle UI updates automatically
    } catch (err) {
      // 424 = credentials required — open the credentials modal
      const { ApiError } = await import("@/api/client");
      if (err instanceof ApiError && err.status === 424) {
        setCredentialsOpen(true);
        setLoadingWorker(false);
        return;
      }

      const errMsg = err instanceof Error ? err.message : String(err);
      const activeId = activeSessionRef.current[activeWorker];
      const errorMsg: ChatMessage = {
        id: makeId(), agent: "System", agentColor: "",
        content: `Failed to load agent: ${errMsg}`,
        timestamp: "", type: "system", thread: activeWorker,
      };
      setSessionsByAgent(prev => ({
        ...prev,
        [activeWorker]: (prev[activeWorker] || []).map(s =>
          s.id === activeId ? { ...s, messages: [...s.messages, errorMsg] } : s
        ),
      }));
    } finally {
      setLoadingWorker(false);
    }
  }, [activeWorker, agentStates]);

  const closeAgentTab = useCallback((agentType: string) => {
    // Pause worker execution if running (saves checkpoint), then kill the
    // entire backend session so the queen and judge don't keep running.
    const state = agentStates[agentType];
    if (state?.sessionId) {
      const pausePromise = (state.currentExecutionId && state.workerRunState === "running")
        ? executionApi.pause(state.sessionId, state.currentExecutionId)
        : Promise.resolve();

      pausePromise
        .catch(() => {})                          // pause failure shouldn't block kill
        .then(() => sessionsApi.stop(state.sessionId!))
        .catch(() => {});                         // fire-and-forget
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

  // Create a new session for any agent type (used by NewTabPopover)
  const addAgentSession = useCallback((agentType: string, agentLabel?: string) => {
    const sessions = sessionsByAgent[agentType] || [];
    const newIndex = sessions.length + 1;
    const existingCreds = sessions.length > 0 ? sessions[0].credentials : undefined;
    const displayLabel = agentLabel || formatAgentDisplayName(agentType);
    const label = newIndex === 1 ? displayLabel : `${displayLabel} #${newIndex}`;
    const newSession = createSession(agentType, label, existingCreds);

    setSessionsByAgent(prev => ({
      ...prev,
      [agentType]: [...(prev[agentType] || []), newSession],
    }));
    setActiveSessionByAgent(prev => ({ ...prev, [agentType]: newSession.id }));
    setActiveWorker(agentType);
  }, [sessionsByAgent]);

  const activeWorkerLabel = activeAgentState?.displayName || formatAgentDisplayName(activeWorker);


  return (
    <div className="flex flex-col h-screen bg-background overflow-hidden">
      <TopBar
        tabs={agentTabs}
        onTabClick={(agentType) => {
          const tab = agentTabs.find(t => t.agentType === agentType);
          if (tab) {
            setActiveWorker(agentType);
            setActiveSessionByAgent(prev => ({ ...prev, [agentType]: tab.sessionId }));
          }
        }}
        onCloseTab={closeAgentTab}
        afterTabs={
          <>
            <button
              ref={newTabBtnRef}
              onClick={() => setNewTabOpen(o => !o)}
              className="flex-shrink-0 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              title="Add tab"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
            <NewTabPopover
              open={newTabOpen}
              onClose={() => setNewTabOpen(false)}
              anchorRef={newTabBtnRef}
              activeWorker={activeWorker}
              discoverAgents={discoverAgents}
              onFromScratch={() => { addAgentSession("new-agent"); }}
              onCloneAgent={(agentPath, agentName) => { addAgentSession(agentPath, agentName); }}
            />
          </>
        }
      >
        {activeWorker === "new-agent" && activeAgentState?.ready && !activeAgentState?.graphId && (
          <>
            <button
              ref={loadAgentBtnRef}
              onClick={() => setLoadAgentOpen(o => !o)}
              disabled={loadingWorker}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
            >
              {loadingWorker ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Bot className="w-3.5 h-3.5" />
              )}
              Load Agent
            </button>
            <LoadAgentPopover
              open={loadAgentOpen}
              onClose={() => setLoadAgentOpen(false)}
              anchorRef={loadAgentBtnRef}
              discoverAgents={discoverAgents}
              onSelect={handleLoadAgent}
            />
          </>
        )}
        <button
          onClick={() => setCredentialsOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
        >
          <KeyRound className="w-3.5 h-3.5" />
          Credentials
        </button>
      </TopBar>

      {/* Main content area */}
      <div className="flex flex-1 min-h-0">
        <div className="w-[340px] min-w-[280px] bg-card/30 flex flex-col border-r border-border/30">
          <div className="flex-1 min-h-0">
          <AgentGraph
              nodes={currentGraph.nodes}
              title={currentGraph.title}
              onNodeClick={(node) => setSelectedNode(prev => prev?.id === node.id ? null : node)}
              onRun={handleRun}
              onPause={handlePause}
              runState={activeAgentState?.workerRunState ?? "idle"}
            />
          </div>
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
              <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-primary/5 border-b border-primary/20 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-primary/60" />
                <span className="text-xs text-primary/80">Connecting to queen...</span>
              </div>
            )}

            {/* Connection error banner */}
            {activeAgentState?.error && !activeAgentState?.loading && (
              activeAgentState.error === "credentials_required" ? (
                <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-amber-500/10 border-b border-amber-500/30 flex items-center gap-2">
                  <KeyRound className="w-4 h-4 text-amber-600" />
                  <span className="text-xs text-amber-700">Missing credentials — configure them to continue</span>
                  <button
                    onClick={() => setCredentialsOpen(true)}
                    className="ml-auto text-xs font-medium text-primary hover:underline"
                  >
                    Open Credentials
                  </button>
                </div>
              ) : (
                <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-destructive/10 border-b border-destructive/30 flex items-center gap-2">
                  <WifiOff className="w-4 h-4 text-destructive" />
                  <span className="text-xs text-destructive">Backend unavailable: {activeAgentState.error}</span>
                </div>
              )
            )}

            {activeSession && (
              <ChatPanel
                messages={activeSession.messages}
                onSend={handleSend}
                activeThread={activeWorker}
                isWaiting={activeAgentState?.isTyping ?? false}
                awaitingInput={activeAgentState?.awaitingInput ?? false}
                disabled={
                  (activeAgentState?.loading ?? true) ||
                  !(activeAgentState?.queenReady)
                }
              />
            )}
          </div>
          {selectedNode && (
            <div className="w-[480px] min-w-[400px] flex-shrink-0">
              <NodeDetailPanel
                node={selectedNode}
                nodeSpec={activeAgentState?.nodeSpecs.find(n => n.id === selectedNode.id) ?? null}
                sessionId={activeAgentState?.sessionId || undefined}
                graphId={activeAgentState?.graphId || undefined}
                workerSessionId={null}
                nodeLogs={activeAgentState?.nodeLogs[selectedNode.id] || []}
                actionPlan={activeAgentState?.nodeActionPlans[selectedNode.id]}
                onClose={() => setSelectedNode(null)}
              />
            </div>
          )}
        </div>
      </div>

      <CredentialsModal
        agentType={activeWorker}
        agentLabel={activeWorkerLabel}
        agentPath={activeWorker !== "new-agent" ? activeWorker : undefined}
        open={credentialsOpen}
        onClose={() => setCredentialsOpen(false)}
        credentials={activeSession?.credentials || []}
        onCredentialChange={() => {
          if (!activeSession) return;
          // Clear credential error so the auto-load effect retries session creation
          if (agentStates[activeWorker]?.error === "credentials_required") {
            updateAgentState(activeWorker, { error: null });
          }
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
