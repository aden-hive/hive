import { api } from "./client";
import type { GraphTopology, NodeDetail, NodeCriteria, ToolInfo } from "./types";

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
  nodes: (sessionId: string, colonyId: string, workerSessionId?: string) =>
    api.get<GraphTopology>(
      `/sessions/${sessionId}/colonies/${colonyId}/nodes${workerSessionId ? `?session_id=${workerSessionId}` : ""}`,
    ),

  node: (sessionId: string, colonyId: string, nodeId: string) =>
    api.get<NodeDetail>(
      `/sessions/${sessionId}/colonies/${colonyId}/nodes/${nodeId}`,
    ),

  nodeCriteria: (
    sessionId: string,
    colonyId: string,
    nodeId: string,
    workerSessionId?: string,
  ) =>
    api.get<NodeCriteria>(
      `/sessions/${sessionId}/colonies/${colonyId}/nodes/${nodeId}/criteria${workerSessionId ? `?session_id=${workerSessionId}` : ""}`,
    ),

  nodeTools: (sessionId: string, colonyId: string, nodeId: string) =>
    api.get<{ tools: ToolInfo[] }>(
      `/sessions/${sessionId}/colonies/${colonyId}/nodes/${nodeId}/tools`,
    ),

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
