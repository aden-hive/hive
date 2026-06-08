/**
 * REST + types for the task system.
 *
 * Two list types:
 *   colony:{colony_id}            — colony template (queen's spawn plan)
 *   session:{agent_id}:{sess_id}  — per-session working list
 *
 * Each agent operates on its OWN session list via the four task tools;
 * the colony template is queen-owned and read by the UI.
 */

import { api, ApiError } from "./client";

export type TaskStatus = "pending" | "in_progress" | "completed";
export type TaskListRole = "template" | "session";

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

export interface TaskListSnapshot {
  task_list_id: string;
  role: TaskListRole;
  meta: {
    task_list_id: string;
    role: TaskListRole;
    creator_agent_id: string | null;
    created_at: number;
    last_seen_session_ids: string[];
    schema_version: number;
  } | null;
  tasks: TaskRecord[];
}

export interface ColonyTaskLists {
  template_task_list_id: string;
  queen_session_task_list_id: string | null;
}

export interface SessionTaskListInfo {
  task_list_id: string | null;
  picked_up_from: { colony_id: string; task_id: number } | null;
}

export const tasksApi = {
  /**
   * Snapshot of one task list, identified by its full task_list_id.
   *
   * Returns ``null`` if the list does not exist on disk yet (404). That
   * happens when a session has just started and no agent has called
   * ``task_create`` — the panel should hide until the first task is
   * created instead of surfacing the 404 as an error.
   */
  async getList(taskListId: string): Promise<TaskListSnapshot | null> {
    try {
      return await api.get<TaskListSnapshot>(`/tasks/${encodeURIComponent(taskListId)}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  },
  /** Helper: resolve template + queen-session list ids for a colony. */
  async getColonyLists(
    colonyId: string,
    queenSessionId?: string,
  ): Promise<ColonyTaskLists> {
    const qs = queenSessionId ? `?queen_session_id=${encodeURIComponent(queenSessionId)}` : "";
    return api.get<ColonyTaskLists>(`/colonies/${encodeURIComponent(colonyId)}/task_lists${qs}`);
  },
  /** Helper: resolve task_list_id + picked_up_from for a session. */
  async getSessionInfo(
    sessionId: string,
    agentId: string = "queen",
  ): Promise<SessionTaskListInfo> {
    return api.get<SessionTaskListInfo>(
      `/sessions/${encodeURIComponent(sessionId)}/task_list_id?agent_id=${encodeURIComponent(agentId)}`,
    );
  },
};

// ---------------------------------------------------------------------------
// SSE event payload shapes
// ---------------------------------------------------------------------------

export interface TaskCreatedEvent {
  task_list_id: string;
  task: TaskRecord;
}

export interface TaskUpdatedEvent {
  task_list_id: string;
  task_id: number;
  after: TaskRecord;
  fields: string[];
}

export interface TaskDeletedEvent {
  task_list_id: string;
  task_id: number;
  cascade: number[];
}

export interface ColonyTemplateAssignmentEvent {
  colony_id: string;
  task_id: number;
  assigned_session: string | null;
  assigned_worker_id: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Parse a task_list_id into structured parts (mirrors server-side scoping). */
export function parseTaskListId(taskListId: string): {
  kind: "colony" | "session" | "raw";
  colony_id?: string;
  agent_id?: string;
  session_id?: string;
  raw?: string;
} {
  if (taskListId.startsWith("colony:")) {
    return { kind: "colony", colony_id: taskListId.slice("colony:".length) };
  }
  if (taskListId.startsWith("session:")) {
    const rest = taskListId.slice("session:".length);
    const idx = rest.indexOf(":");
    return idx > 0
      ? { kind: "session", agent_id: rest.slice(0, idx), session_id: rest.slice(idx + 1) }
      : { kind: "raw", raw: taskListId };
  }
  return { kind: "raw", raw: taskListId };
}

export function colonyTaskListId(colonyId: string): string {
  return `colony:${colonyId}`;
}

export function sessionTaskListId(agentId: string, sessionId: string): string {
  return `session:${agentId}:${sessionId}`;
}
