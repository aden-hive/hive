/**
 * Per-session live task state. Mounts a single session's task list
 * (snapshot + SSE diffs). Mount one for the queen-DM, colony-overview,
 * and worker-detail views.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
  type ReactNode,
} from "react";

import {
  tasksApi,
  type TaskRecord,
  type TaskListRole,
  type TaskCreatedEvent,
  type TaskUpdatedEvent,
  type TaskDeletedEvent,
} from "@/api/tasks";
import { useSSE } from "@/hooks/use-sse";
import type { AgentEvent } from "@/api/types";

interface TaskListState {
  sessionId: string;
  role: TaskListRole | "unknown";
  tasks: TaskRecord[];
  /** Anchor goal from the snapshot's meta. Null until the first snapshot
   *  resolves (or always null on legacy sessions whose first task_create
   *  predated the goal field). Carried in the snapshot only — task_* events
   *  don't include it. Rendered as the panel title so the queen-DM rail and
   *  colony overview both surface what this list is FOR. */
  goal: string | null;
  loading: boolean;
  error: string | null;
  /** False until the list exists on disk. Sessions that haven't created
   *  any task yet return 404 from the snapshot endpoint; the panel
   *  should hide rather than render an error. Becomes true on first
   *  successful snapshot or on the first task_created event. */
  exists: boolean;
}

type Action =
  | { type: "SNAPSHOT"; tasks: TaskRecord[]; role: TaskListRole; goal: string | null }
  | { type: "LOADING" }
  | { type: "NOT_FOUND" }
  | { type: "ERROR"; error: string }
  | { type: "CREATED"; task: TaskRecord }
  | { type: "UPDATED"; task: TaskRecord }
  | { type: "DELETED"; taskId: number; cascade: number[] };

function reducer(state: TaskListState, action: Action): TaskListState {
  switch (action.type) {
    case "LOADING":
      return { ...state, loading: true, error: null };
    case "NOT_FOUND":
      return { ...state, loading: false, error: null, exists: false, tasks: [], goal: null };
    case "ERROR":
      return { ...state, loading: false, error: action.error };
    case "SNAPSHOT":
      return {
        ...state,
        tasks: action.tasks,
        role: action.role,
        goal: action.goal,
        loading: false,
        error: null,
        exists: true,
      };
    case "CREATED": {
      // First task_created event for a previously-empty session marks
      // the list as existing — the panel will reveal itself live.
      if (state.tasks.some((t) => t.id === action.task.id)) {
        return { ...state, exists: true };
      }
      const next = [...state.tasks, action.task].sort((a, b) => a.id - b.id);
      return { ...state, tasks: next, exists: true };
    }
    case "UPDATED": {
      const next = state.tasks.map((t) => (t.id === action.task.id ? action.task : t));
      return { ...state, tasks: next, exists: true };
    }
    case "DELETED": {
      const surviving = state.tasks
        .filter((t) => t.id !== action.taskId)
        .map((t) => {
          if (action.cascade.includes(t.id)) {
            return {
              ...t,
              blocks: t.blocks.filter((b) => b !== action.taskId),
              blocked_by: t.blocked_by.filter((b) => b !== action.taskId),
            };
          }
          return t;
        });
      return { ...state, tasks: surviving };
    }
    default:
      return state;
  }
}

const initial: TaskListState = {
  sessionId: "",
  role: "unknown",
  tasks: [],
  goal: null,
  loading: false,
  error: null,
  exists: false,
};

const TaskListContext = createContext<TaskListState | undefined>(undefined);

interface TaskListProviderProps {
  /** The session whose task list to load and subscribe to. */
  sessionId: string;
  /** Optional SSE channel override — defaults to ``sessionId``. Pass a
   *  different value only when the live diffs for this list are
   *  published on a different session's event bus. */
  eventSessionId?: string;
  children: ReactNode;
}

const TASK_EVENT_TYPES = [
  "task_created",
  "task_updated",
  "task_deleted",
  "task_list_reset",
] as const;

