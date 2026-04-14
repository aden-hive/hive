import { api } from "./client";
import type {
  AgentEvent,
  HistorySession,
  LiveSession,
  LiveSessionDetail,
  EntryPoint,
} from "./types";

export const sessionsApi = {
  // --- Session lifecycle ---

  /** Create a session. If agentPath is provided, loads a colony in one step. */
  create: (agentPath?: string, agentId?: string, model?: string, initialPrompt?: string, queenResumeFrom?: string, initialPhase?: string, workerName?: string) =>
    api.post<LiveSession>("/sessions", {
      agent_path: agentPath,
      agent_id: agentId,
      model,
      initial_prompt: initialPrompt,
      queen_resume_from: queenResumeFrom || undefined,
      initial_phase: initialPhase || undefined,
      worker_name: workerName || undefined,
    }),

  /** List all active sessions. */
  list: () => api.get<{ sessions: LiveSession[] }>("/sessions"),

  /** Get session detail (includes entry_points, colonies when a worker is loaded). */
  get: (sessionId: string) =>
    api.get<LiveSessionDetail>(`/sessions/${sessionId}`),

  /** Stop a session entirely. */
  stop: (sessionId: string) =>
    api.delete<{ session_id: string; stopped: boolean }>(
      `/sessions/${sessionId}`,
    ),

  // --- Colony lifecycle ---

  loadColony: (
    sessionId: string,
    agentPath: string,
    colonyId?: string,
    model?: string,
  ) =>
    api.post<LiveSession>(`/sessions/${sessionId}/colony`, {
      agent_path: agentPath,
      colony_id: colonyId,
      model,
    }),

  unloadColony: (sessionId: string) =>
    api.delete<{ session_id: string; colony_unloaded: boolean }>(
      `/sessions/${sessionId}/colony`,
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

  activateTrigger: (sessionId: string, triggerId: string) =>
    api.post<{ status: string; trigger_id: string }>(
      `/sessions/${sessionId}/triggers/${triggerId}/activate`,
    ),

  deactivateTrigger: (sessionId: string, triggerId: string) =>
    api.post<{ status: string; trigger_id: string }>(
      `/sessions/${sessionId}/triggers/${triggerId}/deactivate`,
    ),

  colonies: (sessionId: string) =>
    api.get<{ colonies: string[] }>(`/sessions/${sessionId}/colonies`),

  /** Get persisted eventbus log for a session (works for cold sessions — used for full UI replay). */
  eventsHistory: (sessionId: string) =>
    api.get<{ events: AgentEvent[]; session_id: string }>(`/sessions/${sessionId}/events/history`),

  /** Open the session's data folder in the OS file manager. */
  revealFolder: (sessionId: string) =>
    api.post<{ path: string }>(`/sessions/${sessionId}/reveal`),

  /** List all queen sessions on disk — live + cold (post-restart). */
  history: () =>
    api.get<{ sessions: HistorySession[] }>("/sessions/history"),

  /** Permanently delete a history session (stops live session + removes disk files). */
  deleteHistory: (sessionId: string) =>
    api.delete<{ deleted: string }>(`/sessions/history/${sessionId}`),
};
