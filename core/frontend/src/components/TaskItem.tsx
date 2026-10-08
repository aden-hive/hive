import { useState } from "react";
import { Archive, Check, Circle, Hourglass, Loader2, Square, CheckSquare } from "lucide-react";

import { type TaskRecord, type TaskStatus } from "@/api/tasks";
import { isTaskIdle } from "@/context/TaskListContext";

interface TaskItemProps {
  task: TaskRecord;
  unresolvedBlockers: number[];
  onJumpToBlocker?: (id: number) => void;
  /** Historical (previous-session) plan. The session is no longer
   *  running, so render static: no spinner, no live elapsed timer, and
   *  the plain subject instead of the present-continuous active form. */
  readOnly?: boolean;
}

const STATUS_ICON: Record<TaskStatus, JSX.Element> = {
  in_progress: (
    <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" aria-label="in progress" />
  ),
  pending: <Square className="h-3.5 w-3.5 text-muted-foreground/60" aria-label="pending" />,
  completed: <CheckSquare className="h-3.5 w-3.5 text-emerald-600" aria-label="completed" />,
  // Abandoned: the sweep job swept this stale in_progress task because the
  // queen never circled back. Same dim look as the client-side "idle" state.
  abandoned: <Square className="h-3.5 w-3.5 text-muted-foreground/40" aria-label="abandoned" />,
  // Archived: the user cleared the plan. Only ever rendered inside the
  // collapsed "Archived" group (read-only), so this icon is the resting
  // look for a parked row.
  archived: <Archive className="h-3.5 w-3.5 text-muted-foreground/50" aria-label="archived" />,
};

function elapsedSince(ts: number): string {
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - ts);
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ${Math.floor(diff % 60)}s`;
  return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`;
}

export default function TaskItem({
  task,
  unresolvedBlockers,
  onJumpToBlocker,
  readOnly = false,
}: TaskItemProps) {
  const [expanded, setExpanded] = useState(false);
  const isBlocked = task.status === "pending" && unresolvedBlockers.length > 0;
  // Two sources of "this row is stale": the server has flipped status to
  // "abandoned" via the sweep job, OR the client-side fallback (`isTaskIdle`)
  // has caught a still-in_progress task that just crossed the threshold but
  // hasn't been re-fetched yet. Both render the same dim look.
  const idle = task.status === "abandoned" || isTaskIdle(task);
  // An in_progress task in a read-only historical plan isn't actually
  // running — the session ended mid-task. Render it static, like a
  // pending row, with no spinner and no ever-frozen elapsed timer.
  const staleInProgress = readOnly && task.status === "in_progress";
  const elapsed =
    !readOnly && task.status === "in_progress" && !idle
      ? elapsedSince(task.updated_at)
      : null;

  return (
    <div className="group">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left flex items-start gap-2 px-2 py-1.5 rounded text-foreground hover:bg-muted/50 focus:bg-muted/60 focus:outline-none"
      >
        <span className="mt-0.5 flex-shrink-0">
          {isBlocked ? (
            <Hourglass
              className="h-3.5 w-3.5 text-muted-foreground/70"
              aria-label="waiting on dependency"
            />
          ) : idle ? (
            <Square className="h-3.5 w-3.5 text-muted-foreground/40" aria-label="idle" />
          ) : staleInProgress ? (
            <Square className="h-3.5 w-3.5 text-muted-foreground/60" aria-label="unfinished" />
          ) : (
            STATUS_ICON[task.status]
          )}
        </span>
        <span className="flex-1 min-w-0">
          <span className={`text-sm flex items-baseline gap-1.5 ${task.status === "completed" ? "line-through text-muted-foreground" : idle ? "text-muted-foreground" : ""}`}>
            <span className="truncate">
              {/* `active_form` is present-continuous ("Doing X…") — only
                  honest while the task is genuinely running. Fall back to
                  the static subject for idle and historical (read-only) rows. */}
              {!readOnly && task.status === "in_progress" && !idle && task.active_form
                ? task.active_form
                : task.subject}
            </span>
          </span>
          <span className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
            {elapsed ? <span>{elapsed}</span> : null}
            {idle ? <span className="italic">idle</span> : null}
            {unresolvedBlockers.length > 0 ? (
              <span>
                blocked by{" "}
                {unresolvedBlockers.map((b, idx) => (
                  <span key={b}>
                    <button
                      type="button"
                      className="text-foreground/70 hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        onJumpToBlocker?.(b);
                      }}
                    >
                      #{b}
                    </button>
                    {idx < unresolvedBlockers.length - 1 ? ", " : ""}
                  </span>
                ))}
              </span>
            ) : null}
          </span>
        </span>
      </button>
      {expanded ? (
        <div className="ml-7 mb-2 text-xs text-muted-foreground space-y-1.5">
          {task.description ? (
            <p className="whitespace-pre-wrap">{task.description}</p>
          ) : null}
          {task.metadata && Object.keys(task.metadata).length > 0 ? (
            <pre className="text-[10px] bg-muted/40 rounded p-2 overflow-x-auto">
              {JSON.stringify(task.metadata, null, 2)}
            </pre>
          ) : null}
          <p className="text-[10px]">
            updated {new Date(task.updated_at * 1000).toLocaleString()}
          </p>
        </div>
      ) : null}
    </div>
  );
}