export function TaskListProvider({ sessionId, eventSessionId, children }: TaskListProviderProps) {
  const [state, dispatch] = useReducer(reducer, { ...initial, sessionId });
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  // Monotonic token: a snapshot fetch that resolves after a newer one
  // started (session id changed, or a reconnect re-fetch raced the mount
  // fetch) is discarded by comparing against the current generation.
  const snapshotGenRef = useRef(0);

  // Fetch the authoritative task-list snapshot. `silent` skips the
  // LOADING dispatch so an in-place refresh (SSE reconnect) keeps the
  // existing tasks on screen instead of flashing an empty loading
  // state — and swallows fetch errors so a transient blip doesn't
  // replace a good list with an error message.
  const loadSnapshot = useCallback((silent = false) => {
    const id = sessionIdRef.current;
    if (!id) return;
    const gen = ++snapshotGenRef.current;
    if (!silent) dispatch({ type: "LOADING" });
    tasksApi
      .getList(id)
      .then((snap) => {
        if (gen !== snapshotGenRef.current) return;
        if (snap === null) {
          // Not yet on disk — the panel hides until the first task_created
          // event arrives via SSE (see CREATED case in the reducer).
          dispatch({ type: "NOT_FOUND" });
        } else {
          dispatch({
            type: "SNAPSHOT",
            tasks: snap.tasks,
            role: snap.role,
            // meta is null only on the legacy "empty list" path; the
            // executor's first-create gate now requires a goal so any
            // post-feature session has one. ?? null keeps legacy
            // serializations (older runtimes) rendering cleanly.
            goal: snap.meta?.goal ?? null,
          });
        }
      })
      .catch((err) => {
        if (gen !== snapshotGenRef.current) return;
        if (!silent) dispatch({ type: "ERROR", error: String(err?.message ?? err) });
      });
  }, []);

  // Snapshot fetch — re-run when sessionId changes.
  useEffect(() => {
    loadSnapshot();
    return () => {
      // Invalidate any in-flight fetch for the previous session id.
      snapshotGenRef.current++;
    };
  }, [sessionId, loadSnapshot]);

  // Subscribe to SSE diffs for this session.
  const sseChannel = eventSessionId ?? sessionId;
  const { connected } = useSSE({
    sessionId: sseChannel,
    eventTypes: TASK_EVENT_TYPES as unknown as AgentEvent["type"][],
    enabled: Boolean(sseChannel),
    onEvent: (ev) => {
      const data = ev.data ?? {};
      if (data.session_id !== sessionIdRef.current) return;
      switch (ev.type) {
        case "task_created":
          dispatch({ type: "CREATED", task: (data as unknown as TaskCreatedEvent).task });
          return;
        case "task_updated":
          dispatch({ type: "UPDATED", task: (data as unknown as TaskUpdatedEvent).after });
          return;
        case "task_deleted": {
          const d = data as unknown as TaskDeletedEvent;
          dispatch({ type: "DELETED", taskId: d.task_id, cascade: d.cascade ?? [] });
          return;
        }
        case "task_list_reset":
          // Reset is a test-only path; preserve the existing goal so the
          // panel header stays anchored if the list is rebuilt under it.
          dispatch({
            type: "SNAPSHOT",
            tasks: [],
            role: state.role === "unknown" ? "session" : state.role,
            goal: state.goal,
          });
          return;
      }
    },
  });

  // Re-snapshot on SSE reconnect. Task events are NOT replayed when the
  // stream reconnects (see _REPLAY_TYPES in the runtime's
  // routes_events.py), so any task_created/updated/deleted that fired
  // while the stream was down is lost — the REST snapshot is the only
  // authoritative catch-up. The first connect is skipped: the
  // sessionId effect above already snapshotted on mount.
  const sseConnectsRef = useRef(0);
  const wasConnectedRef = useRef(false);
  useEffect(() => {
    if (connected && !wasConnectedRef.current) {
      sseConnectsRef.current += 1;
      if (sseConnectsRef.current > 1) loadSnapshot(true);
    }
    wasConnectedRef.current = connected;
  }, [connected, loadSnapshot]);

  return <TaskListContext.Provider value={state}>{children}</TaskListContext.Provider>;
}

export function useTaskList(): TaskListState {
  const ctx = useContext(TaskListContext);
  if (!ctx) throw new Error("useTaskList must be used inside <TaskListProvider>");
  return ctx;
}

