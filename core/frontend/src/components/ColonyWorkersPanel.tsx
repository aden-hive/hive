import { useCallback, useEffect, useRef, useState } from "react";
import { X, Users, RefreshCw } from "lucide-react";
import { colonyWorkersApi, type WorkerSummary } from "@/api/colonyWorkers";

interface ColonyWorkersPanelProps {
  sessionId: string;
  onClose: () => void;
}

function statusClasses(status: string): string {
  const s = status.toLowerCase();
  if (s === "running" || s === "pending") return "bg-primary/15 text-primary";
  if (s === "completed") return "bg-emerald-500/15 text-emerald-500";
  if (s === "failed") return "bg-destructive/15 text-destructive";
  if (s === "stopped") return "bg-muted text-muted-foreground";
  return "bg-muted text-muted-foreground";
}

function shortId(worker_id: string): string {
  return worker_id.length > 8 ? worker_id.slice(0, 8) : worker_id;
}

function fmtStarted(ts: number): string {
  if (!ts) return "";
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

export default function ColonyWorkersPanel({
  sessionId,
  onClose,
}: ColonyWorkersPanelProps) {
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    colonyWorkersApi
      .list(sessionId)
      .then((r) => setWorkers(r.workers))
      .catch((e) => setError(e?.message ?? "Failed to load workers"))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // ── Resizable width (mirrors QueenProfilePanel) ─────────────────────
  const MIN_WIDTH = 280;
  const MAX_WIDTH = 600;
  const [width, setWidth] = useState(360);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const onDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragging.current = true;
      startX.current = e.clientX;
      startWidth.current = width;

      const onMove = (ev: MouseEvent) => {
        if (!dragging.current) return;
        const delta = startX.current - ev.clientX;
        setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth.current + delta)));
      };
      const onUp = () => {
        dragging.current = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [width],
  );

  return (
    <aside
      className="flex-shrink-0 border-l border-border/60 bg-card overflow-y-auto relative"
      style={{ width }}
    >
      <div
        onMouseDown={onDragStart}
        className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
      />
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/60">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Users className="w-4 h-4 text-primary" />
          COLONY WORKERS
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={refresh}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="px-4 py-4">
        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive mb-3">
            {error}
          </div>
        )}

        {loading && workers.length === 0 ? (
          <div className="flex justify-center py-10">
            <div className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          </div>
        ) : workers.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-8">
            No workers spawned yet.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {workers.map((w) => (
              <li
                key={w.worker_id}
                className="rounded-lg border border-border/60 bg-background/40 px-3 py-2.5 hover:bg-muted/30 transition-colors cursor-default"
              >
                <div className="flex items-center justify-between mb-1">
                  <code className="text-xs font-mono text-foreground">
                    {shortId(w.worker_id)}
                  </code>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${statusClasses(w.status)}`}
                  >
                    {w.status}
                  </span>
                </div>
                {w.task && (
                  <p className="text-xs text-foreground/80 line-clamp-2 mb-1">
                    {w.task}
                  </p>
                )}
                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                  <span>{fmtStarted(w.started_at)}</span>
                  {w.result && (
                    <span>
                      {w.result.duration_seconds
                        ? `${w.result.duration_seconds.toFixed(1)}s`
                        : ""}
                      {w.result.tokens_used
                        ? ` · ${w.result.tokens_used.toLocaleString()} tok`
                        : ""}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
