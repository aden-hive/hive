import { api } from "./client";

export interface QueenProfile {
  id: string;
  name: string;
  title: string;
  summary?: string;
  experience?: Array<{ role: string; details: string[] }>;
  skills?: string;
  signature_achievement?: string;
}

export interface QueenSessionResult {
  session_id: string;
  queen_id: string;
  status: "live" | "resumed" | "created";
}

export const queensApi = {
  /** List all queen profiles (id, name, title). */
  list: () =>
    api.get<{ queens: Array<{ id: string; name: string; title: string }> }>(
      "/queen/profiles",
    ),

  /** Get full profile for a queen. */
  getProfile: (queenId: string) =>
    api.get<QueenProfile>(`/queen/${queenId}/profile`),

  /** Update queen profile fields (partial update). */
  updateProfile: (queenId: string, updates: Partial<QueenProfile>) =>
    api.patch<QueenProfile>(`/queen/${queenId}/profile`, updates),

  /** Get or create a persistent session for a queen. */
  getOrCreateSession: (queenId: string, initialPrompt?: string) =>
    api.post<QueenSessionResult>(`/queen/${queenId}/session`, {
      initial_prompt: initialPrompt,
    }),
};
