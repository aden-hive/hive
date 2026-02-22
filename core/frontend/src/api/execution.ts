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
    agentId: string,
    entryPointId: string,
    inputData: Record<string, unknown>,
    sessionState?: Record<string, unknown>,
  ) =>
    api.post<TriggerResult>(`/agents/${agentId}/trigger`, {
      entry_point_id: entryPointId,
      input_data: inputData,
      session_state: sessionState,
    }),

  inject: (
    agentId: string,
    nodeId: string,
    content: string,
    graphId?: string,
  ) =>
    api.post<InjectResult>(`/agents/${agentId}/inject`, {
      node_id: nodeId,
      content,
      graph_id: graphId,
    }),

  chat: (agentId: string, message: string) =>
    api.post<ChatResult>(`/agents/${agentId}/chat`, { message }),

  stop: (agentId: string, executionId: string) =>
    api.post<StopResult>(`/agents/${agentId}/stop`, {
      execution_id: executionId,
    }),

  pause: (agentId: string, executionId: string) =>
    api.post<StopResult>(`/agents/${agentId}/pause`, {
      execution_id: executionId,
    }),

  resume: (agentId: string, sessionId: string, checkpointId?: string) =>
    api.post<ResumeResult>(`/agents/${agentId}/resume`, {
      session_id: sessionId,
      checkpoint_id: checkpointId,
    }),

  replay: (agentId: string, sessionId: string, checkpointId: string) =>
    api.post<ReplayResult>(`/agents/${agentId}/replay`, {
      session_id: sessionId,
      checkpoint_id: checkpointId,
    }),

  goalProgress: (agentId: string) =>
    api.get<GoalProgress>(`/agents/${agentId}/goal-progress`),
};
