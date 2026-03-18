import { Activity, X, Zap, Clock } from "lucide-react";
import { ExecutionStepCard } from "./ExecutionStep";
import { EXECUTION_STEPS } from "@/data/mock-data";
import type { ExecutionStep } from "@/hooks/useExecutionSteps";
import type { AgentTemplate } from "@/data/mock-data";

interface ExecutionPanelProps {
  isOpen?: boolean;
  onClose?: () => void;
  steps: ExecutionStep[];
  tokenUsage: number;
  activeTemplate?: AgentTemplate | null;
}

export function ExecutionPanel({ isOpen, onClose, steps, tokenUsage, activeTemplate }: ExecutionPanelProps) {
  const isDemo = steps.length === 0;
  const displaySteps = isDemo
    ? (activeTemplate?.executionSteps || EXECUTION_STEPS)
    : steps;
  const displayTokens = isDemo ? 2840 : tokenUsage;

  const successCount = displaySteps.filter((s) => s.status === "success").length;
  const totalSteps = displaySteps.length;
  const hasSteps = totalSteps > 0;
  const isRunning = displaySteps.some((s) => s.status === "running");
  const progressPercent = totalSteps > 0 ? Math.round((successCount / totalSteps) * 100) : 0;

  return (
    <>
      {isOpen && (
        <div className="fixed inset-0 bg-foreground/20 backdrop-blur-[2px] z-40 lg:hidden" onClick={onClose} />
      )}

      <aside
        className={`fixed right-0 top-0 z-50 h-full w-[280px] border-l border-border bg-card flex flex-col shrink-0 transition-transform duration-200 ease-out lg:relative lg:translate-x-0 lg:z-auto ${
          isOpen ? "translate-x-0" : "translate-x-full lg:translate-x-0"
        } hidden lg:flex ${isOpen ? "!flex" : ""}`}
      >
        {/* Header */}
        <div className="h-12 px-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity size={13} className="text-primary" />
            <span className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground font-display">Pipeline</span>
          </div>
          <div className="flex items-center gap-2">
            {hasSteps && (
              <span className={`px-2 py-0.5 text-[9px] font-bold rounded-full uppercase tracking-wide ${
                isRunning ? "bg-primary/10 text-primary animate-pulse" : "bg-success/10 text-success"
              }`}>
                {isRunning ? "Running" : "Complete"}
              </span>
            )}
            <button onClick={onClose} className="p-1.5 text-muted-foreground hover:text-foreground rounded-md hover:bg-muted transition-colors lg:hidden">
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Template context */}
        {activeTemplate && isDemo && (
          <div className="px-4 py-2.5 border-b border-border/50 bg-primary/3">
            <p className="text-[10px] font-semibold text-primary truncate">{activeTemplate.title}</p>
            <p className="text-[9px] text-muted-foreground/50 mt-0.5">Template execution preview</p>
          </div>
        )}

        {/* Progress summary */}
        {hasSteps && (
          <div className="px-4 py-3 border-b border-border/50 bg-muted/20">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">Progress</span>
              <span className="text-[11px] font-bold text-foreground tabular-nums">{progressPercent}%</span>
            </div>
            <div className="w-full h-1 bg-muted rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-700 ease-out ${isRunning ? "bg-primary" : "bg-success"}`}
                style={{ width: `${progressPercent}%` }}
              />
            </div>
            <div className="flex items-center justify-between mt-2 text-[9px] text-muted-foreground/50">
              <span className="tabular-nums">{successCount} of {totalSteps} steps</span>
              <span className="flex items-center gap-1"><Clock size={8} /> {isRunning ? "in progress" : "finished"}</span>
            </div>
          </div>
        )}

        {/* Steps */}
        <div className="px-4 py-4 overflow-y-auto flex-1 no-scrollbar">
          {hasSteps ? (
            <div>
              {displaySteps.map((step, i) => (
                <ExecutionStepCard key={step.id} step={step as any} isLast={i === displaySteps.length - 1} />
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center px-4">
              <div className="w-10 h-10 bg-muted rounded-xl flex items-center justify-center mb-3">
                <Activity size={18} className="text-muted-foreground/40" />
              </div>
              <p className="text-[11px] text-muted-foreground/50 leading-relaxed">
                Agent steps will appear here
              </p>
            </div>
          )}
        </div>

        {/* Token footer */}
        <div className="px-4 py-3 border-t border-border bg-muted/20">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
              <Zap size={10} className="text-primary" /> Tokens
            </span>
            <span className="text-[12px] font-bold text-foreground tabular-nums">{displayTokens.toLocaleString()}</span>
          </div>
          <div className="w-full h-1 bg-muted rounded-full overflow-hidden">
            <div className="h-full bg-primary/50 rounded-full transition-all" style={{ width: `${Math.min((displayTokens / 4000) * 100, 100)}%` }} />
          </div>
          <p className="text-[8px] text-muted-foreground/35 mt-1 tabular-nums text-right">{displayTokens.toLocaleString()} / 4,000</p>
        </div>
      </aside>
    </>
  );
}
