import { api } from "./client";

export type McpTransport = "stdio" | "http" | "sse" | "unix";

/** How agents reach a server. "tools": its tools load into their tool list.
 * "cli": they run it from the terminal with `hive mcp run`, so its tool
 * schemas cost no context until a command is used. */
export type McpMode = "tools" | "cli";

export interface McpServer {
  name: string;
  /** "local": added via UI/CLI (user-editable). "registry": installed from
   * the remote MCP registry. "built-in": baked into the queen package —
   * visible but not removable from the UI. */
  source: "local" | "registry" | "built-in";
  transport: McpTransport | string;
  /** Absent on built-in harness groups. */
  mode?: McpMode;
  description: string;
  enabled: boolean;
  last_health_status: "healthy" | "unhealthy" | null;
  last_error: string | null;
  last_health_check_at: string | null;
  tool_count: number | null;
  /** Servers flagged removable:false cannot be deleted from the UI. */
  removable?: boolean;
}

export interface AddMcpServerBody {
  name: string;
  transport: McpTransport;
  /** stdio */
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
  /** http / sse */
  url?: string;
  headers?: Record<string, string>;
  /** unix */
  socket_path?: string;
  description?: string;
  mode?: McpMode;
}

export interface McpHealthResult {
  name: string;
  status: "healthy" | "unhealthy" | "unknown";
  tools: number;
  error: string | null;
}

/** Backend MCPError shape when an operation fails. */
export interface McpErrorBody {
  error: string;
  code?: string;
  what?: string;
  why?: string;
  fix?: string;
}

export const mcpApi = {
  listServers: () => api.get<{ servers: McpServer[] }>("/mcp/servers"),
  addServer: (body: AddMcpServerBody) =>
    api.post<{ server: McpServer; hint: string }>("/mcp/servers", body),
  removeServer: (name: string) =>
    api.delete<{ removed: string }>(`/mcp/servers/${encodeURIComponent(name)}`),
  setEnabled: (name: string, enabled: boolean) =>
    api.post<{ name: string; enabled: boolean }>(
      `/mcp/servers/${encodeURIComponent(name)}/${enabled ? "enable" : "disable"}`,
    ),
  setMode: (name: string, mode: McpMode) =>
    api.post<{ name: string; mode: McpMode; hint: string }>(
      `/mcp/servers/${encodeURIComponent(name)}/mode`,
      { mode },
    ),
  checkHealth: (name: string) =>
    api.post<McpHealthResult>(`/mcp/servers/${encodeURIComponent(name)}/health`),
};
