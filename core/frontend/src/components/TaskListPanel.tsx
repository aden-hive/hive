/**
 * Task list panel — renders one task list (queen-DM session, colony
 * template, or worker session). Variants:
 *
 *   variant="rail"      -> right-rail panel with header & close button
 *   variant="embedded"  -> inline (e.g., inside WorkerDetail)
 */

import { useRef, useState } from "react";
import { ChevronDown, ChevronRight, X } from "lucide-react";

import {
  TaskListProvider,
  useTaskList,
  bucketTasks,
  unresolvedBlockers,
} from "@/context/TaskListContext";
import TaskItem from "@/components/TaskItem";
import type { TaskRecord } from "@/api/tasks";

interface TaskListPanelProps {
  taskListId: string;
  sessionId?: string;
  /** Override the default header label. */
  title?: string;
  variant?: "rail" | "embedded";
  onClose?: () => void;
}

export default function TaskListPanel(props: TaskListPanelProps) {
  return (
    <TaskListProvider taskListId={props.taskListId} sessionId={props.sessionId}>
      <TaskListPanelInner {...props} />
    </TaskListProvider>
  );
}

function TaskListPanelInner({ title, variant = "rail", onClose }: TaskListPanelProps) {
  const { tasks, loading, error, role, exists } = useTaskList();
  const buckets = bucketTasks(tasks);

  // Don't render anything when the list doesn't exist yet AND we're in
  // the rail variant (queen-DM session that hasn't created any task).
  // The embedded variant always shows so the section in WorkerDetail/
  // colony overview keeps a stable layout.
  if (!loading && !exists && variant === "rail") return null;

  const [activeOpen, setActiveOpen] = useState(true);
  const [pendingOpen, setPendingOpen] = useState(true);
  const [completedOpen, setCompletedOpen] = useState(false);

  const itemRefs = useRef(new Map<number, HTMLLIElement>());
  const handleJumpToBlocker = (id: number) => {
    const node = itemRefs.current.get(id);
    if (!node) return;
    node.scrollIntoView({ behavior: "smooth", block: "center" });
    node.classList.add("ring-2", "ring-primary/40");
    setTimeout(() => node.classList.remove("ring-2", "ring-primary/40"), 1500);
  };

  const headerLabel =
    title ??
    (role === "template"
      ? "Colony plan"
      : role === "session"
      ? "Tasks"
      : "Tasks");
  const inProgressCount = buckets.active.length;
  const totalVisible = buckets.visible.length;

  return (
    <aside
      className={
        variant === "rail"
          ? "w-[320px] flex-shrink-0 border-l border-border bg-background flex flex-col h-full overflow-hidden"
          : "w-full border border-border rounded-md bg-background flex flex-col"
      }
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <span>{headerLabel}</span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {inProgressCount}/{totalVisible}
          </span>
        </h2>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {loading ? (
          <p className="text-xs text-muted-foreground p-2">Loading…</p>
        ) : error ? (
          <p className="text-xs text-destructive p-2">Error: {error}</p>
        ) : totalVisible === 0 ? (
          <p className="text-xs text-muted-foreground p-2">
            {role === "template"
              ? "No template entries yet. The queen will populate this when planning a fan-out."
              : "No tasks yet. The agent will create them as it plans."}
          </p>
        ) : (
          <>
            {/* Completed sits above Active so finished tasks stay visually
             *  "above" the work that came after them — preserves the order
             *  the user originally saw before the status flipped. */}
            <Section
              label="Completed"
              count={buckets.completed.length}
              open={completedOpen}
              onToggle={() => setCompletedOpen((v) => !v)}
            >
              {buckets.completed.map((t) => (
                <RefItem
                  key={t.id}
                  task={t}
                  itemRefs={itemRefs}
                  unresolved={[]}
                  onJumpToBlocker={handleJumpToBlocker}
                />
              ))}
            </Section>
            <Section
              label="Active"
              count={buckets.active.length}
              open={activeOpen}
              onToggle={() => setActiveOpen((v) => !v)}
            >
              {buckets.active.map((t) => (
                <RefItem
                  key={t.id}
                  task={t}
                  itemRefs={itemRefs}
                  unresolved={unresolvedBlockers(t, buckets.completedIds)}
                  onJumpToBlocker={handleJumpToBlocker}
                />
              ))}
            </Section>
            <Section
              label="Pending"
              count={buckets.pending.length}
              open={pendingOpen}
              onToggle={() => setPendingOpen((v) => !v)}
            >
              {buckets.pending.map((t) => (
                <RefItem
                  key={t.id}
                  task={t}
                  itemRefs={itemRefs}
                  unresolved={unresolvedBlockers(t, buckets.completedIds)}
                  onJumpToBlocker={handleJumpToBlocker}
                />
              ))}
            </Section>
          </>
        )}
      </div>
    </aside>
  );
}

function Section({
  label,
  count,
  open,
  onToggle,
  children,
}: {
  label: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-1 text-xs font-medium text-muted-foreground px-2 py-1 hover:text-foreground"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span>{label}</span>
        <span className="tabular-nums">({count})</span>
      </button>
      {open ? <ul className="space-y-0.5">{children}</ul> : null}
    </div>
  );
}

function RefItem({
  task,
  itemRefs,
  unresolved,
  onJumpToBlocker,
}: {
  task: TaskRecord;
  itemRefs: React.MutableRefObject<Map<number, HTMLLIElement>>;
  unresolved: number[];
  onJumpToBlocker: (id: number) => void;
}) {
  return (
    <li
      ref={(el) => {
        if (el) itemRefs.current.set(task.id, el);
        else itemRefs.current.delete(task.id);
      }}
      className="rounded transition-shadow"
    >
      <TaskItem
        task={task}
        unresolvedBlockers={unresolved}
        onJumpToBlocker={onJumpToBlocker}
      />
    </li>
  );
}

// ---------------------------------------------------------------------------
// Stacked variant: two TaskListPanels (colony template + queen session).
// Used in the colony chat right rail.
// ---------------------------------------------------------------------------

interface TaskListPanelStackedProps {
  templateTaskListId: string;
  queenSessionTaskListId: string | null;
  sessionId: string;
  onClose?: () => void;
}

export function TaskListPanelStacked(props: TaskListPanelStackedProps) {
  return (
    <aside className="w-[320px] flex-shrink-0 border-l border-border bg-background flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <h2 className="text-sm font-semibold">Tasks</h2>
        {props.onClose ? (
          <button
            type="button"
            onClick={props.onClose}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <div className="flex-1 min-h-0 overflow-hidden border-b border-border">
          <TaskListPanel
            taskListId={props.templateTaskListId}
            sessionId={props.sessionId}
            title="Colony plan"
            variant="embedded"
          />
        </div>
        {props.queenSessionTaskListId ? (
          <div className="flex-1 min-h-0 overflow-hidden">
            <TaskListPanel
              taskListId={props.queenSessionTaskListId}
              sessionId={props.sessionId}
              title="Queen's notes"
              variant="embedded"
            />
          </div>
        ) : null}
      </div>
    </aside>
  );
}
