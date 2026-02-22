import { api } from "./client";
import type {
  Agent,
  AgentDetail,
  DiscoverResult,
  EntryPoint,
} from "./types";

export const agentsApi = {
  discover: () => api.get<DiscoverResult>("/discover"),

  list: () => api.get<{ agents: Agent[] }>("/agents"),

  load: (agentPath: string, agentId?: string, model?: string) =>
    api.post<Agent>("/agents", {
      agent_path: agentPath,
      agent_id: agentId,
      model,
    }),

  get: (agentId: string) => api.get<AgentDetail>(`/agents/${agentId}`),

  unload: (agentId: string) =>
    api.delete<{ unloaded: string }>(`/agents/${agentId}`),

  stats: (agentId: string) =>
    api.get<Record<string, unknown>>(`/agents/${agentId}/stats`),

  entryPoints: (agentId: string) =>
    api.get<{ entry_points: EntryPoint[] }>(`/agents/${agentId}/entry-points`),

  graphs: (agentId: string) =>
    api.get<{ graphs: string[] }>(`/agents/${agentId}/graphs`),
};
