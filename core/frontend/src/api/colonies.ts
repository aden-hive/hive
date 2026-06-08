import { api } from "./client";
import type { ToolMeta, McpServerTools } from "./queens";

export interface ColonySummary {
  name: string;
  queen_name: string | null;
  created_at: string | null;
  has_allowlist: boolean;
  enabled_count: number | null;
}

export interface ColonyToolsResponse {
  colony_name: string;
  enabled_mcp_tools: string[] | null;
  stale: boolean;
  lifecycle: ToolMeta[];
  synthetic: ToolMeta[];
  mcp_servers: McpServerTools[];
}

export interface ColonyToolsUpdateResult {
  colony_name: string;
  enabled_mcp_tools: string[] | null;
  refreshed_runtimes: number;
  note?: string;
}

/** A worker template within a colony. ``integrations`` maps provider
 *  id (``slack``, ``google``, etc.) to the alias of the connected
 *  account this profile pins by default for MCP tool calls. */
export interface WorkerProfile {
  name: string;
  task?: string;
  skill_name?: string;
  integrations?: Record<string, string>;
  concurrency_hint?: number;
  prompt_override?: string;
  tool_filter?: string[];
}

export const coloniesApi = {
  /** List every colony on disk with a summary of its tool allowlist. */
  list: () =>
    api.get<{ colonies: ColonySummary[] }>(`/colonies/tools-index`),

  /** Enumerate a colony's tool surface (lifecycle + synthetic + MCP). */
  getTools: (colonyName: string) =>
    api.get<ColonyToolsResponse>(
      `/colony/${encodeURIComponent(colonyName)}/tools`,
    ),

  /** Persist a colony's MCP tool allowlist.
   *
   * ``null`` resets to "allow every MCP tool". A list of names enables
   * only those MCP tools. Changes take effect on the next worker spawn;
   * in-flight workers keep their booted tool list.
   */
  updateTools: (colonyName: string, enabled: string[] | null) =>
    api.patch<ColonyToolsUpdateResult>(
      `/colony/${encodeURIComponent(colonyName)}/tools`,
      { enabled_mcp_tools: enabled },
    ),

  /** List the colony's worker profiles. Always returns at least one
   *  entry — legacy colonies materialise a synthetic ``default``. */
  listWorkerProfiles: (colonyName: string) =>
    api.get<{ worker_profiles: WorkerProfile[] }>(
      `/colonies/${encodeURIComponent(colonyName)}/worker_profiles`,
    ),

  /** Insert or replace a single worker profile. Existing siblings are
   *  preserved. The desktop uses this for both add and edit. */
  upsertWorkerProfile: (colonyName: string, profile: WorkerProfile) =>
    api.post<{ worker_profiles: WorkerProfile[] }>(
      `/colonies/${encodeURIComponent(colonyName)}/worker_profiles`,
      profile,
    ),

  /** Delete a worker profile. Returns 409 with ``bound_workers`` when a
   *  live worker is still using it; the UI should prompt the user to
   *  stop those workers first. The synthetic ``default`` profile cannot
   *  be deleted. */
  deleteWorkerProfile: (colonyName: string, profileName: string) =>
    api.delete<{ deleted: boolean; profile_name: string }>(
      `/colonies/${encodeURIComponent(colonyName)}/worker_profiles/${encodeURIComponent(profileName)}`,
    ),
};
