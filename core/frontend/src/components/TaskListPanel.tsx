/**
 * Task list panel — renders one session task list (queen-DM session or
 * worker session). Variants:
 *
 *   variant="rail"      -> right-rail panel with header & close button
 *   variant="embedded"  -> inline (e.g., inside WorkerDetail)
 *
 * Tasks render ungrouped, in creation order. When `previousSessions` is
 * supplied (the queen-DM Action Plan) a collapsed "Previous sessions"
 * section lists each prior session's plan — so a session fork can swap
 * the live plan in without burying or losing the old one.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  CheckCheck,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  History,
  ListTodo,
  Loader2,
  Sparkles,
  Square,
  Trash2,
  X,
} from "lucide-react";

import {
  TaskListProvider,
  useTaskList,
  orderedVisibleTasks,
  archivedBatches,
  type ArchivedBatch,
  unresolvedBlockers,
} from "@/context/TaskListContext";
import TaskItem from "@/components/TaskItem";
import { tasksApi, type TaskRecord } from "@/api/tasks";
import { executionApi } from "@/api/execution";

/** Prompt sent to the queen when the user hits "Update plan". It lands in
 *  the conversation as a visible user message, phrased as a natural
 *  first-person request. The queen tidies its OWN task list — including
 *  archiving finished/stale tasks (task_update status="archived"), which
 *  moves them into History — so the active plan shows only current and
 *  upcoming work. No client-side archiving: the queen is the single owner
 *  of the plan, so there's no tug-of-war over it. */
const REFRESH_PLAN_PROMPT =
  "Can you review the action plan and bring it up to date? Mark anything " +
  "you've finished as complete, then archive the stale or " +
  "no-longer-relevant tasks so they move out of the active plan into " +
  "history. Make sure the work you're doing now and what's coming up next is " +
  "listed as clear pending tasks, so the active plan shows only your current " +
  "plan at a glance.";

/** Prompt sent to the queen when the user hits "Distill prompt". Like
 *  {@link REFRESH_PLAN_PROMPT} it lands as a visible first-person user
 *  message. It asks the queen to synthesize a single reusable prompt for
 *  the work she's currently doing, folding in everything she's learned from
 *  the colony's users so far (their feedback, preferences, and corrections).
 *  The output is meant to be handed to OTHER colonies, so it must read like
 *  a plain-language brief a business user would write — goal-first, no
 *  skill/tool names, file paths, or other internal machinery — so it stays
 *  readable and repeatable outside this colony's specific setup. */
const DISTILL_PROMPT_PROMPT =
  "Based on the tasks you're working on right now, write a single reusable " +
  "prompt that captures this work so another colony could pick it up and run " +
  "it. Fold in everything you've learned from this colony's users so far — " +
  "their feedback, preferences, and corrections — so the outcome reflects how " +
  "they like things done.\n\n" +
  "Write it for a business user, not an engineer:\n" +
  "- Lead with the goal and the outcome that defines success, then the steps " +
  "to get there.\n" +
  "- Use plain, everyday language. Don't name specific skills, tools, " +
  "integrations, file paths, or any internal machinery — describe what to " +
  "achieve, not the mechanics of how this colony happens to do it.\n" +
  "- Keep it self-contained and general enough to repeat in a different " +
  "colony with a different setup.\n\n" +
  "Return just the prompt.";

/** One prior session whose action plan can be folded into the panel. */
export interface PreviousSessionInfo {
  sessionId: string;
  /** Row label — typically the session's start date/time. */
  label: string;
}

interface TaskListPanelProps {
  /** The session whose task list to display. */
  sessionId: string;
  /** Optional SSE channel override — defaults to ``sessionId``. */
  eventSessionId?: string;
  /** Override the default header label. */
  title?: string;
  variant?: "rail" | "embedded";
  onClose?: () => void;
  /** Render nothing when the list has no visible tasks (and isn't loading
   *  or errored). Used by embedded sections that should collapse out of
   *  the layout instead of showing an empty-state message. */
  hideWhenEmpty?: boolean;
  /** Prior sessions of the same queen, newest first. When present the
   *  panel renders a collapsed "Previous sessions" section below the
   *  current plan. Omitted for worker / embedded views. */
  previousSessions?: PreviousSessionInfo[];
  /** Show the History + Update plan footer. Defaults to true for the rail
   *  variant (the queen-DM Action Plan). Embedded surfaces that are also a
   *  live, re-plannable queen session (the colony overview) pass `true`;
   *  worker embedded views leave it unset so they don't get the controls. */
  showActionControls?: boolean;
  /** How "Update plan" sends its prompt to the queen. Defaults to a direct
   *  `executionApi.chat` (queen-DM rail, whose chat renders the user bubble
   *  live from SSE). The colony overview lives in a SEPARATE tree from its
   *  chat, which surfaces user messages via an optimistic insert in its own
   *  `handleSend` — so it must pass that (ColonyWorkersContext's
   *  `requestQueenPrompt`) here, or the message won't appear until refresh. */
  sendPrompt?: (text: string) => void;
}

