import { api } from "./client";
import type { ChatResult } from "./types";

export interface UploadAttachmentResult {
  filename: string;
  path: string;
  session_id: string;
  content_type: string;
  original_name: string;
  extracted_text?: string;
  /** @deprecated The runtime stopped rasterizing PDFs at upload — PDFs
   * now ride into chat as a native `file` data URI via the chat
   * endpoint. Kept on the type so older payloads parse, but always
   * empty going forward. */
  page_images?: string[];
}

export const executionApi = {
  /** Upload a file attachment to a session's attachments directory. */
  uploadAttachment: (sessionId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.upload<UploadAttachmentResult>(`/sessions/${sessionId}/upload-attachment`, fd);
  },

  chat: (
    sessionId: string,
    message: string,
    images?: { type: string; image_url: { url: string } }[],
    displayMessage?: string,
  ) => {
    return api.post<ChatResult>(`/sessions/${sessionId}/chat`, {
      message,
      ...(images?.length ? { images } : {}),
      ...(displayMessage !== undefined ? { display_message: displayMessage } : {}),
    });
  },

  /** Queue context for the queen without triggering an LLM response. */
  queenContext: (sessionId: string, message: string) => {
    return api.post<ChatResult>(`/sessions/${sessionId}/queen-context`, { message });
  },

  /**
   * Persist a user message straight to the on-disk transcript WITHOUT running
   * the queen or requiring an active plan. For free/unpaid users whose
   * selection in a read-only (never-booted) session must survive reload and be
   * picked up when the queen resumes after they upgrade. Deliberately omits
   * assertSubscriptionActive — recording costs zero compute (see the runtime's
   * /record-message handler).
   */
  recordMessage: (sessionId: string, message: string) =>
    api.post<{ status: string; seq: number }>(
      `/sessions/${sessionId}/record-message`,
      { message },
    ),

  cancelQueen: (sessionId: string) =>
    api.post<{ cancelled: boolean; error?: string }>(
      `/sessions/${sessionId}/cancel-queen`,
    ),

  /** Signal that the user (re-)entered this chat. Lifts an explicit
   *  user-stop so a stopped agent un-freezes (it resumes via the normal
   *  idle nudge, not instantly). No-op when the agent isn't stopped. */
  markPresence: (sessionId: string) =>
    api.post<{ ok: boolean; resumed: boolean }>(`/sessions/${sessionId}/presence`),

  /** Lock a queen DM session because the user opened a spawned colony.
   *  After this call /chat returns 409 until compactAndFork creates a new session.
   */
  markColonySpawned: (sessionId: string, colonyId: string) =>
    api.post<{
      session_id: string;
      colony_spawned: boolean;
      spawned_colony_id: string;
    }>(`/sessions/${sessionId}/mark-colony-spawned`, {
      colony_id: colonyId,
    }),

  /** Compact the locked session and fork into a fresh session under the same queen.
   *  Returns the new session ID; the frontend should navigate the user to it.
   */
  compactAndFork: (sessionId: string) =>
    api.post<{
      new_session_id: string;
      queen_id: string;
      compacted_from: string;
      summary_chars: number;
      messages_compacted: number;
    }>(`/sessions/${sessionId}/compact-and-fork`),
};
