import { useState, useEffect } from "react";
import { Search, CheckCircle2, CircleDashed, XCircle, MessageSquare, Filter, Loader2, Trash2, Wrench, ChevronDown } from "lucide-react";
import { NexusCard } from "@/components/nexus/NexusCard";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/hooks/useAuth";
import { MOCK_LOG_ENTRIES } from "@/data/mock-data";
import { motion, AnimatePresence } from "framer-motion";

type SessionStatus = "completed" | "running" | "failed";

interface LogSession {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  token_estimate: number;
  tools?: string[];
}

const STATUS_FILTERS: { label: string; value: SessionStatus | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Running", value: "running" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
];

const STATUS_ICON: Record<string, typeof CheckCircle2> = {
  completed: CheckCircle2,
  running: CircleDashed,
  failed: XCircle,
};

const STATUS_COLOR: Record<string, string> = {
  completed: "text-success",
  running: "text-primary",
  failed: "text-destructive",
};

const STATUS_BG: Record<string, string> = {
  completed: "bg-success/10",
  running: "bg-primary/10",
  failed: "bg-destructive/10",
};

export function LogsPage() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<LogSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<SessionStatus | "all">("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    (async () => {
      const { data } = await supabase
        .from("chat_sessions")
        .select("id, title, status, created_at, updated_at, message_count, token_estimate")
        .order("updated_at", { ascending: false })
        .limit(50);
      if (data && data.length > 0) {
        setSessions(data as LogSession[]);
      } else {
        setSessions(MOCK_LOG_ENTRIES as LogSession[]);
      }
      setLoading(false);
    })();
  }, [user]);

  const handleDelete = async (id: string) => {
    await supabase.from("chat_messages").delete().eq("session_id", id);
    await supabase.from("chat_sessions").delete().eq("id", id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
  };

  const filtered = sessions.filter((s) => {
    const matchesSearch = s.title.toLowerCase().includes(search.toLowerCase());
    const matchesStatus = statusFilter === "all" || s.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-5xl mx-auto w-full">
      <header className="mb-8">
        <h1 className="text-xl font-bold text-foreground tracking-tight font-display">Sessions & Logs</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Review previous conversations and agent activity.
        </p>
      </header>

      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <div className="relative flex-1">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/50" />
          <input
            type="text"
            placeholder="Search sessions…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-background border border-border rounded-lg pl-9 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary/15 focus:border-primary/30 outline-none text-foreground placeholder:text-muted-foreground/50 transition-all"
          />
        </div>
        <div className="flex gap-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setStatusFilter(f.value)}
              className={`whitespace-nowrap px-3 py-2 rounded-lg text-[11px] font-semibold transition-colors ${
                statusFilter === f.value
                  ? "bg-foreground text-background"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="text-[11px] text-muted-foreground mb-3 font-medium">
        {filtered.length} session{filtered.length !== 1 ? "s" : ""} found
      </div>

      {filtered.length > 0 ? (
        <div className="space-y-2">
          {filtered.map((session) => {
            const StatusIcon = STATUS_ICON[session.status] || CircleDashed;
            const isExpanded = expandedId === session.id;
            const mockEntry = MOCK_LOG_ENTRIES.find(e => e.id === session.id);
            const tools = (session as any).tools || mockEntry?.tools || [];
            return (
              <NexusCard key={session.id} className="hover:shadow-elevated transition-shadow duration-200 !p-0">
                <div className="px-5 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1.5">
                        <h3 className="text-[13px] font-semibold text-foreground truncate">{session.title}</h3>
                        <span className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full capitalize ${STATUS_COLOR[session.status] || "text-muted-foreground"} ${STATUS_BG[session.status] || "bg-muted"}`}>
                          <StatusIcon size={10} />
                          {session.status}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-[11px] text-muted-foreground/60">
                        <span className="tabular-nums">{session.token_estimate.toLocaleString()} tokens</span>
                        <span className="flex items-center gap-1">
                          <MessageSquare size={10} /> {session.message_count} messages
                        </span>
                        {tools.length > 0 && (
                          <span className="flex items-center gap-1">
                            <Wrench size={10} /> {tools.length} tools
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[10px] text-muted-foreground/50 whitespace-nowrap">
                        {new Date(session.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      </span>
                      <button
                        onClick={() => setExpandedId(isExpanded ? null : session.id)}
                        className="p-1.5 text-muted-foreground/40 hover:text-foreground hover:bg-muted rounded-md transition-colors"
                      >
                        <ChevronDown size={13} className={`transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                      </button>
                      <button
                        onClick={() => handleDelete(session.id)}
                        className="p-1.5 text-muted-foreground/40 hover:text-destructive hover:bg-destructive/10 rounded-md transition-colors"
                        title="Delete session"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                </div>

                <AnimatePresence>
                  {isExpanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.15 }}
                      className="overflow-hidden"
                    >
                      <div className="px-5 pb-4 pt-0 border-t border-border/50">
                        <div className="pt-3 space-y-2">
                          {tools.length > 0 && (
                            <div>
                              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">Tools Used</p>
                              <div className="flex flex-wrap gap-1.5">
                                {tools.map((t: string) => (
                                  <span key={t} className="flex items-center gap-1 px-2 py-0.5 bg-muted rounded border border-border/50 text-[10px] font-mono text-muted-foreground">
                                    <Wrench size={9} /> {t}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          <div className="grid grid-cols-3 gap-3 pt-1">
                            <div>
                              <p className="text-[10px] text-muted-foreground/50">Created</p>
                              <p className="text-[11px] text-foreground font-medium tabular-nums">
                                {new Date(session.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                              </p>
                            </div>
                            <div>
                              <p className="text-[10px] text-muted-foreground/50">Messages</p>
                              <p className="text-[11px] text-foreground font-medium tabular-nums">{session.message_count}</p>
                            </div>
                            <div>
                              <p className="text-[10px] text-muted-foreground/50">Tokens</p>
                              <p className="text-[11px] text-foreground font-medium tabular-nums">{session.token_estimate.toLocaleString()}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </NexusCard>
            );
          })}
        </div>
      ) : (
        <NexusCard className="text-center py-16">
          <Filter size={28} className="mx-auto text-muted-foreground/30 mb-3" />
          <h3 className="text-sm font-semibold text-foreground mb-1 font-display">No sessions found</h3>
          <p className="text-xs text-muted-foreground">
            {search ? "Try adjusting your search query." : "No sessions match the selected filter."}
          </p>
        </NexusCard>
      )}
    </div>
  );
}
