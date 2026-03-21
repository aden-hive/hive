import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Crown, Mail, Briefcase, Shield, Search, Newspaper, ArrowRight, Hexagon, Send, Bot, Radar, Reply, DollarSign, MapPin, Calendar, UserPlus, Twitter, RotateCcw, X, Clock } from "lucide-react";
import TopBar from "@/components/TopBar";
import type { LucideIcon } from "lucide-react";
import { agentsApi } from "@/api/agents";
import { sessionsApi } from "@/api/sessions";
import type { DiscoverEntry } from "@/api/types";
import type { HistorySession } from "@/components/HistorySidebar";

// --- Icon and color maps (backend can't serve icons) ---

const AGENT_ICONS: Record<string, LucideIcon> = {
  email_inbox_management: Mail,
  job_hunter: Briefcase,
  vulnerability_assessment: Shield,
  deep_research_agent: Search,
  tech_news_reporter: Newspaper,
  competitive_intel_agent: Radar,
  email_reply_agent: Reply,
  hubspot_revenue_leak_detector: DollarSign,
  local_business_extractor: MapPin,
  meeting_scheduler: Calendar,
  sdr_agent: UserPlus,
  twitter_news_agent: Twitter,
};

const AGENT_COLORS: Record<string, string> = {
  email_inbox_management: "hsl(38,80%,55%)",
  job_hunter: "hsl(30,85%,58%)",
  vulnerability_assessment: "hsl(15,70%,52%)",
  deep_research_agent: "hsl(210,70%,55%)",
  tech_news_reporter: "hsl(270,60%,55%)",
  competitive_intel_agent: "hsl(190,70%,45%)",
  email_reply_agent: "hsl(45,80%,55%)",
  hubspot_revenue_leak_detector: "hsl(145,60%,42%)",
  local_business_extractor: "hsl(350,65%,55%)",
  meeting_scheduler: "hsl(220,65%,55%)",
  sdr_agent: "hsl(165,55%,45%)",
  twitter_news_agent: "hsl(200,85%,55%)",
};

function agentSlug(path: string): string {
  return path.replace(/\/$/, "").split("/").pop() || path;
}

// --- Generic prompt hints (not tied to specific agents) ---

const promptHints = [
  "Check my inbox for urgent emails",
  "Find senior engineer roles that match my profile",
  "Research the latest trends in AI agents",
  "Run a security scan on my domain",
];

// --- Slash command helpers (copied from HistorySidebar.tsx) ---

function defaultLabel(s: HistorySession, index: number): string {
  if (s.agent_name) return s.agent_name;
  if (s.agent_path) {
    const base = s.agent_path.replace(/\/$/, "").split("/").pop() || s.agent_path;
    return base
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  }
  return `New Agent${index > 0 ? ` #${index + 1}` : ""}`;
}

