/**
 * HistorySidebar — persistent ChatGPT-style session history sidebar.
 *
 * Shown on both the Home page and the Workspace.  Clicking a session fires
 * `onOpen(sessionId, agentPath)` so the caller decides what to do (navigate
 * to workspace on Home, open/switch tab on Workspace).
 *
 * Labels (user-visible names) are stored purely in localStorage — backend
 * session IDs are never touched.
 *
 * Session deduplication: the backend may have multiple session directories
 * for the same agent (cold restarts create new directories). We deduplicate
 * by agent_path and show only the most-recent session per agent so the
 * history list stays clean.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { ChevronLeft, ChevronRight, Clock, Bot, Loader2, MoreHorizontal, Pencil, Trash2, Check, X } from "lucide-react";
import { sessionsApi } from "@/api/sessions";

// ── Types ─────────────────────────────────────────────────────────────────────

export type HistorySession = {
  session_id: string;
  cold: boolean;
  live: boolean;
  has_messages: boolean;
  created_at: number;
  agent_name?: string | null;
  agent_path?: string | null;
  /** Snippet of the last assistant message — for sidebar preview. */
  last_message?: string | null;
  /** Total number of client-facing messages in this session. */
  message_count?: number;
};

const LABEL_STORE_KEY = "hive:history-labels";

