import { useState } from "react";
import { Check, Circle, Hourglass, Loader2 } from "lucide-react";

import type { TaskRecord, TaskStatus } from "@/api/tasks";

interface TaskItemProps {
  task: TaskRecord;
  unresolvedBlockers: number[];
  onJumpToBlocker?: (id: number) => void;
}

const STATUS_ICON: Record<TaskStatus, JSX.Element> = {
  in_progress: (
    <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" aria-label="in progress" />
  ),
  pending: <Circle className="h-3.5 w-3.5 text-muted-foreground" aria-label="pending" />,
  completed: <Check className="h-3.5 w-3.5 text-emerald-600" aria-label="completed" />,
};

function elapsedSince(ts: number): string {
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - ts);
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ${Math.floor(diff % 60)}s`;
  return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`;
}

export default function TaskItem({ task, unresolvedBlockers, onJumpToBlocker }: TaskItemProps) {
  const [expanded, setExpanded] = useState(false);
  const isBlocked = task.status === "pending" && unresolvedBlockers.length > 0;
  const elapsed = task.status === "in_progress" ? elapsedSince(task.updated_at) : null;

  return (
    <li className="group">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left flex items-start gap-2 px-2 py-1.5 rounded hover:bg-muted/50 focus:bg-muted/60 focus:outline-none"
      >
        <span className="mt-0.5 flex-shrink-0">
          {isBlocked ? (
            <Hourglass
              className="h-3.5 w-3.5 text-muted-foreground/70"
              aria-label="waiting on dependency"
            />
          ) : (
            STATUS_ICON[task.status]
          )}
        </span>
        <span className="flex-1 min-w-0">
          <span className="text-sm flex items-baseline gap-1.5">
            <span className="text-muted-foreground tabular-nums">#{task.id}</span>
            <span className="truncate">
              {task.status === "in_progress" && task.active_form
                ? task.active_form
                : task.subject}
            </span>
          </span>
          <span className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
            {task.owner ? (
              <span className="rounded bg-muted px-1.5 py-0.5">{task.owner.slice(0, 12)}</span>
            ) : null}
            {elapsed ? <span>{elapsed}</span> : null}
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
        <div className="ml-7 mb-2 text-xs text-muted-foreground space-y-1">
          {task.description ? <p className="whitespace-pre-wrap">{task.description}</p> : null}
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
    </li>
  );
}
