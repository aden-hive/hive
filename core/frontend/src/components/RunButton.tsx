import { memo, useState } from "react";
import { Play, Pause, Loader2, CheckCircle2 } from "lucide-react";
import type { RunButtonProps } from "./graph-types";

export const RunButton = memo(function RunButton({ runState, disabled, onRun, onPause, btnRef }: RunButtonProps) {
  const [hovered, setHovered] = useState(false);
  const showPause = runState === "running" && hovered;

  return (
    <button
      ref={btnRef}
      onClick={runState === "running" ? onPause : onRun}
      disabled={runState === "deploying" || disabled}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all duration-200 ${
        showPause
          ? "bg-amber-500/15 text-amber-400 border border-amber-500/40 hover:bg-amber-500/25 active:scale-95 cursor-pointer"
          : runState === "running"
          ? "bg-green-500/15 text-green-400 border border-green-500/30 cursor-pointer"
          : runState === "deploying"
          ? "bg-primary/10 text-primary border border-primary/20 cursor-default"
          : disabled
          ? "bg-muted/30 text-muted-foreground/40 border border-border/20 cursor-not-allowed"
          : "bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 hover:border-primary/40 active:scale-95"
      }`}
    >
      {runState === "deploying" ? (
        <Loader2 className="w-3 h-3 animate-spin" />
      ) : showPause ? (
        <Pause className="w-3 h-3 fill-current" />
      ) : runState === "running" ? (
        <CheckCircle2 className="w-3 h-3" />
      ) : (
        <Play className="w-3 h-3 fill-current" />
      )}
      {runState === "deploying" ? "Deploying\u2026" : showPause ? "Pause" : runState === "running" ? "Running" : "Run"}
    </button>
  );
});
