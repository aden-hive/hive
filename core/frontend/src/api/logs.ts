import { api } from "./client";
import type { LogEntry, LogNodeDetail, LogToolStep } from "./types";

export const logsApi = {
  list: (agentId: string, limit?: number) =>
    api.get<{ logs: LogEntry[] }>(
      `/agents/${agentId}/logs${limit ? `?limit=${limit}` : ""}`,
    ),

  summary: (agentId: string, sessionId: string) =>
    api.get<LogEntry>(
      `/agents/${agentId}/logs?session_id=${sessionId}&level=summary`,
    ),

  details: (agentId: string, sessionId: string) =>
    api.get<{ session_id: string; nodes: LogNodeDetail[] }>(
      `/agents/${agentId}/logs?session_id=${sessionId}&level=details`,
    ),

  tools: (agentId: string, sessionId: string) =>
    api.get<{ session_id: string; steps: LogToolStep[] }>(
      `/agents/${agentId}/logs?session_id=${sessionId}&level=tools`,
    ),

  nodeLogs: (
    agentId: string,
    graphId: string,
    nodeId: string,
    sessionId: string,
    level?: string,
  ) =>
    api.get<{
      session_id: string;
      node_id: string;
      details?: LogNodeDetail[];
      tool_logs?: LogToolStep[];
    }>(
      `/agents/${agentId}/graphs/${graphId}/nodes/${nodeId}/logs?session_id=${sessionId}${level ? `&level=${level}` : ""}`,
    ),
};
