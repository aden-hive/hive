import { api } from "./client";
import type {
  AgentEvent,
  LiveSession,
  LiveSessionDetail,
  EntryPoint,
} from "./types";

export const sessionsApi = {
  // --- Session lifecycle ---

  /** Create a session. If agentPath is provided, loads a graph in one step. */
  create: (agentPath?: string, agentId?: string, model?: string, initialPrompt?: string, queenResumeFrom?: string, initialPhase?: string) =>
    api.post<LiveSession>("/sessions", {
      agent_path: agentPath,
      agent_id: agentId,
      model,
      initial_prompt: initialPrompt,
      queen_resume_from: queenResumeFrom || undefined,
      initial_phase: initialPhase || undefined,
    }),

  /** List all active sessions. */
  list: () => api.get<{ sessions: LiveSession[] }>("/sessions"),

  /** Get session detail (includes entry_points, graphs when a graph is loaded). */
  get: (sessionId: string) =>
    api.get<LiveSessionDetail>(`/sessions/${sessionId}`),

  /** Stop a session entirely. */
  stop: (sessionId: string) =>
    api.delete<{ session_id: string; stopped: boolean }>(
      `/sessions/${sessionId}`,
    ),

  // --- Graph lifecycle ---

  loadGraph: (
    sessionId: string,
    agentPath: string,
    graphId?: string,
    model?: string,
  ) =>
    api.post<LiveSession>(`/sessions/${sessionId}/graph`, {
      agent_path: agentPath,
      graph_id: graphId,
      model,
    }),

  unloadGraph: (sessionId: string) =>
    api.delete<{ session_id: string; graph_unloaded: boolean }>(
      `/sessions/${sessionId}/graph`,
    ),

  // --- Session info ---

  stats: (sessionId: string) =>
    api.get<Record<string, unknown>>(`/sessions/${sessionId}/stats`),

  entryPoints: (sessionId: string) =>
    api.get<{ entry_points: EntryPoint[] }>(
      `/sessions/${sessionId}/entry-points`,
    ),

  updateTrigger: (
    sessionId: string,
    triggerId: string,
    patch: { task?: string; trigger_config?: Record<string, unknown> },
  ) =>
    api.patch<{ trigger_id: string; task: string; trigger_config: Record<string, unknown> }>(
      `/sessions/${sessionId}/triggers/${triggerId}`,
      patch,
    ),

  graphs: (sessionId: string) =>
    api.get<{ graphs: string[] }>(`/sessions/${sessionId}/graphs`),

  /** Get persisted eventbus log for a session (works for cold sessions — used for full UI replay). */
  eventsHistory: (sessionId: string) =>
    api.get<{ events: AgentEvent[]; session_id: string }>(`/sessions/${sessionId}/events/history`),

  /** Open the session's data folder in the OS file manager. */
  revealFolder: (sessionId: string) =>
    api.post<{ path: string }>(`/sessions/${sessionId}/reveal`),

  /** List all queen sessions on disk — live + cold (post-restart). */
  history: () =>
    api.get<{ sessions: Array<{ session_id: string; cold: boolean; live: boolean; has_messages: boolean; created_at: number; agent_name?: string | null; agent_path?: string | null }> }>("/sessions/history"),

  /** Permanently delete a history session (stops live session + removes disk files). */
  deleteHistory: (sessionId: string) =>
    api.delete<{ deleted: string }>(`/sessions/history/${sessionId}`),
};
