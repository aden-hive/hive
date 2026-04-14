import { useState } from "react";
import { X, Webhook, Clock, Activity, ArrowRight, Zap, Play, Square, Loader2 } from "lucide-react";
import type { GraphNode } from "./graph-types";
import { cronToLabel } from "@/lib/graphUtils";
import { sessionsApi } from "@/api/sessions";

interface TriggerDetailPanelProps {
  trigger: GraphNode;
  sessionId: string;
  onClose: () => void;
}

function TriggerIcon({ type }: { type?: string }) {
  const cls = "w-4 h-4";
  switch (type) {
    case "webhook":
      return <Webhook className={cls} />;
    case "timer":
      return <Clock className={cls} />;
    case "api":
      return <ArrowRight className={cls} />;
    case "event":
      return <Activity className={cls} />;
    default:
      return <Zap className={cls} />;
  }
}

function formatCountdown(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

export default function TriggerDetailPanel({ trigger, sessionId, onClose }: TriggerDetailPanelProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isActive = trigger.status === "running" || trigger.status === "complete";
  const config = (trigger.triggerConfig || {}) as Record<string, unknown>;
  const cron = config.cron as string | undefined;
  const interval = config.interval_minutes as number | undefined;
  const nextFireIn = config.next_fire_in as number | undefined;
  const triggerId = trigger.id.replace(/^__trigger_/, "");

  const handleToggle = async () => {
    if (!sessionId || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (isActive) {
        await sessionsApi.deactivateTrigger(sessionId, triggerId);
      } else {
        await sessionsApi.activateTrigger(sessionId, triggerId);
      }
      // The SSE TRIGGER_ACTIVATED / TRIGGER_DEACTIVATED event will flip
      // the card status; we don't need to set local state here.
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const schedule = cron
    ? cronToLabel(cron)
    : interval != null
    ? interval >= 60
      ? `Every ${interval / 60}h`
      : `Every ${interval}m`
    : null;

  // Hide noisy frontend-only fields so only the raw operator config shows
  const displayEntries = Object.entries(config).filter(
    ([k]) => k !== "next_fire_in" && k !== "entry_node",
  );

  return (
    <div className="flex flex-col h-full border-l border-border/40 bg-card/20 animate-in slide-in-from-right">
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-border/30 flex items-start justify-between gap-2 flex-shrink-0">
        <div className="flex items-start gap-3 min-w-0">
          <div
            className={[
              "w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0",
              isActive ? "bg-primary/15 text-primary" : "bg-muted/50 text-muted-foreground",
            ].join(" ")}
          >
            <TriggerIcon type={trigger.triggerType} />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground leading-tight truncate">
              {trigger.label}
            </h3>
            <div className="flex items-center gap-2 mt-1">
              <span
                className={[
                  "text-[10px] font-medium px-1.5 py-0.5 rounded-full",
                  isActive
                    ? "bg-emerald-500/15 text-emerald-400"
                    : "bg-muted/60 text-muted-foreground",
                ].join(" ")}
              >
                {isActive ? "active" : "inactive"}
              </span>
              {trigger.triggerType && (
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  {trigger.triggerType}
                </span>
              )}
            </div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto px-4 py-4 space-y-4">
        {schedule && (
          <div>
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
              Schedule
            </p>
            <div className="rounded-lg border border-border/30 bg-background/60 px-3 py-2.5">
              <p className="text-xs text-foreground">{schedule}</p>
              {cron && (
                <p className="text-[10px] text-muted-foreground mt-1 font-mono">{cron}</p>
              )}
            </div>
          </div>
        )}

        {isActive && nextFireIn != null && nextFireIn > 0 && (
          <div>
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
              Next fire
            </p>
            <div className="rounded-lg border border-border/30 bg-background/60 px-3 py-2.5">
              <p className="text-xs text-foreground italic">in {formatCountdown(nextFireIn)}</p>
            </div>
          </div>
        )}

        {displayEntries.length > 0 && (
          <div>
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
              Config
            </p>
            <div className="rounded-lg border border-border/30 bg-background/60 px-3 py-2.5 space-y-1">
              {displayEntries.map(([k, v]) => (
                <div key={k} className="flex items-start justify-between gap-3 text-[11px]">
                  <span className="text-muted-foreground font-mono">{k}</span>
                  <span className="text-foreground font-mono text-right truncate">
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div>
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
            Trigger ID
          </p>
          <div className="rounded-lg border border-border/30 bg-background/60 px-3 py-2.5">
            <p className="text-[11px] text-muted-foreground font-mono break-all">
              {triggerId}
            </p>
          </div>
        </div>
      </div>

      {/* Footer with start/stop control */}
      <div className="px-4 py-3 border-t border-border/30 flex-shrink-0 space-y-2">
        {error && (
          <p className="text-[10.5px] text-red-400 leading-snug">{error}</p>
        )}
        <button
          type="button"
          onClick={handleToggle}
          disabled={busy || !sessionId}
          className={[
            "w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            isActive
              ? "bg-muted/50 text-foreground hover:bg-muted/70 border border-border/30"
              : "bg-primary/15 text-primary hover:bg-primary/25 border border-primary/30",
          ].join(" ")}
        >
          {busy ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : isActive ? (
            <Square className="w-3.5 h-3.5" />
          ) : (
            <Play className="w-3.5 h-3.5" />
          )}
          {busy ? "Working…" : isActive ? "Stop trigger" : "Start trigger"}
        </button>
      </div>
    </div>
  );
}
