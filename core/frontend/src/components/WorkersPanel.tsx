import { useEffect, useState, useCallback } from "react";
import { Loader2, Square, XCircle, CheckCircle2, OctagonX } from "lucide-react";
import { workersApi, type LiveWorker } from "@/api/workers";

interface WorkersPanelProps {
  sessionId: string | null;
  // Refresh the panel every this many ms. 0 disables polling.
  pollMs?: number;
}

function statusClassName(w: LiveWorker): string {
  if (w.is_active) return "text-blue-600";
  const s = (w.result_status || w.status || "").toLowerCase();
  if (s.includes("success")) return "text-emerald-600";
  if (s.includes("fail") || s.includes("error")) return "text-destructive";
  if (s.includes("stop") || s.includes("timeout")) return "text-amber-600";
  return "text-muted-foreground";
}

function StatusIcon({ worker }: { worker: LiveWorker }) {
  const cls = `w-3.5 h-3.5 ${statusClassName(worker)}`;
  if (worker.is_active) return <Loader2 className={`${cls} animate-spin`} />;
  const s = (worker.result_status || worker.status || "").toLowerCase();
  if (s.includes("success")) return <CheckCircle2 className={cls} />;
  if (s.includes("fail") || s.includes("error")) return <XCircle className={cls} />;
  if (s.includes("stop") || s.includes("timeout")) return <OctagonX className={cls} />;
  return <CheckCircle2 className={cls} />;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export default function WorkersPanel({ sessionId, pollMs = 2000 }: WorkersPanelProps) {
  const [workers, setWorkers] = useState<LiveWorker[]>([]);
  const [loading, setLoading] = useState(false);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [stoppingAll, setStoppingAll] = useState(false);

  const fetchWorkers = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await workersApi.listLive(sessionId);
      setWorkers(res.workers || []);
    } catch {
      // Backend down or 404 — clear rather than crash.
      setWorkers([]);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    fetchWorkers().finally(() => setLoading(false));
    if (pollMs <= 0) return;
    const id = setInterval(fetchWorkers, pollMs);
    return () => clearInterval(id);
  }, [sessionId, pollMs, fetchWorkers]);

  const stopOne = useCallback(
    async (workerId: string) => {
      if (!sessionId) return;
      setStoppingId(workerId);
      try {
        await workersApi.stopLive(sessionId, workerId);
      } catch {
        // Non-fatal — the next poll will reflect the true state.
      } finally {
        setStoppingId(null);
        fetchWorkers();
      }
    },
    [sessionId, fetchWorkers],
  );

  const stopAll = useCallback(async () => {
    if (!sessionId) return;
    setStoppingAll(true);
    try {
      await workersApi.stopAllLive(sessionId);
    } catch {
      // ignore
    } finally {
      setStoppingAll(false);
      fetchWorkers();
    }
  }, [sessionId, fetchWorkers]);

  const activeCount = workers.filter((w) => w.is_active).length;

  return (
    <div className="h-full flex flex-col border-l border-border bg-card/30">
      <div className="px-3 py-2 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Workers
          </span>
          {activeCount > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-600 font-medium">
              {activeCount} active
            </span>
          )}
        </div>
        {activeCount > 0 && (
          <button
            onClick={stopAll}
            disabled={stoppingAll}
            className="text-[10px] px-2 py-0.5 rounded border border-destructive/40 text-destructive hover:bg-destructive/10 disabled:opacity-50 transition-colors"
            title="Stop all active workers"
          >
            {stoppingAll ? "Stopping…" : "Stop all"}
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {loading && workers.length === 0 && (
          <div className="text-xs text-muted-foreground p-2">Loading…</div>
        )}
        {!loading && workers.length === 0 && (
          <div className="text-xs text-muted-foreground p-2">
            No workers have been spawned in this session yet.
          </div>
        )}
        {workers.map((w) => (
          <div
            key={w.worker_id}
            className="rounded border border-border/60 bg-background/70 p-2 text-xs"
          >
            <div className="flex items-start gap-2">
              <StatusIcon worker={w} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="font-mono text-[10px] text-muted-foreground truncate"
                    title={w.worker_id}
                  >
                    {w.worker_id.slice(0, 24)}
                  </span>
                  <span className={`text-[10px] ${statusClassName(w)}`}>
                    {w.is_active ? w.status : (w.result_status || w.status)}
                  </span>
                </div>
                <div className="mt-1 text-[11px] text-foreground/90 line-clamp-2">
                  {w.task || "(no task)"}
                </div>
                <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                  <span>{formatDuration(w.duration_seconds)}</span>
                  {w.is_active && (
                    <button
                      onClick={() => stopOne(w.worker_id)}
                      disabled={stoppingId === w.worker_id}
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-destructive/40 text-destructive hover:bg-destructive/10 disabled:opacity-50 transition-colors"
                      title="Stop this worker"
                    >
                      <Square className="w-2.5 h-2.5" />
                      {stoppingId === w.worker_id ? "…" : "Stop"}
                    </button>
                  )}
                </div>
                {w.result_summary && !w.is_active && (
                  <div className="mt-1 text-[10px] text-muted-foreground line-clamp-2 italic">
                    {w.result_summary}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
