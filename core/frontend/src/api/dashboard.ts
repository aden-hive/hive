import { api } from "./client";

export interface HealthStatus {
  status: string;
  session_count: number;
  [key: string]: unknown;
}

export interface SessionStats {
  session_id: string;
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_tool_calls?: number;
  total_llm_calls?: number;
  uptime_seconds?: number;
  [key: string]: unknown;
}

export const dashboardApi = {
  health: () => api.get<HealthStatus>("/health"),

  /** Fetch stats for a single session. */
  sessionStats: (sessionId: string) =>
    api.get<SessionStats>(`/sessions/${sessionId}/stats`),

  /** Fetch evaluations for a session. */
  evaluations: (sessionId: string, streamId?: string, limit = 20) =>
    api.get<{ stream_id: string; evaluations: unknown[] }>(
      `/sessions/${sessionId}/evaluations${streamId ? `?stream_id=${streamId}&limit=${limit}` : `?limit=${limit}`}`,
    ),

  /** Fetch improvement plan for a session. */
  improvementPlan: (sessionId: string, streamId?: string, window = 10) =>
    api.get<{ stream_id: string; plan: unknown }>(
      `/sessions/${sessionId}/improvement-plan${streamId ? `?stream_id=${streamId}&window=${window}` : `?window=${window}`}`,
    ),
};
