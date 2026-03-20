import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Activity, Moon, Plus, Layers, Cpu, Hexagon, ArrowLeft } from "lucide-react";
import TopBar from "@/components/TopBar";
import { agentsApi } from "@/api/agents";
import type { DiscoverEntry } from "@/api/types";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "Just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours !== 1 ? "s" : ""} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days !== 1 ? "s" : ""} ago`;
}

export default function MyAgents() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<DiscoverEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "active" | "idle">("all");

  useEffect(() => {
    agentsApi
      .discover()
      .then((result) => {
        const entries = result["Your Agents"] || [];
        entries.sort((a, b) => {
          if (!a.last_active && !b.last_active) return 0;
          if (!a.last_active) return 1;
          if (!b.last_active) return -1;
          return b.last_active.localeCompare(a.last_active);
        });
        setAgents(entries);
      })
      .catch((err) => {
        setError(err.message || "Failed to load agents");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const activeCount = agents.filter((a) => a.is_loaded).length;
  const idleCount = agents.length - activeCount;
  const totalRuns = agents.reduce((sum, a) => sum + a.run_count, 0);
  const totalNodes = agents.reduce((sum, a) => sum + a.node_count, 0);
  const totalTools = agents.reduce((sum, a) => sum + a.tool_count, 0);

  const filtered = agents.filter((a) => {
    if (filter === "active") return a.is_loaded;
    if (filter === "idle") return !a.is_loaded;
    return true;
  });

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <TopBar />

      <div className="flex-1 p-6 md:p-10 max-w-6xl mx-auto w-full overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate("/dashboard")}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              title="Back to Dashboard"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
            <div>
              <h1 className="text-xl font-semibold text-foreground">My Agents</h1>
              <p className="text-sm text-muted-foreground mt-0.5">
                {agents.length} agents · {activeCount} active · {idleCount} idle
              </p>
            </div>
          </div>
          <button
            onClick={() => navigate("/workspace?agent=new-agent")}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Agent
          </button>
        </div>

        {/* Summary Stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          <StatPill icon={Hexagon} label="Total Agents" value={agents.length} color="hsl(210,70%,55%)" />
          <StatPill icon={Activity} label="Active" value={activeCount} color="hsl(45,95%,58%)" />
          <StatPill icon={Cpu} label="Total Runs" value={totalRuns} color="hsl(145,60%,42%)" />
          <StatPill icon={Layers} label="Total Nodes" value={totalNodes} color="hsl(270,60%,55%)" />
          <StatPill icon={Bot} label="Total Tools" value={totalTools} color="hsl(38,80%,55%)" />
        </div>

        {/* Filter Tabs */}
        <div className="flex items-center gap-1 mb-5">
          {(["all", "active", "idle"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filter === f
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
              }`}
            >
              {f === "all" ? `All (${agents.length})` : f === "active" ? `Active (${activeCount})` : `Idle (${idleCount})`}
            </button>
          ))}
        </div>

        {loading && (
          <div className="text-center py-16 text-sm text-muted-foreground">Loading agents...</div>
        )}
        {error && (
          <div className="text-center py-16 text-sm text-destructive">{error}</div>
        )}
        {!loading && !error && filtered.length === 0 && (
          <div className="text-center py-16 text-sm text-muted-foreground">
            {filter === "all" ? "No agents found in exports/" : `No ${filter} agents.`}
          </div>
        )}

        {!loading && !error && filtered.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((agent) => (
              <button
                key={agent.path}
                onClick={() => navigate(`/workspace?agent=${encodeURIComponent(agent.path)}`)}
                className="group text-left rounded-xl border border-border/60 bg-card/50 p-5 hover:border-primary/40 hover:bg-card transition-all duration-200"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="p-2 rounded-lg bg-muted/60">
                    <Bot className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
                  </div>
                  <div className="flex items-center gap-1.5">
                    {agent.is_loaded ? (
                      <>
                        <span className="relative flex h-2 w-2">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-50" />
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
                        </span>
                        <span className="text-xs font-medium text-primary">Active</span>
                      </>
                    ) : (
                      <>
                        <Moon className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">Idle</span>
                      </>
                    )}
                  </div>
                </div>

                <h3 className="text-sm font-semibold text-foreground mb-1 group-hover:text-primary transition-colors">
                  {agent.name}
                </h3>
                <p className="text-xs text-muted-foreground leading-relaxed mb-3 line-clamp-2">
                  {agent.description}
                </p>

                {/* Stats row */}
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground">
                    {agent.node_count} nodes
                  </span>
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground">
                    {agent.tool_count} tools
                  </span>
                  {agent.session_count > 0 && (
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground">
                      {agent.session_count} sessions
                    </span>
                  )}
                </div>

                {/* Tags */}
                {agent.tags.length > 0 && (
                  <div className="flex gap-1.5 flex-wrap mb-3">
                    {agent.tags.map((tag) => (
                      <span
                        key={tag}
                        className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary/70"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}

                <div className="flex items-center justify-between text-xs text-muted-foreground pt-2 border-t border-border/30">
                  <div className="flex items-center gap-1">
                    <Activity className="w-3 h-3" />
                    <span>
                      {agent.run_count} run{agent.run_count !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <span>{agent.last_active ? timeAgo(agent.last_active) : "Never run"}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatPill({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: typeof Activity;
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-card/50 p-3 flex items-center gap-3">
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ backgroundColor: `${color}15` }}
      >
        <Icon className="w-4 h-4" style={{ color }} />
      </div>
      <div>
        <p className="text-lg font-bold text-foreground">{value}</p>
        <p className="text-[10px] text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}