export default function TaskListPanel(props: TaskListPanelProps) {
  return (
    <TaskListProvider sessionId={props.sessionId} eventSessionId={props.eventSessionId}>
      <TaskListPanelInner {...props} />
    </TaskListProvider>
  );
}

function TaskListPanelInner({
  sessionId,
  title,
  variant = "rail",
  onClose,
  hideWhenEmpty = false,
  previousSessions,
  showActionControls,
  sendPrompt,
}: TaskListPanelProps) {
  const { tasks, loading, error, goal } = useTaskList();
  const ordered = orderedVisibleTasks(tasks);
  const inProgressCount = ordered.filter((t) => t.status === "in_progress").length;
  const totalVisible = ordered.length;
  const batchCount = useMemo(() => archivedBatches(tasks).length, [tasks]);

  // `hideWhenEmpty` only ever combines with embedded worker views, which
  // never pass `previousSessions` — so the empty current plan is the
  // whole panel and collapsing it out of layout is safe.
  if (hideWhenEmpty && !loading && !error && totalVisible === 0) {
    return null;
  }

  const headerLabel = title ?? "Tasks";
  // The History + Update plan controls: a live, re-plannable queen session
  // (the rail Action Plan, or an embedded overview that opts in) — never
  // worker embedded views or historical plans — and only once the list
  // actually exists (active work or an archived batch).
  const controlsEnabled = showActionControls ?? variant === "rail";
  const showControls =
    controlsEnabled && !loading && !error && (totalVisible > 0 || batchCount > 0);

  return (
    <aside
      className={
        variant === "rail"
          ? "w-[320px] flex-shrink-0 border-l border-border bg-background flex flex-col h-full overflow-hidden"
          : // An embedded panel that hosts the footer must fill its
            // container so the body scrolls and the footer pins to the
            // bottom (the colony overview); plain embedded views size to
            // content as before.
            `w-full border border-border rounded-md bg-background flex flex-col${
              controlsEnabled ? " h-full overflow-hidden" : ""
            }`
      }
    >
      <div className="flex items-start justify-between gap-2 px-3 py-2 border-b border-border">
        <div className="min-w-0">
          {/* When a goal (meta.goal) is set it becomes the panel title; the
              static label ("Action Plan"/"Tasks") demotes to a small eyebrow
              that carries the in-progress/total count. Falls back to the
              static label as the title when no goal is set. The goal is also
              the queen's pivot reference (the snapshot reminder / idle nudge
              surface this same string). */}
          {goal ? (
            <span className="block text-[11px] font-medium uppercase tracking-wide text-muted-foreground tabular-nums">
              {headerLabel} · {inProgressCount}/{totalVisible}
            </span>
          ) : null}
          <h2 className="text-sm font-semibold flex items-center gap-2 min-w-0">
            <span className="truncate" title={goal ?? undefined}>
              {goal ?? headerLabel}
            </span>
            {goal ? null : (
              <span className="text-xs text-muted-foreground tabular-nums">
                {inProgressCount}/{totalVisible}
              </span>
            )}
          </h2>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground flex-shrink-0"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2">
        {loading ? (
          <p className="text-xs text-muted-foreground p-2">Loading…</p>
        ) : error ? (
          <p className="text-xs text-destructive p-2">Error: {error}</p>
        ) : totalVisible === 0 ? (
          <TasksEmptyState />
        ) : (
          // Current session's live plan — interactive.
          <OrderedTaskList tasks={tasks} sessionId={sessionId} />
        )}

        {previousSessions && previousSessions.length > 0 ? (
          <PreviousSessionsSection previousSessions={previousSessions} />
        ) : null}
      </div>

      {showControls ? (
        <div className="flex-shrink-0 border-t border-border px-3 py-2">
          <ActionPlanControls sessionId={sessionId} sendPrompt={sendPrompt} />
        </div>
      ) : null}
    </aside>
  );
}