function formatDateTime(createdAt: number, sessionId: string): string {
  const match = sessionId.match(/^session_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  const d = match
    ? new Date(+match[1], +match[2] - 1, +match[3], +match[4], +match[5], +match[6])
    : new Date(createdAt * 1000);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function deduplicateByAgent(sessions: HistorySession[]): HistorySession[] {
  const seen = new Set<string>();
  const result: HistorySession[] = [];
  for (const s of sessions) {
    const key = s.agent_path ? s.agent_path.replace(/\/$/, "") : `__no_agent__${s.session_id}`;
    if (!seen.has(key)) {
      seen.add(key);
      result.push(s);
    }
  }
  return result;
}

function groupByDate(sessions: HistorySession[]): { label: string; items: HistorySession[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 86_400_000;
  const weekAgo = today - 7 * 86_400_000;
  const groups: { label: string; items: HistorySession[] }[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Last 7 days", items: [] },
    { label: "Older", items: [] },
  ];
  for (const s of sessions) {
    const d = new Date(s.created_at * 1000);
    const dayTs = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    if (dayTs >= today) groups[0].items.push(s);
    else if (dayTs >= yesterday) groups[1].items.push(s);
    else if (dayTs >= weekAgo) groups[2].items.push(s);
    else groups[3].items.push(s);
  }
  return groups.filter((g) => g.items.length > 0);
}

// --- Slash command registry ---

const SLASH_COMMANDS = [
  { id: "resume", label: "resume", description: "Continue a previous session", Icon: RotateCcw },
] as const;

export default function Home() {
  const navigate = useNavigate();
  const [inputValue, setInputValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showAgents, setShowAgents] = useState(false);
  const [agents, setAgents] = useState<DiscoverEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Slash menu
  const [slashMenuOpen, setSlashMenuOpen] = useState(false);
  const [slashQuery, setSlashQuery] = useState("");
  const [slashHighlight, setSlashHighlight] = useState(0);

  // Session modal
  const [sessionModalOpen, setSessionModalOpen] = useState(false);
  const [sessions, setSessions] = useState<HistorySession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionSearch, setSessionSearch] = useState("");
  const [sessionHighlight, setSessionHighlight] = useState(0);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Derived session values — computed early so useEffects can reference them
  const filteredSessions = sessions.filter((s) => {
    if (!sessionSearch.trim()) return true;
    const q = sessionSearch.toLowerCase();
    return (
      (s.agent_name || s.agent_path || "").toLowerCase().includes(q) ||
      (s.last_message || "").toLowerCase().includes(q)
    );
  });
  const sessionGroups = groupByDate(filteredSessions);

  // Fetch agents on mount so data is ready when user toggles
  useEffect(() => {
    setLoading(true);
    agentsApi
      .discover()
      .then((result) => {
        const examples = result["Examples"] || [];
        setAgents(examples);
      })
      .catch((err) => {
        setError(err.message || "Failed to load agents");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  // Keyboard navigation for session modal
  useEffect(() => {
    if (!sessionModalOpen) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setSessionModalOpen(false); return; }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSessionHighlight((p) => Math.min(p + 1, filteredSessions.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSessionHighlight((p) => Math.max(p - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        if (filteredSessions[sessionHighlight]) handleSessionSelect(filteredSessions[sessionHighlight]);
        return;
      }
    };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [sessionModalOpen, filteredSessions, sessionHighlight]);

  // Auto-scroll highlighted session row into view
  useEffect(() => {
    if (!sessionModalOpen) return;
    const el = document.querySelector(`[data-session-idx="${sessionHighlight}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [sessionHighlight, sessionModalOpen]);

  const handleSelect = (agentPath: string) => {
    navigate(`/workspace?agent=${encodeURIComponent(agentPath)}`);
  };

  const handlePromptHint = (text: string) => {
    navigate(`/workspace?agent=new-agent&prompt=${encodeURIComponent(text)}`);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputValue.trim()) {
      navigate(`/workspace?agent=new-agent&prompt=${encodeURIComponent(inputValue.trim())}`);
    }
  };

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const value = e.target.value;
    setInputValue(value);
    // Auto-resize
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
    // Slash menu
    const trimmed = value.trimStart();
    if (trimmed.startsWith("/")) {
      setSlashQuery(trimmed.slice(1).toLowerCase());
      setSlashMenuOpen(true);
      setSlashHighlight(0);
    } else {
      setSlashMenuOpen(false);
    }
  }

  function handleTextareaKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (slashMenuOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashHighlight((h) => Math.min(h + 1, filteredCommands.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSlashHighlight((h) => Math.max(h - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        if (filteredCommands[safeHighlight]) {
          handleSlashSelect(filteredCommands[safeHighlight].id);
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSlashMenuOpen(false);
        return;
      }
    } else {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit(e);
      }
    }
  }

  function handleSlashSelect(id: string) {
    setSlashMenuOpen(false);
    setInputValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    if (id === "resume") openSessionModal();
  }

  function openSessionModal() {
    setSessionModalOpen(true);
    setSessionSearch("");
    setSessionsLoading(true);
    sessionsApi
      .history()
      .then((r) => setSessions(deduplicateByAgent(r.sessions as HistorySession[])))
      .catch(() => setSessions([]))
      .finally(() => {
        setSessionsLoading(false);
        requestAnimationFrame(() => searchInputRef.current?.focus());
      });
  }

  function handleSessionSelect(s: HistorySession) {
    setSessionModalOpen(false);
    if (s.agent_path) {
      navigate(`/workspace?agent=${encodeURIComponent(s.agent_path)}&session=${s.session_id}`);
    }
  }

  // Derived slash command values
  const filteredCommands = SLASH_COMMANDS.filter((cmd) => cmd.id.startsWith(slashQuery));
  const safeHighlight = Math.min(slashHighlight, filteredCommands.length - 1);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <TopBar />

      {/* Main content */}
      <div className="flex-1 flex flex-col items-center justify-center p-6">
        <div className="w-full max-w-2xl">
          {/* Queen Bee greeting */}
          <div className="text-center mb-8">
            <div
              className="inline-flex w-12 h-12 rounded-2xl items-center justify-center mb-4"
              style={{
                backgroundColor: "hsl(45,95%,58%,0.1)",
                border: "1.5px solid hsl(45,95%,58%,0.25)",
                boxShadow: "0 0 24px hsl(45,95%,58%,0.08)",
              }}
            >
              <Crown className="w-6 h-6 text-primary" />
            </div>
            <h1 className="text-xl font-semibold text-foreground mb-1.5">What can I help you with?</h1>
            <p className="text-sm text-muted-foreground">
              I'm your Queen Bee — I create and coordinate worker agents to handle tasks for you.
            </p>
          </div>

          {/* Chat input */}
          <form onSubmit={handleSubmit} className="mb-6">
            <div className="relative border border-border/60 rounded-xl bg-card/50 hover:border-primary/30 focus-within:border-primary/40 transition-colors shadow-sm">
              {/* Slash command dropdown — above textarea */}
              {slashMenuOpen && filteredCommands.length > 0 && (
                <div className="absolute bottom-full left-0 right-0 mb-1.5 z-50 rounded-xl border border-border/60 bg-card shadow-xl overflow-hidden">
                  <div className="px-3 py-1.5">
                    <span className="text-[10px] font-semibold text-muted-foreground/50 uppercase tracking-wider">Commands</span>
                  </div>
                  {filteredCommands.map((cmd, i) => (
                    <button
                      key={cmd.id}
                      type="button"
                      onMouseEnter={() => setSlashHighlight(i)}
                      onClick={() => handleSlashSelect(cmd.id)}
                      className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                        i === safeHighlight ? "bg-primary/10" : "hover:bg-muted/40"
                      }`}
                    >
                      <cmd.Icon className="w-4 h-4 text-primary/70 flex-shrink-0" />
                      <span className="text-sm font-semibold text-foreground">/{cmd.label}</span>
                      <span className="text-sm text-muted-foreground flex-1">{cmd.description}</span>
                      <span className="text-muted-foreground/40 text-xs">...</span>
                    </button>
                  ))}
                </div>
              )}

              <textarea
                ref={textareaRef}
                rows={1}
                value={inputValue}
                onChange={handleInputChange}
                onKeyDown={handleTextareaKeyDown}
                placeholder="Describe a task for the hive..."
                className="w-full bg-transparent px-5 py-4 pr-12 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none rounded-xl resize-none overflow-y-auto"
              />
              <div className="absolute right-3 bottom-2.5">
                <button
                  type="submit"
                  disabled={!inputValue.trim()}
                  className="w-7 h-7 rounded-lg bg-primary/90 hover:bg-primary text-primary-foreground flex items-center justify-center transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <Send className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </form>

          {/* Action buttons */}
          <div className="flex items-center justify-center gap-3 mb-6">
            <button
              onClick={() => setShowAgents(!showAgents)}
              className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-lg border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/30 hover:bg-primary/[0.03] transition-all"
            >
              <Hexagon className="w-4 h-4 text-primary/60" />
              <span>Try a sample agent</span>
              <ArrowRight className={`w-3.5 h-3.5 transition-transform duration-200 ${showAgents ? "rotate-90" : ""}`} />
            </button>
            <button
              onClick={() => navigate("/my-agents")}
              className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-lg border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/30 hover:bg-primary/[0.03] transition-all"
            >
              <Bot className="w-4 h-4 text-primary/60" />
              <span>My Agents</span>
            </button>
          </div>

          {/* Prompt hint pills */}
          <div className="flex flex-wrap justify-center gap-2 mb-6">
            {promptHints.map((hint) => (
              <button
                key={hint}
                onClick={() => handlePromptHint(hint)}
                className="text-xs text-muted-foreground hover:text-foreground border border-border/50 hover:border-primary/30 rounded-full px-3.5 py-1.5 transition-all hover:bg-primary/[0.03]"
              >
                {hint}
              </button>
            ))}
          </div>

          {/* Agent cards — revealed on toggle */}
          {showAgents && (
            <div className="animate-in fade-in slide-in-from-bottom-2 duration-300">
              {loading && (
                <div className="text-center py-8 text-sm text-muted-foreground">Loading agents...</div>
              )}
              {error && (
                <div className="text-center py-8 text-sm text-destructive">{error}</div>
              )}
              {!loading && !error && agents.length === 0 && (
                <div className="text-center py-8 text-sm text-muted-foreground">No sample agents found.</div>
              )}
              {!loading && !error && agents.length > 0 && (
                <div className="grid grid-cols-3 gap-3">
                  {agents.map((agent) => {
                    const slug = agentSlug(agent.path);
                    const Icon = AGENT_ICONS[slug] || Hexagon;
                    const color = AGENT_COLORS[slug] || "hsl(45,95%,58%)";
                    return (
                      <button
                        key={agent.path}
                        onClick={() => handleSelect(agent.path)}
                        className="text-left rounded-xl border border-border/60 p-4 transition-all duration-200 hover:border-primary/30 hover:bg-primary/[0.03] group relative overflow-hidden h-full flex flex-col"
                      >
                        <div className="flex flex-col flex-1">
                          <div className="flex items-center gap-3 mb-2.5">
                            <div
                              className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                              style={{
                                backgroundColor: `${color}15`,
                                border: `1.5px solid ${color}30`,
                              }}
                            >
                              <Icon className="w-4 h-4" style={{ color }} />
                            </div>
                            <h3 className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors">
                              {agent.name}
                            </h3>
                          </div>
                          <p className="text-xs text-muted-foreground leading-relaxed mb-3 line-clamp-2">
                            {agent.description}
                          </p>
                          <div className="flex gap-1.5 flex-wrap mt-auto">
                            {agent.tags.length > 0 ? (
                              agent.tags.map((tag) => (
                                <span
                                  key={tag}
                                  className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground"
                                >
                                  {tag}
                                </span>
                              ))
                            ) : (
                              <>
                                {agent.node_count > 0 && (
                                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground">
                                    {agent.node_count} nodes
                                  </span>
                                )}
                                {agent.tool_count > 0 && (
                                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground">
                                    {agent.tool_count} tools
                                  </span>
                                )}
                              </>
                            )}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Session picker modal */}
      {sessionModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/70 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) setSessionModalOpen(false); }}
        >
          <div className="w-full max-w-[600px] bg-card border border-border/60 rounded-2xl shadow-2xl flex flex-col overflow-hidden max-h-[70vh]">
            {/* Search header */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-border/40">
              <Search className="w-4 h-4 text-muted-foreground/50 flex-shrink-0" />
              <input
                ref={searchInputRef}
                value={sessionSearch}
                onChange={(e) => { setSessionSearch(e.target.value); setSessionHighlight(0); }}
                placeholder="Search sessions..."
                className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none"
              />
              {sessionSearch && (
                <button
                  type="button"
                  onClick={() => { setSessionSearch(""); setSessionHighlight(0); }}
                  className="p-1 rounded-md text-muted-foreground/50 hover:text-foreground hover:bg-muted/40 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
              <button
                type="button"
                onClick={() => setSessionModalOpen(false)}
                className="p-1 rounded-md text-muted-foreground/50 hover:text-foreground hover:bg-muted/40 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto">
              {sessionsLoading && (
                <div className="py-12 text-center text-sm text-muted-foreground">Loading sessions...</div>
              )}
              {!sessionsLoading && sessions.length === 0 && (
                <div className="py-12 text-center text-sm text-muted-foreground">No previous sessions found.</div>
              )}
              {!sessionsLoading && sessions.length > 0 && sessionGroups.length === 0 && (
                <div className="py-12 text-center text-sm text-muted-foreground">No sessions match your search.</div>
              )}
              {!sessionsLoading && (() => {
                let flatIdx = 0;
                return sessionGroups.map(({ label: gLabel, items }) => (
                  <div key={gLabel}>
                    <p className="px-4 pt-4 pb-1.5 text-[10px] font-semibold text-muted-foreground/50 uppercase tracking-wider">
                      {gLabel}
                    </p>
                    {items.map((s, i) => {
                      const idx = flatIdx++;
                      return (
                      <button
                        key={s.session_id}
                        type="button"
                        data-session-idx={idx}
                        onClick={() => handleSessionSelect(s)}
                        onMouseEnter={() => setSessionHighlight(idx)}
                        className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${idx === sessionHighlight ? "bg-primary/10" : "hover:bg-muted/40"}`}
                      >
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 bg-primary/10 border border-primary/20">
                          <Bot className="w-4 h-4 text-primary/70" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-foreground truncate">{defaultLabel(s, i)}</div>
                          {s.last_message && (
                            <div className="text-xs text-muted-foreground/60 truncate mt-0.5">{s.last_message}</div>
                          )}
                        </div>
                        <div className="flex items-center gap-1 text-xs text-muted-foreground/40 flex-shrink-0">
                          <Clock className="w-3 h-3" />
                          <span>{formatDateTime(s.created_at, s.session_id)}</span>
                        </div>
                      </button>
                      );
                    })}
                  </div>
                ));
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
