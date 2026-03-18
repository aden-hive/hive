import { MessageSquare, CheckCircle2, Clock, Zap, Loader2, TrendingUp, ArrowUpRight } from "lucide-react";
import { NexusCard } from "@/components/nexus/NexusCard";
import { MetricCard } from "@/components/nexus/MetricCard";
import { useDashboardStats } from "@/hooks/useDashboardStats";
import { DASHBOARD_STATS, RECENT_SESSIONS } from "@/data/mock-data";

const STAT_ICONS = [MessageSquare, CheckCircle2, Clock, Zap];

const STATUS_STYLES: Record<string, string> = {
  completed: "text-success",
  running: "text-primary",
  failed: "text-destructive",
};

const CHART_BARS = [35, 52, 48, 70, 65, 80, 74, 90, 85, 95, 88, 78];
const CHART_LABELS = ["Mar 6", "", "", "Mar 9", "", "", "Mar 12", "", "", "Mar 15", "", "Mar 18"];

export function DashboardPage() {
  const { stats, recentSessions, loading } = useDashboardStats();

  const hasRealData = !loading && recentSessions.length > 0;
  const displayStats = hasRealData ? stats : DASHBOARD_STATS;
  const displaySessions = hasRealData ? recentSessions : RECENT_SESSIONS.map(s => ({
    id: s.id,
    title: s.title,
    status: s.status,
    message_count: s.messageCount,
    token_estimate: s.tokens,
    created_at: s.date,
  }));

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-6xl mx-auto w-full">
      <header className="mb-8">
        <h1 className="text-xl font-bold text-foreground tracking-tight font-display">System Overview</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Monitor agent performance and usage across all sessions.
        </p>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {displayStats.map((stat, i) => (
          <MetricCard key={i} {...stat} icon={STAT_ICONS[i]} />
        ))}
      </div>

      {/* Activity chart */}
      <NexusCard className="mb-8">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-sm font-semibold text-foreground font-display">Session Activity</h3>
            <p className="text-[11px] text-muted-foreground mt-0.5">Last 12 days</p>
          </div>
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-success">
            <TrendingUp size={13} />
            <span>+18% vs previous period</span>
          </div>
        </div>
        <div className="flex items-end gap-1.5 h-[120px]">
          {CHART_BARS.map((h, i) => (
            <div key={i} className="flex-1 flex flex-col items-center gap-1">
              <div
                className="w-full bg-primary/15 hover:bg-primary/25 rounded-t transition-colors"
                style={{ height: `${h}%` }}
              />
              {CHART_LABELS[i] && (
                <span className="text-[8px] text-muted-foreground/50 tabular-nums whitespace-nowrap">{CHART_LABELS[i]}</span>
              )}
            </div>
          ))}
        </div>
      </NexusCard>

      <NexusCard noPadding className="overflow-hidden">
        <div className="px-5 py-4 border-b border-border flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground font-display">Recent Activity</h3>
          <span className="text-[11px] text-muted-foreground font-medium">{displaySessions.length} sessions</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/40 text-muted-foreground text-[10px] uppercase font-semibold tracking-wider">
              <tr>
                <th className="px-5 py-2.5">Session</th>
                <th className="px-5 py-2.5">Status</th>
                <th className="px-5 py-2.5">Messages</th>
                <th className="px-5 py-2.5">Tokens</th>
                <th className="px-5 py-2.5">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {displaySessions.map((session) => (
                <tr key={session.id} className="hover:bg-muted/20 transition-colors">
                  <td className="px-5 py-3.5 font-medium text-foreground text-[13px] truncate max-w-[220px]">{session.title}</td>
                  <td className="px-5 py-3.5">
                    <span className={`flex items-center gap-1.5 font-medium text-[11px] capitalize ${STATUS_STYLES[session.status] || "text-muted-foreground"}`}>
                      <CheckCircle2 size={12} />
                      {session.status}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-muted-foreground tabular-nums text-[13px]">{session.message_count}</td>
                  <td className="px-5 py-3.5 text-muted-foreground tabular-nums text-[13px]">{session.token_estimate.toLocaleString()}</td>
                  <td className="px-5 py-3.5 text-muted-foreground text-[11px]">{session.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </NexusCard>
    </div>
  );
}
