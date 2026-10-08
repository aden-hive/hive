import { memo } from "react";
import { Cpu } from "lucide-react";
import type { ChatMessage } from "@/components/ChatPanel";
import { useColonyWorkers } from "@/context/ColonyWorkersContext";
import { workerIdFromStreamId } from "@/lib/chat-helpers";

const workerColor = "hsl(220,60%,55%)";

export interface WorkerRunGroup {
  messages: ChatMessage[];
}

interface WorkerRunBubbleProps {
  runId: string;
  group: WorkerRunGroup;
  /** Short identifier shown next to the "Worker" badge. Populated
   *  only when the parent grouping has multiple parallel workers
   *  in the same run span, so N stacked bubbles can be told apart
   *  at a glance. Omitted for single-worker runs. */
  label?: string;
}

type RunPhase = "running" | "completed" | "stopped";

/** Collapse the raw API ``status`` string into the three buckets the
 *  bubble renders. Synonyms (``claimed``/``in_progress`` for in-flight,
 *  ``done`` for completed) are folded in so the pill agrees with the
 *  Workers panel's own status classes regardless of which legacy
 *  label the runtime emits. Unknown / empty falls into ``stopped``. */
function runPhaseFromStatus(status: string | undefined | null): RunPhase {
  const s = (status || "").toLowerCase();
  if (s === "pending" || s === "running" || s === "claimed" || s === "in_progress")
    return "running";
  if (s === "completed" || s === "done") return "completed";
  return "stopped";
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
 * Strip markdown formatting so the head/tail previews are single
 * readable lines instead of a scatter of code pills.
 *
 * MarkdownContent turns every backtick-wrapped fragment into its own
 * visually-boxed inline-code pill. In a worker text message those
 * pills can be coordinates, UUIDs, selectors, tool names — the
 * preview ends up looking like confetti. We just want the plain
 * prose, one line, truncated.
 */
function stripMarkdownToPreview(s: string, maxLen = 200): string {
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
  return cleaned.slice(0, maxLen - 1).trimEnd() + "…";
}

/**
 * Compact, single-state worker run bubble.
 *
 * Shows the worker's first text (head) so you can see what it started
 * on, a wrap-row of tool pills so you can see what it's been doing,
 * and the latest text (tail) so you can see where it currently is.
 * Together those three rows tell you the worker is alive and roughly
 * what it's doing without revealing the full transcript inline.
 *
 * Clicking anywhere on the bubble (avatar, header, or body) opens the
 * Colony side panel scoped to this worker, where the full transcript
 * lives. Tool pills retain their in-line drill-down for args/result;
 * their click is stopped from also opening the panel.
 */
const WorkerRunBubble = memo(
  function WorkerRunBubble({ group, label }: WorkerRunBubbleProps) {
    const { openColonyWorkers, workers } = useColonyWorkers();

    // Derive the colony worker id from the first message that carries
    // a parallel-worker streamId (``worker:{uuid}``). Legacy single-worker
    // bubbles (streamId="worker") have no uuid — the click still opens
    // the sidebar, just without a preselection.
    const workerId = (() => {
      for (const m of group.messages) {
        const id = workerIdFromStreamId(m.streamId);
        if (id) return id;
      }
      return null;
    })();
    const openPanel = () => openColonyWorkers(workerId ?? undefined);

    // Match to the polled worker record so the pill mirrors the
    // Workers panel exactly. Legacy bubbles with no parseable
    // worker_id (workerId=null) fall through to "stopped" —
    // historically-correct for the single-worker-no-uuid case
    // where these bubbles only appear after the run has ended.
    const workerRecord = workerId
      ? workers.find((w) => w.worker_id === workerId)
      : undefined;
    const runPhase = runPhaseFromStatus(workerRecord?.status);

    const pillClass =
      runPhase === "running"
        ? "bg-amber-500/15 text-amber-400"
        : runPhase === "completed"
          ? "bg-emerald-500/15 text-emerald-500"
          : "bg-muted text-muted-foreground";
    const cardClass =
      runPhase === "running"
        ? "border-amber-500/30 bg-amber-500/10 hover:bg-amber-500/15"
        : runPhase === "completed"
          ? "border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/15"
          : "border-border bg-muted/60 hover:bg-muted/80";

    const textMsgs = group.messages.filter(
      (m) => m.type !== "tool_status" && m.content?.trim(),
    );
    const toolStatusMsgs = group.messages.filter(
      (m) => m.type === "tool_status",
    );

    const allTools = toolStatusMsgs.flatMap((m) => parseToolStatus(m.content));
    const toolCount = allTools.length;
    const doneCount = allTools.filter((t) => t.done).length;

    // Unique tool names in first-appearance order — the chain is a
    // glanceable shape-of-the-run, not a full per-call list.
    const uniqueNames: string[] = [];
    const seen = new Set<string>();
    for (const t of allTools) {
      if (!seen.has(t.name)) {
        seen.add(t.name);
        uniqueNames.push(t.name);
      }
    }
    const HEAD = 2;
    const TAIL = 2;
    const isLong = uniqueNames.length > HEAD + TAIL;
    const chainParts = isLong
      ? [...uniqueNames.slice(0, HEAD), "⋯", ...uniqueNames.slice(-TAIL)]
      : uniqueNames;
    const hiddenCount = isLong ? uniqueNames.length - HEAD - TAIL : 0;

    // Head: the queen-authored `goal` wins when present — it's the plain-
    // language "what is this worker doing" seeded at spawn, present from t=0
    // even for unwatched workers, and spares non-technical users the raw
    // task prompt (username lists, bindings, protocol text). Watched workers
    // fall back to their streamed prose, then to the raw task string —
    // scraping only llm_text_delta would leave every unwatched bubble blank,
    // while `task` and `result.summary` are already in the 2s workers poll.
    const headText =
      workerRecord?.goal?.trim() ||
      textMsgs[0]?.content?.trim() ||
      (workerRecord?.task ?? "");
    const streamedTail = textMsgs[textMsgs.length - 1]?.content?.trim() ?? "";
    const tailText = streamedTail || (workerRecord?.result?.summary ?? "");
    const showTail = !!tailText && tailText !== headText;

    // Progress: prefer the worker's own task list (from the poll) over the
    // tool-call count, which is only observable while watching.
    const taskSummary = workerRecord?.task_summary ?? null;
    const progressLabel =
      taskSummary && taskSummary.total > 0
        ? `${taskSummary.completed}/${taskSummary.total} tasks`
        : toolCount > 0
          ? `${doneCount}/${toolCount} tools`
          : null;

    return (
      <div className="flex gap-3">
        {/* Avatar — opens the Colony side panel for this worker. */}
        <button
          type="button"
          onClick={openPanel}
          aria-label="Open worker session"
          title="Open worker session"
          className="flex-shrink-0 w-7 h-7 rounded-xl flex items-center justify-center mt-1 transition-opacity hover:opacity-80 cursor-pointer"
          style={{
            backgroundColor: `${workerColor}18`,
            border: `1.5px solid ${workerColor}35`,
          }}
        >
          <Cpu className="w-3.5 h-3.5" style={{ color: workerColor }} />
        </button>

        <div className="flex-1 min-w-0 max-w-[90%]">
          {/* Header — same click target as the body. */}
          <button
            type="button"
            onClick={openPanel}
            className="w-full flex items-center gap-2 mb-1 text-left cursor-pointer"
            title="Open worker session"
          >
            <span
              className="font-medium text-xs"
              style={{ color: workerColor }}
            >
              Worker
            </span>
            {label && (
              <span className="text-[10px] font-mono text-muted-foreground/80 tabular-nums">
                {label}
              </span>
            )}
            <span
              className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md ${pillClass}`}
            >
              {runPhase}
            </span>
            {progressLabel && (
              <span className="text-[10px] text-muted-foreground tabular-nums">
                {progressLabel}
              </span>
            )}
          </button>

          <div
            role="button"
            tabIndex={0}
            onClick={openPanel}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openPanel();
              }
            }}
            className={`rounded-2xl rounded-tl-md border cursor-pointer transition-colors ${cardClass}`}
          >
            <div className="px-4 py-3 space-y-2">
              {headText ? (
                <div className="text-sm text-muted-foreground truncate">
                  {stripMarkdownToPreview(headText)}
                </div>
              ) : toolCount === 0 ? (
                <div className="text-xs text-muted-foreground/60 italic">
                  {"waiting for first action…"}
                </div>
              ) : null}

              {chainParts.length > 0 && (
                <div className="text-xs font-mono text-muted-foreground truncate">
                  {chainParts.join(" · ")}
                  {hiddenCount > 0 && (
                    <span className="text-muted-foreground/60 ml-1 font-sans not-italic">
                      (+{hiddenCount})
                    </span>
                  )}
                </div>
              )}

              {showTail && (
                <div className="text-sm text-foreground/85 truncate">
                  {stripMarkdownToPreview(tailText)}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  },
  (prev, next) =>
    prev.runId === next.runId &&
    prev.label === next.label &&
    prev.group.messages.length === next.group.messages.length &&
    prev.group.messages[prev.group.messages.length - 1]?.content ===
      next.group.messages[next.group.messages.length - 1]?.content,
);

export default WorkerRunBubble;
