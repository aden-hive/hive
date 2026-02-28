import { api } from "./client";
import type { LogEntry, LogNodeDetail, LogToolStep } from "./types";

export const logsApi = {
  list: (sessionId: string, limit?: number) =>
    api.get<{ logs: LogEntry[] }>(
      `/sessions/${sessionId}/logs${limit ? `?limit=${limit}` : ""}`,
    ),

  summary: (sessionId: string, workerSessionId: string) =>
    api.get<LogEntry>(
      `/sessions/${sessionId}/logs?session_id=${workerSessionId}&level=summary`,
    ),

  details: (sessionId: string, workerSessionId: string) =>
    api.get<{ session_id: string; nodes: LogNodeDetail[] }>(
      `/sessions/${sessionId}/logs?session_id=${workerSessionId}&level=details`,
    ),

  tools: (sessionId: string, workerSessionId: string) =>
    api.get<{ session_id: string; steps: LogToolStep[] }>(
      `/sessions/${sessionId}/logs?session_id=${workerSessionId}&level=tools`,
    ),

  nodeLogs: (
    sessionId: string,
    graphId: string,
    nodeId: string,
    workerSessionId: string,
    level?: string,
  ) =>
    api.get<{
      session_id: string;
      node_id: string;
      details?: LogNodeDetail[];
      tool_logs?: LogToolStep[];
    }>(
      `/sessions/${sessionId}/graphs/${graphId}/nodes/${nodeId}/logs?session_id=${workerSessionId}${level ? `&level=${level}` : ""}`,
    ),
};
