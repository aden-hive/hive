import { api } from "./client";
import type {
  SessionSummary,
  SessionDetail,
  Checkpoint,
  Message,
} from "./types";

export const sessionsApi = {
  list: (agentId: string) =>
    api.get<{ sessions: SessionSummary[] }>(`/agents/${agentId}/sessions`),

  get: (agentId: string, sessionId: string) =>
    api.get<SessionDetail>(`/agents/${agentId}/sessions/${sessionId}`),

  delete: (agentId: string, sessionId: string) =>
    api.delete<{ deleted: string }>(`/agents/${agentId}/sessions/${sessionId}`),

  checkpoints: (agentId: string, sessionId: string) =>
    api.get<{ checkpoints: Checkpoint[] }>(
      `/agents/${agentId}/sessions/${sessionId}/checkpoints`,
    ),

  restore: (agentId: string, sessionId: string, checkpointId: string) =>
    api.post<{ execution_id: string }>(
      `/agents/${agentId}/sessions/${sessionId}/checkpoints/${checkpointId}/restore`,
    ),

  messages: (agentId: string, sessionId: string, nodeId?: string) =>
    api.get<{ messages: Message[] }>(
      `/agents/${agentId}/sessions/${sessionId}/messages${nodeId ? `?node_id=${nodeId}` : ""}`,
    ),
};
