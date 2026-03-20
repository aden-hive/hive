import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Crown,
  Activity,
  Bot,
  Zap,
  CheckCircle2,
  AlertTriangle,
  Hexagon,
  Cpu,
  ArrowRight,
  RefreshCw,
  Layers,
  Timer,
  Webhook,
  BarChart3,
  TrendingUp,
  Moon,
} from "lucide-react";
import TopBar from "@/components/TopBar";
import { sessionsApi } from "@/api/sessions";
import { agentsApi } from "@/api/agents";
import { logsApi } from "@/api/logs";
import { dashboardApi, type HealthStatus, type SessionStats } from "@/api/dashboard";
import type { LiveSession, LiveSessionDetail, DiscoverEntry, EntryPoint, LogEntry } from "@/api/types";

// ── Helpers ──────────────────────────────────────────────────────────────

function timeAgo(iso: string | number): string {
  const ts = typeof iso === "number" ? iso * 1000 : new Date(iso).getTime();
  const diff = Date.now() - ts;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "Just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatAgentName(path: string): string {
  const slug = path.replace(/\/$/, "").split("/").pop() || path;
  return slug
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function phaseColor(phase?: string): string {
  switch (phase) {
    case "running":
      return "hsl(45,95%,58%)";
    case "building":
      return "hsl(210,70%,55%)";
    case "staging":
      return "hsl(270,60%,55%)";
    case "planning":
      return "hsl(190,70%,45%)";
    default:
      return "hsl(0,0%,45%)";
  }
}

// ── Types ────────────────────────────────────────────────────────────────

interface SessionWithStats extends LiveSession {
  stats?: SessionStats;
  detail?: LiveSessionDetail;
}

interface ActivityEvent {
  id: string;
  type: "session_created" | "execution" | "trigger" | "phase_change";
  label: string;
  detail: string;
  timestamp: number;
  color: string;
  icon: typeof Activity;
}

// ── Main Dashboard ──────────────────────────────────────────────────────

export default function Dashboard() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sessions, setSessions] = useState<SessionWithStats[]>([]);
  const [agents, setAgents] = useState<DiscoverEntry[]>([]);
  const [allAgents, setAllAgents] = useState<DiscoverEntry[]>([]);
  const [recentLogs, setRecentLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(Date.now());
  const [refreshing, setRefreshing] = useState(false);
  const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [healthRes, sessionsRes, discoverRes] = await Promise.all([
        dashboardApi.health().catch(() => null),
        sessionsApi.list().catch(() => ({ sessions: [] })),
        agentsApi.discover().catch(() => ({} as Record<string, DiscoverEntry[]>)),
      ]);

      if (healthRes) setHealth(healthRes);

      const yourAgents = discoverRes["Your Agents"] || [];
      const examples = discoverRes["Examples"] || [];
      setAgents(yourAgents);
      setAllAgents([...yourAgents, ...examples]);

      // Fetch stats + detail for each active session in parallel
      const enriched = await Promise.all(
        sessionsRes.sessions.map(async (s) => {
          const [stats, detail] = await Promise.all([
            dashboardApi.sessionStats(s.session_id).catch(() => undefined),
            sessionsApi.get(s.session_id).catch(() => undefined),
          ]);
          return { ...s, stats, detail } as SessionWithStats;
        }),
      );
      setSessions(enriched);

      // Fetch recent logs from first few sessions
      const logSessions = enriched.slice(0, 5);
      const logResults = await Promise.all(
        logSessions.map((s) =>
          logsApi.list(s.session_id, 5).catch(() => ({ logs: [] })),
        ),
      );
      const allLogs = logResults.flatMap((r) => r.logs);
      setRecentLogs(allLogs);

      setLastRefresh(Date.now());
    } catch {
      // Silently handle errors for dashboard resilience
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    // Auto-refresh every 15 seconds
    autoRefreshRef.current = setInterval(fetchAll, 15000);
    return () => {
      if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
    };
  }, [fetchAll]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchAll();
  };

  // ── Derived metrics ──

  const activeSessions = sessions.length;
  const activeAgents = agents.filter((a) => a.is_loaded).length;
  const totalAgents = agents.length;
  const totalRuns = agents.reduce((sum, a) => sum + a.run_count, 0);
  const totalTokensIn = sessions.reduce(
    (sum, s) => sum + (s.stats?.total_input_tokens || 0),
    0,
  );
  const totalTokensOut = sessions.reduce(
    (sum, s) => sum + (s.stats?.total_output_tokens || 0),
    0,
  );
  const totalToolCalls = sessions.reduce(
    (sum, s) => sum + (s.stats?.total_tool_calls || 0),
    0,
  );
  const totalLlmCalls = sessions.reduce(
    (sum, s) => sum + (s.stats?.total_llm_calls || 0),
    0,
  );
  const runningSessions = sessions.filter(
    (s) => s.queen_phase === "running",
  ).length;
  const buildingSessions = sessions.filter(
    (s) => s.queen_phase === "building" || s.queen_phase === "staging",
  ).length;
  const planningSessions = sessions.filter(
    (s) => s.queen_phase === "planning",
  ).length;

  // Triggers
  const allTriggers: Array<{ session: SessionWithStats; trigger: EntryPoint }> = [];
  for (const s of sessions) {
    if (s.detail?.entry_points) {
      for (const ep of s.detail.entry_points) {
        allTriggers.push({ session: s, trigger: ep });
      }
    }
  }

  // Activity events from logs
  const activityEvents: ActivityEvent[] = recentLogs
    .filter((log) => log.started_at || log.run_id)
    .map((log, i) => ({
      id: `log-${i}`,
      type: "execution" as const,
      label: String(log.agent_id || "Execution"),
      detail: `${log.status === "success" ? "Completed" : log.status === "failure" ? "Failed" : String(log.status || "Unknown")} · ${log.total_nodes_executed || 0} nodes · ${formatTokens(((log.total_input_tokens as number) || 0) + ((log.total_output_tokens as number) || 0))} tokens`,
      timestamp: log.started_at ? new Date(log.started_at as string).getTime() : Date.now(),
      color: log.status === "success" ? "hsl(145,60%,42%)" : log.status === "failure" ? "hsl(0,65%,55%)" : "hsl(45,95%,58%)",
      icon: log.status === "success" ? CheckCircle2 : log.status === "failure" ? AlertTriangle : Activity,
    }))
    .sort((a, b) => b.timestamp - a.timestamp)
    .slice(0, 15);

  if (loading) {
    return (
      <div className="h-screen bg-background flex flex-col">
        <TopBar />
        <div className="flex-1 flex items-center justify-center">
          <div className="flex items-center gap-3 text-muted-foreground">
            <RefreshCw className="w-5 h-5 animate-spin" />
            <span className="text-sm">Loading dashboard...</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <TopBar />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-7xl mx-auto p-6 space-y-6">
          {/* ── Header ─────────────────────────────────────── */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center"
                style={{
                  backgroundColor: "hsl(45,95%,58%,0.1)",
                  border: "1.5px solid hsl(45,95%,58%,0.25)",
                }}
              >
                <Crown className="w-5 h-5 text-primary" />
              </div>
              <div>
                <h1 className="text-lg font-semibold text-foreground">Hive Command Center</h1>
                <p className="text-xs text-muted-foreground">
                  Real-time monitoring & control
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground">
                Updated {timeAgo(lastRefresh)}
              </span>
              <button
                onClick={handleRefresh}
                disabled={refreshing}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border/60 text-xs text-muted-foreground hover:text-foreground hover:border-primary/30 transition-all disabled:opacity-50"
              >
                <RefreshCw
                  className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`}
                />
                Refresh
              </button>
            </div>
          </div>

          {/* ── KPI Cards ──────────────────────────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            <KpiCard
              label="Active Sessions"
              value={activeSessions}
              icon={Zap}
              color="hsl(45,95%,58%)"
              subtitle={`${runningSessions} running`}
            />
            <KpiCard
              label="Agents"
              value={totalAgents}
              icon={Bot}
              color="hsl(210,70%,55%)"
              subtitle={`${activeAgents} active · ${allAgents.length} total`}
            />
            <KpiCard
              label="Total Runs"
              value={totalRuns}
              icon={Activity}
              color="hsl(145,60%,42%)"
            />
            <KpiCard
              label="Tokens Used"
              value={formatTokens(totalTokensIn + totalTokensOut)}
              icon={Cpu}
              color="hsl(270,60%,55%)"
              subtitle={`${formatTokens(totalTokensIn)} in · ${formatTokens(totalTokensOut)} out`}
            />
            <KpiCard
              label="LLM Calls"
              value={totalLlmCalls}
              icon={BarChart3}
              color="hsl(190,70%,45%)"
            />
            <KpiCard
              label="Tool Calls"
              value={totalToolCalls}
              icon={Layers}
              color="hsl(38,80%,55%)"
            />
          </div>

          {/* ── Phase Distribution Bar ─────────────────────── */}
          {activeSessions > 0 && (
            <div className="rounded-xl border border-border/60 bg-card/50 p-4">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-foreground">Session Phase Distribution</h2>
                <span className="text-xs text-muted-foreground">{activeSessions} total sessions</span>
              </div>
              <div className="flex h-3 rounded-full overflow-hidden bg-muted/40 gap-px">
                {runningSessions > 0 && (
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${(runningSessions / activeSessions) * 100}%`,
                      backgroundColor: phaseColor("running"),
                    }}
                    title={`${runningSessions} running`}
                  />
                )}
                {buildingSessions > 0 && (
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${(buildingSessions / activeSessions) * 100}%`,
                      backgroundColor: phaseColor("building"),
                    }}
                    title={`${buildingSessions} building/staging`}
                  />
                )}
                {planningSessions > 0 && (
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${(planningSessions / activeSessions) * 100}%`,
                      backgroundColor: phaseColor("planning"),
                    }}
                    title={`${planningSessions} planning`}
                  />
                )}
              </div>
              <div className="flex items-center gap-4 mt-2">
                <PhaseLabel color={phaseColor("running")} label="Running" count={runningSessions} />
                <PhaseLabel color={phaseColor("building")} label="Building" count={buildingSessions} />
                <PhaseLabel color={phaseColor("planning")} label="Planning" count={planningSessions} />
              </div>
            </div>
          )}

          {/* ── Main Grid: Sessions + Activity ─────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Active Sessions — 2 cols */}
            <div className="lg:col-span-2 rounded-xl border border-border/60 bg-card/50 p-4">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <Zap className="w-4 h-4 text-primary" />
                  Active Sessions
                </h2>
                <span className="text-xs text-muted-foreground">{activeSessions} live</span>
              </div>
              {sessions.length === 0 ? (
                <div className="text-center py-12 text-sm text-muted-foreground">
                  No active sessions. Start an agent from the{" "}
                  <button
                    onClick={() => navigate("/")}
                    className="text-primary hover:underline"
                  >
                    home page
                  </button>.
                </div>
              ) : (
                <div className="space-y-2">
                  {sessions.map((s) => (
                    <SessionCard
                      key={s.session_id}
                      session={s}
                      onClick={() =>
                        navigate(
                          `/workspace?agent=${encodeURIComponent(s.agent_path)}`,
                        )
                      }
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Activity Feed — 1 col */}
            <div className="rounded-xl border border-border/60 bg-card/50 p-4">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2 mb-4">
                <TrendingUp className="w-4 h-4 text-primary" />
                Recent Activity
              </h2>
              {activityEvents.length === 0 ? (
                <div className="text-center py-12 text-sm text-muted-foreground">
                  No recent activity yet.
                </div>
              ) : (
                <div className="space-y-1">
                  {activityEvents.map((ev) => (
                    <div
                      key={ev.id}
                      className="flex items-start gap-2.5 p-2 rounded-lg hover:bg-muted/30 transition-colors"
                    >
                      <div
                        className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 mt-0.5"
                        style={{ backgroundColor: `${ev.color}20` }}
                      >
                        <ev.icon className="w-3 h-3" style={{ color: ev.color }} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium text-foreground truncate">
                          {ev.label}
                        </p>
                        <p className="text-[11px] text-muted-foreground truncate">
                          {ev.detail}
                        </p>
                      </div>
                      <span className="text-[10px] text-muted-foreground flex-shrink-0 mt-0.5">
                        {timeAgo(ev.timestamp)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ── Triggers Overview ──────────────────────────── */}
          {allTriggers.length > 0 && (
            <div className="rounded-xl border border-border/60 bg-card/50 p-4">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2 mb-4">
                <Timer className="w-4 h-4 text-primary" />
                Active Triggers & Automations
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {allTriggers.map(({ session, trigger }) => (
                  <TriggerCard
                    key={`${session.session_id}-${trigger.id}`}
                    session={session}
                    trigger={trigger}
                    onClick={() =>
                      navigate(
                        `/workspace?agent=${encodeURIComponent(session.agent_path)}`,
                      )
                    }
                  />
                ))}
              </div>
            </div>
          )}

          {/* ── Agents Overview ────────────────────────────── */}
          <div className="rounded-xl border border-border/60 bg-card/50 p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Hexagon className="w-4 h-4 text-primary" />
                Agents Overview
              </h2>
              <button
                onClick={() => navigate("/my-agents")}
                className="text-xs text-primary hover:underline flex items-center gap-1"
              >
                View all <ArrowRight className="w-3 h-3" />
              </button>
            </div>
            {agents.length === 0 ? (
              <div className="text-center py-8 text-sm text-muted-foreground">
                No agents configured yet.
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                {agents.slice(0, 8).map((agent) => (
                  <AgentMiniCard
                    key={agent.path}
                    agent={agent}
                    onClick={() =>
                      navigate(
                        `/workspace?agent=${encodeURIComponent(agent.path)}`,
                      )
                    }
                  />
                ))}
              </div>
            )}
          </div>

          {/* ── System Health ──────────────────────────────── */}
          <div className="rounded-xl border border-border/60 bg-card/50 p-4">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2 mb-4">
              <Activity className="w-4 h-4 text-primary" />
              System Health
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <HealthItem
                label="API Status"
                value={health ? "Online" : "Unknown"}
                color={health ? "hsl(145,60%,42%)" : "hsl(0,0%,45%)"}
              />
              <HealthItem
                label="Live Sessions"
                value={String(health?.session_count ?? 0)}
                color="hsl(45,95%,58%)"
              />
              <HealthItem
                label="Agents Deployed"
                value={String(totalAgents)}
                color="hsl(210,70%,55%)"
              />
              <HealthItem
                label="Active Workers"
                value={String(sessions.filter((s) => s.has_worker).length)}
                color="hsl(270,60%,55%)"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  icon: Icon,
  color,
  subtitle,
}: {
  label: string;
  value: string | number;
  icon: typeof Activity;
  color: string;
  subtitle?: string;
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-card/50 p-4 hover:border-primary/20 transition-colors">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-muted-foreground">{label}</span>
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: `${color}15` }}
        >
          <Icon className="w-3.5 h-3.5" style={{ color }} />
        </div>
      </div>
      <div className="text-xl font-bold text-foreground">{value}</div>
      {subtitle && (
        <p className="text-[11px] text-muted-foreground mt-0.5">{subtitle}</p>
      )}
    </div>
  );
}

function PhaseLabel({ color, label, count }: { color: string; label: string; count: number }) {
  if (count === 0) return null;
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
      <span className="text-xs text-muted-foreground">
        {label} ({count})
      </span>
    </div>
  );
}

function SessionCard({
  session,
  onClick,
}: {
  session: SessionWithStats;
  onClick: () => void;
}) {
  const phase = session.queen_phase || "idle";
  const color = phaseColor(phase);
  const tokensIn = session.stats?.total_input_tokens || 0;
  const tokensOut = session.stats?.total_output_tokens || 0;
  const tools = session.stats?.total_tool_calls || 0;

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-lg border border-border/40 bg-background/50 p-3 hover:border-primary/30 hover:bg-muted/20 transition-all group"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="relative flex-shrink-0">
            <Bot className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
            {phase === "running" && (
              <span className="absolute -top-0.5 -right-0.5 flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-50" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
              </span>
            )}
          </div>
          <span className="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
            {formatAgentName(session.agent_path)}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span
            className="text-[10px] font-medium px-2 py-0.5 rounded-full"
            style={{
              backgroundColor: `${color}20`,
              color,
            }}
          >
            {phase}
          </span>
          <span className="text-[10px] text-muted-foreground">
            {formatUptime(session.uptime_seconds)}
          </span>
        </div>
      </div>
      <p className="text-xs text-muted-foreground line-clamp-1 mb-2">
        {session.description || session.goal || "No description"}
      </p>
      <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
        <span>{session.node_count} nodes</span>
        <span className="text-border">·</span>
        <span>{formatTokens(tokensIn + tokensOut)} tokens</span>
        <span className="text-border">·</span>
        <span>{tools} tool calls</span>
        {session.has_worker && (
          <>
            <span className="text-border">·</span>
            <span className="text-primary/70">Worker active</span>
          </>
        )}
      </div>
    </button>
  );
}

function TriggerCard({
  session,
  trigger,
  onClick,
}: {
  session: SessionWithStats;
  trigger: EntryPoint;
  onClick: () => void;
}) {
  const isTimer = trigger.trigger_type === "timer";
  const Icon = isTimer ? Timer : Webhook;
  const color = isTimer ? "hsl(38,80%,55%)" : "hsl(210,70%,55%)";

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-lg border border-border/40 bg-background/50 p-3 hover:border-primary/30 transition-all"
    >
      <div className="flex items-center gap-2 mb-2">
        <div
          className="w-6 h-6 rounded-md flex items-center justify-center"
          style={{ backgroundColor: `${color}15` }}
        >
          <Icon className="w-3 h-3" style={{ color }} />
        </div>
        <span className="text-xs font-medium text-foreground truncate">
          {trigger.name}
        </span>
      </div>
      <p className="text-[11px] text-muted-foreground mb-1.5 truncate">
        {formatAgentName(session.agent_path)}
      </p>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">
          {trigger.trigger_type}
        </span>
        {trigger.next_fire_in != null && (
          <span className="text-[10px] text-primary/70">
            Next in {formatUptime(trigger.next_fire_in)}
          </span>
        )}
      </div>
    </button>
  );
}

function AgentMiniCard({
  agent,
  onClick,
}: {
  agent: DiscoverEntry;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-lg border border-border/40 bg-background/50 p-3 hover:border-primary/30 transition-all group"
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium text-foreground group-hover:text-primary transition-colors truncate">
          {agent.name}
        </span>
        {agent.is_loaded ? (
          <span className="relative flex h-2 w-2 flex-shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-50" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
          </span>
        ) : (
          <Moon className="w-3 h-3 text-muted-foreground/50 flex-shrink-0" />
        )}
      </div>
      <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
        <span>{agent.run_count} runs</span>
        <span className="text-border">·</span>
        <span>{agent.node_count} nodes</span>
        <span className="text-border">·</span>
        <span>{agent.tool_count} tools</span>
      </div>
    </button>
  );
}

function HealthItem({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <div
        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
        style={{ backgroundColor: color }}
      />
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm font-semibold text-foreground">{value}</p>
      </div>
    </div>
  );
}
