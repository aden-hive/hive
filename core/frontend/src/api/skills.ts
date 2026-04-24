import { api } from "./client";

export type SkillScopeKind = "queen" | "colony" | "user";

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
  colony_name?: string;
  all_defaults_disabled: boolean;
  skills: SkillRow[];
  inherited_from_queen?: string[];
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

const scopePath = (scope: "queen" | "colony", targetId: string) =>
  scope === "queen"
    ? `/queen/${encodeURIComponent(targetId)}/skills`
    : `/colonies/${encodeURIComponent(targetId)}/skills`;

export const skillsApi = {
  // Aggregated library
  listAll: () => api.get<AggregatedSkillsResponse>("/skills"),
  listScopes: () => api.get<SkillScopesResponse>("/skills/scopes"),
  getDetail: (name: string) =>
    api.get<SkillDetailResponse>(`/skills/${encodeURIComponent(name)}`),

  // Per-scope
  listForQueen: (queenId: string) =>
    api.get<ScopeSkillsResponse>(`/queen/${encodeURIComponent(queenId)}/skills`),
  listForColony: (colonyName: string) =>
    api.get<ScopeSkillsResponse>(
      `/colonies/${encodeURIComponent(colonyName)}/skills`,
    ),

  create: (
    scope: "queen" | "colony",
    targetId: string,
    payload: SkillCreatePayload,
  ) => api.post<SkillRow>(scopePath(scope, targetId), payload),

  patch: (
    scope: "queen" | "colony",
    targetId: string,
    skillName: string,
    payload: SkillPatchPayload,
  ) =>
    api.patch<{ name: string; enabled: boolean | null; ok: boolean }>(
      `${scopePath(scope, targetId)}/${encodeURIComponent(skillName)}`,
      payload,
    ),

  putBody: (
    scope: "queen" | "colony",
    targetId: string,
    skillName: string,
    payload: { body: string; description?: string },
  ) =>
    api.put<{ name: string; installed_path: string }>(
      `${scopePath(scope, targetId)}/${encodeURIComponent(skillName)}/body`,
      payload,
    ),

  remove: (scope: "queen" | "colony", targetId: string, skillName: string) =>
    api.delete<{ name: string; removed: boolean }>(
      `${scopePath(scope, targetId)}/${encodeURIComponent(skillName)}`,
    ),

  reload: (scope: "queen" | "colony", targetId: string) =>
    api.post<{ ok: boolean }>(`${scopePath(scope, targetId)}/reload`),

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
