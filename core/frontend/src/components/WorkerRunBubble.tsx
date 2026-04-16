import { memo, useState, useRef, useEffect } from "react";
import { ChevronDown, ChevronUp, Cpu } from "lucide-react";
import type { ChatMessage } from "@/components/ChatPanel";
import MarkdownContent from "@/components/MarkdownContent";

const workerColor = "hsl(220,60%,55%)";

export interface WorkerRunGroup {
  messages: ChatMessage[];
}

interface WorkerRunBubbleProps {
  runId: string;
  group: WorkerRunGroup;
}

/** Parse a tool_status JSON blob into a list of tool entries. */
function parseToolStatus(content: string): { name: string; done: boolean }[] {
  try {
    const parsed = JSON.parse(content);
    return parsed.tools || [];
  } catch {
    return [];
  }
}

/**
 * Strip markdown formatting so the collapsed preview is a single
 * readable line instead of a scatter of code pills.
 *
 * MarkdownContent turns every backtick-wrapped fragment into its own
 * visually-boxed inline-code pill. In a worker text message those
 * pills can be coordinates, UUIDs, selectors, tool names — the
 * collapsed preview ends up looking like confetti. We just want the
 * plain prose, one line, truncated.
 */
function stripMarkdownToPreview(s: string, maxLen = 160): string {
  const cleaned = s
    .replace(/```[\s\S]*?```/g, " [code] ") // fenced code blocks
    .replace(/`([^`]+)`/g, "$1") // inline code — keep the text, drop the backticks
    .replace(/\*\*([^*]+)\*\*/g, "$1") // bold
    .replace(/\*([^*]+)\*/g, "$1") // italic
    .replace(/~~([^~]+)~~/g, "$1") // strikethrough
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // links -> link text
    .replace(/^#{1,6}\s+/gm, "") // ATX headers
    .replace(/^[>\-*+]\s+/gm, "") // blockquote/list markers
    .replace(/\s+/g, " ") // collapse whitespace
    .trim();
  if (cleaned.length <= maxLen) return cleaned;
  return cleaned.slice(0, maxLen - 1).trimEnd() + "\u2026";
}

/**
 * Collapsible card that groups all worker messages from a single run
 * (the span between the queen's `run_agent_with_input` call and the
 * worker's final `set_output`/`escalate`/idle).
 *
 * Collapsed (default): header bar with tool count + latest text snippet.
 * Expanded: scrollable list of every message and tool status in order.
 */
const WorkerRunBubble = memo(
  function WorkerRunBubble({ group }: WorkerRunBubbleProps) {
    const [expanded, setExpanded] = useState(false);
    const bodyRef = useRef<HTMLDivElement>(null);

    // Separate text messages from tool status
    const textMsgs = group.messages.filter(
      (m) => m.type !== "tool_status" && m.content?.trim()
    );
    const toolStatusMsgs = group.messages.filter(
      (m) => m.type === "tool_status"
    );

    // Count total tool calls from tool_status messages
    const allTools: { name: string; done: boolean }[] = [];
    for (const m of toolStatusMsgs) {
      for (const t of parseToolStatus(m.content)) {
        allTools.push(t);
      }
    }
    const toolCount = allTools.length;
    const doneCount = allTools.filter((t) => t.done).length;
    const isFinished = toolCount > 0 && doneCount === toolCount;

    // Latest text from the worker (the last non-empty text message)
    const latestText = textMsgs.length > 0
      ? textMsgs[textMsgs.length - 1].content
      : "";

    // Status label. We prefer concrete states over the vague
    // "starting" fallback — if the worker has emitted any text or
    // any tool, it's past the startup phase.
    const statusLabel = isFinished
      ? "done"
      : toolCount > 0
        ? "running"
        : textMsgs.length > 0
          ? "active"
          : "starting";

    // Unique tool names for the summary (deduplicated, ordered by first appearance)
    const uniqueToolNames: string[] = [];
    const seen = new Set<string>();
    for (const t of allTools) {
      if (!seen.has(t.name)) {
        seen.add(t.name);
        uniqueToolNames.push(t.name);
      }
    }

    // Auto-scroll body when expanded
    useEffect(() => {
      if (expanded && bodyRef.current) {
        bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
      }
    }, [expanded, group.messages.length]);

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
          {/* Clickable header */}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="w-full flex items-center gap-2 mb-1 text-left cursor-pointer group"
          >
            <span className="font-medium text-xs" style={{ color: workerColor }}>
              Worker
            </span>
            <span
              className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md ${
                isFinished
                  ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {statusLabel}
            </span>
            {toolCount > 0 && (
              <span className="text-[10px] text-muted-foreground tabular-nums">
                {doneCount}/{toolCount} tools
              </span>
            )}
            <span className="ml-auto text-muted-foreground/60 group-hover:text-muted-foreground transition-colors p-0.5 rounded">
              {expanded ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </span>
          </button>

          {/* Card body — use Tailwind theme tokens so dark mode
              gets a proper dark background instead of a glaring
              near-white hardcoded hsl. Finished runs get a subtle
              green tint that also respects theme. */}
          <div
            className={`rounded-2xl rounded-tl-md overflow-hidden border ${
              isFinished
                ? "border-green-300/50 bg-green-50/50 dark:border-green-900/40 dark:bg-green-950/20"
                : "border-border bg-muted/60"
            }`}
          >
            {/* Collapsed: single-line plain-text preview of the
                latest worker text, OR a tool-name chain when the
                worker hasn't emitted any prose yet. MarkdownContent
                is intentionally NOT used here — its inline-code
                rendering turns every backtick-wrapped fragment into
                a floating pill, which wrecks the preview. */}
            {!expanded && (
              <div className="px-4 py-2.5 text-sm text-muted-foreground">
                {latestText ? (
                  <div className="truncate">
                    {stripMarkdownToPreview(latestText)}
                  </div>
                ) : uniqueToolNames.length > 0 ? (
                  <span className="text-xs font-mono truncate block">
                    {uniqueToolNames.slice(0, 5).join(" \u2192 ")}
                    {uniqueToolNames.length > 5 &&
                      ` + ${uniqueToolNames.length - 5} more`}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground/60 italic">
                    {"waiting for first action\u2026"}
                  </span>
                )}
              </div>
            )}

            {/* Expanded: full scrollable message stream */}
            {expanded && (
              <div
                ref={bodyRef}
                className="max-h-[400px] overflow-y-auto px-4 py-3 space-y-2"
              >
                {group.messages.map((m, i) => {
                  if (m.type === "tool_status") {
                    const tools = parseToolStatus(m.content);
                    if (tools.length === 0) return null;
                    return (
                      <div key={m.id || i} className="flex flex-wrap gap-1.5">
                        {tools.map((t, ti) => (
                          <span
                            key={ti}
                            className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md border ${
                              t.done
                                ? "bg-green-50 border-green-200 text-green-700 dark:bg-green-900/20 dark:border-green-800 dark:text-green-400"
                                : "bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-900/20 dark:border-blue-800 dark:text-blue-400"
                            }`}
                          >
                            <span>{t.done ? "\u2713" : "\u25cf"}</span>
                            <span className="font-mono">{t.name}</span>
                          </span>
                        ))}
                      </div>
                    );
                  }
                  if (!m.content?.trim()) return null;
                  return (
                    <div key={m.id || i} className="text-sm leading-relaxed">
                      <MarkdownContent content={m.content} />
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  },
  (prev, next) =>
    prev.runId === next.runId &&
    prev.group.messages.length === next.group.messages.length &&
    prev.group.messages[prev.group.messages.length - 1]?.content ===
      next.group.messages[next.group.messages.length - 1]?.content
);

export default WorkerRunBubble;
