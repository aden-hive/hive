import { memo, useState, useRef, useEffect, useCallback } from "react";
import { ChevronDown, ChevronUp, Cpu } from "lucide-react";
import type { ChatMessage, ContextUsageEntry } from "@/components/ChatPanel";
import MarkdownContent from "@/components/MarkdownContent";

// ---------------------------------------------------------------------------
// Matrix rain canvas for subagent squares
// ---------------------------------------------------------------------------

/** Render a matrix-rain effect inside a canvas. Drops only fall within the
 *  filled region (bottom `fillPct`% of the canvas). */
function MatrixRainCanvas({
  color,
  fillPct,
  width,
  height,
}: {
  color: string;
  fillPct: number;
  width: number;
  height: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<{
    columns: number[];
    frameId: number;
    lastTick: number;
  } | null>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = width * dpr;
    const h = height * dpr;

    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }

    const fontSize = 7 * dpr;
    const cols = Math.floor(w / fontSize);
    const fillH = (Math.min(fillPct, 100) / 100) * h;
    const topOfFill = h - fillH;

    // Init columns
    if (!stateRef.current || stateRef.current.columns.length !== cols) {
      stateRef.current = {
        columns: Array.from({ length: cols }, () =>
          topOfFill + Math.random() * fillH
        ),
        frameId: 0,
        lastTick: 0,
      };
    }

    const state = stateRef.current;
    const now = performance.now();
    // Tick at ~8 fps for a slow, ambient feel
    if (now - state.lastTick < 125) {
      state.frameId = requestAnimationFrame(draw);
      return;
    }
    state.lastTick = now;

    // Fade previous frame
    ctx.fillStyle = "rgba(0,0,0,0.25)";
    ctx.fillRect(0, 0, w, h);

    ctx.font = `${fontSize}px monospace`;
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.8;

    for (let i = 0; i < cols; i++) {
      // Random character (digits, symbols, katakana-ish)
      const chars = "01.:+*#>|~";
      const char = chars[Math.floor(Math.random() * chars.length)];
      const x = i * fontSize;
      const y = state.columns[i];

      if (y >= topOfFill && y <= h) {
        ctx.fillText(char, x, y);
      }

      // Advance drop; reset when past bottom
      state.columns[i] += fontSize;
      if (state.columns[i] > h || Math.random() > 0.96) {
        state.columns[i] = topOfFill;
      }
    }

    ctx.globalAlpha = 1.0;
    state.frameId = requestAnimationFrame(draw);
  }, [color, fillPct, width, height]);

  useEffect(() => {
    const frameId = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frameId);
      if (stateRef.current) cancelAnimationFrame(stateRef.current.frameId);
    };
  }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0"
      style={{ width, height }}
    />
  );
}

const workerColor = "hsl(220,60%,55%)";

/** Palette for distinguishing individual subagent squares */
const SUBAGENT_COLORS = [
  "hsl(220,60%,55%)",  // blue
  "hsl(260,50%,55%)",  // purple
  "hsl(180,50%,45%)",  // teal
  "hsl(30,70%,50%)",   // orange
  "hsl(340,55%,50%)",  // rose
  "hsl(150,45%,45%)",  // green
  "hsl(45,80%,50%)",   // amber
  "hsl(290,45%,55%)",  // violet
];

function colorForIndex(i: number): string {
  return SUBAGENT_COLORS[i % SUBAGENT_COLORS.length];
}

