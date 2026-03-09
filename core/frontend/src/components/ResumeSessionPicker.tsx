/**
 * ResumeSessionPicker — full-screen modal for browsing and resuming past sessions.
 *
 * Rendered via a React portal.  Displayed after the user selects /resume from
 * the slash command menu.  Sessions are grouped by date, searchable by name or
 * agent path.  Clicking a session navigates to /workspace?session=<id>.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import ReactDOM from "react-dom";
import { useNavigate } from "react-router-dom";
import { X, Search, Bot, Loader2, Clock } from "lucide-react";
import { sessionsApi } from "@/api/sessions";

// ── Types ─────────────────────────────────────────────────────────────────────

type HistoryEntry = {
  session_id: string;
  cold: boolean;
  live: boolean;
  has_messages: boolean;
  created_at: number;
  agent_name?: string | null;
  agent_path?: string | null;
  /** Optional preview text from the last message (backend may include this). */
  last_message?: string | null;
  last_role?: string | null;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function getDisplayName(s: HistoryEntry): string {
  if (s.agent_name) return s.agent_name;
  if (s.agent_path) {
    const base =
      s.agent_path.replace(/\/$/, "").split("/").pop() || s.agent_path;
    return base
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  }
  return "New Agent";
}

function formatDate(createdAt: number, sessionId: string): string {
  const match = sessionId.match(
    /^session_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/
  );
  const d = match
    ? new Date(
        +match[1],
        +match[2] - 1,
        +match[3],
        +match[4],
        +match[5],
        +match[6]
      )
    : new Date(createdAt * 1000);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function groupByDate(
  sessions: HistoryEntry[]
): { label: string; items: HistoryEntry[] }[] {
  const now = new Date();
  const today = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate()
  ).getTime();
  const yesterday = today - 86_400_000;
  const weekAgo = today - 7 * 86_400_000;

  const groups: { label: string; items: HistoryEntry[] }[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Last 7 days", items: [] },
    { label: "Older", items: [] },
  ];

  for (const s of sessions) {
    const d = new Date(s.created_at * 1000);
    const dayTs = new Date(
      d.getFullYear(),
      d.getMonth(),
      d.getDate()
    ).getTime();
    if (dayTs >= today) groups[0].items.push(s);
    else if (dayTs >= yesterday) groups[1].items.push(s);
    else if (dayTs >= weekAgo) groups[2].items.push(s);
    else groups[3].items.push(s);
  }

  return groups.filter((g) => g.items.length > 0);
}

// ── Component ─────────────────────────────────────────────────────────────────

interface ResumeSessionPickerProps {
  onClose: () => void;
}

export default function ResumeSessionPicker({
  onClose,
}: ResumeSessionPickerProps) {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // Fetch sessions on open
  useEffect(() => {
    sessionsApi
      .history()
      .then((r) => setSessions(r.sessions as HistoryEntry[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // Auto-focus search input
  useEffect(() => {
    requestAnimationFrame(() => searchRef.current?.focus());
  }, []);

  const handleSelect = useCallback(
    (s: HistoryEntry) => {
      const params = new URLSearchParams({ session: s.session_id });
      if (s.agent_path) params.set("agent", s.agent_path);
      navigate(`/workspace?${params.toString()}`);
      onClose();
    },
    [navigate, onClose]
  );

  // Filter by display name or agent path
  const filtered = query.trim()
    ? sessions.filter((s) => {
        const haystack =
          `${getDisplayName(s)} ${s.agent_path ?? ""}`.toLowerCase();
        return haystack.includes(query.toLowerCase());
      })
    : sessions;

  const groups = groupByDate(filtered);

  return ReactDOM.createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Resume a session"
        className="w-full max-w-lg mx-4 rounded-2xl border border-border/60 bg-card shadow-2xl shadow-black/40 flex flex-col overflow-hidden"
        style={{ maxHeight: "70vh" }}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        {/* Search header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/30">
          <Search className="w-4 h-4 text-muted-foreground flex-shrink-0" />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions…"
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none"
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <button
            onClick={onClose}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground/40" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground/50">
              {query
                ? "No sessions match your search."
                : "No previous sessions found."}
            </div>
          ) : (
            groups.map(({ label, items }) => (
              <div key={label}>
                <p className="px-4 pt-4 pb-1 text-[10px] font-semibold text-muted-foreground/40 uppercase tracking-wider">
                  {label}
                </p>
                {items.map((s) => (
                  <button
                    key={s.session_id}
                    onClick={() => handleSelect(s)}
                    className="w-full flex items-start gap-3 px-4 py-2.5 text-left hover:bg-muted/40 transition-colors group"
                  >
                    <Bot className="w-4 h-4 flex-shrink-0 mt-0.5 text-muted-foreground/40 group-hover:text-muted-foreground/70 transition-colors" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-foreground/90 truncate">
                          {getDisplayName(s)}
                        </span>
                        {s.live && (
                          <span className="text-[9px] font-semibold text-emerald-500/80 uppercase tracking-wide flex-shrink-0">
                            live
                          </span>
                        )}
                      </div>
                      {s.last_message && (
                        <div className="text-xs text-muted-foreground/50 mt-0.5 truncate">
                          {s.last_message}
                        </div>
                      )}
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <Clock className="w-3 h-3 text-muted-foreground/30" />
                        <span className="text-[10px] text-muted-foreground/40">
                          {formatDate(s.created_at, s.session_id)}
                        </span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
