import { api } from "./client";
import type { DiscoverResult } from "./types";

export const agentsApi = {
  discover: () => api.get<DiscoverResult>("/discover"),

  /** Permanently delete an agent and all its sessions/files. */
  deleteAgent: (agentPath: string) =>
    api.delete<{ deleted: string }>("/agents", { agent_path: agentPath }),
};