/**
 * The action-plan controls: "History" (open archived batches) + "Update
 * plan" (ask the queen to re-state the current plan). Renders as a bare
 * button group (no footer chrome) so callers can place it wherever — the
 * queen-DM rail wraps it in `ActionPlanFooter`, the colony overview drops
 * it into the drawer footer next to "Open colony folder". Must sit inside
 * a `TaskListProvider` so it reads the same live task state.
 */
export function ActionPlanControls({
  sessionId,
  sendPrompt,
}: {
  sessionId: string;
  sendPrompt?: (text: string) => void;
}) {
  const { tasks } = useTaskList();
  const batches = useMemo(() => archivedBatches(tasks), [tasks]);
  const archivedCount = useMemo(
    () => batches.reduce((n, b) => n + b.tasks.length, 0),
    [batches],
  );
  const completedCount = useMemo(
    () => tasks.filter((t) => t.status === "completed").length,
    [tasks],
  );
  const [historyOpen, setHistoryOpen] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [distilling, setDistilling] = useState(false);
  const [clearing, setClearing] = useState(false);

  const handleDistillPrompt = async () => {
    if (distilling) return;
    setDistilling(true);
    try {
      // Same delivery path as Update plan: prefer the colony chat's
      // sendPrompt (optimistic bubble) and fall back to a direct chat for
      // the queen-DM rail. The queen answers inline with the distilled
      // prompt — no task mutations, so nothing to reconcile client-side.
      if (sendPrompt) {
        sendPrompt(DISTILL_PROMPT_PROMPT);
      } else {
        await executionApi.chat(sessionId, DISTILL_PROMPT_PROMPT);
      }
    } catch (err) {
      console.error("[action-plan] distill prompt failed:", err);
    } finally {
      setDistilling(false);
    }
  };

  const handleClearCompleted = async () => {
    if (clearing || completedCount === 0) return;
    setClearing(true);
    try {
      // Archive every completed task server-side — same non-destructive
      // move to History as the queen's task_update status="archived". The
      // per-task task_updated events flip them to archived, so they drop out
      // of the active plan live (orderedVisibleTasks filters archived); no
      // optimistic update needed.
      await tasksApi.clearCompleted(sessionId);
    } catch (err) {
      console.error("[action-plan] clear completed failed:", err);
    } finally {
      setClearing(false);
    }
  };

  const handleUpdatePlan = async () => {
    if (updating) return;
    setUpdating(true);
    try {
      // The queen owns the plan: it marks finished work complete and
      // archives the done/stale tasks itself (task_update status="archived"),
      // which streams back as task_updated events. No client-side archive —
      // that avoids the queen and the UI fighting over the same tasks.
      //
      // Prefer `sendPrompt` (the colony chat's handleSend, via
      // requestQueenPrompt) so the message gets an optimistic bubble and
      // shows immediately; the colony chat is a separate tree and doesn't
      // render a raw executionApi.chat injection live. Fall back to a
      // direct chat for the queen-DM rail (which renders it live from SSE).
      if (sendPrompt) {
        sendPrompt(REFRESH_PLAN_PROMPT);
      } else {
        await executionApi.chat(sessionId, REFRESH_PLAN_PROMPT);
      }
    } catch (err) {
      console.error("[action-plan] update plan failed:", err);
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="@container flex items-center gap-1.5 w-full">
      {batches.length > 0 ? (
        <button
          type="button"
          onClick={() => setHistoryOpen(true)}
          className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          title="View archived tasks"
        >
          <History className="w-3.5 h-3.5 flex-shrink-0" />
          <span className="hidden @sm:inline whitespace-nowrap">
            History <span className="tabular-nums">({archivedCount})</span>
          </span>
        </button>
      ) : null}
      {completedCount > 0 ? (
        <button
          type="button"
          onClick={handleClearCompleted}
          disabled={clearing}
          className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
          title="Archive all completed tasks — moves them out of the active plan into History (restorable)"
        >
          {clearing ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <CheckCheck className="w-3.5 h-3.5" />
          )}
          Clear done
          <span className="tabular-nums">({completedCount})</span>
        </button>
      ) : null}
      <button
        type="button"
        onClick={handleUpdatePlan}
        disabled={updating}
        className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
        title={
          updating
            ? "Asking the queen to refresh the plan…"
            : "Ask the queen to review the plan — complete finished work, archive done/stale tasks, and list what's next"
        }
      >
        {updating ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin flex-shrink-0" />
        ) : (
          <Archive className="w-3.5 h-3.5 flex-shrink-0" />
        )}
        <span className="hidden @sm:inline whitespace-nowrap">Update plan</span>
      </button>
      <button
        type="button"
        onClick={handleDistillPrompt}
        disabled={distilling}
        className="ml-auto flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
        title={
          distilling
            ? "Asking the queen to distill a prompt…"
            : "Ask the queen to produce a reusable prompt for her current tasks, aggregating all feedback learned from the colony's users so far"
        }
      >
        {distilling ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin flex-shrink-0" />
        ) : (
          <Sparkles className="w-3.5 h-3.5 flex-shrink-0" />
        )}
        <span className="hidden @sm:inline whitespace-nowrap">Distill prompt</span>
      </button>

      {historyOpen ? (
        <ArchiveHistoryModal
          sessionId={sessionId}
          batches={batches}
          onClose={() => setHistoryOpen(false)}
        />
      ) : null}
    </div>
  );
}

