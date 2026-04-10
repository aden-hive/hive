import { api } from "./client";
import type {
  TriggerResult,
  InjectResult,
  ChatResult,
  StopResult,
  GoalProgress,
} from "./types";

export const executionApi = {
  trigger: (
    sessionId: string,
    entryPointId: string,
    inputData: Record<string, unknown>,
    sessionState?: Record<string, unknown>,
  ) =>
    api.post<TriggerResult>(`/sessions/${sessionId}/trigger`, {
      entry_point_id: entryPointId,
      input_data: inputData,
      session_state: sessionState,
    }),

  inject: (
    sessionId: string,
    nodeId: string,
    content: string,
    colonyId?: string,
  ) =>
    api.post<InjectResult>(`/sessions/${sessionId}/inject`, {
      node_id: nodeId,
      content,
      colony_id: colonyId,
    }),

  chat: (
    sessionId: string,
    message: string,
    images?: { type: string; image_url: { url: string } }[],
    displayMessage?: string,
  ) =>
    api.post<ChatResult>(`/sessions/${sessionId}/chat`, {
      message,
      ...(images?.length ? { images } : {}),
      ...(displayMessage !== undefined ? { display_message: displayMessage } : {}),
    }),

  /** Queue context for the queen without triggering an LLM response. */
  queenContext: (sessionId: string, message: string) =>
    api.post<ChatResult>(`/sessions/${sessionId}/queen-context`, { message }),

  stop: (sessionId: string, executionId: string) =>
    api.post<StopResult>(`/sessions/${sessionId}/stop`, {
      execution_id: executionId,
    }),

  pause: (sessionId: string, executionId: string) =>
    api.post<StopResult>(`/sessions/${sessionId}/pause`, {
      execution_id: executionId,
    }),

  cancelQueen: (sessionId: string) =>
    api.post<{ cancelled: boolean }>(`/sessions/${sessionId}/cancel-queen`),

  goalProgress: (sessionId: string) =>
    api.get<GoalProgress>(`/sessions/${sessionId}/goal-progress`),

  colonySpawn: (sessionId: string, colonyName: string, task?: string) =>
    api.post<{
      colony_path: string;
      colony_name: string;
      queen_session_id: string;
      is_new: boolean;
    }>(
      `/sessions/${sessionId}/colony-spawn`,
      { colony_name: colonyName, task },
    ),
};
