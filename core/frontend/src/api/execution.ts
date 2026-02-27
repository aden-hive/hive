import { api } from "./client";
import type {
  TriggerResult,
  InjectResult,
  ChatResult,
  StopResult,
  ResumeResult,
  ReplayResult,
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
    graphId?: string,
  ) =>
    api.post<InjectResult>(`/sessions/${sessionId}/inject`, {
      node_id: nodeId,
      content,
      graph_id: graphId,
    }),

  chat: (sessionId: string, message: string) =>
    api.post<ChatResult>(`/sessions/${sessionId}/chat`, { message }),

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

  resume: (sessionId: string, workerSessionId: string, checkpointId?: string) =>
    api.post<ResumeResult>(`/sessions/${sessionId}/resume`, {
      session_id: workerSessionId,
      checkpoint_id: checkpointId,
    }),

  replay: (sessionId: string, workerSessionId: string, checkpointId: string) =>
    api.post<ReplayResult>(`/sessions/${sessionId}/replay`, {
      session_id: workerSessionId,
      checkpoint_id: checkpointId,
    }),

  goalProgress: (sessionId: string) =>
    api.get<GoalProgress>(`/sessions/${sessionId}/goal-progress`),
};