/**
 * Queen-DM rail footer wrapper around {@link ActionPlanControls}. The
 * colony overview doesn't use this — it renders the controls in its own
 * drawer footer instead.
 */
function ActionPlanFooter({
  sessionId,
  sendPrompt,
}: {
  sessionId: string;
  sendPrompt?: (text: string) => void;
}) {
  return (
    <div className="flex-shrink-0 border-t border-border px-3 py-2 flex items-center gap-1.5">
      <ActionPlanControls sessionId={sessionId} sendPrompt={sendPrompt} />
    </div>
  );
}

/**
 * Standalone plan controls (History + Update plan) for hosting in a bar
 * OUTSIDE the TaskListPanel — e.g. the colony drawer footer, so the plan
 * tab doesn't stack a second bar under it. Mounts its own TaskListProvider
 * for the session and renders nothing until the plan has tasks or an
 * archived batch (matching the in-panel footer's gating).
 */
export function PlanControlsBar({
  sessionId,
  sendPrompt,
}: {
  sessionId: string;
  sendPrompt?: (text: string) => void;
}) {
  return (
    <TaskListProvider sessionId={sessionId}>
      <PlanControlsBarInner sessionId={sessionId} sendPrompt={sendPrompt} />
    </TaskListProvider>
  );
}

function PlanControlsBarInner({
  sessionId,
  sendPrompt,
}: {
  sessionId: string;
  sendPrompt?: (text: string) => void;
}) {
  const { tasks, loading, error } = useTaskList();
  const hasPlan =
    orderedVisibleTasks(tasks).length > 0 || archivedBatches(tasks).length > 0;
  if (loading || error || !hasPlan) return null;
  return <ActionPlanControls sessionId={sessionId} sendPrompt={sendPrompt} />;
}

/**
 * History overlay — archived tasks grouped by goal, newest group first.
 * Each group is named by its goal (falling back to the archive date) and
 * expands to its tasks. "Remove" un-archives the whole group server-side,
 * so its tasks return to the live plan and the agent's working set.
 */
