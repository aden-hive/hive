import { api } from "./client";

export interface LiveWorker {
  worker_id: string;
  task: string;
  status: string;
  is_active: boolean;
  duration_seconds: number;
  explicit_report: Record<string, unknown> | null;
  result_status: string | null;
  result_summary: string | null;
}

export interface StopWorkerResult {
  stopped: boolean;
  worker_id?: string;
  reason?: string;
  status?: string;
  error?: string;
}

export interface StopAllWorkersResult {
  stopped: string[];
  stopped_count: number;
  errors?: { worker_id: string; error: string }[] | null;
}

export const workersApi = {
  // Live fan-out control
  listLive: (sessionId: string) =>
    api.get<{ workers: LiveWorker[] }>(`/sessions/${sessionId}/workers`),

  stopLive: (sessionId: string, workerId: string) =>
    api.post<StopWorkerResult>(
      `/sessions/${sessionId}/workers/${workerId}/stop`,
      {},
    ),

  stopAllLive: (sessionId: string) =>
    api.post<StopAllWorkersResult>(`/sessions/${sessionId}/workers/stop-all`, {}),
};
