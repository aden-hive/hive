import { memo, useState, useRef, useEffect } from "react";
import { ChevronDown, ChevronUp, Cpu } from "lucide-react";
import type { ChatMessage, ContextUsageEntry } from "@/components/ChatPanel";
import MarkdownContent from "@/components/MarkdownContent";

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const workerColor = "hsl(220,60%,55%)";

const SUBAGENT_COLORS = [
  "hsl(220,60%,55%)",
  "hsl(260,50%,55%)",
  "hsl(180,50%,45%)",
  "hsl(30,70%,50%)",
  "hsl(340,55%,50%)",
  "hsl(150,45%,45%)",
  "hsl(45,80%,50%)",
  "hsl(290,45%,55%)",
];

function colorForIndex(i: number): string {
  return SUBAGENT_COLORS[i % SUBAGENT_COLORS.length];
}

function subagentLabel(nodeId: string): string {
  const parts = nodeId.split(":subagent:");
  const raw = parts.length >= 2 ? parts[1] : nodeId;
  return raw
    .replace(/:\d+$/, "") // strip instance suffix like ":3"
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

function last<T>(arr: T[]): T | undefined {
  return arr[arr.length - 1];
}

export interface SubagentGroup {
  nodeId: string;
  messages: ChatMessage[];
  contextUsage?: ContextUsageEntry;
}

interface ParallelSubagentBubbleProps {
  groups: SubagentGroup[];
  groupId: string;
}

// ---------------------------------------------------------------------------
// Thermometer — vertical context gauge on right edge of each pane
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Tool overlay — shown when a tool_status message is active (not all done)
// ---------------------------------------------------------------------------

function ToolOverlay({
  toolName,
  color,
  visible,
}: {
  toolName: string;
  color: string;
  visible: boolean;
}) {
  return (
    <div
      className="absolute inset-0 top-[22px] flex items-center justify-center transition-opacity duration-200 z-10"
      style={{
        background: "rgba(8,8,14,0.82)",
        opacity: visible ? 1 : 0,
        pointerEvents: visible ? "auto" : "none",
      }}
    >
      <div className="text-center px-3 py-2 rounded-md border" style={{ borderColor: `${color}40` }}>
        <div className="text-[10px] font-medium" style={{ color }}>
          {toolName}
        </div>
        <div className="text-[11px] mt-0.5" style={{ color }}>
          {visible ? "..." : "\u2713"}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single tmux pane
// ---------------------------------------------------------------------------

function MuxPane({
  group,
  index,
  label,
  isFocused,
  isZoomed,
  onClickTitle,
}: {
  group: SubagentGroup;
  index: number;
  label: string;
  isFocused: boolean;
  isZoomed: boolean;
  onClickTitle: () => void;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const color = colorForIndex(index);
  const pct = group.contextUsage?.usagePct ?? 0;

  const streamMsgs = group.messages.filter((m) => m.type !== "tool_status");
  const latestContent = last(streamMsgs)?.content ?? "";
  const msgCount = streamMsgs.length;

  // Detect active tool and finished state from latest tool_status
  const latestTool = last(
    group.messages.filter((m) => m.type === "tool_status")
  );
  let activeToolName = "";
  let toolRunning = false;
  let isFinished = false;
  if (latestTool) {
    try {
      const parsed = JSON.parse(latestTool.content);
      const tools: { name: string; done: boolean }[] = parsed.tools || [];
      const allDone = parsed.allDone as boolean | undefined;
      const running = tools.find((t) => !t.done);
      if (running) {
        activeToolName = running.name;
        toolRunning = true;
      }
      // Finished when all tools are done and one of them is set_output
      // or report_to_parent (terminal tool calls)
      if (allDone && tools.length > 0) {
        const hasTerminal = tools.some(
          (t) =>
            t.done &&
            (t.name === "set_output" || t.name === "report_to_parent")
        );
        if (hasTerminal) isFinished = true;
      }
    } catch {
      /* ignore */
    }
  }

  // Auto-scroll
  useEffect(() => {
    if (stickRef.current && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [latestContent]);

  const handleScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
  };

  return (
    <div
      className="flex flex-col min-h-0 overflow-hidden relative transition-all duration-200"
      style={{
        borderWidth: 1,
        borderStyle: "solid",
        borderColor: isFocused && !isFinished ? `${color}60` : "transparent",
        opacity: isFinished ? 0.4 : isFocused || isZoomed ? 1 : 0.55,
        ...(isZoomed
          ? { gridColumn: "1 / -1", gridRow: "1 / -1", zIndex: 10 }
          : {}),
      }}
    >
      {/* Title bar */}
      <div
        className="flex items-center gap-1.5 px-2 py-[3px] flex-shrink-0 cursor-pointer select-none"
        style={{ background: "#0e0e16", borderBottom: "1px solid #1a1a2a" }}
        onClick={onClickTitle}
      >
        {isFinished ? (
          <span className="text-[8px] flex-shrink-0 leading-none" style={{ color: "#4a4" }}>&#10003;</span>
        ) : (
          <div
            className="w-[6px] h-[6px] rounded-full flex-shrink-0"
            style={{ background: color }}
          />
        )}
        <span className="text-[9px] flex-shrink-0" style={{ color: isFinished ? "#555" : color }}>
          {label}
        </span>
        <span className="flex-1" />
        <span className="text-[8px] tabular-nums flex-shrink-0" style={{ color: "#555" }}>
          {msgCount}
        </span>
        <div
          className="w-[36px] h-[3px] rounded-full overflow-hidden flex-shrink-0"
          style={{ background: "#1a1a2a" }}
        >
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${Math.min(pct, 100)}%`,
              backgroundColor:
                pct >= 80 ? "hsl(0,65%,55%)" : pct >= 50 ? "hsl(35,90%,55%)" : color,
            }}
          />
        </div>
        <span className="text-[8px] tabular-nums flex-shrink-0" style={{ color: "#555" }}>
          {pct}%
        </span>
      </div>

      {/* Body */}
      <div
        ref={bodyRef}
        onScroll={handleScroll}
        className="flex-1 min-h-0 overflow-y-auto px-2 py-1 text-[10px] leading-[1.7]"
        style={{ background: "#08080e", color: "#555", fontFamily: "monospace" }}
      >
        {latestContent ? (
          <div style={{ color: "#ccc" }}>
            <MarkdownContent content={latestContent} />
          </div>
        ) : (
          <span style={{ color: "#333" }}>waiting...</span>
        )}
        {/* Blinking cursor — hidden when finished */}
        {!isFinished && (
          <span
            className="inline-block w-[6px] h-[11px] align-middle ml-0.5"
            style={{
              background: color,
              animation: "cursorBlink 1s step-end infinite",
            }}
          />
        )}
      </div>

      {/* Tool overlay */}
      <ToolOverlay
        toolName={activeToolName}
        color={color}
        visible={toolRunning}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const ParallelSubagentBubble = memo(
  function ParallelSubagentBubble({ groups }: ParallelSubagentBubbleProps) {
    const [expanded, setExpanded] = useState(false);
    const [zoomedIdx, setZoomedIdx] = useState<number | null>(null);

    // Labels with instance numbers for duplicates
    const labels: string[] = (() => {
      const countByBase = new Map<string, number>();
      const bases = groups.map((g) => subagentLabel(g.nodeId));
      for (const b of bases)
        countByBase.set(b, (countByBase.get(b) ?? 0) + 1);
      const idxByBase = new Map<string, number>();
      return bases.map((b) => {
        if ((countByBase.get(b) ?? 1) <= 1) return b;
        const idx = (idxByBase.get(b) ?? 0) + 1;
        idxByBase.set(b, idx);
        return `${b} #${idx}`;
      });
    })();

    // Latest-active pane
    const latestIdx = groups.reduce<number>((best, g, i) => {
      const filtered = g.messages.filter((m) => m.type !== "tool_status");
      const lm = last(filtered);
      if (!lm) return best;
      if (best < 0) return i;
      const bm = last(
        groups[best].messages.filter((m) => m.type !== "tool_status")
      );
      if (!bm) return i;
      return (lm.createdAt ?? 0) >= (bm.createdAt ?? 0) ? i : best;
    }, -1);

    // Per-group finished detection (same logic as MuxPane)
    const finishedFlags = groups.map((g) => {
      const lt = last(g.messages.filter((m) => m.type === "tool_status"));
      if (!lt) return false;
      try {
        const p = JSON.parse(lt.content);
        const tools: { name: string; done: boolean }[] = p.tools || [];
        if (!p.allDone || tools.length === 0) return false;
        return tools.some(
          (t) => t.done && (t.name === "set_output" || t.name === "report_to_parent")
        );
      } catch { return false; }
    });
    const activeCount = finishedFlags.filter((f) => !f).length;

    if (groups.length === 0) return null;

    // Grid sizing: 2 columns, auto rows capped at a fixed height
    const rows = Math.ceil(groups.length / 2);
    const gridHeight = expanded
      ? Math.min(rows * 200, 480)
      : Math.min(rows * 100, 240);

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

        <div className="flex-1 min-w-0 max-w-[90%]">
          {/* Header */}
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-xs" style={{ color: workerColor }}>
              {groups.length === 1 ? "Sub-agent" : "Parallel Agents"}
            </span>
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground">
              {activeCount > 0 ? `${activeCount} running` : `${groups.length} done`}
            </span>
            <button
              onClick={() => {
                setExpanded((v) => !v);
                setZoomedIdx(null);
              }}
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

          {/* Mux frame */}
          <div
            className="rounded-lg overflow-hidden"
            style={{
              border: "2px solid #1a1a2a",
              background: "#08080e",
            }}
          >
            {/* Grid */}
            <div
              className="grid gap-px"
              style={{
                gridTemplateColumns:
                  groups.length === 1 ? "1fr" : "1fr 1fr",
                gridTemplateRows: `repeat(${rows}, 1fr)`,
                height: gridHeight,
                background: "#111",
              }}
            >
              {groups.map((group, i) => (
                <MuxPane
                  key={group.nodeId}
                  group={group}
                  index={i}
                  label={labels[i]}
                  isFocused={latestIdx === i}
                  isZoomed={zoomedIdx === i}
                  onClickTitle={() =>
                    setZoomedIdx(zoomedIdx === i ? null : i)
                  }
                />
              ))}
            </div>
          </div>
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
    )
);

export default ParallelSubagentBubble;

// Injected as a global style (keyframes can't be inline)
if (typeof document !== "undefined") {
  const id = "parallel-subagent-keyframes";
  if (!document.getElementById(id)) {
    const style = document.createElement("style");
    style.id = id;
    style.textContent = `
      @keyframes cursorBlink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
      @keyframes thermoPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
    `;
    document.head.appendChild(style);
  }
}
