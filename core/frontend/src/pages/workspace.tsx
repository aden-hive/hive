import { useState, useCallback, useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Crown, Plus, X, KeyRound, Sparkles, Layers, ChevronLeft, Bot, Loader2, WifiOff } from "lucide-react";
import AgentGraph, { type GraphNode } from "@/components/AgentGraph";
import ChatPanel, { type ChatMessage, workerList } from "@/components/ChatPanel";
import NodeDetailPanel from "@/components/NodeDetailPanel";
import CredentialsModal, { type Credential, createFreshCredentials, cloneCredentials, allRequiredCredentialsMet } from "@/components/CredentialsModal";
import { agentsApi } from "@/api/agents";
import { executionApi } from "@/api/execution";
import { sessionsApi } from "@/api/sessions";
import { useSSE } from "@/hooks/use-sse";
import type { Agent, AgentEvent, Message } from "@/api/types";
import { backendMessageToChatMessage, sseEventToChatMessage, formatAgentDisplayName } from "@/lib/chat-helpers";

const makeId = () => Math.random().toString(36).slice(2, 9);

// --- Graph templates per agent type ---
const workerGraphs: Record<string, { nodes: GraphNode[]; title: string }> = {
  "content-writer": {
    title: "content_writer_graph",
    nodes: [
      { id: "brief-intake", label: "brief-intake", status: "complete", next: ["research"], iterations: 1 },
      { id: "research", label: "research", status: "complete", next: ["outline"], iterations: 1 },
      { id: "outline", label: "outline", status: "complete", next: ["draft"], iterations: 1 },
      { id: "draft", label: "draft", status: "running", next: ["review"], iterations: 1, statusLabel: "writing..." },
      { id: "review", label: "review", status: "pending", next: [], backEdges: ["draft"] },
    ],
  },
  "new-agent": {
    title: "new_agent_graph",
    nodes: [],
  },
  "inbox-management": {
    title: "inbox_management_graph",
    nodes: [
      { id: "fetch-mail", label: "fetch-mail", status: "complete", next: ["classify"], iterations: 1 },
      { id: "classify", label: "classify", status: "complete", next: ["prioritize"], iterations: 1 },
      { id: "prioritize", label: "prioritize", status: "running", next: ["draft-replies"], iterations: 1, statusLabel: "sorting..." },
      { id: "draft-replies", label: "draft-replies", status: "pending", next: ["send-or-archive"] },
      { id: "send-or-archive", label: "send-or-archive", status: "pending", next: [], backEdges: ["fetch-mail"] },
    ],
  },
  "job-hunter": {
    title: "job_hunter_graph",
    nodes: [
      { id: "intake", label: "intake", status: "complete", next: ["job-search"], iterations: 1 },
      { id: "job-search", label: "job-search", status: "complete", next: ["job-review"], iterations: 1 },
      { id: "job-review", label: "job-review", status: "complete", next: ["customize"], iterations: 1 },
      { id: "customize", label: "customize", status: "complete", next: [], iterations: 1 },
    ],
  },
  "fitness-coach": {
    title: "fitness_coach_graph",
    nodes: [
      { id: "intake", label: "intake", status: "complete", next: ["coach"], iterations: 1 },
      { id: "coach", label: "coach", status: "running", next: ["meal-checkin", "exercise-reminder"], backEdges: ["coach"], iterations: 2, statusLabel: "coaching..." },
      { id: "meal-checkin", label: "meal-checkin", status: "pending", next: [] },
      { id: "exercise-reminder", label: "exercise-reminder", status: "pending", next: [] },
    ],
  },
  "vuln-assessment": {
    title: "vuln_assessment_graph",
    nodes: [
      { id: "intake", label: "intake", status: "complete", next: ["passive-recon"], iterations: 1 },
      { id: "passive-recon", label: "passive-recon", status: "complete", next: ["risk-scoring"], iterations: 1 },
      { id: "risk-scoring", label: "risk-scoring", status: "complete", next: ["findings-review"], backEdges: ["passive-recon"], iterations: 1 },
      { id: "findings-review", label: "findings-review", status: "running", next: ["final-report"], iterations: 1, statusLabel: "analyzing..." },
      { id: "final-report", label: "final-report", status: "pending", next: [], backEdges: ["intake"] },
    ],
  },
};

