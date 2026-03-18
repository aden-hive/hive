import { useState } from "react";
import { CheckCircle2, CircleDashed, XCircle, Wrench, ChevronDown, AlertTriangle, Clock } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { ExecutionStep } from "@/hooks/useExecutionSteps";

interface ExecutionStepProps {
  step: ExecutionStep;
  isLast: boolean;
}

const STATUS_CONFIG = {
  success: { icon: CheckCircle2, color: "text-success", bg: "bg-success/10", lineColor: "bg-success/30" },
  running: { icon: CircleDashed, color: "text-primary", bg: "bg-primary/10", lineColor: "bg-primary/30", spin: true },
  failed: { icon: XCircle, color: "text-destructive", bg: "bg-destructive/10", lineColor: "bg-destructive/20" },
  warning: { icon: AlertTriangle, color: "text-warning", bg: "bg-warning/10", lineColor: "bg-warning/20" },
  pending: { icon: Clock, color: "text-muted-foreground/30", bg: "bg-muted", lineColor: "bg-border" },
};

export function ExecutionStepCard({ step, isLast }: ExecutionStepProps) {
  const [expanded, setExpanded] = useState(false);
  const config = STATUS_CONFIG[step.status] || STATUS_CONFIG.pending;
  const Icon = config.icon;
  const isPending = step.status === "pending";

  return (
    <div className="flex gap-3 relative pb-5 last:pb-0">
      {/* Timeline line */}
      {!isLast && (
        <div className={`absolute left-[9px] top-[24px] bottom-0 w-px ${config.lineColor} transition-colors duration-300`} />
      )}

      {/* Icon node */}
      <div className="mt-[2px] shrink-0 relative z-10">
        <div className={`w-[18px] h-[18px] rounded-full ${config.bg} flex items-center justify-center`}>
          <Icon
            size={11}
            strokeWidth={2.5}
            className={`${config.color} ${"spin" in config && config.spin ? "animate-spin" : ""}`}
          />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 -mt-px">
        <button
          onClick={() => step.details && setExpanded(!expanded)}
          className={`flex justify-between items-start w-full text-left group ${step.details ? "cursor-pointer" : "cursor-default"}`}
        >
          <p className={`text-[12px] font-medium leading-snug ${isPending ? "text-muted-foreground/40" : "text-foreground"}`}>
            {step.label}
          </p>
          <div className="flex items-center gap-1 shrink-0 ml-2 mt-px">
            {step.duration && !isPending && (
              <span className="text-[9px] tabular-nums text-muted-foreground/40 font-medium bg-muted/60 px-1.5 py-0.5 rounded">
                {step.duration}
              </span>
            )}
            {step.details && (
              <ChevronDown size={10} className={`text-muted-foreground/30 transition-transform group-hover:text-muted-foreground/60 ${expanded ? "rotate-180" : ""}`} />
            )}
          </div>
        </button>

        {step.tool && (
          <div className="mt-1 flex items-center gap-1 px-1.5 py-0.5 bg-muted/50 rounded border border-border/40 w-fit">
            <Wrench size={9} className="text-muted-foreground/50" />
            <span className="text-[9px] font-mono text-muted-foreground/60 font-medium">{step.tool}</span>
          </div>
        )}

        <AnimatePresence>
          {expanded && step.details && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="overflow-hidden"
            >
              <p className="text-[10px] text-muted-foreground/70 mt-1.5 p-2 bg-muted/40 rounded-md border border-border/30 leading-relaxed font-mono">
                {step.details}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