// An `in_progress` task whose `updated_at` is older than this is considered
// idle/abandoned — the queen marked it started but never circled back to mark
// it complete (typically because she asked the user a question and the user
// moved on without answering). The UI demotes such tasks from "Active" to
// "Past" so the rail doesn't keep showing fake live work indefinitely.
//
// 30 min is conservative: a busy queen calls `task_update` between most
// substeps, so a 30-min gap with no update is a strong signal of abandonment.
// On a slow provider where a single LLM turn legitimately exceeds 30 min,
// this would prematurely demote — adjust if that becomes an issue.
export const IDLE_TASK_THRESHOLD_SECONDS = 30 * 60;

/** True when an in_progress task has been silent past the idle threshold. */
export function isTaskIdle(t: TaskRecord): boolean {
  if (t.status !== "in_progress") return false;
  const ageSeconds = Date.now() / 1000 - (t.updated_at ?? 0);
  return ageSeconds > IDLE_TASK_THRESHOLD_SECONDS;
}

/**
 * Tasks for one session in display order. The Action Plan no longer
 * groups by status — tasks render in creation order (id ascending), as
 * the agent planned them. Filtered out:
 *   - `_internal` metadata tasks (never user-facing).
 *   - `abandoned` tasks, and still-`in_progress` tasks gone stale past
 *     the idle threshold — treated like deleted tasks: dropped from view.
 *   - `archived` tasks — the user cleared them from the active plan; they
 *     surface only in History, grouped into batches (see archivedBatches).
 * Genuinely deleted tasks are already absent (the DELETED reducer action
 * removes them), so they need no extra filter here.
 */
export function orderedVisibleTasks(tasks: TaskRecord[]): TaskRecord[] {
  return tasks
    .filter((t) => !(t.metadata as { _internal?: boolean })._internal)
    .filter((t) => t.status !== "abandoned" && t.status !== "archived" && !isTaskIdle(t))
    .sort((a, b) => a.id - b.id);
}

/**
 * Archived tasks for one session, id-ascending — the plans the user
 * cleared. Rendered read-only in History. `_internal` tasks stay hidden
 * even once archived.
 */
export function archivedTasks(tasks: TaskRecord[]): TaskRecord[] {
  return tasks
    .filter((t) => !(t.metadata as { _internal?: boolean })._internal)
    .filter((t) => t.status === "archived")
    .sort((a, b) => a.id - b.id);
}

/** One History group — the archived tasks for a given goal. */
export interface ArchivedBatch {
  /** Stable key for React lists — the goal (or a sentinel when null). */
  key: string;
  /** Most recent archive time in the group (epoch seconds) — sort/label. */
  archivedAt: number;
  /** The goal these tasks were archived under — the group's display name. */
  goal: string | null;
  tasks: TaskRecord[];
}

interface ArchiveMeta {
  archived_at?: number;
  archived_goal?: string | null;
}

const NO_GOAL_KEY = " no-goal";

/**
 * Archived tasks grouped for History, newest group first. The agent
 * archives tasks one-by-one (each `task_update` stamps its own
 * `archived_at`), so grouping by timestamp would fragment a single
 * "Update plan" into many one-task groups. Group by `archived_goal`
 * instead — one History entry per goal — and label the group with the
 * most recent archive time. Tasks with no goal fall into one group.
 */
export function archivedBatches(tasks: TaskRecord[]): ArchivedBatch[] {
  const groups = new Map<string, ArchivedBatch>();
  for (const t of archivedTasks(tasks)) {
    const meta = t.metadata as ArchiveMeta;
    const goal = meta.archived_goal ?? null;
    const key = goal ?? NO_GOAL_KEY;
    const at = meta.archived_at ?? t.updated_at ?? 0;
    let batch = groups.get(key);
    if (!batch) {
      batch = { key, archivedAt: at, goal, tasks: [] };
      groups.set(key, batch);
    } else if (at > batch.archivedAt) {
      batch.archivedAt = at;
    }
    batch.tasks.push(t);
  }
  for (const batch of groups.values()) batch.tasks.sort((a, b) => a.id - b.id);
  return [...groups.values()].sort((a, b) => b.archivedAt - a.archivedAt);
}

export function unresolvedBlockers(task: TaskRecord, completedIds: Set<number>): number[] {
  return task.blocked_by.filter((b) => !completedIds.has(b));
}

export const TASK_LIST_PANEL_LOCALSTORAGE_KEY = (sessionId: string) =>
  `taskListPanel.${sessionId}`;