function ArchiveHistoryModal({
  sessionId,
  batches,
  onClose,
}: {
  sessionId: string;
  batches: ArchivedBatch[];
  onClose: () => void;
}) {
  const totalTasks = batches.reduce((n, b) => n + b.tasks.length, 0);
  const handleRemove = (batch: ArchivedBatch) => {
    // Optimism isn't needed: the per-task `task_updated` events flip these
    // back to their prior status, so the group drops out of History live.
    tasksApi.unarchive(sessionId, batch.tasks.map((t) => t.id)).catch(() => {});
  };

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-lg pointer-events-auto flex flex-col max-h-[85vh]">
          <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                <History className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">Archived tasks</h2>
                <p className="text-[11px] text-muted-foreground">
                  {totalTasks} archived task{totalTasks === 1 ? "" : "s"}, grouped by goal.
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto px-5 py-3">
            {batches.length === 0 ? (
              <p className="text-[11.5px] text-muted-foreground italic py-6 text-center">
                Nothing archived yet. Use “Update plan” to archive completed tasks.
              </p>
            ) : (
              <div className="space-y-2">
                {batches.map((b) => (
                  <ArchiveBatchRow key={b.key} batch={b} onRemove={() => handleRemove(b)} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function ArchiveBatchRow({
  batch,
  onRemove,
}: {
  batch: ArchivedBatch;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const date = new Date(batch.archivedAt * 1000).toLocaleString();

  return (
    <div className="rounded border border-border">
      <div className="flex items-center gap-1.5 px-2 py-1.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex-1 min-w-0 flex items-center gap-1.5 text-left"
        >
          {open ? (
            <ChevronDown className="h-3 w-3 flex-shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 flex-shrink-0 text-muted-foreground" />
          )}
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium truncate" title={batch.goal ?? date}>
              {batch.goal ?? "Untitled plan"}
            </div>
            <div className="text-[10px] text-muted-foreground truncate">{date}</div>
          </div>
        </button>
        <span className="text-[11px] text-muted-foreground tabular-nums flex-shrink-0">
          {batch.tasks.length}
        </span>
        <button
          type="button"
          onClick={onRemove}
          className="p-1 rounded text-muted-foreground/60 hover:text-destructive hover:bg-destructive/10 transition-colors flex-shrink-0"
          title="Remove from history (restores these tasks to the plan)"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
      {open ? (
        <ul className="px-2 pb-1.5 border-t border-border space-y-0.5 pt-1">
          {batch.tasks.map((t) => {
            const wasDone =
              (t.metadata as { archived_from?: string }).archived_from === "completed";
            return (
              <li
                key={t.id}
                className="flex items-start gap-1.5 text-[11px] text-muted-foreground"
              >
                {wasDone ? (
                  <CheckSquare className="w-3 h-3 mt-0.5 flex-shrink-0 text-emerald-600" />
                ) : (
                  <Square className="w-3 h-3 mt-0.5 flex-shrink-0 text-muted-foreground/50" />
                )}
                <span className={wasDone ? "line-through break-words" : "break-words"}>
                  {t.subject}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

function TasksEmptyState() {
  return (
    <div className="flex flex-col items-center text-center px-2 py-10">
      <div className="w-10 h-10 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center text-primary mb-3">
        <ListTodo className="w-4 h-4" />
      </div>
      <h3 className="text-sm font-semibold text-foreground mb-1.5">
        No tasks yet
      </h3>
      <p className="text-[11.5px] text-muted-foreground leading-relaxed max-w-[260px]">
        The agent will create them as it plans.
      </p>
    </div>
  );
}

/**
 * One session's tasks rendered ungrouped, in creation order. Pass
 * `sessionId` for the live session; omit it for historical plans,
 * which render read-only.
 */
function OrderedTaskList({
  tasks,
  sessionId,
}: {
  tasks: TaskRecord[];
  sessionId?: string;
}) {
  const ordered = orderedVisibleTasks(tasks);
  // No live session id -> historical plan: render rows static (no spinners
  // or ticking timers).
  const readOnly = !sessionId;
  // Completed tasks stay visible, so blocker references resolve against
  // the full list, not just the ordered subset.
  const completedIds = new Set(
    tasks.filter((t) => t.status === "completed").map((t) => t.id),
  );

  const itemRefs = useRef(new Map<number, HTMLLIElement>());
  const handleJumpToBlocker = (id: number) => {
    const node = itemRefs.current.get(id);
    if (!node) return;
    node.scrollIntoView({ behavior: "smooth", block: "center" });
    node.classList.add("ring-2", "ring-primary/40");
    setTimeout(() => node.classList.remove("ring-2", "ring-primary/40"), 1500);
  };

  if (ordered.length === 0) {
    return <p className="text-[11px] text-muted-foreground px-2 py-1 italic">No tasks.</p>;
  }

  return (
    <ul className="space-y-0.5">
      {ordered.map((t) => (
        <li
          key={t.id}
          ref={(el) => {
            if (el) itemRefs.current.set(t.id, el);
            else itemRefs.current.delete(t.id);
          }}
          className="rounded transition-shadow"
        >
          <TaskItem
            task={t}
            readOnly={readOnly}
            unresolvedBlockers={unresolvedBlockers(t, completedIds)}
            onJumpToBlocker={handleJumpToBlocker}
          />
        </li>
      ))}
    </ul>
  );
}

/** Lazy-fetched snapshot for one prior session's row. */
interface PreviousSessionPlan {
  tasks: TaskRecord[];
  /** Anchor goal pulled from snap.meta.goal — null on legacy sessions. */
  goal: string | null;
}

/**
 * Collapsed "Previous sessions" fold. Snapshots for prior sessions are
 * fetched lazily the first time the section opens (and for any session
 * that appears later — e.g. a fork adds the just-left session to the
 * list). Historical plans are static, so there is no SSE subscription:
 * a one-shot snapshot per session is enough.
 */
function PreviousSessionsSection({
  previousSessions,
}: {
  previousSessions: PreviousSessionInfo[];
}) {
  const [open, setOpen] = useState(false);
  // sessionId -> plan (tasks + goal). `null` once fetched if the
  // session has no task list on disk (404) or the fetch failed.
  // Absent key = not fetched yet.
  const [plans, setPlans] = useState<Record<string, PreviousSessionPlan | null>>({});
  // Guards against a re-render re-issuing an in-flight fetch.
  const fetchedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!open) return;
    for (const ps of previousSessions) {
      if (fetchedRef.current.has(ps.sessionId)) continue;
      fetchedRef.current.add(ps.sessionId);
      tasksApi
        .getList(ps.sessionId)
        .then((snap) => {
          setPlans((p) => ({
            ...p,
            [ps.sessionId]: snap
              ? { tasks: snap.tasks, goal: snap.meta?.goal ?? null }
              : null,
          }));
        })
        .catch(() => {
          setPlans((p) => ({ ...p, [ps.sessionId]: null }));
        });
    }
  }, [open, previousSessions]);

  // Only sessions that resolved with at least one displayable task.
  const withPlan = previousSessions.filter((ps) => {
    const plan = plans[ps.sessionId];
    return plan != null && orderedVisibleTasks(plan.tasks).length > 0;
  });
  const settled = previousSessions.every((ps) => ps.sessionId in plans);

  return (
    <div className="mt-3 border-t border-border pt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs font-medium text-muted-foreground px-2 py-1 hover:text-foreground"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span>Previous sessions</span>
        {withPlan.length > 0 ? (
          <span className="tabular-nums">({withPlan.length})</span>
        ) : null}
      </button>
      {open ? (
        !settled && withPlan.length === 0 ? (
          <p className="text-[11px] text-muted-foreground px-2 py-1">Loading…</p>
        ) : withPlan.length === 0 ? (
          <p className="text-[11px] text-muted-foreground px-2 py-1 italic">
            No previous action plans.
          </p>
        ) : (
          <div className="space-y-1 mt-1">
            {withPlan.map((ps) => {
              const plan = plans[ps.sessionId] as PreviousSessionPlan;
              return (
                <PreviousSessionRow
                  key={ps.sessionId}
                  info={ps}
                  plan={plan}
                />
              );
            })}
          </div>
        )
      ) : null}
    </div>
  );
}

/** One collapsible prior-session plan inside the "Previous sessions" fold.
 *
 *  Aggregation title is the session's goal when one is set, with the
 *  start date as the secondary line. Falls back to date-only on legacy
 *  sessions whose first task_create predated the goal field.
 */
function PreviousSessionRow({
  info,
  plan,
}: {
  info: PreviousSessionInfo;
  plan: PreviousSessionPlan;
}) {
  const [open, setOpen] = useState(false);
  const count = orderedVisibleTasks(plan.tasks).length;
  const hasGoal = Boolean(plan.goal);

  return (
    <div className="rounded border border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1.5 px-2 py-1.5 text-left hover:bg-muted/50"
      >
        {open ? (
          <ChevronDown className="h-3 w-3 flex-shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 flex-shrink-0 text-muted-foreground" />
        )}
        <div className="flex-1 min-w-0">
          <div
            className="text-xs font-medium truncate"
            title={hasGoal ? plan.goal! : info.label}
          >
            {hasGoal ? plan.goal : info.label}
          </div>
          {hasGoal ? (
            <div className="text-[10px] text-muted-foreground truncate">
              {info.label}
            </div>
          ) : null}
        </div>
        <span className="text-[11px] text-muted-foreground tabular-nums flex-shrink-0">
          {count}
        </span>
      </button>
      {open ? (
        <div className="px-1 pb-1 border-t border-border">
          {/* No sessionId -> historical plan renders read-only (no SSE
              subscription backs it). */}
          <OrderedTaskList tasks={plan.tasks} />
        </div>
      ) : null}
    </div>
  );
}
