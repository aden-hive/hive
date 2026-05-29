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
};
