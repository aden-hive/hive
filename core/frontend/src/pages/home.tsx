import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Crown, Mail, Briefcase, Shield, Search, Newspaper, ArrowRight, Hexagon, Send, Bot } from "lucide-react";
import TopBar from "@/components/TopBar";
import type { LucideIcon } from "lucide-react";
import { agentsApi } from "@/api/agents";
import type { DiscoverEntry } from "@/api/types";

// --- Icon and color maps (backend can't serve icons) ---

const AGENT_ICONS: Record<string, LucideIcon> = {
  email_inbox_management: Mail,
  job_hunter: Briefcase,
  vulnerability_assessment: Shield,
  deep_research_agent: Search,
  tech_news_reporter: Newspaper,
};

const AGENT_COLORS: Record<string, string> = {
  email_inbox_management: "hsl(38,80%,55%)",
  job_hunter: "hsl(30,85%,58%)",
  vulnerability_assessment: "hsl(15,70%,52%)",
  deep_research_agent: "hsl(210,70%,55%)",
  tech_news_reporter: "hsl(270,60%,55%)",
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

export default function Home() {
  const navigate = useNavigate();
  const [inputValue, setInputValue] = useState("");
  const textareaRef = useRef<HTMLInputElement>(null);
  const [showAgents, setShowAgents] = useState(false);
  const [agents, setAgents] = useState<DiscoverEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
              <input
                ref={textareaRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder="Describe a task for the hive..."
                className="w-full bg-transparent px-5 py-4 pr-12 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none rounded-xl"
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
    </div>
  );
}
