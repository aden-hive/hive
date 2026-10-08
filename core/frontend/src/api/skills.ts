import { api } from "./client";

export type SkillScopeKind = "queen" | "user";

export type SkillProvenance =
  | "framework"
  | "preset"
  | "user_dropped"
  | "user_ui_created"
  | "queen_created"
  | "learned_runtime"
  | "project_dropped"
  | "other";

export interface SkillOwner {
  type: "queen" | "colony";
  id: string;
  name: string;
}

export interface SkillRow {
  name: string;
  description: string;
  source_scope: string;
  provenance: SkillProvenance;
  enabled: boolean;
  editable: boolean;
  deletable: boolean;
  location: string;
  base_dir?: string;
  visibility: string[] | null;
  trust: string | null;
  created_at: string | null;
  created_by: string | null;
  notes: string | null;
  param_overrides?: Record<string, unknown>;
  owner?: SkillOwner | null;
  visible_to?: { queens: string[]; colonies: string[] };
  enabled_by_default?: boolean;
}

export interface ScopeSkillsResponse {
  queen_id?: string;
  all_defaults_disabled: boolean;
  skills: SkillRow[];
}

export interface AggregatedSkillsResponse {
  skills: SkillRow[];
  queens: Array<{ id: string; name: string }>;
  colonies: Array<{ name: string; queen_id: string | null }>;
}

export interface SkillScopesResponse {
  queens: Array<{ id: string; name: string }>;
  colonies: Array<{ name: string; queen_id: string | null }>;
}

export interface SkillDetailResponse {
  name: string;
  description: string;
  source_scope: string;
  location: string;
  base_dir: string;
  body: string;
  visibility: string[] | null;
  // Only the queen-scoped body endpoint sets this; the scope-less detail
  // endpoint leaves it undefined.
  editable?: boolean;
}

export interface SkillCreatePayload {
  name: string;
  description: string;
  body: string;
  files?: Array<{ path: string; content: string }>;
  enabled?: boolean;
  notes?: string | null;
  replace_existing?: boolean;
}

export interface SkillPatchPayload {
  enabled?: boolean;
  param_overrides?: Record<string, unknown>;
  notes?: string | null;
  all_defaults_disabled?: boolean;
}

const queenPath = (queenId: string) =>
  `/queen/${encodeURIComponent(queenId)}/skills`;

export const skillsApi = {
  // Aggregated library
  listAll: () => api.get<AggregatedSkillsResponse>("/skills"),
  listScopes: () => api.get<SkillScopesResponse>("/skills/scopes"),
  getDetail: (name: string) =>
    api.get<SkillDetailResponse>(`/skills/${encodeURIComponent(name)}`),

  // Per-queen (colonies inherit their owning queen's skill config)
  listForQueen: (queenId: string) =>
    api.get<ScopeSkillsResponse>(queenPath(queenId)),

  create: (queenId: string, payload: SkillCreatePayload) =>
    api.post<SkillRow>(queenPath(queenId), payload),

  patch: (queenId: string, skillName: string, payload: SkillPatchPayload) =>
    api.patch<{ name: string; enabled: boolean | null; ok: boolean }>(
      `${queenPath(queenId)}/${encodeURIComponent(skillName)}`,
      payload,
    ),

  // Queen-scoped body read: returns THIS queen's copy with a frontmatter-
  // stripped `body` (round-trips through putBody, which re-adds frontmatter).
  getBody: (queenId: string, skillName: string) =>
    api.get<SkillDetailResponse>(
      `${queenPath(queenId)}/${encodeURIComponent(skillName)}/body`,
    ),

  putBody: (
    queenId: string,
    skillName: string,
    payload: { body: string; description?: string },
  ) =>
    api.put<{ name: string; installed_path: string }>(
      `${queenPath(queenId)}/${encodeURIComponent(skillName)}/body`,
      payload,
    ),

  rename: (queenId: string, skillName: string, newName: string) =>
    api.post<{ old_name: string; new_name: string; ok: boolean }>(
      `${queenPath(queenId)}/${encodeURIComponent(skillName)}/rename`,
      { new_name: newName },
    ),

  remove: (queenId: string, skillName: string) =>
    api.delete<{ name: string; removed: boolean }>(
      `${queenPath(queenId)}/${encodeURIComponent(skillName)}`,
    ),

  reload: (queenId: string) =>
    api.post<{ ok: boolean }>(`${queenPath(queenId)}/reload`),

  // Multipart upload. File may be a SKILL.md or a .zip bundle.
  upload: (formData: FormData) =>
    api.upload<{
      name: string;
      installed_path: string;
      replaced: boolean;
      scope: SkillScopeKind;
      target_id: string | null;
      enabled: boolean;
    }>("/skills/upload", formData),
};
