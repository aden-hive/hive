import { api } from "./client";
import type { DiscoverResult } from "./types";

export const agentsApi = {
  discover: () => api.get<DiscoverResult>("/discover"),

  /** Delete an agent. By default this is a soft delete that hides the
   * colony from discovery while keeping its data on disk. Pass purge=true
   * to permanently remove the agent directory and all tracked data. */
  deleteAgent: (agentPath: string, purge = false) =>
    api.delete<{ deleted: string; purged: boolean }>("/agents", {
      agent_path: agentPath,
      purge,
    }),

  /** Update colony metadata (e.g. icon). */
  updateMetadata: (agentPath: string, updates: { icon?: string }) =>
    api.patch<{ ok: boolean }>("/agents/metadata", { agent_path: agentPath, ...updates }),
};
