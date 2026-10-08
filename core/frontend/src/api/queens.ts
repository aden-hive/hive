import { api } from "./client";

export interface PortraitDescriptor {
  cut?: string;
  eyes?: string;
  face?: string;
  hair?: string;
  skin?: string;
  mouth?: string;
  shirt?: string;
  brow?: string;
  glasses?: string;
  moustache?: boolean;
  beard?: string;
  earring?: boolean;
  leather?: boolean;
  neck?: string;
  collar?: string;
}

export interface QueenProfile {
  id: string;
  name: string;
  title: string;
  summary?: string;
  experience?: Array<{ role: string; details: string[] }>;
  skills?: string;
  signature_achievement?: string;
  portrait?: PortraitDescriptor | null;
}

export interface QueenSessionResult {
  session_id: string;
  queen_id: string;
  status: "live" | "resumed" | "created" | "colony";
  /** Set when status is "colony": the on-disk colony slug that owns this
   *  session. The DM page must route to the colony page instead of
   *  adopting the session. */
  colony_id?: string;
}

export interface ToolMeta {
  name: string;
  description: string;
  input_schema?: Record<string, unknown>;
  editable?: boolean;
  /** OAuth provider this tool depends on (e.g. ``google``, ``github``).
   * ``null`` for credential-less tools (browser, terminal, charts, …). */
  provider?: string | null;
  /** True when the user has at least one live OAuth account for the
   * tool's provider. ``true`` for credential-less tools so the UI can
   * treat the flag as "callable right now". */
  provider_connected?: boolean;
}

export interface McpServerTools {
  name: string;
  tools: Array<ToolMeta & { enabled: boolean }>;
}

export interface ToolCategory {
  /** Category id (e.g. "spreadsheet_advanced", "browser_basic"). */
  name: string;
  /** Concrete tool names that belong to this category, after expansion
   * of any ``@server:NAME`` shorthands against the live MCP catalog. */
  tools: string[];
  /** True when this category contributes to the queen's role-based default. */
  in_role_default: boolean;
  /** True when this category's tools are loaded up front and bypass the
   * allowlist (the "always-enabled" tier — locked on; the agent always has
   * them). False categories are searchable: listed to the agent by name and
   * loaded on demand via the search_tools tool. */
  always_enabled?: boolean;
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
  /** Curated category groupings (file_ops, browser_basic, security, …)
   * with resolved tool members. ``in_role_default`` flags categories
   * baked into this queen's default allowlist. */
  categories: ToolCategory[];
  /** Sorted list of OAuth providers with at least one live account.
   * Mirrors the per-tool ``provider_connected`` flag for callers that
   * need a top-level summary (e.g. the "Connect Slack" affordance
   * grouped above the row when no rows are connected yet). */
  connected_providers?: string[];
}

/** PATCH and DELETE now return the full post-mutation snapshot (same
 * shape as GET) plus refreshed_sessions / removed flags. The editor
 * consumes the snapshot directly so its local state can never drift
 * against a catalog that may have changed concurrently. */
export type QueenToolsUpdateResult = QueenToolsResponse & {
  refreshed_sessions: number;
};

export type QueenToolsResetResult = QueenToolsResponse & {
  removed: boolean;
  refreshed_sessions: number;
};

export const queensApi = {
  /** List all queen profiles (id, name, title, portrait, has_avatar). */
  list: () =>
    api.get<{
      queens: Array<{
        id: string;
        name: string;
        title: string;
        portrait?: PortraitDescriptor | null;
        has_avatar?: boolean;
        custom?: boolean;
      }>;
    }>("/queen/profiles"),

  /** Create a brand-new custom queen (writes queens/<id>/profile.yaml).
   * `queen_id` is derived from the name when omitted. */
  createQueen: (body: {
    name: string;
    title?: string;
    persona?: string;
    queen_id?: string;
  }) =>
    api.post<{
      queen: {
        id: string;
        name: string;
        title: string;
        has_avatar?: boolean;
        custom?: boolean;
      };
    }>("/queen/create", body),

  /** Get full profile for a queen. */
  getProfile: (queenId: string) =>
    api.get<QueenProfile>(`/queen/${queenId}/profile`),

  /** Update queen profile fields (partial update). */
  updateProfile: (queenId: string, updates: Partial<QueenProfile>) =>
    api.patch<QueenProfile>(`/queen/${queenId}/profile`, updates),

  /** Upload queen avatar image. */
  uploadAvatar: (queenId: string, file: Blob) => {
    const fd = new FormData();
    fd.append("avatar", file);
    return api.upload<{ avatar_url: string }>(`/queen/${queenId}/avatar`, fd);
  },

  /** Remove the queen's avatar. Idempotent; resolves with ``has_avatar: false``
   * even when nothing was on disk. Cloud sync pushes the deletion onward. */
  deleteAvatar: (queenId: string) =>
    api.delete<{ has_avatar: false }>(`/queen/${queenId}/avatar`),

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

  /** Create a fresh session for a queen.
   *
   * `crmSetup` labels the session as a CRM setup / configuration conversation
   * (the `?crm-setup=1` / `?crm-continue=1` doors). The runtime cannot infer it:
   * the CRM's host queen is also the default queen, so most sessions created
   * here with that id are ordinary chats. Setup-only nudges key off the label.
   */
  createNewSession: (
    queenId: string,
    initialPrompt?: string,
    initialPhase?: string,
    crmSetup?: boolean,
  ) =>
    api.post<QueenSessionResult>(`/queen/${queenId}/session/new`, {
      initial_prompt: initialPrompt,
      initial_phase: initialPhase || undefined,
      crm_setup: crmSetup || undefined,
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