/** Extract a short display label from a subagent node_id like "parentNode:subagent:myAgent" */
function subagentLabel(nodeId: string): string {
  const parts = nodeId.split(":subagent:");
  if (parts.length >= 2) {
    // Title-case the agent ID portion
    return parts[1]
      .replace(/[_-]/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
      .trim();
  }
  return nodeId
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

export interface SubagentGroup {
  /** Unique node_id for this subagent (includes instance suffix for duplicates) */
  nodeId: string;
  /** All chat messages from this subagent (stream snapshots, tool pills, etc.) */
  messages: ChatMessage[];
  /** Context window usage for this subagent's event loop */
  contextUsage?: ContextUsageEntry;
}

interface ParallelSubagentBubbleProps {
  /** Grouped subagent data — one entry per parallel subagent */
  groups: SubagentGroup[];
  /** ID for the overall group — used for expand/collapse persistence */
  groupId: string;
}

/** A single subagent square in the folded view */
function SubagentSquare({
  group,
  index,
  isLatest,
  label,
}: {
  group: SubagentGroup;
  index: number;
  isLatest: boolean;
  /** Display label — may include instance number for duplicates */
  label: string;
}) {
  const color = colorForIndex(index);
  const fillPct = group.contextUsage?.usagePct ?? 0;
  const msgCount = group.messages.filter(
    (m) => m.type !== "tool_status" && m.role === "worker"
  ).length;

  return (
    <div
      className="relative flex flex-col items-center gap-1"
      title={`${label}\n${msgCount} message${msgCount !== 1 ? "s" : ""}\nContext: ${fillPct}%`}
    >
      {/* Message count badge */}
      <span
        className="text-[10px] font-semibold tabular-nums leading-none"
        style={{ color }}
      >
        {msgCount}
      </span>

      {/* Pixel-rain square — matrix rain within the filled region */}
      <div
        className={`relative w-10 h-10 rounded-md overflow-hidden transition-all ${
          isLatest ? "ring-2 ring-offset-1 ring-offset-background" : ""
        }`}
        style={{
          backgroundColor: "#0a0a0a",
          ...(isLatest ? { ringColor: color } : {}),
        }}
      >
        {/* Dim base fill so there's something visible even without animation */}
        <div
          className="absolute bottom-0 left-0 right-0 transition-all duration-500 ease-out"
          style={{
            height: `${Math.min(fillPct, 100)}%`,
            backgroundColor: color,
            opacity: 0.1,
          }}
        />
        {/* Matrix rain canvas */}
        <MatrixRainCanvas
          color={color}
          fillPct={fillPct}
          width={40}
          height={40}
        />
        {/* Percentage overlay */}
        <span
          className="absolute inset-0 flex items-center justify-center text-[10px] font-bold tabular-nums"
          style={{
            color: "#fff",
            textShadow: `0 0 6px ${color}, 0 0 2px ${color}`,
          }}
        >
          {fillPct}%
        </span>
      </div>

      {/* Subagent label */}
      <span
        className="text-[9px] text-muted-foreground/70 max-w-[56px] truncate text-center leading-tight"
        title={label}
      >
        {label}
      </span>
    </div>
  );
}

/** Return the last element of an array (compat with ES2021 targets). */
function last<T>(arr: T[]): T | undefined {
  return arr[arr.length - 1];
}

/** Stable unique key for a group. */
function groupKey(g: SubagentGroup): string {
  return g.nodeId;
}

const ParallelSubagentBubble = memo(function ParallelSubagentBubble({
  groups,
}: ParallelSubagentBubbleProps) {
  const [expanded, setExpanded] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);

  // Compute display labels — append instance number when multiple groups
  // share the same nodeId (e.g. 3× browser-researcher → #1, #2, #3).
  const labels: string[] = (() => {
    const countByNode = new Map<string, number>();
    for (const g of groups) {
      countByNode.set(g.nodeId, (countByNode.get(g.nodeId) ?? 0) + 1);
    }
    const indexByNode = new Map<string, number>();
    return groups.map((g) => {
      const base = subagentLabel(g.nodeId);
      if ((countByNode.get(g.nodeId) ?? 1) <= 1) return base;
      const idx = (indexByNode.get(g.nodeId) ?? 0) + 1;
      indexByNode.set(g.nodeId, idx);
      return `${base} #${idx}`;
    });
  })();

  // Find the subagent that most recently received a stream update
  const latestIdx = groups.reduce<number>((bestIdx, g, i) => {
    const filtered = g.messages.filter((m) => m.type !== "tool_status");
    const lastMsg = last(filtered);
    if (!lastMsg) return bestIdx;
    if (bestIdx < 0) return i;
    const bestFiltered = groups[bestIdx].messages.filter((m) => m.type !== "tool_status");
    const bestLast = last(bestFiltered);
    if (!bestLast) return i;
    return (lastMsg.createdAt ?? 0) >= (bestLast.createdAt ?? 0) ? i : bestIdx;
  }, -1);

  const latestGroup = latestIdx >= 0 ? groups[latestIdx] : null;

  const latestContent = latestGroup
    ? last(latestGroup.messages.filter((m) => m.type !== "tool_status"))?.content ?? ""
    : "";

  const latestLabel = latestIdx >= 0 ? labels[latestIdx] : "";

  // Auto-scroll the preview window to bottom when content changes
  useEffect(() => {
    if (previewRef.current) {
      previewRef.current.scrollTop = previewRef.current.scrollHeight;
    }
  }, [latestContent]);

  if (groups.length === 0) return null;

  return (
    <div className="flex gap-3">
      {/* Left icon */}
      <div
        className="flex-shrink-0 w-7 h-7 rounded-xl flex items-center justify-center mt-1"
        style={{
          backgroundColor: `${workerColor}18`,
          border: `1.5px solid ${workerColor}35`,
        }}
      >
        <Cpu className="w-3.5 h-3.5" style={{ color: workerColor }} />
      </div>

      <div className="flex-1 min-w-0 max-w-[85%]">
        {/* Header */}
        <div className="flex items-center gap-2 mb-1">
          <span className="font-medium text-xs" style={{ color: workerColor }}>
            {groups.length === 1 ? "Sub-agent" : "Parallel Agents"}
          </span>
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground">
            {groups.length} running
          </span>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="ml-auto text-muted-foreground/60 hover:text-muted-foreground transition-colors p-0.5 rounded"
            title={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>
        </div>

        {expanded ? (
          /* ── Expanded view: show individual subagent messages ── */
          <div className="space-y-3 rounded-2xl rounded-tl-md border border-border/30 bg-muted/20 p-3">
            {groups.map((group, gi) => {
              const color = colorForIndex(gi);
              const streamMsgs = group.messages.filter(
                (m) => m.type !== "tool_status"
              );
              const lastContent = last(streamMsgs)?.content ?? "";
              return (
                <div key={groupKey(group)} className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Cpu
                      className="w-3 h-3 flex-shrink-0"
                      style={{ color }}
                    />
                    <span
                      className="text-xs font-medium"
                      style={{ color }}
                    >
                      {labels[gi]}
                    </span>
                    {group.contextUsage && (
                      <span className="text-[10px] text-muted-foreground/60 tabular-nums">
                        {group.contextUsage.usagePct}% ctx
                      </span>
                    )}
                  </div>
                  {lastContent && (
                    <div className="text-sm leading-relaxed rounded-xl bg-muted/40 px-3 py-2">
                      <MarkdownContent content={lastContent} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          /* ── Folded view: preview window + squares ── */
          <div className="rounded-2xl rounded-tl-md border border-border/30 bg-muted/20 overflow-hidden">
            {/* Preview window: latest stream content */}
            <div className="border-b border-border/20 px-3 py-2">
              {latestContent ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-1.5">
                    <Cpu
                      className="w-2.5 h-2.5 flex-shrink-0"
                      style={{
                        color: latestIdx >= 0
                          ? colorForIndex(latestIdx)
                          : workerColor,
                      }}
                    />
                    <span className="text-[10px] text-muted-foreground/70 font-medium">
                      {latestLabel}
                    </span>
                  </div>
                  <div
                    ref={previewRef}
                    className="text-sm leading-relaxed max-h-[120px] overflow-y-auto"
                  >
                    <MarkdownContent content={latestContent} />
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-1.5 py-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
              )}
            </div>

            {/* Subagent squares row */}
            <div className="flex items-start gap-3 px-3 py-2.5 flex-wrap">
              {groups.map((group, i) => (
                <SubagentSquare
                  key={groupKey(group)}
                  group={group}
                  index={i}
                  label={labels[i]}
                  isLatest={latestIdx === i}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
},
(prev, next) =>
  prev.groupId === next.groupId &&
  prev.groups.length === next.groups.length &&
  prev.groups.every(
    (g, i) =>
      g.nodeId === next.groups[i].nodeId &&
      g.messages.length === next.groups[i].messages.length &&
      last(g.messages)?.content === last(next.groups[i].messages)?.content &&
      g.contextUsage?.usagePct === next.groups[i].contextUsage?.usagePct
  ));

export default ParallelSubagentBubble;
