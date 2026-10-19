/**
 * REST + types for the task system.
 *
 * Each session owns exactly one task list, identified by its session_id.
 * Each agent operates on its OWN session's list via the four task tools.
 */

import { api, ApiError } from "./client";

export type TaskStatus = "pending" | "in_progress" | "completed" | "abandoned" | "archived";
export type TaskListRole = "session";

export interface TaskRecord {
  id: number;
  subject: string;
  description: string;
  active_form: string | null;
  owner: string | null;
  status: TaskStatus;
  blocks: number[];
  blocked_by: number[];
  metadata: Record<string, unknown>;
  created_at: number;
  updated_at: number;
}

// Shape mirrors the backend snapshot (routes_tasks.handle_get_task_list):
// top-level session_id/role/meta/tasks, with meta = TaskListMeta.model_dump().
export interface TaskListSnapshot {
  session_id: string;
  role: TaskListRole;
  meta: {
    role: TaskListRole;
    creator_agent_id: string | null;
    /** Anchor goal set on the first task_create of this session (in the
     *  user's terms). Used as the pivot reference point — a future batch
     *  whose work falls outside this goal is the queen's signal to fork
     *  via new_session (DM) or new_colony (colony). Surfaced in the UI as
     *  the panel title and beside each previous session's date label. */
    goal: string | null;
    created_at: number;
    schema_version: number;
  } | null;
  tasks: TaskRecord[];
}

export const tasksApi = {
  /**
   * Snapshot of one session's task list, keyed by the bare session_id.
   *
   * The backend stores tasks per session (``GET /sessions/{id}/tasks``);
   * there is no composite ``task_list_id`` route. Returns ``null`` if the
   * list does not exist on disk yet (404) — happens when a session has
   * just started and no agent has called ``task_create`` — so the panel
   * hides until the first task is created instead of surfacing an error.
   */
  async getList(sessionId: string): Promise<TaskListSnapshot | null> {
    try {
      return await api.get<TaskListSnapshot>(`/sessions/${encodeURIComponent(sessionId)}/tasks`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  },

  /**
   * Restore archived tasks to their pre-archive status (History "remove").
   * Each restored task re-enters the live plan and the agent's working set.
   * Returns the restored ids. The panel also updates via per-task
   * `task_updated` SSE events.
   */
  async unarchive(
    sessionId: string,
    taskIds: number[],
  ): Promise<{ session_id: string; restored: number[] }> {
    return await api.post<{ session_id: string; restored: number[] }>(
      `/sessions/${encodeURIComponent(sessionId)}/tasks/unarchive`,
      { task_ids: taskIds },
    );
  },

  /**
   * Archive every completed task on the plan (the panel's "Clear done"
   * button). Finished tasks move out of the active plan into History — the
   * same non-destructive archive the queen does, restorable from History.
   * Returns the archived ids. The panel also updates live via per-task
   * `task_updated` SSE events flipping them to `archived`.
   */
  async clearCompleted(
    sessionId: string,
  ): Promise<{ session_id: string; archived: number[] }> {
    return await api.post<{ session_id: string; archived: number[] }>(
      `/sessions/${encodeURIComponent(sessionId)}/tasks/clear-completed`,
      {},
    );
  },
};

// ---------------------------------------------------------------------------
// SSE event payload shapes. The backend (tasks/events.py) keys these on the
// bare `session_id` — there is no `task_list_id` field on the wire.
// ---------------------------------------------------------------------------

export interface TaskCreatedEvent {
  session_id: string;
  task: TaskRecord;
}

export interface TaskUpdatedEvent {
  session_id: string;
  task_id: number;
  after: TaskRecord;
  fields: string[];
}

export interface TaskDeletedEvent {
  session_id: string;
  task_id: number;
  cascade: number[];
}
