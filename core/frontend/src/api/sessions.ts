import { api } from "./client";
import type {
  LiveSession,
  LiveSessionDetail,
  SessionSummary,
  SessionDetail,
  Checkpoint,
  Message,
  EntryPoint,
} from "./types";

export const sessionsApi = {
  // --- Session lifecycle ---

  /** Create a session. If agentPath is provided, loads worker in one step. */
  create: (agentPath?: string, agentId?: string, model?: string) =>
    api.post<LiveSession>("/sessions", {
      agent_path: agentPath,
      agent_id: agentId,
      model,
    }),

  /** List all active sessions. */
  list: () => api.get<{ sessions: LiveSession[] }>("/sessions"),

  /** Get session detail (includes entry_points, graphs when worker is loaded). */
  get: (sessionId: string) =>
    api.get<LiveSessionDetail>(`/sessions/${sessionId}`),

  /** Stop a session entirely. */
  stop: (sessionId: string) =>
    api.delete<{ session_id: string; stopped: boolean }>(
      `/sessions/${sessionId}`,
    ),

  // --- Worker lifecycle ---

  loadWorker: (
    sessionId: string,
    agentPath: string,
    workerId?: string,
    model?: string,
  ) =>
    api.post<LiveSession>(`/sessions/${sessionId}/worker`, {
      agent_path: agentPath,
      worker_id: workerId,
      model,
    }),

  unloadWorker: (sessionId: string) =>
    api.delete<{ session_id: string; worker_unloaded: boolean }>(
      `/sessions/${sessionId}/worker`,
    ),

  // --- Session info ---

  stats: (sessionId: string) =>
    api.get<Record<string, unknown>>(`/sessions/${sessionId}/stats`),

  entryPoints: (sessionId: string) =>
    api.get<{ entry_points: EntryPoint[] }>(
      `/sessions/${sessionId}/entry-points`,
    ),

  graphs: (sessionId: string) =>
    api.get<{ graphs: string[] }>(`/sessions/${sessionId}/graphs`),

  /** Get queen conversation history for a session. */
  queenMessages: (sessionId: string) =>
    api.get<{ messages: Message[] }>(`/sessions/${sessionId}/queen-messages`),

  // --- Worker session browsing (persisted execution runs) ---

  workerSessions: (sessionId: string) =>
    api.get<{ sessions: SessionSummary[] }>(
      `/sessions/${sessionId}/worker-sessions`,
    ),

  workerSession: (sessionId: string, wsId: string) =>
    api.get<SessionDetail>(
      `/sessions/${sessionId}/worker-sessions/${wsId}`,
    ),

  deleteWorkerSession: (sessionId: string, wsId: string) =>
    api.delete<{ deleted: string }>(
      `/sessions/${sessionId}/worker-sessions/${wsId}`,
    ),

  checkpoints: (sessionId: string, wsId: string) =>
    api.get<{ checkpoints: Checkpoint[] }>(
      `/sessions/${sessionId}/worker-sessions/${wsId}/checkpoints`,
    ),

  restore: (sessionId: string, wsId: string, checkpointId: string) =>
    api.post<{ execution_id: string }>(
      `/sessions/${sessionId}/worker-sessions/${wsId}/checkpoints/${checkpointId}/restore`,
    ),

  messages: (sessionId: string, wsId: string, nodeId?: string) => {
    const params = new URLSearchParams({ client_only: "true" });
    if (nodeId) params.set("node_id", nodeId);
    return api.get<{ messages: Message[] }>(
      `/sessions/${sessionId}/worker-sessions/${wsId}/messages?${params}`,
    );
  },
};
