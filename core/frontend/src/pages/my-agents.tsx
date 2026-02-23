import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Crown, Bot, Activity, Moon, Plus } from "lucide-react";
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

  useEffect(() => {
    agentsApi
      .discover()
      .then((result) => {
        setAgents(result["Your Agents"] || []);
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

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Top bar */}
      <div className="h-12 flex items-center px-6 border-b border-border/40 flex-shrink-0">
        <button onClick={() => navigate("/")} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <Crown className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold text-primary">Hive</span>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 p-6 md:p-10 max-w-5xl mx-auto w-full">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-xl font-semibold text-foreground">My Agents</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {activeCount} active · {idleCount} idle
            </p>
          </div>
          <button
            onClick={() => navigate("/workspace?agent=new-agent")}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Agent
          </button>
        </div>

        {loading && (
          <div className="text-center py-16 text-sm text-muted-foreground">Loading agents...</div>
        )}
        {error && (
          <div className="text-center py-16 text-sm text-destructive">{error}</div>
        )}
        {!loading && !error && agents.length === 0 && (
          <div className="text-center py-16 text-sm text-muted-foreground">No agents found in exports/</div>
        )}

        {!loading && !error && agents.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {agents.map((agent) => (
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
                <p className="text-xs text-muted-foreground leading-relaxed mb-4 line-clamp-2">
                  {agent.description}
                </p>

                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <div className="flex items-center gap-1">
                    <Activity className="w-3 h-3" />
                    <span>
                      {agent.session_count} session{agent.session_count !== 1 ? "s" : ""}
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
