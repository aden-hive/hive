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

  chat: (sessionId: string, message: string, attachmentIds?: string[]) =>
    api.post<ChatResult>(`/sessions/${sessionId}/chat`, {
      message,
      ...(attachmentIds?.length ? { attachment_ids: attachmentIds } : {}),
    }),

  /** Upload files for chat attachments. Returns file_ids to pass to chat(). */
  uploadFiles: async (
    sessionId: string,
    files: File[],
  ): Promise<{ files: { file_id: string; filename: string; size: number }[]; errors?: string[] }> => {
    const { ApiError } = await import("./client");
    const formData = new FormData();
    for (const f of files) formData.append("file", f);
    const res = await fetch(`/api/sessions/${sessionId}/uploads`, {
      method: "POST",
      body: formData,
      // Do not set Content-Type — browser sets multipart boundary
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.details ? `${data.error}: ${(data.details as string[]).join("; ")}` : (data.error as string) || res.statusText;
      throw new ApiError(res.status, { error: msg, ...data });
    }
    return data;
  },

  /** Queue context for the queen without triggering an LLM response. */
  queenContext: (sessionId: string, message: string) =>
    api.post<ChatResult>(`/sessions/${sessionId}/queen-context`, { message }),

  workerInput: (sessionId: string, message: string) =>
    api.post<ChatResult>(`/sessions/${sessionId}/worker-input`, { message }),

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
