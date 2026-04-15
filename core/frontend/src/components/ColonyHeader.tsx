import { Hash, Share2, Download, Play, Pause, Loader2, CheckCircle2, KeyRound, FolderOpen } from "lucide-react";
import { memo, useState } from "react";
import BrowserStatusBadge from "./BrowserStatusBadge";
import { sessionsApi } from "@/api/sessions";

interface ColonyHeaderProps {
  colonyName: string;
  pipelineVersion?: string;
  runState: "idle" | "deploying" | "running";
  onRun?: () => void;
  onPause?: () => void;
  onCredentials?: () => void;
  sessionId?: string | null;
  disabled?: boolean;
}

export default memo(function ColonyHeader({
  colonyName,
  pipelineVersion,
  runState,
  onRun,
  onPause,
  onCredentials,
  sessionId,
  disabled,
}: ColonyHeaderProps) {
  const [hovered, setHovered] = useState(false);
  const showPause = runState === "running" && hovered;

  return (
    <div className="h-12 flex items-center justify-between px-5 border-b border-border/60 bg-card/50 backdrop-blur-sm flex-shrink-0">
      {/* Left: colony name */}
      <div className="flex items-center gap-2">
        <Hash className="w-4 h-4 text-muted-foreground/60" />
        <h1 className="text-sm font-semibold text-foreground">{colonyName}</h1>
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-2">
        <button
          onClick={onCredentials}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
        >
          <KeyRound className="w-3.5 h-3.5" />
          Credentials
        </button>
        {sessionId && (
          <button
            onClick={() => sessionsApi.revealFolder(sessionId).catch(() => {})}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
            title="Open session data folder"
          >
            <FolderOpen className="w-3.5 h-3.5" />
            Data
          </button>
        )}
        <BrowserStatusBadge />

        <span className="w-px h-4 bg-border/60" />

        <button
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          title="Share"
        >
          <Share2 className="w-3.5 h-3.5" />
        </button>
        <button
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          title="Export"
        >
          <Download className="w-3.5 h-3.5" />
        </button>

        {pipelineVersion && (
          <>
            <span className="text-border text-xs">|</span>
            <span className="text-[11px] text-muted-foreground font-medium uppercase tracking-wide">
              Pipeline {pipelineVersion}
            </span>
          </>
        )}

        {/* Run button */}
        <button
          onClick={runState === "running" ? onPause : onRun}
          disabled={runState === "deploying" || disabled}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all duration-200 ${
            showPause
              ? "bg-amber-500/15 text-amber-400 border border-amber-500/40 hover:bg-amber-500/25"
              : runState === "running"
              ? "bg-green-500/15 text-green-400 border border-green-500/30"
              : runState === "deploying"
              ? "bg-primary/10 text-primary border border-primary/20 cursor-default"
              : disabled
              ? "bg-muted/30 text-muted-foreground/40 border border-border/20 cursor-not-allowed"
              : "bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 hover:border-primary/40"
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
          {runState === "deploying"
            ? "Deploying..."
            : showPause
            ? "Pause"
            : runState === "running"
            ? "Running"
            : "Run"}
        </button>
      </div>
    </div>
  );
});
