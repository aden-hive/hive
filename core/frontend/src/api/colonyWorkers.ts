import { api } from "./client";

export interface WorkerResult {
  status: string;
  summary: string;
  error: string | null;
  tokens_used: number;
  duration_seconds: number;
}

export interface WorkerSummary {
  worker_id: string;
  task: string;
  status: string;
  started_at: number;
  result: WorkerResult | null;
}

export interface ColonySkill {
  name: string;
  description: string;
  location: string;
  base_dir: string;
  source_scope: string;
}

export interface ColonyTool {
  name: string;
  description: string;
  /** Canonical credential/provider key (e.g. "hubspot", "gmail") for
   *  tools bound to an Aden credential. ``null`` for framework/core
   *  tools that don't require a provider credential. */
  provider: string | null;
}

export interface ProgressTask {
  id: string;
  seq: number | null;
  priority: number;
  goal: string;
  payload: string | null;
  status: string;
  worker_id: string | null;
  claim_token: string | null;
  claimed_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  retry_count: number;
  max_retries: number;
  last_error: string | null;
  parent_task_id: string | null;
  source: string | null;
}

export interface ProgressStep {
  id: string;
  task_id: string;
  seq: number;
  title: string;
  detail: string | null;
  status: string;
  evidence: string | null;
  worker_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  /** Present only on upsert events; not on snapshot rows. */
  _ts?: string | null;
}

export interface ProgressSnapshot {
  tasks: ProgressTask[];
  steps: ProgressStep[];
}

export const colonyWorkersApi = {
  /** List spawned workers (live + completed) for a colony session. */
  list: (sessionId: string) =>
    api.get<{ workers: WorkerSummary[] }>(`/sessions/${sessionId}/workers`),

  /** List the colony's shared skills catalog. */
  listSkills: (sessionId: string) =>
    api.get<{ skills: ColonySkill[] }>(`/sessions/${sessionId}/colony/skills`),

  /** List the colony's default tools. */
  listTools: (sessionId: string) =>
    api.get<{ tools: ColonyTool[] }>(`/sessions/${sessionId}/colony/tools`),

  /** Snapshot of progress.db tasks + steps, optionally filtered by worker_id. */
  progressSnapshot: (sessionId: string, workerId?: string) => {
    const qs = workerId ? `?worker_id=${encodeURIComponent(workerId)}` : "";
    return api.get<ProgressSnapshot>(
      `/sessions/${sessionId}/colony/progress/snapshot${qs}`,
    );
  },

  /** Build the URL for the live progress SSE stream. */
  progressStreamUrl: (sessionId: string, workerId?: string): string => {
    const qs = workerId ? `?worker_id=${encodeURIComponent(workerId)}` : "";
    return `/api/sessions/${sessionId}/colony/progress/stream${qs}`;
  },
};
