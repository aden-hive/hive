import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Loader2 } from "lucide-react";
import type { HistorySession } from "@/api/types";

interface QueenSessionSwitcherProps {
  sessions: HistorySession[];
  currentSessionId: string | null;
  loading?: boolean;
  switchingSessionId?: string | null;
  onSelect: (sessionId: string) => void;
}

function formatSessionDate(createdAt: number): string {
  if (!createdAt) return "Unknown date";
  const date = new Date(createdAt * 1000);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function summarizeSession(session: HistorySession): string {
  const pieces = [formatSessionDate(session.created_at)];
  if (session.agent_name) pieces.push(session.agent_name);
  return pieces.join(" · ");
}

export default function QueenSessionSwitcher({
  sessions,
  currentSessionId,
  loading = false,
  switchingSessionId = null,
  onSelect,
}: QueenSessionSwitcherProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const currentSession = useMemo(
    () => sessions.find((session) => session.session_id === currentSessionId) ?? null,
    [sessions, currentSessionId],
  );

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((prev) => !prev)}
        disabled={loading || sessions.length === 0}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors border border-transparent hover:border-border/40 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <span className="max-w-[160px] truncate">
          {currentSession ? summarizeSession(currentSession) : "Sessions"}
        </span>
        {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <ChevronDown className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} />}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-[320px] bg-card border border-border/60 rounded-lg shadow-xl z-50 overflow-hidden">
          <div className="max-h-[360px] overflow-y-auto">
            {sessions.map((session) => {
              const isActive = session.session_id === currentSessionId;
              const isSwitching = session.session_id === switchingSessionId;
              return (
                <button
                  key={session.session_id}
                  onClick={() => {
                    setOpen(false);
                    if (!isActive && !isSwitching) onSelect(session.session_id);
                  }}
                  className={`w-full text-left px-3 py-2.5 text-xs transition-colors border-b border-border/30 last:border-b-0 ${
                    isActive
                      ? "bg-primary/10 text-foreground"
                      : "text-foreground hover:bg-muted/30"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {isSwitching ? (
                      <Loader2 className="w-3 h-3 animate-spin flex-shrink-0" />
                    ) : isActive ? (
                      <Check className="w-3 h-3 text-primary flex-shrink-0" />
                    ) : (
                      <span className="w-3 h-3 flex-shrink-0" />
                    )}
                    <span className="font-medium truncate">{formatSessionDate(session.created_at)}</span>
                    <span
                      className={`ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                        session.live
                          ? "bg-primary/10 text-primary"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {session.live ? "Live" : "History"}
                    </span>
                  </div>
                  <div className="mt-1 pl-5 text-[11px] text-muted-foreground truncate">
                    {session.last_message || "No assistant reply yet"}
                  </div>
                  {session.agent_name && (
                    <div className="mt-1 pl-5 text-[10px] text-muted-foreground/70 truncate">
                      {session.agent_name}
                    </div>
                  )}
                </button>
              );
            })}
            {sessions.length === 0 && (
              <div className="px-3 py-3 text-xs text-muted-foreground">
                No sessions yet
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
