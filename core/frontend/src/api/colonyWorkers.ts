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

export const colonyWorkersApi = {
  /** List spawned workers (live + completed) for a colony session. */
  list: (sessionId: string) =>
    api.get<{ workers: WorkerSummary[] }>(`/sessions/${sessionId}/workers`),
};
