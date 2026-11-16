import { api } from "./client";

/** Where a slot's model comes from. "custom" is an address set by hand in configuration.json. */
export type ModelSource = "catalog" | "endpoint" | "subscription" | "custom";

/** What a slot uses (never its key). */
export interface SlotSummary {
  source: ModelSource;
  provider: string | null;
  model: string;
  endpoint: string | null;
  subscription: string | null;
  api_base: string | null;
  max_context_tokens: number | null;
  has_extra_body: boolean;
}

export type RoleSlot = "llm" | "worker_llm" | "vision_fallback";
/** A role slot, or a queen's own model as `queen:<id>`. */
export type SlotId = RoleSlot | `queen:${string}`;

export interface CatalogModel {
  id: string;
  label: string;
  recommended: boolean;
  max_context_tokens: number | null;
  supports_vision: boolean;
}

export interface CatalogProvider {
  id: string;
  connected: boolean;
  models: CatalogModel[];
}

/** A named OpenAI-compatible endpoint: Magpie (built in), Ollama, vLLM, LM Studio, a gateway. */
export interface ModelEndpoint {
  name: string;
  api_base: string;
  builtin: boolean;
  has_key: boolean;
  running: boolean;
}

export interface EndpointModel {
  id: string;
  /** A readable name, when the endpoint gives one (Magpie's says where the model comes from). */
  label?: string | null;
  max_context_tokens: number | null;
}

export interface DetectedSubscription {
  id: string;
  name: string;
  description: string;
  model: string;
  detected: boolean;
  active: boolean;
  /** Running a plan unattended, for agents, may break its terms: at the user's own risk. */
  own_risk: boolean;
}

export interface ModelsOverview {
  slots: Record<RoleSlot, SlotSummary | null>;
  judge: { configured: boolean; model: string | null; api_base: string | null };
  queens: Array<{ id: string; name: string } & SlotSummary>;
  providers: CatalogProvider[];
  endpoints: ModelEndpoint[];
  subscriptions: DetectedSubscription[];
}

/** What a slot is set to: a catalog model (with its provider's key) or an endpoint's model. */
export type ModelChoice =
  | { source: "catalog"; provider: string; model: string }
  | { source: "endpoint"; endpoint: string; model: string };

export const modelsApi = {
  overview: () => api.get<ModelsOverview>("/models/overview"),

  setSlot: (slot: SlotId, choice: ModelChoice) =>
    api.put<{ slot: SlotId; summary: SlotSummary | null; sessions_switched: number }>(`/models/slots/${slot}`, choice),

  /** Return a slot to its default: the main model (worker, a queen) or none (vision fallback). */
  clearSlot: (slot: SlotId) => api.delete<{ slot: SlotId; summary: null }>(`/models/slots/${slot}`),

  endpointModels: (name: string, fresh = false) =>
    api.get<{ models: EndpointModel[] }>(`/models/endpoints/${name}/models${fresh ? "?fresh=1" : ""}`),

  /** Add an endpoint, or change its address or key (a string saves it, null removes it). */
  saveEndpoint: (name: string, body: { api_base?: string; api_key?: string | null }) =>
    api.put<ModelEndpoint>(`/models/endpoints/${name}`, body),

  deleteEndpoint: (name: string) => api.delete<{ deleted: string }>(`/models/endpoints/${name}`),
};

/** "262k" for 262144 tokens. */
export function contextLabel(tokens: number | null | undefined): string | null {
  if (!tokens) return null;
  if (tokens >= 1_000_000) return `${+(tokens / 1_000_000).toFixed(1)}M`;
  return `${Math.round(tokens / 1000)}k`;
}
