import { api } from "./client";
import type { LlmSection } from "./config";

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

export type QueenLlm = {
  queen_id: string;
  section: LlmSection | null;
  /** The main model she uses without a section of her own. */
  default_model?: string;
};

/** Her persona as profile.yaml holds it (the fields the profile page edits). */
export type QueenPersona = {
  name?: string;
  title?: string;
  /** The heart of the persona: free text, often in <tag>…</tag> chapters. */
  core_traits?: string;
  /** Comma-separated. */
  skills?: string;
  hidden_background?: Record<string, string>;
  psychological_profile?: Record<string, string>;
  world_lore?: Record<string, string>;
  behavior_triggers?: { trigger: string; reaction: string }[];
};

export type QueenOverview = {
  queen_id: string;
  /** `limit`: the most notes her memory keeps. */
  memory: { count: number; limit: number; by_type: Record<string, number> };
  sessions: { count: number; first: string | null; last_active: string | null };
};

export type SoulItem = { text: string; date: string };

export type SoulSectionView = {
  key: string;
  title: string;
  /** Characters the section may hold, and holds now. */
  limit: number;
  used: number;
  max_age_days: number | null;
  /** Quotes, from different people or chats, each change to it needs. */
  evidence: number;
  items: SoulItem[];
};

export type SoulEdit = {
  op: "add" | "update" | "remove";
  section: string;
  text: string;
  old: string;
  date: string;
  evidence: { quote: string; where: string }[];
  reason: string;
  /** Dropped for its age, not by her. */
  expired: boolean;
};

export type SoulProposal = {
  id: string;
  created_at: string;
  base_version: number;
  edits: SoulEdit[];
  summary: string;
  status: "pending" | "applied" | "dismissed";
  sources: string[];
  bootstrap: boolean;
  /** Her probe questions answered with the soul before and after these changes. */
  probes: { q: string; anchor: string; before: string; after: string }[];
};

export type SoulVersion = { version: number; at: string; author: string; note: string; changes: number };

/** A queen's soul: the short self-description she revises once a day (configuration.json `soul`). */
export type QueenSoul =
  | { queen_id: string; enabled: false }
  | {
      queen_id: string;
      enabled: true;
      /** "review": changes wait for approval; "auto": they apply at once. */
      mode: "review" | "auto";
      /** Local hour after which the daily reflection runs. */
      hour: number;
      version: number;
      updated_at: string;
      sections: SoulSectionView[];
      proposal: SoulProposal | null;
      history: SoulVersion[];
      reflecting: boolean;
      /** How many probe questions she has, and whether she is answering them now. */
      probes: number;
      probing: boolean;
      last_run: string | null;
      last_result: string | null;
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

  /** Take her out of the catalog (the position goes; her files stay, for a restore). */
  removeQueen: (queenId: string) =>
    api.post<{ queen_id: string; removed: boolean }>(`/queen/${queenId}/remove`),

  /** Put a removed queen back in the catalog, as she was. */
  restoreQueen: (queenId: string) =>
    api.post<{ queen_id: string; removed: boolean }>(`/queen/${queenId}/restore`),

  /** The queens taken out of the catalog. */
  listRemoved: () =>
    api.get<{ queens: Array<{ id: string; name: string; title: string; custom?: boolean }> }>("/queen/removed"),

  /** Get full profile for a queen. */
  getProfile: (queenId: string) =>
    api.get<QueenProfile>(`/queen/${queenId}/profile`),

  /** The queen's own model (configuration.json `queen_llm`), or `section: null` when she
   * uses the main model (AI Model → LLM). */
  getLlm: (queenId: string) =>
    api.get<QueenLlm>(`/queen/${queenId}/llm`),

  /** Give the queen a model of her own (same shape and key check as the main slot), or
   * `null` to return her to the main model. Her running sessions switch at once. */
  setLlm: (queenId: string, section: LlmSection | null) =>
    api.put<QueenLlm & { sessions_switched: number }>(`/queen/${queenId}/llm`, { section }),

  /** Her persona fields as profile.yaml holds them. */
  getPersona: (queenId: string) =>
    api.get<{ queen_id: string; persona: QueenPersona }>(`/queen/${queenId}/persona`),

  /** Replace persona fields whole (`null` removes a map or list); her running chats follow. */
  setPersona: (queenId: string, persona: Partial<Record<keyof QueenPersona, unknown>>) =>
    api.put<{ queen_id: string; persona: QueenPersona }>(`/queen/${queenId}/persona`, { persona }),

  /** What her profile page counts: memories by type, sessions, last activity. */
  getOverview: (queenId: string) => api.get<QueenOverview>(`/queen/${queenId}/overview`),

  /** Her soul by section, the proposal waiting for a decision, and its history. */
  getSoul: (queenId: string) => api.get<QueenSoul>(`/queen/${queenId}/soul`),

  /** Replace her soul by hand: a new version. */
  setSoul: (queenId: string, sections: Record<string, SoulItem[]>) =>
    api.put<QueenSoul>(`/queen/${queenId}/soul`, { sections }),

  /** Apply the accepted changes of a proposal (`null`: all of them; `[]`: dismiss it). */
  decideSoulProposal: (queenId: string, proposalId: string, accept: number[] | null) =>
    api.post<QueenSoul>(`/queen/${queenId}/soul/proposals/${proposalId}/decide`, { accept }),

  /** Make an earlier version current again (as a new version). */
  rollbackSoul: (queenId: string, version: number) =>
    api.post<QueenSoul>(`/queen/${queenId}/soul/rollback`, { version }),

  /** Answer her probe questions before and after a proposal's changes, in the background. */
  probeSoulProposal: (queenId: string, proposalId: string) =>
    api.post<{ started: boolean }>(`/queen/${queenId}/soul/proposals/${proposalId}/probe`),

  /** Run a reflection now, in the background; `bootstrap` writes the first draft. */
  reflectSoul: (queenId: string, bootstrap = false) =>
    api.post<{ started: boolean }>(`/queen/${queenId}/soul/reflect`, { bootstrap }),

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
