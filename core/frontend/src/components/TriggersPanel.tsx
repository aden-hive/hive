import { Clock, Webhook, Zap, ArrowRight, Activity } from "lucide-react";
import type { GraphNode } from "./graph-types";
import { cronToLabel } from "@/lib/graphUtils";

interface TriggersPanelProps {
  triggers: GraphNode[];
  selectedId?: string | null;
  onSelect?: (trigger: GraphNode) => void;
}

function TriggerIcon({ type }: { type?: string }) {
  const cls = "w-3.5 h-3.5";
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

function scheduleLabel(config: Record<string, unknown> | undefined): string | null {
  if (!config) return null;
  const cron = config.cron as string | undefined;
  if (cron) return cronToLabel(cron);
  const interval = config.interval_minutes as number | undefined;
  if (interval != null) {
    if (interval >= 60) return `Every ${interval / 60}h`;
    return `Every ${interval}m`;
  }
  return null;
}

function countdownLabel(nextFireIn: number | undefined): string | null {
  if (nextFireIn == null || nextFireIn <= 0) return null;
  const h = Math.floor(nextFireIn / 3600);
  const m = Math.floor((nextFireIn % 3600) / 60);
  const s = Math.floor(nextFireIn % 60);
  return h > 0
    ? `next in ${h}h ${String(m).padStart(2, "0")}m`
    : `next in ${m}m ${String(s).padStart(2, "0")}s`;
}

function TriggerCard({
  trigger,
  selected,
  onClick,
}: {
  trigger: GraphNode;
  selected: boolean;
  onClick?: () => void;
}) {
  const isActive = trigger.status === "running" || trigger.status === "complete";
  const schedule = scheduleLabel(trigger.triggerConfig);
  const nextFireIn = trigger.triggerConfig?.next_fire_in as number | undefined;
  const countdown = isActive ? countdownLabel(nextFireIn) : null;

  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "w-full text-left rounded-lg border px-3 py-2.5 transition-colors",
        selected
          ? "bg-primary/10 border-primary/30"
          : "bg-background/60 border-border/30 hover:bg-muted/40 hover:border-border/50",
      ].join(" ")}
    >
      <div className="flex items-center gap-2">
        <span
          className={[
            "flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center",
            isActive ? "bg-primary/15 text-primary" : "bg-muted/60 text-muted-foreground",
          ].join(" ")}
        >
          <TriggerIcon type={trigger.triggerType} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-foreground truncate">{trigger.label}</p>
          {schedule && schedule !== trigger.label && (
            <p className="text-[10.5px] text-muted-foreground truncate mt-0.5">{schedule}</p>
          )}
        </div>
        <span
          className={[
            "flex-shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded-full",
            isActive
              ? "bg-emerald-500/15 text-emerald-400"
              : "bg-muted/60 text-muted-foreground",
          ].join(" ")}
        >
          {isActive ? "active" : "inactive"}
        </span>
      </div>
      {countdown && (
        <p className="text-[10px] text-muted-foreground mt-1.5 italic pl-8">{countdown}</p>
      )}
    </button>
  );
}

export default function TriggersPanel({ triggers, selectedId, onSelect }: TriggersPanelProps) {
  return (
    <div className="flex flex-col h-full bg-card/30 border-l border-border/30">
      <div className="px-4 py-3 border-b border-border/30 flex items-center gap-2">
        <Clock className="w-3.5 h-3.5 text-muted-foreground" />
        <h3 className="text-xs font-semibold text-foreground uppercase tracking-wide">
          Triggers
        </h3>
        {triggers.length > 0 && (
          <span className="ml-auto text-[10px] text-muted-foreground">
            {triggers.length}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
        {triggers.length === 0 ? (
          <div className="text-center py-8">
            <Clock className="w-6 h-6 mx-auto text-muted-foreground/40 mb-2" />
            <p className="text-[11px] text-muted-foreground">No triggers configured</p>
            <p className="text-[10px] text-muted-foreground/70 mt-1 px-2">
              Ask the queen to set a schedule or webhook
            </p>
          </div>
        ) : (
          triggers.map((t) => (
            <TriggerCard
              key={t.id}
              trigger={t}
              selected={selectedId === t.id}
              onClick={onSelect ? () => onSelect(t) : undefined}
            />
          ))
        )}
      </div>
    </div>
  );
}