function loadLabelStore(): Record<string, string> {
  try {
    const raw = localStorage.getItem(LABEL_STORE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function saveLabelStore(store: Record<string, string>) {
  try {
    localStorage.setItem(LABEL_STORE_KEY, JSON.stringify(store));
  } catch { }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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
  // Prefer timestamp embedded in session_id: session_YYYYMMDD_HHMMSS_xxx
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

/**
 * Deduplicate sessions by agent_path — keep only the most recent session
 * per agent. Sessions are already sorted newest-first by the backend.
 * Sessions without an agent_path (new-agent / queen-only) are kept individually.
 */
function deduplicateByAgent(sessions: HistorySession[]): HistorySession[] {
  const seen = new Set<string>();
  const result: HistorySession[] = [];
  for (const s of sessions) {
    // Group key: use agent_path when present, otherwise use session_id (unique)
    const key = s.agent_path ? s.agent_path.replace(/\/$/, "") : `__no_agent__${s.session_id}`;
    if (!seen.has(key)) {
      seen.add(key);
      result.push(s);
    }
    // Additional sessions for the same agent are silently skipped
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

// ── Row component ─────────────────────────────────────────────────────────────

interface RowProps {
  session: HistorySession;
  label: string;
  index: number;
  isActive: boolean;
  isLive: boolean;
  onOpen: () => void;
  onRename: (newLabel: string) => void;
  onDelete: () => void;
}

function HistoryRow({ session: s, label, isActive, isLive, onOpen, onRename, onDelete }: RowProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draftLabel, setDraftLabel] = useState(label);
  const menuRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  useEffect(() => {
    if (renaming) {
      setDraftLabel(label);
      requestAnimationFrame(() => inputRef.current?.select());
    }
  }, [renaming, label]);

  const commitRename = () => {
    const trimmed = draftLabel.trim();
    if (trimmed) onRename(trimmed);
    setRenaming(false);
  };

  const dateStr = formatDateTime(s.created_at, s.session_id);

  return (
    <div
      className={`group relative flex items-start gap-2 px-3 py-2 cursor-pointer transition-colors ${isActive
        ? "bg-primary/10 border-l-2 border-primary"
        : "border-l-2 border-transparent hover:bg-muted/40"
        }`}
      onClick={() => { if (!renaming) onOpen(); }}
    >
      <Bot className="w-3.5 h-3.5 flex-shrink-0 mt-[3px] text-muted-foreground/40 group-hover:text-muted-foreground/70 transition-colors" />

      <div className="min-w-0 flex-1">
        {renaming ? (
          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <input
              ref={inputRef}
              value={draftLabel}
              onChange={(e) => setDraftLabel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitRename();
                if (e.key === "Escape") setRenaming(false);
              }}
              className="flex-1 min-w-0 text-[11px] bg-muted/60 border border-border/50 rounded px-1.5 py-0.5 text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
            />
            <button onClick={commitRename} className="p-0.5 text-primary hover:text-primary/80">
              <Check className="w-3 h-3" />
            </button>
            <button onClick={() => setRenaming(false)} className="p-0.5 text-muted-foreground hover:text-foreground">
              <X className="w-3 h-3" />
            </button>
          </div>
        ) : (
          <>
            <div className={`text-[11px] font-medium truncate leading-tight ${isActive ? "text-foreground" : "text-foreground/80"}`}>
              {label}
            </div>
            {/* Message preview — most recent assistant message */}
            {s.last_message && (
              <div className="text-[10px] text-muted-foreground/50 mt-0.5 leading-tight line-clamp-2 break-words">
                {s.last_message}
              </div>
            )}
            <div className="flex items-center gap-1.5 mt-0.5">
              <div className="text-[10px] text-muted-foreground/40">{dateStr}</div>
              {(s.message_count ?? 0) > 0 && (
                <span className="text-[9px] text-muted-foreground/30">· {s.message_count} msgs</span>
              )}
            </div>
            {isLive && (
              <span className="text-[9px] text-emerald-500/80 font-semibold uppercase tracking-wide">live</span>
            )}
          </>
        )}
      </div>

      {/* 3-dot button — visible on row hover */}
      {!renaming && (
        <div className="relative flex-shrink-0" ref={menuRef} onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => setMenuOpen((o) => !o)}
            className={`p-0.5 rounded transition-colors text-muted-foreground/40 hover:text-foreground hover:bg-muted/60 ${menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100"
              }`}
            title="More options"
          >
            <MoreHorizontal className="w-3.5 h-3.5" />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-5 z-50 w-36 rounded-lg border border-border/60 bg-card shadow-xl shadow-black/30 overflow-hidden py-1">
              <button
                onClick={() => { setMenuOpen(false); setRenaming(true); }}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted/60 transition-colors"
              >
                <Pencil className="w-3 h-3 text-muted-foreground" />
                Rename
              </button>
              <button
                onClick={() => { setMenuOpen(false); onDelete(); }}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-destructive hover:bg-destructive/10 transition-colors"
              >
                <Trash2 className="w-3 h-3" />
                Delete
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main sidebar component ────────────────────────────────────────────────────

interface HistorySidebarProps {
  /** Called when a history session is clicked. */
  onOpen: (sessionId: string, agentPath?: string | null, agentName?: string | null) => void;
  /** session_ids of tabs already open (for highlighting). */
  openSessionIds?: string[];
  /** session_id of the currently active/viewed session (live backend ID). */
  activeSessionId?: string | null;
  /** historySourceId of the active session — the original cold session ID before revive,
   * stays stable even after the backend creates a new live session on cold-restore. */
  activeHistorySourceId?: string | null;
  /** Increment this to force a refresh of the session list. */
  refreshKey?: number;
}

export default function HistorySidebar({ onOpen, openSessionIds = [], activeSessionId, activeHistorySourceId, refreshKey }: HistorySidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  // Raw sessions from the backend (may contain duplicates per agent)
  const [rawSessions, setRawSessions] = useState<HistorySession[]>([]);
  const [loading, setLoading] = useState(false);
  const [labels, setLabels] = useState<Record<string, string>>(loadLabelStore);

  const refresh = useCallback(() => {
    setLoading(true);
    sessionsApi
      .history()
      .then((r) => setRawSessions(r.sessions))
      .catch(() => { })
      .finally(() => setLoading(false));
  }, []);

  // Refresh on mount and whenever the parent forces a refresh
  useEffect(() => {
    refresh();
  }, [refresh, refreshKey]);

  // Refresh when the browser tab regains visibility
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [refresh]);

  const handleRename = (sessionId: string, newLabel: string) => {
    const next = { ...labels, [sessionId]: newLabel };
    setLabels(next);
    saveLabelStore(next);
  };

  const handleDelete = (sessionId: string) => {
    // Optimistically remove from in-memory list immediately
    setRawSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    const next = { ...labels };
    delete next[sessionId];
    setLabels(next);
    saveLabelStore(next);

    // Permanently delete session files from disk (fire-and-forget)
    sessionsApi.deleteHistory(sessionId).catch(() => {
      // Soft failure — the entry is already removed from the UI.
      // The file may linger on disk, but won't appear in the next refresh
      // because it's been removed from rawSessions.
    });
  };

  // ── Deduplicate & render ────────────────────────────────────────────────────

  // Deduplicate: show only the most-recent session per agent_path.
  // rawSessions is already sorted newest-first by the backend.
  const sessions = deduplicateByAgent(rawSessions);
  const groups = groupByDate(sessions);

  return (
    <div
      className={`flex-shrink-0 flex flex-col bg-card/20 border-r border-border/30 transition-[width] duration-200 overflow-hidden ${collapsed ? "w-[44px]" : "w-[220px]"
        }`}
    >
      {/* Header */}
      <div
        className={`flex items-center border-b border-border/20 flex-shrink-0 h-10 ${collapsed ? "justify-center" : "px-3 gap-2"
          }`}
      >
        {!collapsed && (
          <span className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider flex-1">
            History
          </span>
        )}
        <button
          onClick={() => setCollapsed((o) => !o)}
          className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
          title={collapsed ? "Expand history" : "Collapse history"}
        >
          {collapsed ? (
            <ChevronRight className="w-3.5 h-3.5" />
          ) : (
            <ChevronLeft className="w-3.5 h-3.5" />
          )}
        </button>
      </div>

      {/* Expanded list */}
      {!collapsed && (
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-4 h-4 animate-spin text-muted-foreground/40" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="px-4 py-12 text-center text-[11px] text-muted-foreground/40 leading-relaxed">
              No previous
              <br />
              sessions yet
            </div>
          ) : (
            groups.map(({ label: groupLabel, items }) => (
              <div key={groupLabel}>
                <p className="px-3 pt-4 pb-1 text-[10px] font-semibold text-muted-foreground/35 uppercase tracking-wider">
                  {groupLabel}
                </p>
                {items.map((s, idx) => {
                  const customLabel = labels[s.session_id];
                  const computedLabel = customLabel || defaultLabel(s, idx);
                  const isActive =
                    s.session_id === activeSessionId ||
                    s.session_id === activeHistorySourceId;
                  // Mark as live if the backend flagged it OR if it's currently open in a tab
                  const isLive = s.live || openSessionIds.includes(s.session_id);
                  return (
                    <HistoryRow
                      key={s.session_id}
                      session={s}
                      label={computedLabel}
                      index={idx}
                      isActive={isActive}
                      isLive={isLive}
                      onOpen={() => onOpen(s.session_id, s.agent_path, s.agent_name)}
                      onRename={(nl) => handleRename(s.session_id, nl)}
                      onDelete={() => handleDelete(s.session_id)}
                    />
                  );
                })}
              </div>
            ))
          )}
        </div>
      )}

      {/* Collapsed icon strip */}
      {collapsed && (
        <div className="flex-1 overflow-y-auto min-h-0 flex flex-col items-center py-2 gap-0.5">
          {sessions.slice(0, 30).map((s) => {
            const isLive = s.live || openSessionIds.includes(s.session_id);
            return (
              <button
                key={s.session_id}
                onClick={() => { setCollapsed(false); onOpen(s.session_id, s.agent_path, s.agent_name); }}
                className="w-7 h-7 rounded-md flex items-center justify-center text-muted-foreground/40 hover:text-foreground hover:bg-muted/50 transition-colors relative"
                title={labels[s.session_id] || defaultLabel(s, 0)}
              >
                <Clock className="w-3 h-3" />
                {isLive && (
                  <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-emerald-500" />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
