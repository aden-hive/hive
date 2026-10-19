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
  colony_id: string;
  enabled_mcp_tools: string[] | null;
  stale: boolean;
  lifecycle: ToolMeta[];
  synthetic: ToolMeta[];
  mcp_servers: McpServerTools[];
}

export interface ColonyToolsUpdateResult {
  colony_id: string;
  enabled_mcp_tools: string[] | null;
  refreshed_runtimes: number;
  note?: string;
}

export const coloniesApi = {
  /** List every colony on disk with a summary of its tool allowlist. */
  list: () =>
    api.get<{ colonies: ColonySummary[] }>(`/colonies/tools-index`),

  /** Create a colony folder (metadata + minimal worker) WITHOUT booting its
   *  queen — no MCP, no LLM. Used by the free-user flow so the colony persists
   *  + shows in the sidebar; the queen boots only when they upgrade. */
  scaffold: (colonyName: string, queenName: string) =>
    api.post<{ colony_id: string; scaffolded: boolean }>(
      `/colonies/${encodeURIComponent(colonyName)}/scaffold`,
      { queen_name: queenName },
    ),

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

  /** Rename a colony on disk. Runtime moves both ``colonies/<name>`` and
   *  ``agents/<name>`` together and stops any sessions bound to the old
   *  path so the move can't corrupt in-flight work. */
  rename: (oldName: string, newName: string) =>
    api.post<{ renamed: boolean; old_name: string; new_name: string }>(
      `/colonies/${encodeURIComponent(oldName)}/rename`,
      { new_name: newName },
    ),

  /** Open the colony's folder in the OS file manager. */
  revealFolder: (colonyName: string) =>
    api.post<{ path: string }>(
      `/colonies/${encodeURIComponent(colonyName)}/reveal`,
    ),

  /** Delete a colony. Soft by default (hidden from discovery, data kept on
   *  disk); ``purge=true`` permanently removes its files. Path-based, so the
   *  request routes to the workspace VM for pushed colonies and to the local
   *  runtime otherwise — deleting whichever copy owns the colony. */
  delete: (colonyName: string, purge = false) =>
    api.delete<{ deleted: string; purged: boolean }>(
      `/colonies/${encodeURIComponent(colonyName)}${purge ? "?purge=true" : ""}`,
    ),
};
