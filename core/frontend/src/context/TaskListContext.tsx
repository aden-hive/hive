/**
 * Per-list live task state. Mounts a single list (snapshot + SSE diffs).
 *
 * Stack two of these for the colony-overview view (template + queen
 * session). Mount one for the queen-DM and worker-detail views.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
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
  taskListId: string;
  role: TaskListRole | "unknown";
  tasks: TaskRecord[];
  loading: boolean;
  error: string | null;
  /** False until the list exists on disk. Sessions that haven't created
   *  any task yet return 404 from the snapshot endpoint; the panel
   *  should hide rather than render an error. Becomes true on first
   *  successful snapshot or on the first task_created event. */
  exists: boolean;
}

type Action =
  | { type: "SNAPSHOT"; tasks: TaskRecord[]; role: TaskListRole }
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
      return { ...state, loading: false, error: null, exists: false, tasks: [] };
    case "ERROR":
      return { ...state, loading: false, error: action.error };
    case "SNAPSHOT":
      return {
        ...state,
        tasks: action.tasks,
        role: action.role,
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
  taskListId: "",
  role: "unknown",
  tasks: [],
  loading: false,
  error: null,
  exists: false,
};

const TaskListContext = createContext<TaskListState | undefined>(undefined);

interface TaskListProviderProps {
  taskListId: string;
  // SSE source — the queen session id is a reasonable default; events for
  // a list are published on the colony's bus. If `sessionId` is missing,
  // the panel renders the snapshot but doesn't subscribe to live diffs.
  sessionId?: string;
  children: ReactNode;
}

const TASK_EVENT_TYPES = [
  "task_created",
  "task_updated",
  "task_deleted",
  "task_list_reset",
] as const;

export function TaskListProvider({ taskListId, sessionId, children }: TaskListProviderProps) {
  const [state, dispatch] = useReducer(reducer, { ...initial, taskListId });
  const taskListIdRef = useRef(taskListId);
  taskListIdRef.current = taskListId;

  // Snapshot fetch — re-run when taskListId changes.
  useEffect(() => {
    if (!taskListId) return;
    let cancelled = false;
    dispatch({ type: "LOADING" });
    tasksApi
      .getList(taskListId)
      .then((snap) => {
        if (cancelled) return;
        if (snap === null) {
          // Not yet on disk — the panel hides until the first task_created
          // event arrives via SSE (see CREATED case in the reducer).
          dispatch({ type: "NOT_FOUND" });
        } else {
          dispatch({ type: "SNAPSHOT", tasks: snap.tasks, role: snap.role });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        dispatch({ type: "ERROR", error: String(err?.message ?? err) });
      });
    return () => {
      cancelled = true;
    };
  }, [taskListId]);

  // Subscribe to SSE diffs scoped to this list_id.
  useSSE({
    sessionId: sessionId ?? "",
    eventTypes: TASK_EVENT_TYPES as unknown as AgentEvent["type"][],
    enabled: Boolean(sessionId),
    onEvent: (ev) => {
      const data = ev.data ?? {};
      if (data.task_list_id !== taskListIdRef.current) return;
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
          dispatch({ type: "SNAPSHOT", tasks: [], role: state.role === "unknown" ? "session" : state.role });
          return;
      }
    },
  });

  return <TaskListContext.Provider value={state}>{children}</TaskListContext.Provider>;
}

export function useTaskList(): TaskListState {
  const ctx = useContext(TaskListContext);
  if (!ctx) throw new Error("useTaskList must be used inside <TaskListProvider>");
  return ctx;
}

// Helpers for components that want pre-bucketed views.
export function bucketTasks(tasks: TaskRecord[]) {
  const completedIds = new Set(tasks.filter((t) => t.status === "completed").map((t) => t.id));
  const visible = tasks.filter((t) => !(t.metadata as { _internal?: boolean })._internal);
  const active = visible.filter((t) => t.status === "in_progress");
  const pending = visible.filter((t) => t.status === "pending");
  const completed = visible.filter((t) => t.status === "completed");
  return { active, pending, completed, completedIds, visible };
}

export function unresolvedBlockers(task: TaskRecord, completedIds: Set<number>): number[] {
  return task.blocked_by.filter((b) => !completedIds.has(b));
}

export const TASK_LIST_PANEL_LOCALSTORAGE_KEY = (taskListId: string) =>
  `taskListPanel.${taskListId}`;

export const useMemoizedBuckets = (tasks: TaskRecord[]) =>
  useMemo(() => bucketTasks(tasks), [tasks]);
