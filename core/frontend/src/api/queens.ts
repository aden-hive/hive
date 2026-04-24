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

export interface ToolMeta {
  name: string;
  description: string;
  input_schema?: Record<string, unknown>;
  editable?: boolean;
}

export interface McpServerTools {
  name: string;
  tools: Array<ToolMeta & { enabled: boolean }>;
}

export interface QueenToolsResponse {
  queen_id: string;
  enabled_mcp_tools: string[] | null;
  /** True when the effective allowlist comes from the role-based default
   * (no tools.json sidecar saved for this queen). False means the user
   * has explicitly saved an allowlist. */
  is_role_default: boolean;
  stale: boolean;
  lifecycle: ToolMeta[];
  synthetic: ToolMeta[];
  mcp_servers: McpServerTools[];
}

export interface QueenToolsUpdateResult {
  queen_id: string;
  enabled_mcp_tools: string[] | null;
  refreshed_sessions: number;
}

export interface QueenToolsResetResult {
  queen_id: string;
  removed: boolean;
  enabled_mcp_tools: string[] | null;
  is_role_default: true;
  refreshed_sessions: number;
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

  /** Upload queen avatar image. */
  uploadAvatar: (queenId: string, file: File) => {
    const fd = new FormData();
    fd.append("avatar", file);
    return api.upload<{ avatar_url: string }>(`/queen/${queenId}/avatar`, fd);
  },

  /** Get or create a persistent session for a queen. */
  getOrCreateSession: (queenId: string, initialPrompt?: string, initialPhase?: string) =>
    api.post<QueenSessionResult>(`/queen/${queenId}/session`, {
      initial_prompt: initialPrompt,
      initial_phase: initialPhase || undefined,
    }),

  /** Select a specific historical session for a queen. */
  selectSession: (queenId: string, sessionId: string) =>
    api.post<QueenSessionResult>(`/queen/${queenId}/session/select`, {
      session_id: sessionId,
    }),

  /** Create a fresh session for a queen. */
  createNewSession: (queenId: string, initialPrompt?: string, initialPhase?: string) =>
    api.post<QueenSessionResult>(`/queen/${queenId}/session/new`, {
      initial_prompt: initialPrompt,
      initial_phase: initialPhase || undefined,
    }),

  /** Enumerate the queen's tool surface (lifecycle + synthetic + MCP). */
  getTools: (queenId: string) =>
    api.get<QueenToolsResponse>(`/queen/${queenId}/tools`),

  /** Persist the MCP tool allowlist for a queen.
   *
   * Pass ``null`` to explicitly allow every MCP tool, or a list to
   * restrict the queen's tool surface. Lifecycle and synthetic tools
   * are always enabled and cannot be listed here.
   */
  updateTools: (queenId: string, enabled: string[] | null) =>
    api.patch<QueenToolsUpdateResult>(`/queen/${queenId}/tools`, {
      enabled_mcp_tools: enabled,
    }),

  /** Drop the queen's tools.json sidecar so she falls back to the
   * role-based default (or allow-all for queens without a role entry). */
  resetTools: (queenId: string) =>
    api.delete<QueenToolsResetResult>(`/queen/${queenId}/tools`),
};