// --- Seed messages per agent type ---
const seedMessages: Record<string, ChatMessage[]> = {
  "new-agent": [
    {
      id: "na-1", agent: "Queen Bee", agentColor: "",
      content: "Welcome! \ud83d\udc1d I'm the Queen Bee \u2014 I'll help you set up your new agent.\n\nWould you like to:\n\n**1. Build from scratch** \u2014 Define a custom pipeline and workers tailored to your needs.\n\n**2. Start from an existing agent** \u2014 Clone one of your current agents and modify it.\n\nJust let me know which option you'd prefer, or describe what you'd like your agent to do and I'll suggest a setup.",
      timestamp: "", role: "queen", thread: "new-agent",
    },
  ],
  "inbox-management": [
    { id: "im-1", agent: "Queen Bee", agentColor: "", content: "Good morning! Let's start with your inbox. Check for anything urgent.", timestamp: "", role: "queen", thread: "inbox-management" },
    { id: "im-2", agent: "inbox-management", agentColor: "", content: "You have 23 unread emails. 4 flagged as urgent:\n\n\u2022 Meeting invite from Sarah (tomorrow 2pm)\n\u2022 Invoice from AWS \u2014 $847.32\n\u2022 2 recruiter messages\n\u2022 Client follow-up from Acme Corp", timestamp: "", role: "worker", thread: "inbox-management" },
    { id: "im-3", agent: "Queen Bee", agentColor: "", content: "Accept Sarah's meeting, archive the invoice after logging it, and forward the recruiter messages to Job Hunter.", timestamp: "", role: "queen", thread: "inbox-management" },
    { id: "im-4", agent: "inbox-management", agentColor: "", content: "Done \u2713\n\n\u2022 Sarah's meeting accepted \u2014 added to calendar\n\u2022 AWS invoice logged to expenses sheet & archived\n\u2022 2 recruiter messages forwarded to Job Hunter\n\u2022 Drafted reply to Acme Corp \u2014 awaiting your review", timestamp: "", role: "worker", thread: "inbox-management" },
    { id: "im-5", agent: "Queen Bee", agentColor: "", content: "Great work. Send the Acme reply as-is. Keep monitoring for anything new.", timestamp: "", role: "queen", thread: "inbox-management" },
  ],
  "job-hunter": [
    { id: "jh-1", agent: "Queen Bee", agentColor: "", content: "I've forwarded 2 recruiter messages from Inbox. Analyze them and scan the boards.", timestamp: "", role: "queen", thread: "job-hunter" },
    { id: "jh-2", agent: "job-hunter", agentColor: "", content: "Analyzing recruiter messages + scanning 3 job boards...\n\nFound 5 new matches:\n\u2022 Senior Engineer @ Stripe \u2014 95% match \u2b50\n\u2022 Staff Engineer @ Vercel \u2014 88% match\n\u2022 Platform Lead @ Datadog \u2014 82% match\n\u2022 Senior SWE @ Notion \u2014 79% match\n\u2022 Backend Engineer @ Linear \u2014 76% match", timestamp: "", role: "worker", thread: "job-hunter" },
    { id: "jh-3", agent: "Queen Bee", agentColor: "", content: "The Stripe role exceeds the 90% threshold. Auto-apply with the latest resume. Bookmark Vercel for manual review.", timestamp: "", role: "queen", thread: "job-hunter" },
    { id: "jh-4", agent: "job-hunter", agentColor: "", content: "Application submitted to Stripe \u2713\n\nDetails:\n\u2022 Applied with resume v4.2\n\u2022 Cover letter auto-generated & personalized\n\u2022 Vercel role bookmarked for your review\n\u2022 Recruiter #1 replied \u2014 they want a call Thursday", timestamp: "", role: "worker", thread: "job-hunter" },
    { id: "jh-5", agent: "Queen Bee", agentColor: "", content: "Schedule the recruiter call for Thursday 3pm. Keep scanning \u2014 update me if anything above 85% comes in.", timestamp: "", role: "queen", thread: "job-hunter" },
  ],
  "fitness-coach": [
    { id: "fc-1", agent: "Queen Bee", agentColor: "", content: "What's on the fitness plan today? Check sleep and recovery data.", timestamp: "", role: "queen", thread: "fitness-coach" },
    { id: "fc-2", agent: "fitness-coach", agentColor: "", content: "Today is leg day \ud83e\uddb5\n\nSleep: 7.2hrs (good)\nHRV: 58ms (above baseline)\nRecovery score: 82% \u2014 green light for heavy lifting\n\nPlanned workout:\n\u2022 Squats 4\u00d78 @ 225lbs\n\u2022 Romanian deadlifts 3\u00d710 @ 185lbs\n\u2022 Leg press 3\u00d712 @ 360lbs\n\u2022 Walking lunges 3\u00d720 steps", timestamp: "", role: "worker", thread: "fitness-coach" },
    { id: "fc-3", agent: "Queen Bee", agentColor: "", content: "Looks solid. Add calf raises \u2014 they've been neglected. Also prep a post-workout meal suggestion.", timestamp: "", role: "queen", thread: "fitness-coach" },
    { id: "fc-4", agent: "fitness-coach", agentColor: "", content: "Updated \u2713\n\nAdded: Standing calf raises 4\u00d715\n\nPost-workout meal suggestion:\n\ud83c\udf57 Grilled chicken (40g protein)\n\ud83c\udf5a Jasmine rice (60g carbs)\n\ud83e\udd66 Steamed broccoli\n\ud83e\udd64 Creatine + electrolyte shake\n\nEstimated workout duration: 52 mins", timestamp: "", role: "worker", thread: "fitness-coach" },
  ],
  "vuln-assessment": [
    { id: "va-1", agent: "Queen Bee", agentColor: "", content: "Run a full vulnerability scan on openclaw.ai. Check all subdomains and headers.", timestamp: "", role: "queen", thread: "vuln-assessment" },
    { id: "va-2", agent: "vuln-assessment", agentColor: "", content: "Scanning openclaw.ai...\n\nDiscovery phase complete:\n\u2022 3 subdomains: api., docs., staging.\n\u2022 12 open ports detected\n\u2022 staging. subdomain has directory listing enabled \u26a0\ufe0f", timestamp: "", role: "worker", thread: "vuln-assessment" },
    { id: "va-3", agent: "Queen Bee", agentColor: "", content: "Critical \u2014 disable that directory listing immediately. Continue with header analysis and SSL check.", timestamp: "", role: "queen", thread: "vuln-assessment" },
    { id: "va-4", agent: "vuln-assessment", agentColor: "", content: "Header & SSL analysis complete:\n\n\ud83d\udd34 Critical:\n\u2022 Missing Content-Security-Policy\n\u2022 No X-Frame-Options header\n\u2022 staging. directory listing (flagged)\n\n\ud83d\udfe1 Medium:\n\u2022 SPF record too permissive\n\u2022 No DMARC record\n\n\ud83d\udfe2 Good:\n\u2022 SSL cert valid (expires in 12 days \u2014 renew soon)\n\u2022 HSTS enabled on main domain\n\u2022 X-Content-Type-Options present", timestamp: "", role: "worker", thread: "vuln-assessment" },
    { id: "va-5", agent: "Queen Bee", agentColor: "", content: "Good scan. Generate a remediation report with priority order. Flag the SSL renewal as a calendar task.", timestamp: "", role: "queen", thread: "vuln-assessment" },
  ],
  "content-writer": [
    { id: "cw-1", agent: "Queen Bee", agentColor: "", content: "Draft a blog post on the future of AI agents. Tone: professional but accessible. Target length: 800 words.", timestamp: "", role: "queen", thread: "content-writer" },
    { id: "cw-2", agent: "content-writer", agentColor: "", content: "Research complete. Here's the outline:\n\n1. Introduction \u2014 The rise of autonomous agents\n2. How AI agents differ from chatbots\n3. Real-world use cases today\n4. What the next 5 years look like\n5. Conclusion \u2014 Humans + agents working together\n\nStarting draft now.", timestamp: "", role: "worker", thread: "content-writer" },
    { id: "cw-3", agent: "Queen Bee", agentColor: "", content: "Good outline. Make sure section 3 includes concrete examples \u2014 email, recruiting, and security. Keep the intro punchy.", timestamp: "", role: "queen", thread: "content-writer" },
    { id: "cw-4", agent: "content-writer", agentColor: "", content: "Draft ready \u2713\n\n\ud83d\udcdd Word count: 823\n\ud83d\udccc Examples added: Inbox Management, Job Hunter, Vuln Assessment\n\ud83d\udd17 3 internal links suggested\n\nReady for your review before publish.", timestamp: "", role: "worker", thread: "content-writer" },
  ],
};

