import { useState, useCallback, useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Crown, Plus, X, KeyRound, Sparkles, Layers, ChevronLeft, Bot, Loader2, WifiOff } from "lucide-react";
import AgentGraph, { type GraphNode, type NodeStatus } from "@/components/AgentGraph";
import ChatPanel, { type ChatMessage } from "@/components/ChatPanel";
import NodeDetailPanel from "@/components/NodeDetailPanel";
import CredentialsModal, { type Credential, createFreshCredentials, cloneCredentials, allRequiredCredentialsMet } from "@/components/CredentialsModal";
import { agentsApi } from "@/api/agents";
import { executionApi } from "@/api/execution";
import { graphsApi } from "@/api/graphs";
import { sessionsApi } from "@/api/sessions";
import { useSSE } from "@/hooks/use-sse";
import type { Agent, AgentEvent, DiscoverEntry, Message, NodeSpec } from "@/api/types";
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
          <div className="flex flex-col">
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

export default function Workspace() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rawAgent = searchParams.get("agent") || "new-agent";
  const initialAgent = rawAgent;
  const initialPrompt = searchParams.get("prompt") || "";

  // Sessions grouped by agent type — only create one for the initial agent
  const [sessionsByAgent, setSessionsByAgent] = useState<Record<string, Session[]>>(() => {
    const initial: Record<string, Session[]> = {};

    if (initialAgent === "new-agent") {
      const session = createSession("new-agent", "New Agent");
      session.messages = [
        {
          id: "na-1", agent: "Queen Bee", agentColor: "",
          content: "Welcome! I'm the Queen Bee \u2014 I'll help you set up your new agent.\n\nWould you like to:\n\n**1. Build from scratch** \u2014 Define a custom pipeline and workers tailored to your needs.\n\n**2. Start from an existing agent** \u2014 Clone one of your current agents and modify it.\n\nJust let me know which option you'd prefer, or describe what you'd like your agent to do and I'll suggest a setup.",
          timestamp: "", role: "queen", thread: "new-agent",
        },
      ];
      if (initialPrompt) {
        session.messages.push(
          {
            id: makeId(), agent: "You", agentColor: "",
            content: initialPrompt, timestamp: "", type: "user" as const, thread: "new-agent",
          },
          {
            id: makeId(), agent: "Queen Bee", agentColor: "",
            content: `Great idea! Let me think about how to set up an agent for that.\n\nI'll design a pipeline to handle: **"${initialPrompt}"**\n\nGive me a moment to put together the right workers and steps for you.`,
            timestamp: "", role: "queen" as const, thread: "new-agent",
          },
        );
      }
      initial["new-agent"] = [session];
    } else {
      // Real agent: start empty, backend will populate via intro_message + session history
      initial[initialAgent] = [createSession(initialAgent, formatAgentDisplayName(initialAgent))];
    }

    return initial;
  });

  // Active session ID per agent type
  const [activeSessionByAgent, setActiveSessionByAgent] = useState<Record<string, string>>(() => {
    const sessions = sessionsByAgent[initialAgent];
    return sessions ? { [initialAgent]: sessions[0].id } : {};
  });

  const [activeWorker, setActiveWorker] = useState(initialAgent);
  const [isTyping, setIsTyping] = useState(false);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [newTabOpen, setNewTabOpen] = useState(false);
  const newTabBtnRef = useRef<HTMLButtonElement>(null);

  // Monotonic counter that increments each time a new agent response turn
  // begins.  Used to give each streaming response a unique message ID so the
  // upsert logic creates a new bubble per turn instead of replacing the same
  // one forever.
  const streamTurnRef = useRef(0);

  // Ref mirror of sessionsByAgent so SSE callback can read current graph
  // state without adding sessionsByAgent to its dependency array.
  const sessionsRef = useRef(sessionsByAgent);
  sessionsRef.current = sessionsByAgent;

  // Tracks the latest LLM text snapshot per node so we can flush it as a
  // log line when the first tool call starts (avoids per-token log spam).
  const llmSnapshotRef = useRef<Record<string, string>>({});

  // --- Backend state ---
  const [backendAgentId, setBackendAgentId] = useState<string | null>(null);
  const [backendLoading, setBackendLoading] = useState(true);
  const [backendReady, setBackendReady] = useState(false);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [awaitingInput, setAwaitingInput] = useState(false);
  // Run button state — driven by SSE events from the worker
  const [workerRunState, setWorkerRunState] = useState<"idle" | "deploying" | "running">("idle");
  // Current execution ID — needed for pause API
  const [currentExecutionId, setCurrentExecutionId] = useState<string | null>(null);
  // Per-node live log lines accumulated from SSE events
  const [nodeLogs, setNodeLogs] = useState<Record<string, string[]>>({});
  // Resolved display name for the loaded agent (e.g. "Competitive Intel Agent")
  const [agentDisplayName, setAgentDisplayName] = useState<string | null>(null);
  // Graph context for NodeDetailPanel
  const [backendGraphId, setBackendGraphId] = useState<string | null>(null);
  const [nodeSpecs, setNodeSpecs] = useState<NodeSpec[]>([]);

  // Version state per agent type: [major, minor]
  const [agentVersions, setAgentVersions] = useState<Record<string, [number, number]>>(() => {
    return { [initialAgent]: [1, 0] };
  });

  const handleVersionBump = useCallback((type: "major" | "minor") => {
    setAgentVersions(prev => {
      const [major, minor] = prev[activeWorker] || [1, 0];
      return {
        ...prev,
        [activeWorker]: type === "major" ? [major + 1, 0] : [major, minor + 1],
      };
    });
  }, [activeWorker]);

  const handleRun = useCallback(async () => {
    if (!backendAgentId || !backendReady) return;
    try {
      setWorkerRunState("deploying");
      const result = await executionApi.trigger(backendAgentId, "default", {});
      setCurrentExecutionId(result.execution_id);
      // State transitions from here are driven by SSE events (step 7)
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      // Show error in chat
      setSessionsByAgent((prev) => {
        const sessions = prev[activeWorker] || [];
        return {
          ...prev,
          [activeWorker]: sessions.map((s) => {
            const activeId = activeSessionByAgent[activeWorker] || sessions[0]?.id;
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
      setWorkerRunState("idle");
    }
  }, [backendAgentId, backendReady, activeWorker, activeSessionByAgent]);

  // --- Fetch discovered agents for NewTabPopover ---
  const [discoverAgents, setDiscoverAgents] = useState<DiscoverEntry[]>([]);
  useEffect(() => {
    agentsApi.discover().then(result => {
      const all = Object.values(result).flat();
      setDiscoverAgents(all);
    }).catch(() => {});
  }, []);

  // --- Agent loading on mount (Phase 4) ---
  useEffect(() => {
    // "new-agent" is a client-side builder concept — no backend to load
    if (rawAgent === "new-agent") {
      setBackendLoading(false);
      return;
    }

    let cancelled = false;

    async function loadAgent() {
      setBackendLoading(true);
      setBackendError(null);
      setBackendReady(false);
      setBackendAgentId(null);

      try {
        // Try loading the agent on the backend
        let agent: Agent;
        try {
          agent = await agentsApi.load(rawAgent);
        } catch (loadErr: unknown) {
          const { ApiError } = await import("@/api/client");
          if (!(loadErr instanceof ApiError) || loadErr.status !== 409) {
            throw loadErr;
          }

          const agentId = loadErr.body.id as string | undefined;
          if (!agentId) throw loadErr;

          if (loadErr.body.loading) {
            // Agent is mid-load — poll GET /api/agents/{id} until it appears
            agent = await (async () => {
              const maxAttempts = 30;
              const delay = 1000;
              for (let i = 0; i < maxAttempts; i++) {
                if (cancelled) throw new Error("cancelled");
                await new Promise((r) => setTimeout(r, delay));
                try {
                  const result = await agentsApi.get(agentId);
                  // 202 returns {id, loading: true} — keep polling
                  const raw = result as Record<string, unknown>;
                  if (raw.loading) continue;
                  return result;
                } catch {
                  if (i === maxAttempts - 1) throw loadErr;
                }
              }
              throw loadErr; // unreachable, satisfies TS
            })();
          } else {
            // Already fully loaded — 409 body contains the agent data
            agent = loadErr.body as unknown as Agent;
          }
        }

        if (cancelled) return;
        setBackendAgentId(agent.id);

        // Resolve a human-readable display name for this agent.
        const displayName = formatAgentDisplayName(agent.name || initialAgent);
        setAgentDisplayName(displayName);

        // Update the session label to use the display name
        setSessionsByAgent((prev) => {
          const sessions = prev[initialAgent] || [];
          if (!sessions.length) return prev;
          return {
            ...prev,
            [initialAgent]: sessions.map((s, i) =>
              i === 0 ? { ...s, label: sessions.length === 1 ? displayName : `${displayName} #${i + 1}` } : s,
            ),
          };
        });

        // Check for existing sessions and load message history
        try {
          const { sessions } = await sessionsApi.list(agent.id);
          const resumable = sessions.find(
            (s) => s.status === "running" || s.status === "paused",
          );
          if (resumable && !cancelled) {
            // Load message history from the existing session
            const { messages } = await sessionsApi.messages(
              agent.id,
              resumable.session_id,
            );
            if (!cancelled && messages.length > 0) {
              const chatMsgs = messages.map((m: Message) =>
                backendMessageToChatMessage(m, initialAgent, displayName),
              );
              setSessionsByAgent((prev) => ({
                ...prev,
                [initialAgent]: (prev[initialAgent] || []).map((s, i) =>
                  i === 0
                    ? { ...s, messages: [...s.messages, ...chatMsgs] }
                    : s,
                ),
              }));
            }
          }
        } catch {
          // Session listing failed — not critical, continue without history
        }

        if (!cancelled) {
          setBackendReady(true);
          setBackendLoading(false);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : String(err);
          setBackendError(msg);
          setBackendLoading(false);
        }
      }
    }

    loadAgent();
    return () => { cancelled = true; };
  }, [rawAgent, initialAgent]);

  // --- Fetch real graph topology when backend is ready ---
  useEffect(() => {
    if (!backendAgentId || !backendReady) return;
    let cancelled = false;

    (async () => {
      try {
        // Discover the actual primary graph ID (not always "primary")
        const { graphs } = await agentsApi.graphs(backendAgentId);
        if (cancelled || !graphs.length) return;

        const graphId = graphs[0];
        const topology = await graphsApi.nodes(backendAgentId, graphId);
        if (cancelled) return;

        setBackendGraphId(graphId);
        setNodeSpecs(topology.nodes);

        const graphNodes = topologyToGraphNodes(topology);
        if (graphNodes.length === 0) return;

        setSessionsByAgent((prev) => {
          const sessions = prev[initialAgent] || [];
          if (!sessions.length) return prev;
          return {
            ...prev,
            [initialAgent]: sessions.map((s, i) =>
              i === 0 ? { ...s, graphNodes } : s,
            ),
          };
        });
      } catch {
        // Graph fetch failed — keep using empty data
      }
    })();

    return () => { cancelled = true; };
  }, [backendAgentId, backendReady, initialAgent]);

  // --- Graph node status helpers (live updates) ---
  const updateGraphNodeStatus = useCallback(
    (nodeId: string, status: NodeStatus, extra?: Partial<GraphNode>) => {
      setSessionsByAgent((prev) => {
        const sessions = prev[activeWorker] || [];
        return {
          ...prev,
          [activeWorker]: sessions.map((s) => {
            const activeId = activeSessionByAgent[activeWorker] || sessions[0]?.id;
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
    [activeWorker, activeSessionByAgent],
  );

  const markAllNodesAs = useCallback(
    (fromStatus: NodeStatus | NodeStatus[], toStatus: NodeStatus) => {
      const fromArr = Array.isArray(fromStatus) ? fromStatus : [fromStatus];
      setSessionsByAgent((prev) => {
        const sessions = prev[activeWorker] || [];
        return {
          ...prev,
          [activeWorker]: sessions.map((s) => {
            const activeId = activeSessionByAgent[activeWorker] || sessions[0]?.id;
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
    [activeWorker, activeSessionByAgent],
  );

  const handlePause = useCallback(async () => {
    if (!backendAgentId || !currentExecutionId) return;
    try {
      await executionApi.pause(backendAgentId, currentExecutionId);
      setWorkerRunState("idle");
      setCurrentExecutionId(null);
      markAllNodesAs(["running", "looping"], "pending");
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setSessionsByAgent((prev) => {
        const sessions = prev[activeWorker] || [];
        return {
          ...prev,
          [activeWorker]: sessions.map((s) => {
            const activeId = activeSessionByAgent[activeWorker] || sessions[0]?.id;
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
  }, [backendAgentId, currentExecutionId, activeWorker, activeSessionByAgent, markAllNodesAs]);

  // --- Node log helpers (live SSE → per-node log lines) ---
  const appendNodeLog = useCallback((nodeId: string, line: string) => {
    setNodeLogs((prev) => ({
      ...prev,
      [nodeId]: [...(prev[nodeId] || []), line].slice(-200),
    }));
  }, []);

  // --- SSE event handler (Phase 5) ---
  // Helper: upsert a chat message into the active session
  const upsertChatMessage = useCallback(
    (chatMsg: ChatMessage) => {
      setSessionsByAgent((prev) => {
        const sessions = prev[activeWorker] || [];
        return {
          ...prev,
          [activeWorker]: sessions.map((s) => {
            const activeId = activeSessionByAgent[activeWorker] || sessions[0]?.id;
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
    [activeWorker, activeSessionByAgent],
  );

  const handleSSEEvent = useCallback(
    (event: AgentEvent) => {
      // --- Source filtering ---
      const streamId = event.stream_id;

      // Suppress judge events (silent background monitoring)
      if (streamId === "worker_health_judge") return;

      // Determine if this is a queen event
      const isQueen = streamId === "queen";

      // Determine the display name for queen vs worker messages
      const displayName = isQueen ? "Queen Bee" : (agentDisplayName || undefined);
      const role = isQueen ? "queen" as const : "worker" as const;

      const ts = fmtLogTs(event.timestamp);

      switch (event.type) {
        case "execution_started":
          streamTurnRef.current += 1;
          if (isQueen) {
            setIsTyping(true);
          } else {
            setIsTyping(true);
            setAwaitingInput(false);
            setWorkerRunState("running");
            if (event.execution_id) setCurrentExecutionId(event.execution_id);
            markAllNodesAs(["running", "looping", "complete", "error"], "pending");
            setNodeLogs({});
            llmSnapshotRef.current = {};
          }
          break;

        case "execution_completed":
          if (isQueen) {
            setIsTyping(false);
          } else {
            setIsTyping(false);
            setAwaitingInput(false);
            setWorkerRunState("idle");
            setCurrentExecutionId(null);
            markAllNodesAs(["running", "looping"], "complete");
          }
          break;

        case "execution_failed":
        case "client_output_delta":
        case "client_input_requested":
        case "llm_text_delta": {
          const chatMsg = sseEventToChatMessage(event, activeWorker, displayName, streamTurnRef.current);
          if (chatMsg) {
            if (isQueen) chatMsg.role = role;
            upsertChatMessage(chatMsg);
          }

          // Track LLM text snapshots for node logs (flushed on tool_call_started)
          if (event.type === "llm_text_delta" && !isQueen && event.node_id) {
            const snapshot = (event.data?.snapshot as string) || "";
            if (snapshot) {
              llmSnapshotRef.current[event.node_id] = snapshot;
            }
          }

          if (event.type === "client_input_requested") {
            setAwaitingInput(true);
            setIsTyping(false);
          }
          if (event.type === "execution_failed") {
            setIsTyping(false);
            setAwaitingInput(false);
            if (!isQueen) {
              setWorkerRunState("idle");
              setCurrentExecutionId(null);
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
          streamTurnRef.current += 1;
          setIsTyping(true);
          if (!isQueen && event.node_id) {
            const sessions = sessionsRef.current[activeWorker] || [];
            const activeId = activeSessionByAgent[activeWorker] || sessions[0]?.id;
            const session = sessions.find((s) => s.id === activeId);
            const existing = session?.graphNodes.find((n) => n.id === event.node_id);
            const isRevisit = existing?.status === "complete";
            updateGraphNodeStatus(event.node_id, isRevisit ? "looping" : "running", {
              maxIterations: (event.data?.max_iterations as number) ?? undefined,
            });
            appendNodeLog(event.node_id, `${ts} INFO  Node started`);
          }
          break;

        case "node_loop_iteration":
          streamTurnRef.current += 1;
          if (!isQueen && event.node_id) {
            // Flush any accumulated LLM text before starting next iteration
            const pendingText = llmSnapshotRef.current[event.node_id];
            if (pendingText?.trim()) {
              appendNodeLog(event.node_id, `${ts} INFO  LLM: ${truncate(pendingText.trim(), 300)}`);
              delete llmSnapshotRef.current[event.node_id];
            }
            const iter = (event.data?.iteration as number) ?? undefined;
            updateGraphNodeStatus(event.node_id, "looping", { iterations: iter });
            appendNodeLog(event.node_id, `${ts} INFO  Iteration ${iter ?? "?"}`);
          }
          break;

        case "node_loop_completed":
          if (!isQueen && event.node_id) {
            // Flush any remaining LLM text
            const pendingText = llmSnapshotRef.current[event.node_id];
            if (pendingText?.trim()) {
              appendNodeLog(event.node_id, `${ts} INFO  LLM: ${truncate(pendingText.trim(), 300)}`);
              delete llmSnapshotRef.current[event.node_id];
            }
            updateGraphNodeStatus(event.node_id, "complete");
            appendNodeLog(event.node_id, `${ts} INFO  Node completed`);
          }
          break;

        case "edge_traversed": {
          if (!isQueen) {
            const sourceNode = event.data?.source_node as string | undefined;
            const targetNode = event.data?.target_node as string | undefined;
            if (sourceNode) updateGraphNodeStatus(sourceNode, "complete");
            if (targetNode) updateGraphNodeStatus(targetNode, "running");
          }
          break;
        }

        case "tool_call_started":
          if (!isQueen && event.node_id) {
            // Flush accumulated LLM reasoning before listing tool calls
            const pendingText = llmSnapshotRef.current[event.node_id];
            if (pendingText?.trim()) {
              appendNodeLog(event.node_id, `${ts} INFO  LLM: ${truncate(pendingText.trim(), 300)}`);
              delete llmSnapshotRef.current[event.node_id];
            }
            const toolName = (event.data?.tool_name as string) || "unknown";
            const toolInput = event.data?.tool_input;
            const argsStr = toolInput ? truncate(JSON.stringify(toolInput), 200) : "";
            appendNodeLog(event.node_id, `${ts} INFO  Calling ${toolName}(${argsStr})`);
          }
          break;

        case "tool_call_completed":
          if (!isQueen && event.node_id) {
            const toolName = (event.data?.tool_name as string) || "unknown";
            const isError = event.data?.is_error as boolean | undefined;
            const result = event.data?.result as string | undefined;
            if (isError) {
              appendNodeLog(event.node_id, `${ts} ERROR ${toolName} failed: ${truncate(result || "unknown error", 200)}`);
            } else {
              const resultStr = result ? ` (${truncate(result, 200)})` : "";
              appendNodeLog(event.node_id, `${ts} INFO  ${toolName} done${resultStr}`);
            }
          }
          break;

        case "node_internal_output":
          if (!isQueen && event.node_id) {
            const content = (event.data?.content as string) || "";
            if (content.trim()) {
              appendNodeLog(event.node_id, `${ts} INFO  ${content}`);
            }
          }
          break;

        case "node_stalled":
          if (!isQueen && event.node_id) {
            const reason = (event.data?.reason as string) || "unknown";
            appendNodeLog(event.node_id, `${ts} WARN  Stalled: ${reason}`);
          }
          break;

        default:
          break;
      }
    },
    [activeWorker, activeSessionByAgent, agentDisplayName, updateGraphNodeStatus, markAllNodesAs, upsertChatMessage, appendNodeLog],
  );

  // SSE subscription
  useSSE({
    agentId: backendAgentId || "",
    onEvent: handleSSEEvent,
    enabled: !!backendAgentId && backendReady,
  });

  const currentSessions = sessionsByAgent[activeWorker] || [];
  const activeSessionId = activeSessionByAgent[activeWorker] || currentSessions[0]?.id;
  const activeSession = currentSessions.find(s => s.id === activeSessionId) || currentSessions[0];

  const currentGraph = activeSession
    ? { nodes: activeSession.graphNodes, title: agentDisplayName || formatAgentDisplayName(activeWorker) }
    : { nodes: [] as GraphNode[], title: "" };

  // --- handleSend: real backend call or mock fallback (Phase 6) ---
  const handleSend = useCallback((text: string, thread: string) => {
    if (!activeSession) return;

    // If credentials aren't met, block and re-prompt
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

    // Add user message to UI immediately (optimistic)
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
    setIsTyping(true);

    // Real backend call if connected, otherwise mock fallback
    if (backendAgentId && backendReady) {
      executionApi.chat(backendAgentId, text).catch((err: unknown) => {
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
        setIsTyping(false);
      });
      // Response content will arrive via SSE events
    } else if (activeWorker === "new-agent") {
      // Builder flow — no backend, placeholder response
      setTimeout(() => {
        const reply: ChatMessage = {
          id: makeId(), agent: "Queen Bee", agentColor: "",
          content: "Got it! Let me design a pipeline for that. (Builder mode — backend integration coming soon.)",
          timestamp: "", role: "queen" as const, thread,
        };
        setSessionsByAgent(prev => ({
          ...prev,
          [activeWorker]: prev[activeWorker].map(s =>
            s.id === activeSession.id ? { ...s, messages: [...s.messages, reply] } : s
          ),
        }));
        setIsTyping(false);
      }, 800);
    } else {
      // Backend not connected — show error
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
      setIsTyping(false);
    }
  }, [activeWorker, activeSession, backendAgentId, backendReady]);

  const closeSession = useCallback((sessionId: string) => {
    const sessions = sessionsByAgent[activeWorker] || [];
    if (sessions.length <= 1) return; // Don't close last tab
    const filtered = sessions.filter(s => s.id !== sessionId);
    setSessionsByAgent(prev => ({ ...prev, [activeWorker]: filtered }));
    if (activeSessionId === sessionId) {
      setActiveSessionByAgent(prev => ({ ...prev, [activeWorker]: filtered[0].id }));
    }
  }, [activeWorker, sessionsByAgent, activeSessionId]);

  // Create a new session for any agent type (used by NewTabPopover)
  const addAgentSession = useCallback((agentType: string, agentLabel?: string, cloned = false) => {
    const sessions = sessionsByAgent[agentType] || [];
    const newIndex = sessions.length + 1;
    const existingCreds = sessions.length > 0 ? sessions[0].credentials : undefined;
    const displayLabel = agentLabel || formatAgentDisplayName(agentType);
    const label = newIndex === 1 ? displayLabel : `${displayLabel} #${newIndex}`;
    const newSession = createSession(agentType, label, existingCreds);

    if (cloned) {
      newSession.messages = [{
        id: makeId(), agent: "Queen Bee", agentColor: "",
        content: `Welcome to a new **${displayLabel}** session.\n\nConfigure any credentials if needed, then kick off a run whenever you're ready.`,
        timestamp: "", role: "queen" as const, thread: agentType,
      }];
    } else if (agentType === "new-agent") {
      // "From scratch" flow -- always show the builder prompt
      newSession.messages = [{
        id: makeId(), agent: "Queen Bee", agentColor: "",
        content: "Hey there! I'm the Queen Bee \u2014 let's build your new agent together.\n\n**What would you like your agent to do?** Here are a few ideas to get you started:\n\n- **Email manager** \u2014 triage inboxes, draft replies, auto-archive\n- **Job hunter** \u2014 scan job boards, match roles, auto-apply\n- **Security auditor** \u2014 run recon, score risks, generate reports\n- **Content writer** \u2014 research, outline, and draft long-form content\n- **Data analyst** \u2014 pull metrics, detect anomalies, summarize trends\n- **E-commerce monitor** \u2014 track prices, restock alerts, competitor analysis\n\nJust describe what you want to automate and I'll design the pipeline for you.",
        timestamp: "", role: "queen" as const, thread: "new-agent",
      }];
    }

    setSessionsByAgent(prev => ({
      ...prev,
      [agentType]: [...(prev[agentType] || []), newSession],
    }));
    setActiveSessionByAgent(prev => ({ ...prev, [agentType]: newSession.id }));
    setActiveWorker(agentType);

    // Initialize version tracking if not present
    setAgentVersions(prev => prev[agentType] ? prev : { ...prev, [agentType]: [1, 0] });
  }, [sessionsByAgent]);

  const activeWorkerLabel = agentDisplayName || formatAgentDisplayName(activeWorker);


  return (
    <div className="flex flex-col h-screen bg-background overflow-hidden">
      {/* Top bar */}
      <div className="relative h-12 flex items-center justify-between px-5 border-b border-border/60 bg-card/50 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={() => navigate("/")} className="flex items-center gap-2 hover:opacity-80 transition-opacity flex-shrink-0">
            <Crown className="w-4 h-4 text-primary" />
            <span className="text-sm font-semibold text-primary">Hive</span>
          </button>
          <span className="text-border text-xs flex-shrink-0">|</span>

          {/* Instance tabs */}
          <div className="flex items-center gap-0.5 min-w-0 overflow-x-auto scrollbar-hide">
            {currentSessions.map((session) => {
              const sessionIsActive = session.graphNodes.some(n => n.status === "running" || n.status === "looping");
              return (
                <button
                  key={session.id}
                  onClick={() => {
                    setActiveSessionByAgent(prev => ({ ...prev, [activeWorker]: session.id }));
                    // Open the first active/running node detail, or clear it
                    const activeNode = session.graphNodes.find(n => n.status === "running" || n.status === "looping") || session.graphNodes[0] || null;
                    setSelectedNode(activeNode);
                  }}
                  className={`group flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap flex-shrink-0 ${
                    session.id === activeSessionId
                      ? "bg-primary/15 text-primary"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
                >
                  {sessionIsActive && (
                    <span className="relative flex h-1.5 w-1.5 flex-shrink-0">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-60" />
                      <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-primary" />
                    </span>
                  )}
                  <span>{session.label}</span>
                  {currentSessions.length > 1 && (
                    <X
                      className="w-3 h-3 opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity"
                      onClick={(e) => { e.stopPropagation(); closeSession(session.id); }}
                    />
                  )}
                </button>
              );
            })}
            <button
              ref={newTabBtnRef}
              onClick={() => setNewTabOpen(o => !o)}
              className="flex-shrink-0 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              title="Add tab"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        <button
          onClick={() => setCredentialsOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
        >
          <KeyRound className="w-3.5 h-3.5" />
          Credentials
        </button>

        {/* Popover portalled to document.body, positioned from anchor button */}
        <NewTabPopover
          open={newTabOpen}
          onClose={() => setNewTabOpen(false)}
          anchorRef={newTabBtnRef}
          activeWorker={activeWorker}
          discoverAgents={discoverAgents}
          onFromScratch={() => { addAgentSession("new-agent"); }}
          onCloneAgent={(agentPath, agentName) => { addAgentSession(agentPath, agentName, true); }}
        />
      </div>

      {/* Main content area */}
      <div className="flex flex-1 min-h-0">
        <div className="w-[340px] min-w-[280px] bg-card/30 flex flex-col border-r border-border/30">
          <div className="flex-1 min-h-0">
          <AgentGraph
              nodes={currentGraph.nodes}
              title={currentGraph.title}
              onNodeClick={(node) => setSelectedNode(prev => prev?.id === node.id ? null : node)}
              onVersionBump={handleVersionBump}
              onRun={handleRun}
              onPause={handlePause}
              version={`v${agentVersions[activeWorker]?.[0] ?? 1}.${agentVersions[activeWorker]?.[1] ?? 0}`}
              runState={workerRunState}
            />
          </div>
        </div>
        <div className="flex-1 min-w-0 flex">
          <div className="flex-1 min-w-0 relative">
            {/* Loading overlay */}
            {backendLoading && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 backdrop-blur-sm">
                <div className="flex items-center gap-3 text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span className="text-sm">Connecting to agent...</span>
                </div>
              </div>
            )}

            {/* Connection error banner */}
            {backendError && !backendLoading && (
              <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-destructive/10 border-b border-destructive/30 flex items-center gap-2">
                <WifiOff className="w-4 h-4 text-destructive" />
                <span className="text-xs text-destructive">Backend unavailable: {backendError}</span>
              </div>
            )}

            {activeSession && (
              <ChatPanel
                messages={activeSession.messages}
                onSend={handleSend}
                activeThread={activeWorker}
                isWaiting={isTyping}
                awaitingInput={awaitingInput}
                disabled={backendLoading}
              />
            )}
          </div>
          {selectedNode && (
            <div className="w-[480px] min-w-[400px] flex-shrink-0">
              <NodeDetailPanel
                node={selectedNode}
                nodeSpec={nodeSpecs.find(n => n.id === selectedNode.id) ?? null}
                agentId={backendAgentId || undefined}
                graphId={backendGraphId || undefined}
                sessionId={null}
                nodeLogs={nodeLogs[selectedNode.id] || []}
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
          // Re-sync local credential state from templates after backend change
          // This keeps the send gate working until plan-chat.md wires real execution
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
