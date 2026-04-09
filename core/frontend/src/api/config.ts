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

export const configApi = {
  getLLMConfig: () => api.get<LLMConfig>("/config/llm"),

  setLLMConfig: (provider: string, model: string) =>
    api.put<LLMConfigUpdateResponse>("/config/llm", { provider, model }),

  activateSubscription: (subscriptionId: string) =>
    api.put<LLMConfigUpdateResponse>("/config/llm", { subscription: subscriptionId }),

  getModels: () => api.get<ModelsCatalogue>("/config/models"),

  getProfile: () =>
    api.get<{ displayName: string; about: string; theme: string }>("/config/profile"),

  setProfile: (displayName: string, about: string, theme?: string) =>
    api.put<{ displayName: string; about: string; theme: string }>("/config/profile", {
      displayName,
      about,
      ...(theme ? { theme } : {}),
    }),
};