// --- Session types ---
interface Session {
  id: string;
  agentType: string;
  label: string;
  messages: ChatMessage[];
  graphNodes: GraphNode[];
  credentials: Credential[];
}

function createSession(agentType: string, index: number, existingCredentials?: Credential[]): Session {
  const graph = workerGraphs[agentType] || { title: agentType, nodes: [] };
  const agentLabel = workerList.find(w => w.id === agentType)?.label || formatAgentDisplayName(agentType);
  return {
    id: makeId(),
    agentType,
    label: index === 1 ? agentLabel : `${agentLabel} #${index}`,
    messages: index === 1 ? (seedMessages[agentType] || []) : [],
    graphNodes: graph.nodes.map(n => ({ ...n })),
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
  onNewInstance: () => void;
  onFromScratch: () => void;
  onCloneAgent: (agentType: string) => void;
}

function NewTabPopover({ open, onClose, anchorRef, onNewInstance: _onNewInstance, onFromScratch, onCloneAgent }: NewTabPopoverProps) {
  void _onNewInstance;
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

  const cloneableAgents = workerList.filter(w => w.id !== "new-agent");

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
          {step === "root" ? "Add Tab" : step === "new-agent-choice" ? "New Agent" : "Clone Existing"}
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
            {cloneableAgents.map(agent => (
              <button
                key={agent.id}
                onClick={() => { onCloneAgent(agent.id); onClose(); }}
                className="flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-left transition-colors hover:bg-muted/60 text-foreground"
              >
                <div className="w-6 h-6 rounded-md bg-muted/80 flex items-center justify-center flex-shrink-0">
                  <Bot className="w-3.5 h-3.5 text-muted-foreground" />
                </div>
                <span className="text-sm font-medium">{agent.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}

// Map discover paths to existing mock IDs
const PATH_TO_MOCK_ID: Record<string, string> = {
  "examples/templates/email_inbox_management": "inbox-management",
  "examples/templates/job_hunter": "job-hunter",
  "examples/templates/vulnerability_assessment": "vuln-assessment",
  "examples/templates/fitness_coach": "fitness-coach",
};

// Reverse mapping: mock ID → real agent path on disk (for credential detection)
const MOCK_ID_TO_PATH: Record<string, string> = Object.fromEntries(
  Object.entries(PATH_TO_MOCK_ID).map(([path, id]) => [id, path]),
);

function resolveMockId(agentParam: string): string {
  if (workerGraphs[agentParam]) return agentParam;
  return PATH_TO_MOCK_ID[agentParam] || agentParam;
}

export default function Workspace() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rawAgent = searchParams.get("agent") || "inbox-management";
  const initialAgent = resolveMockId(rawAgent);
  const initialPrompt = searchParams.get("prompt") || "";

  // Sessions grouped by agent type
  const [sessionsByAgent, setSessionsByAgent] = useState<Record<string, Session[]>>(() => {
    const initial: Record<string, Session[]> = {};
    workerList.forEach(w => {
      const session = createSession(w.id, 1);
      // If this is the new-agent and there's an initial prompt, append user message + queen reply
      if (w.id === "new-agent" && w.id === initialAgent && initialPrompt) {
        session.messages = [
          ...session.messages,
          {
            id: makeId(), agent: "You", agentColor: "",
            content: initialPrompt, timestamp: "", type: "user" as const, thread: "new-agent",
          },
          {
            id: makeId(), agent: "Queen Bee", agentColor: "",
            content: `Great idea! Let me think about how to set up an agent for that.\n\nI'll design a pipeline to handle: **"${initialPrompt}"**\n\nGive me a moment to put together the right workers and steps for you.`,
            timestamp: "", role: "queen" as const, thread: "new-agent",
          },
        ];
      }
      initial[w.id] = [session];
    });

    // If the initial agent is not in workerList, create an empty session.
    // The intro_message will be injected once the backend responds.
    if (!initial[initialAgent]) {
      initial[initialAgent] = [{
        id: makeId(),
        agentType: initialAgent,
        label: formatAgentDisplayName(initialAgent),
        messages: [],
        graphNodes: [],
        credentials: [],
      }];
    }

    return initial;
  });

  // Active session ID per agent type
  const [activeSessionByAgent, setActiveSessionByAgent] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    workerList.forEach(w => {
      initial[w.id] = sessionsByAgent[w.id][0].id;
    });
    // Also set active session for dynamic agent not in workerList
    if (sessionsByAgent[initialAgent] && !initial[initialAgent]) {
      initial[initialAgent] = sessionsByAgent[initialAgent][0].id;
    }
    return initial;
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

  // --- Backend state ---
  const [backendAgentId, setBackendAgentId] = useState<string | null>(null);
  const [backendLoading, setBackendLoading] = useState(true);
  const [backendReady, setBackendReady] = useState(false);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [awaitingInput, setAwaitingInput] = useState(false);
  // Resolved display name for the loaded agent (e.g. "Competitive Intel Agent")
  const [agentDisplayName, setAgentDisplayName] = useState<string | null>(null);

  // Version state per agent type: [major, minor]
  const [agentVersions, setAgentVersions] = useState<Record<string, [number, number]>>(() => {
    const init: Record<string, [number, number]> = {};
    workerList.forEach(w => { init[w.id] = [1, 0]; });
    return init;
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

  // --- Agent loading on mount (Phase 4) ---
  useEffect(() => {
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
        // Prefer workerList label, then format the backend name / agent id.
        const displayName =
          workerList.find((w) => w.id === initialAgent)?.label ||
          formatAgentDisplayName(agent.name || initialAgent);
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

        // Inject intro_message as seed message (only if session is empty)
        if (agent.intro_message) {
          const introMsg: ChatMessage = {
            id: `intro-${agent.id}`,
            agent: displayName,
            agentColor: "",
            content: agent.intro_message,
            timestamp: "",
            role: "worker" as const,
            thread: initialAgent,
          };
          setSessionsByAgent((prev) => {
            const sessions = prev[initialAgent] || [];
            if (!sessions.length || sessions[0].messages.length > 0) return prev;
            return {
              ...prev,
              [initialAgent]: [{ ...sessions[0], messages: [introMsg] }, ...sessions.slice(1)],
            };
          });
        }

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

  // --- SSE event handler (Phase 5) ---
  const handleSSEEvent = useCallback(
    (event: AgentEvent) => {
      switch (event.type) {
        case "execution_started":
          streamTurnRef.current += 1;
          setIsTyping(true);
          setAwaitingInput(false);
          break;

        case "execution_completed":
          setIsTyping(false);
          setAwaitingInput(false);
          break;

        case "execution_failed":
        case "client_output_delta":
        case "client_input_requested":
        case "llm_text_delta": {
          // DEBUG: trace message ID generation
          console.log(`[SSE] type=${event.type} node_id=${event.node_id} turn=${streamTurnRef.current} → id=stream-${streamTurnRef.current}-${event.node_id}`);
          // Convert event to a chat message (if applicable)
          const chatMsg = sseEventToChatMessage(event, activeWorker, agentDisplayName || undefined, streamTurnRef.current);
          if (chatMsg) {
            // Upsert: if a message with this ID already exists, replace it (streaming)
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
          }

          if (event.type === "client_input_requested") {
            setAwaitingInput(true);
            setIsTyping(false);
          }
          if (event.type === "execution_failed") {
            setIsTyping(false);
            setAwaitingInput(false);
          }
          break;
        }

        case "node_loop_started":
          streamTurnRef.current += 1;
          setIsTyping(true);
          break;

        case "node_loop_iteration":
          streamTurnRef.current += 1;
          break;

        default:
          break;
      }
    },
    [activeWorker, activeSessionByAgent, agentDisplayName],
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
    ? { nodes: activeSession.graphNodes, title: workerGraphs[activeWorker]?.title || "" }
    : workerGraphs[activeWorker] || workerGraphs["inbox-management"];

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
    } else {
      // Mock fallback when backend isn't available
      setTimeout(() => {
        const reply: ChatMessage = {
          id: makeId(), agent: "Queen Bee", agentColor: "",
          content: "Acknowledged. Dispatching worker swarm...", timestamp: "", role: "queen" as const, thread,
        };
        setSessionsByAgent(prev => ({
          ...prev,
          [activeWorker]: prev[activeWorker].map(s =>
            s.id === activeSession.id ? { ...s, messages: [...s.messages, reply] } : s
          ),
        }));
        setIsTyping(false);
      }, 800);
    }
  }, [activeWorker, activeSession, backendAgentId, backendReady]);

  const addSession = useCallback(() => {
    const sessions = sessionsByAgent[activeWorker] || [];
    const newIndex = sessions.length + 1;
    // Auto-fill credentials from the first existing session
    const existingCreds = sessions.length > 0 ? sessions[0].credentials : undefined;
    const newSession = createSession(activeWorker, newIndex, existingCreds);
    // If credentials are missing, add a queen message prompting configuration
    if (!existingCreds || !allRequiredCredentialsMet(existingCreds)) {
      const promptMsg: ChatMessage = {
        id: makeId(),
        agent: "Queen Bee",
        agentColor: "",
        content: "Before we get started, you'll need to configure your credentials. Click the **Credentials** button in the top bar to connect the required integrations for this agent.",
        timestamp: "",
        role: "queen" as const,
        thread: activeWorker,
      };
      newSession.messages = [...newSession.messages, promptMsg];
    }
    setSessionsByAgent(prev => ({
      ...prev,
      [activeWorker]: [...(prev[activeWorker] || []), newSession],
    }));
    setActiveSessionByAgent(prev => ({ ...prev, [activeWorker]: newSession.id }));
  }, [activeWorker, sessionsByAgent]);

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
  const addAgentSession = useCallback((agentType: string, cloned = false) => {
    const sessions = sessionsByAgent[agentType] || [];
    const newIndex = sessions.length + 1;
    const existingCreds = sessions.length > 0 ? sessions[0].credentials : undefined;
    const newSession = createSession(agentType, newIndex, existingCreds);

    // For cloned sessions: reset animated states so the graph is static
    if (cloned) {
      newSession.graphNodes = newSession.graphNodes.map(n => ({
        ...n,
        status: (n.status === "running" || n.status === "looping") ? "complete" : n.status,
        statusLabel: undefined,
        iterations: n.status === "running" || n.status === "looping" ? n.iterations : n.iterations,
      }));
    }

    // Build intro message
    const agentLabel = workerList.find(w => w.id === agentType)?.label || agentType;

    if (cloned) {
      newSession.messages = [{
        id: makeId(), agent: "Queen Bee", agentColor: "",
        content: `Welcome to a new **${agentLabel}** session. \ud83d\udc1d\n\nThis instance is cloned from the existing agent \u2014 the pipeline is ready to go. Configure any credentials if needed, then kick off a run whenever you're ready.`,
        timestamp: "", role: "queen" as const, thread: agentType,
      }];
    } else if (agentType === "new-agent") {
      // "From scratch" flow -- always show the builder prompt
      newSession.messages = [{
        id: makeId(), agent: "Queen Bee", agentColor: "",
        content: "Hey there! \ud83d\udc1d I'm the Queen Bee \u2014 let's build your new agent together.\n\n**What would you like your agent to do?** Here are a few ideas to get you started:\n\n- \ud83d\udce7 **Email manager** \u2014 triage inboxes, draft replies, auto-archive\n- \ud83d\udcbc **Job hunter** \u2014 scan job boards, match roles, auto-apply\n- \ud83d\udd12 **Security auditor** \u2014 run recon, score risks, generate reports\n- \ud83d\udcdd **Content writer** \u2014 research, outline, and draft long-form content\n- \ud83d\udcca **Data analyst** \u2014 pull metrics, detect anomalies, summarize trends\n- \ud83d\uded2 **E-commerce monitor** \u2014 track prices, restock alerts, competitor analysis\n\nJust describe what you want to automate and I'll design the pipeline for you.",
        timestamp: "", role: "queen" as const, thread: "new-agent",
      }];
    }

    setSessionsByAgent(prev => ({
      ...prev,
      [agentType]: [...(prev[agentType] || []), newSession],
    }));
    setActiveSessionByAgent(prev => ({ ...prev, [agentType]: newSession.id }));
    setActiveWorker(agentType);
  }, [sessionsByAgent]);

  const activeWorkerLabel = agentDisplayName
    || workerList.find(w => w.id === activeWorker)?.label
    || formatAgentDisplayName(activeWorker);


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
          onNewInstance={() => { addSession(); }}
          onFromScratch={() => { addAgentSession("new-agent"); }}
          onCloneAgent={(agentType) => { addAgentSession(agentType, true); }}
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
              version={`v${agentVersions[activeWorker]?.[0] ?? 1}.${agentVersions[activeWorker]?.[1] ?? 0}`}
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
                onClose={() => setSelectedNode(null)}
              />
            </div>
          )}
        </div>
      </div>

      <CredentialsModal
        agentType={activeWorker}
        agentLabel={activeWorkerLabel}
        agentPath={MOCK_ID_TO_PATH[activeWorker] || rawAgent}
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
