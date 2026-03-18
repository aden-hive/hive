import { useState, useEffect } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/hooks/useAuth";

export interface DashboardStat {
  label: string;
  value: string;
  trend: string;
  trendUp: boolean | null;
}

export interface RecentSession {
  id: string;
  title: string;
  status: string;
  created_at: string;
  message_count: number;
  token_estimate: number;
}

export function useDashboardStats() {
  const { user } = useAuth();
  const [stats, setStats] = useState<DashboardStat[]>([]);
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) return;
    (async () => {
      // Fetch sessions
      const { data: sessions } = await supabase
        .from("chat_sessions")
        .select("id, title, status, created_at, message_count, token_estimate")
        .order("created_at", { ascending: false })
        .limit(50);

      const all = sessions || [];
      const totalSessions = all.length;
      const totalMessages = all.reduce((s, r) => s + (r.message_count || 0), 0);
      const totalTokens = all.reduce((s, r) => s + (r.token_estimate || 0), 0);
      const completedCount = all.filter((s) => s.status === "completed").length;
      const successRate = totalSessions > 0 ? ((completedCount / totalSessions) * 100).toFixed(1) : "0";

      setStats([
        { label: "Total Sessions", value: String(totalSessions), trend: "Live", trendUp: null },
        { label: "Messages Sent", value: totalMessages.toLocaleString(), trend: "All time", trendUp: null },
        { label: "Success Rate", value: `${successRate}%`, trend: `${completedCount} completed`, trendUp: completedCount > 0 ? true : null },
        { label: "Tokens Used", value: totalTokens.toLocaleString(), trend: "Estimated", trendUp: null },
      ]);

      setRecentSessions(all.slice(0, 10) as RecentSession[]);
      setLoading(false);
    })();
  }, [user]);

  return { stats, recentSessions, loading };
}
