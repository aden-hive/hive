import { api } from "./client";

export interface SubscriptionInfo {
  id: string;
  name: string;
  description: string;
  provider: string;
  flag: string;
  default_model: string;
  api_base?: string;
}

export interface LLMConfig {
  provider: string;
  model: string;
  has_api_key: boolean;
  max_tokens: number | null;
  max_context_tokens: number | null;
  connected_providers: string[];
  active_subscription: string | null;
  detected_subscriptions: string[];
  subscriptions: SubscriptionInfo[];
  /** The endpoint configuration.json actually points at — set for custom
   * OpenAI-compatible endpoints (self-hosted vLLM, vendor proxies, …). */
  api_base?: string | null;
  api_key_env_var?: string | null;
}

export interface LLMConfigUpdateResponse {
  provider: string;
  model: string;
  has_api_key: boolean;
  max_tokens: number;
  max_context_tokens: number;
  sessions_swapped: number;
  active_subscription: string | null;
}

export interface ModelOption {
  id: string;
  label: string;
  recommended: boolean;
  max_tokens: number;
  max_context_tokens: number;
}

export interface ModelsCatalogue {
  models: Record<string, ModelOption[]>;
}

export interface RateLimitEntry {
  platform: string;
  action_type: string;
  min_delay_s: number;
  hourly?: number;
  hourly_max?: number;
  hourly_default?: number;
  daily?: number;
  daily_max?: number;
  daily_default?: number;
  weekly?: number;
  weekly_max?: number;
  weekly_default?: number;
}

export interface FeaturesConfig {
  /** Colony-adaptive worker tool budgets (Developer options toggle). */
  adaptive_tool_budget: boolean;
  /**
   * Email senders — the sender pool, rotation and send tools (Developer
   * options toggle). Off by default. Also gates whether the runtime registers
   * the sender tools with the MCP server, so this is what hides the feature
   * from the agent, not just from the UI. See useEmailSendersEnabled.
   */
  email_senders: boolean;
}

/** One provider slot in configuration.json (llm / worker_llm /
 * vision_fallback) — displayed and saved verbatim, unknown keys included. */
export type LlmRole = "llm" | "worker_llm" | "vision_fallback";
export interface LlmSection {
  provider?: string;
  model?: string;
  api_base?: string;
  api_key?: string;
  api_key_env_var?: string;
  max_tokens?: number | null;
  max_context_tokens?: number | null;
  [k: string]: unknown;
}

/** One configured external skill root and its resolution status. */
export interface ExternalSkillSource {
  path: string;
  resolved?: string;
  exists: boolean;
  skills: number;
  error?: string;
}

export const configApi = {
  getLLMConfig: () => api.get<LLMConfig>("/config/llm"),

  /** The three provider slots in configuration.json, verbatim. */
  getLlmSections: () =>
    api.get<Record<LlmRole, LlmSection | null>>("/config/llm-sections"),

  /** Write one slot verbatim (null clears worker/vision; the api_key is
   * health-checked against api_base before committing). */
  putLlmSection: (role: LlmRole, section: LlmSection | null) =>
    api.put<{ role: LlmRole; section: LlmSection | null; sessions_swapped?: number }>(
      "/config/llm-sections",
      { role, section },
    ),

  /** Saved vendor configs (configuration.json "provider_library"), verbatim. */
  getProviderLibrary: () =>
    api.get<{ library: Record<string, LlmSection> }>("/config/provider-library"),

  /** Save (or delete, with null) one named library entry. No health check —
   * validation happens when the entry is applied to a slot. */
  putProviderLibraryEntry: (name: string, section: LlmSection | null) =>
    api.put<{ name: string; section: LlmSection | null }>(
      "/config/provider-library",
      { name, section },
    ),

  /** Copy a library entry into a slot — same validation + hot-swap path as
   * putLlmSection. */
  applyProviderLibraryEntry: (name: string, role: LlmRole) =>
    api.post<{ role: LlmRole; section: LlmSection; sessions_swapped?: number }>(
      "/config/provider-library/apply",
      { name, role },
    ),

  /** External skill roots (configuration.json "external_skills"), verbatim.
   * `suggestions` = auto-discovered known agent skill dirs (exist, contain
   * skills, not yet configured). */
  getExternalSkills: () =>
    api.get<{ paths: string[]; resolved: ExternalSkillSource[]; suggestions?: ExternalSkillSource[] }>(
      "/config/external-skills",
    ),

  setExternalSkills: (paths: string[]) =>
    api.put<{ paths: string[]; resolved: ExternalSkillSource[] }>("/config/external-skills", { paths }),

  getFeatures: () => api.get<{ features: FeaturesConfig }>("/config/features"),

  /**
   * Persists to configuration.json (new sessions) and hot-applies to
   * running colonies; colonies with a per-colony metadata pin keep it.
   */
  setFeatures: (features: Partial<FeaturesConfig>) =>
    api.put<{ features: Partial<FeaturesConfig>; colonies_applied: number }>(
      "/config/features",
      { features },
    ),

  setLLMConfig: (provider: string, model: string) =>
    api.put<LLMConfigUpdateResponse>("/config/llm", { provider, model }),

  /** Switch models on the config's own (custom) endpoint — no catalogue
   * validation, api_base / api_key_env_var stay as configured. */
  setLLMConfigCustom: (model: string) =>
    api.put<LLMConfigUpdateResponse>("/config/llm", { custom: true, model }),

  activateSubscription: (subscriptionId: string) =>
    api.put<LLMConfigUpdateResponse>("/config/llm", { subscription: subscriptionId }),

  getModels: () => api.get<ModelsCatalogue>("/config/models"),

  getProfile: () =>
    api.get<{
      displayName: string;
      about: string;
      theme: string;
      /** True when an avatar.{jpg|png|webp} exists in the hive config dir. */
      has_avatar?: boolean;
      prompt_library_sort?: { my?: string; community?: string } | null;
    }>("/config/profile"),

  setProfile: (
    displayName?: string,
    about?: string,
    theme?: string,
    density?: string,
    promptLibrarySort?: { my?: string; community?: string },
  ) =>
    api.put<{
      displayName: string;
      about: string;
      theme: string;
      prompt_library_sort?: { my?: string; community?: string } | null;
    }>("/config/profile", {
      // Each field is only included when explicitly supplied — the runtime
      // treats present-but-empty as authoritative ("set to empty"), so
      // theme/density toggles can't be allowed to send "" for displayName.
      ...(displayName !== undefined ? { displayName } : {}),
      ...(about !== undefined ? { about } : {}),
      ...(theme ? { theme } : {}),
      ...(density ? { density } : {}),
      ...(promptLibrarySort ? { prompt_library_sort: promptLibrarySort } : {}),
    }),

  getRateLimits: () =>
    api.get<{ limits: RateLimitEntry[] }>("/config/rate-limits"),

  setRateLimits: (limits: Record<string, number>) =>
    api.put<{ limits: RateLimitEntry[]; warnings?: string[] }>("/config/rate-limits", { limits }),

  uploadAvatar: (file: Blob) => {
    const fd = new FormData();
    fd.append("avatar", file);
    return api.upload<{ avatar_url: string }>("/config/profile/avatar", fd);
  },
};
