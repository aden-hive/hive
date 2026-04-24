import { useEffect, useState } from "react";
import {
  Plus,
  Trash2,
  RefreshCw,
  Loader2,
  AlertCircle,
  Check,
  X,
  Server,
  CircleCheck,
  CircleAlert,
  CircleDashed,
} from "lucide-react";
import {
  mcpApi,
  type McpServer,
  type McpTransport,
  type AddMcpServerBody,
} from "@/api/mcp";

type TransportKey = McpTransport;

const TRANSPORT_OPTIONS: TransportKey[] = ["stdio", "http", "sse", "unix"];

function healthBadge(server: McpServer) {
  if (!server.enabled) {
    return (
      <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
        <CircleDashed className="w-3 h-3" /> Disabled
      </span>
    );
  }
  if (server.last_health_status === "healthy") {
    return (
      <span className="flex items-center gap-1 text-[11px] text-green-500">
        <CircleCheck className="w-3 h-3" /> Healthy
      </span>
    );
  }
  if (server.last_health_status === "unhealthy") {
    return (
      <span
        className="flex items-center gap-1 text-[11px] text-red-400"
        title={server.last_error || "Unhealthy"}
      >
        <CircleAlert className="w-3 h-3" /> Unhealthy
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
      <CircleDashed className="w-3 h-3" /> Unknown
    </span>
  );
}

interface AddFormState {
  name: string;
  transport: TransportKey;
  command: string;
  args: string;
  env: string;
  cwd: string;
  url: string;
  headers: string;
  socketPath: string;
  description: string;
}

const EMPTY_FORM: AddFormState = {
  name: "",
  transport: "stdio",
  command: "",
  args: "",
  env: "",
  cwd: "",
  url: "",
  headers: "",
  socketPath: "",
  description: "",
};

function parseKeyValueLines(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .forEach((line) => {
      const eq = line.indexOf("=");
      if (eq < 0) return;
      const k = line.slice(0, eq).trim();
      const v = line.slice(eq + 1).trim();
      if (k) out[k] = v;
    });
  return out;
}

function buildAddBody(form: AddFormState): AddMcpServerBody {
  const body: AddMcpServerBody = {
    name: form.name.trim(),
    transport: form.transport,
    description: form.description.trim() || undefined,
  };
  if (form.transport === "stdio") {
    body.command = form.command.trim();
    const args = form.args
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (args.length) body.args = args;
    const env = parseKeyValueLines(form.env);
    if (Object.keys(env).length) body.env = env;
    if (form.cwd.trim()) body.cwd = form.cwd.trim();
  } else if (form.transport === "http" || form.transport === "sse") {
    body.url = form.url.trim();
    const headers = parseKeyValueLines(form.headers);
    if (Object.keys(headers).length) body.headers = headers;
  } else if (form.transport === "unix") {
    body.socket_path = form.socketPath.trim();
  }
  return body;
}

export default function McpServersPanel() {
  const [servers, setServers] = useState<McpServer[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState<AddFormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [busyByName, setBusyByName] = useState<Record<string, boolean>>({});

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const { servers } = await mcpApi.listServers();
      setServers(servers);
    } catch (e: unknown) {
      setError((e as Error)?.message || "Failed to load MCP servers");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const setBusy = (name: string, v: boolean) =>
    setBusyByName((p) => ({ ...p, [name]: v }));

  const handleToggle = async (server: McpServer) => {
    setBusy(server.name, true);
    try {
      await mcpApi.setEnabled(server.name, !server.enabled);
      await refresh();
    } catch (e: unknown) {
      setError((e as Error)?.message || "Toggle failed");
    } finally {
      setBusy(server.name, false);
    }
  };

  const handleRemove = async (server: McpServer) => {
    if (!confirm(`Remove MCP server "${server.name}"?`)) return;
    setBusy(server.name, true);
    try {
      await mcpApi.removeServer(server.name);
      await refresh();
    } catch (e: unknown) {
      const body = (e as { body?: { error?: string } }).body;
      setError(body?.error || (e as Error)?.message || "Remove failed");
    } finally {
      setBusy(server.name, false);
    }
  };

  const handleHealth = async (server: McpServer) => {
    setBusy(server.name, true);
    try {
      await mcpApi.checkHealth(server.name);
      await refresh();
    } catch (e: unknown) {
      setError((e as Error)?.message || "Health check failed");
    } finally {
      setBusy(server.name, false);
    }
  };

  const canSubmit = (() => {
    if (!form.name.trim()) return false;
    if (form.transport === "stdio") return !!form.command.trim();
    if (form.transport === "http" || form.transport === "sse")
      return !!form.url.trim();
    if (form.transport === "unix") return !!form.socketPath.trim();
    return false;
  })();

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const body = buildAddBody(form);
      const { server } = await mcpApi.addServer(body);
      // Best-effort: auto-run health check so the UI shows tool count.
      try {
        await mcpApi.checkHealth(server.name);
      } catch {
        /* health check is informational; don't block the add flow */
      }
      setAdding(false);
      setForm(EMPTY_FORM);
      await refresh();
    } catch (e: unknown) {
      const body = (e as { body?: { error?: string; fix?: string } }).body;
      setSubmitError(
        [body?.error, body?.fix].filter(Boolean).join(" — ") ||
          (e as Error)?.message ||
          "Add failed",
      );
    } finally {
      setSubmitting(false);
    }
  };

  // Group by origin. "local" = user-registered via the UI or CLI. Everything
  // else (built-in package entries, registry-installed entries) sits under
  // "Built-in" since the user can't remove them from the UI.
  const builtIns = (servers || []).filter((s) => s.source !== "local");
  const custom = (servers || []).filter((s) => s.source === "local");

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-foreground">MCP Servers</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Register your own MCP servers so queens can use their tools. New
            servers take effect in the next queen session you start.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border/60 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/30 disabled:opacity-50"
            title="Refresh"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
          </button>
          <button
            onClick={() => {
              setAdding(true);
              setForm(EMPTY_FORM);
              setSubmitError(null);
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90"
          >
            <Plus className="w-3 h-3" />
            Add MCP Server
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 text-xs text-destructive p-2.5 rounded-md bg-destructive/10 border border-destructive/30">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button
            onClick={() => setError(null)}
            className="text-destructive/70 hover:text-destructive"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {loading && !servers && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="w-3 h-3 animate-spin" /> Loading MCP servers…
        </div>
      )}

      {servers && (
        <>
          {custom.length > 0 && (
            <Section title="My Custom">
              {custom.map((s) => (
                <ServerRow
                  key={s.name}
                  server={s}
                  busy={!!busyByName[s.name]}
                  onToggle={() => handleToggle(s)}
                  onRemove={() => handleRemove(s)}
                  onHealth={() => handleHealth(s)}
                  isLocal
                />
              ))}
            </Section>
          )}
          <Section title="Built-in">
            {builtIns.length === 0 ? (
              <p className="text-xs text-muted-foreground px-2 py-2">
                No built-in servers registered.
              </p>
            ) : (
              builtIns.map((s) => (
                <ServerRow
                  key={s.name}
                  server={s}
                  busy={!!busyByName[s.name]}
                  onToggle={() => handleToggle(s)}
                  onRemove={() => handleRemove(s)}
                  onHealth={() => handleHealth(s)}
                />
              ))
            )}
          </Section>
        </>
      )}

      {/* Add MCP modal */}
      {adding && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => !submitting && setAdding(false)}
          />
          <div className="relative bg-card border border-border/60 rounded-xl shadow-2xl w-full max-w-lg p-5 space-y-4 max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-foreground">
                Add MCP Server
              </h3>
              <button
                onClick={() => !submitting && setAdding(false)}
                className="p-1 rounded text-muted-foreground hover:text-foreground"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <FieldRow label="Name *" hint="Unique identifier, e.g. my-search-tool">
              <input
                autoFocus
                value={form.name}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    name: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""),
                  }))
                }
                placeholder="my-search-tool"
                className={inputCls}
              />
            </FieldRow>

            <FieldRow label="Transport *">
              <div className="flex gap-1">
                {TRANSPORT_OPTIONS.map((t) => (
                  <button
                    key={t}
                    onClick={() => setForm((f) => ({ ...f, transport: t }))}
                    className={`flex-1 px-3 py-1.5 rounded-md text-xs font-medium border ${
                      form.transport === t
                        ? "bg-primary/15 text-primary border-primary/40"
                        : "text-muted-foreground hover:text-foreground border-border/60 hover:bg-muted/30"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </FieldRow>

            {form.transport === "stdio" && (
              <>
                <FieldRow
                  label="Command *"
                  hint="Executable that speaks MCP over stdin/stdout"
                >
                  <input
                    value={form.command}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, command: e.target.value }))
                    }
                    placeholder="uv"
                    className={inputCls}
                  />
                </FieldRow>
                <FieldRow label="Args (one per line)">
                  <textarea
                    value={form.args}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, args: e.target.value }))
                    }
                    rows={3}
                    placeholder={"run\npython\nmy_server.py\n--stdio"}
                    className={textareaCls}
                  />
                </FieldRow>
                <FieldRow label="Env (KEY=VALUE, one per line)">
                  <textarea
                    value={form.env}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, env: e.target.value }))
                    }
                    rows={2}
                    placeholder="API_KEY=abc123"
                    className={textareaCls}
                  />
                </FieldRow>
                <FieldRow label="Working directory">
                  <input
                    value={form.cwd}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, cwd: e.target.value }))
                    }
                    placeholder="/path/to/repo"
                    className={inputCls}
                  />
                </FieldRow>
              </>
            )}

            {(form.transport === "http" || form.transport === "sse") && (
              <>
                <FieldRow label="URL *">
                  <input
                    value={form.url}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, url: e.target.value }))
                    }
                    placeholder="https://example.com/mcp"
                    className={inputCls}
                  />
                </FieldRow>
                <FieldRow label="Headers (KEY=VALUE, one per line)">
                  <textarea
                    value={form.headers}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, headers: e.target.value }))
                    }
                    rows={2}
                    placeholder="Authorization=Bearer ..."
                    className={textareaCls}
                  />
                </FieldRow>
              </>
            )}

            {form.transport === "unix" && (
              <FieldRow label="Socket path *">
                <input
                  value={form.socketPath}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, socketPath: e.target.value }))
                  }
                  placeholder="/tmp/mcp.sock"
                  className={inputCls}
                />
              </FieldRow>
            )}

            <FieldRow label="Description">
              <input
                value={form.description}
                onChange={(e) =>
                  setForm((f) => ({ ...f, description: e.target.value }))
                }
                placeholder="What this server does"
                className={inputCls}
              />
            </FieldRow>

            {submitError && (
              <div className="flex items-start gap-2 text-xs text-destructive p-2 rounded-md bg-destructive/10 border border-destructive/30">
                <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                <span>{submitError}</span>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => setAdding(false)}
                disabled={submitting}
                className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={!canSubmit || submitting}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Check className="w-3 h-3" />
                )}
                {submitting ? "Adding…" : "Add"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const inputCls =
  "w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40";
const textareaCls = `${inputCls} resize-none font-mono text-xs`;

function FieldRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">
        {label}
      </label>
      {children}
      {hint && (
        <p className="text-[11px] text-muted-foreground/70 mt-1">{hint}</p>
      )}
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider mb-2">
        {title}
      </p>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  );
}

function ServerRow({
  server,
  busy,
  onToggle,
  onRemove,
  onHealth,
  isLocal,
}: {
  server: McpServer;
  busy: boolean;
  onToggle: () => void;
  onRemove: () => void;
  onHealth: () => void;
  isLocal?: boolean;
}) {
  // Package-baked servers live in the repo and aren't managed by
  // MCPRegistry, so toggling / removing / health-checking them would
  // fail against the backend. Show them as read-only.
  const isBuiltIn = server.source === "built-in";
  return (
    <div className="flex items-center gap-3 py-2.5 px-2 rounded-lg hover:bg-muted/20">
      <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
        <Server className="w-4 h-4 text-primary" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-foreground truncate">
            {server.name}
          </p>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
            {server.transport}
          </span>
          {isBuiltIn && (
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/80 bg-muted/40 px-1.5 py-0.5 rounded">
              Built-in
            </span>
          )}
          {server.tool_count !== null && server.tool_count !== undefined && (
            <span className="text-[11px] text-muted-foreground">
              {server.tool_count} tools
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {!isBuiltIn && healthBadge(server)}
          {server.description && (
            <span className="text-xs text-muted-foreground truncate">
              {isBuiltIn ? server.description : `· ${server.description}`}
            </span>
          )}
        </div>
      </div>
      {!isBuiltIn && (
        <>
          <button
            onClick={onHealth}
            disabled={busy}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/40 disabled:opacity-50"
            title="Health check"
          >
            {busy ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
          </button>
          <button
            onClick={onToggle}
            disabled={busy}
            className={`px-3 py-1 rounded-md text-[11px] font-semibold border disabled:opacity-50 ${
              server.enabled
                ? "text-muted-foreground border-border/60 hover:bg-muted/30"
                : "bg-primary/15 text-primary border-primary/40 hover:bg-primary/25"
            }`}
          >
            {server.enabled ? "Disable" : "Enable"}
          </button>
        </>
      )}
      {isLocal && !isBuiltIn && (
        <button
          onClick={onRemove}
          disabled={busy}
          className="p-1.5 rounded-md text-muted-foreground hover:text-red-400 hover:bg-red-500/10 disabled:opacity-50"
          title="Remove"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
