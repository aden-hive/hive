import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  X,
  Users,
  RefreshCw,
  Wrench,
  Database,
  ChevronRight,
  ChevronDown,
  ArrowLeft,
  Square,
  Play,
  Clock,
  Webhook,
  Zap,
  Activity,
  Loader2,
} from "lucide-react";
import {
  colonyWorkersApi,
  type ColonySkill,
  type ColonyTool,
  type ProgressSnapshot,
  type ProgressStep,
  type WorkerSummary,
} from "@/api/colonyWorkers";
import {
  colonyDataApi,
  type CellValue,
  type TableOverview,
  type TableRowsResponse,
} from "@/api/colonyData";
import { workersApi } from "@/api/workers";
import { sessionsApi } from "@/api/sessions";
import { cronToLabel } from "@/lib/graphUtils";
import type { GraphNode } from "@/components/graph-types";
import { useColonyWorkers } from "@/context/ColonyWorkersContext";
import { DataGrid, type SortDir } from "@/components/data-grid";

interface ColonyWorkersPanelProps {
  sessionId: string;
  /** Colony directory name (e.g. ``linkedin_honeycomb_messaging``) for
   *  the colony-scoped progress + data endpoints. ``null`` when the
   *  attached session isn't bound to a colony — those tabs render
   *  empty rather than fire requests with an invalid name. */
  colonyName: string | null;
  onClose: () => void;
}

type TabKey = "skills" | "tools" | "sessions" | "triggers" | "data";

function statusClasses(status: string): string {
  const s = status.toLowerCase();
  if (s === "running" || s === "pending" || s === "claimed" || s === "in_progress")
    return "bg-primary/15 text-primary";
  if (s === "completed" || s === "done") return "bg-emerald-500/15 text-emerald-500";
  if (s === "failed") return "bg-destructive/15 text-destructive";
  if (s === "stopped") return "bg-muted text-muted-foreground";
  return "bg-muted text-muted-foreground";
}

function shortId(worker_id: string): string {
  return worker_id.length > 8 ? worker_id.slice(0, 8) : worker_id;
}

function fmtStarted(ts: number): string {
  if (!ts) return "";
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

function fmtIso(ts: string | null | undefined): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

export default function ColonyWorkersPanel({
  sessionId,
  colonyName,
  onClose,
}: ColonyWorkersPanelProps) {
  const [tab, setTab] = useState<TabKey>("sessions");
  const { focusWorkerId } = useColonyWorkers();

  // When an external caller (e.g. clicking a worker avatar in chat)
  // requests focus on a specific worker, jump to the Sessions tab so
  // the pre-select in SessionsTab is visible. The actual select +
  // focus-clear happens inside SessionsTab.
  useEffect(() => {
    if (focusWorkerId) setTab("sessions");
  }, [focusWorkerId]);

  // ── Resizable width (mirrors QueenProfilePanel) ─────────────────────
  const MIN_WIDTH = 280;
  const MAX_WIDTH = 600;
  const [width, setWidth] = useState(380);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const onDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragging.current = true;
      startX.current = e.clientX;
      startWidth.current = width;

      const onMove = (ev: MouseEvent) => {
        if (!dragging.current) return;
        const delta = startX.current - ev.clientX;
        setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth.current + delta)));
      };
      const onUp = () => {
        dragging.current = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [width],
  );

  return (
    <aside
      className="flex-shrink-0 border-l border-border/60 bg-card overflow-hidden relative flex flex-col"
      style={{ width }}
    >
      <div
        onMouseDown={onDragStart}
        className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
      />
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/60 flex-shrink-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Users className="w-4 h-4 text-primary" />
          COLONY WORKERS
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-border/60 flex-shrink-0">
        <TabButton active={tab === "sessions"} onClick={() => setTab("sessions")} label="Sessions" />
        <TabButton active={tab === "triggers"} onClick={() => setTab("triggers")} label="Triggers" />
        <TabButton active={tab === "skills"} onClick={() => setTab("skills")} label="Skills" />
        <TabButton active={tab === "tools"} onClick={() => setTab("tools")} label="Tools" />
        <TabButton active={tab === "data"} onClick={() => setTab("data")} label="Data" />
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "sessions" && (
          <SessionsTab sessionId={sessionId} colonyName={colonyName} />
        )}
        {tab === "triggers" && <TriggersTab sessionId={sessionId} />}
        {tab === "skills" && <SkillsTab sessionId={sessionId} />}
        {tab === "tools" && <ToolsTab sessionId={sessionId} />}
        {tab === "data" && <DataTab colonyName={colonyName} />}
      </div>
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 px-3 py-2 text-xs font-medium transition-colors border-b-2 ${
        active
          ? "border-primary text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/30"
      }`}
    >
      {label}
    </button>
  );
}

// ── Skills tab ─────────────────────────────────────────────────────────

function SkillsTab({ sessionId }: { sessionId: string }) {
  const [skills, setSkills] = useState<ColonySkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    colonyWorkersApi
      .listSkills(sessionId)
      .then((r) => setSkills(r.skills))
      .catch((e) => setError(e?.message ?? "Failed to load skills"))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Group by source_scope: user + project are shown expanded; framework
  // is folded by default to keep the tab scannable (framework skills are
  // the long list of built-ins that rarely change).
  const groups = useMemo(() => {
    const byScope: Record<string, ColonySkill[]> = { user: [], project: [], framework: [] };
    for (const s of skills) {
      const bucket = byScope[s.source_scope] ?? (byScope[s.source_scope] = []);
      bucket.push(s);
    }
    return [
      { key: "user", label: "User skills", items: byScope.user, defaultOpen: true },
      { key: "project", label: "Project skills", items: byScope.project, defaultOpen: true },
      { key: "framework", label: "Framework skills", items: byScope.framework, defaultOpen: false },
    ].filter((g) => g.items.length > 0);
  }, [skills]);

  return (
    <TabShell loading={loading} error={error} onRefresh={refresh} empty={skills.length === 0 ? "No skills loaded." : null}>
      <div className="flex flex-col gap-3">
        {groups.map((g) => (
          <SkillGroup key={g.key} label={g.label} items={g.items} defaultOpen={g.defaultOpen} />
        ))}
      </div>
    </TabShell>
  );
}

function SkillGroup({
  label,
  items,
  defaultOpen,
}: {
  label: string;
  items: ColonySkill[];
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1.5 mb-1.5 text-[11px] uppercase tracking-wide font-semibold text-muted-foreground hover:text-foreground"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span>{label}</span>
        <span className="text-muted-foreground/60">({items.length})</span>
      </button>
      {open && (
        <ul className="flex flex-col gap-1.5">
          {items.map((s) => (
            <li
              key={s.name}
              className="rounded-lg border border-border/60 bg-background/40 px-3 py-2.5"
            >
              <code className="text-xs font-mono text-foreground block mb-1 truncate">
                {s.name}
              </code>
              {s.description && (
                <p className="text-xs text-foreground/75 line-clamp-3">{s.description}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Tools tab ──────────────────────────────────────────────────────────

function ToolsTab({ sessionId }: { sessionId: string }) {
  const [tools, setTools] = useState<ColonyTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    colonyWorkersApi
      .listTools(sessionId)
      .then((r) => setTools(r.tools))
      .catch((e) => setError(e?.message ?? "Failed to load tools"))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const groups = useMemo(() => groupTools(tools), [tools]);

  return (
    <TabShell loading={loading} error={error} onRefresh={refresh} empty={tools.length === 0 ? "No tools configured." : null}>
      <div className="flex flex-col gap-3">
        {groups.map((g) => (
          <ToolGroup key={g.key} label={g.label} items={g.items} />
        ))}
      </div>
    </TabShell>
  );
}

/** Display-label overrides for provider keys and framework-prefix
 *  groups that don't titlecase nicely. Anything not listed here gets
 *  a snake_case → Title Case conversion. */
const _LABEL_OVERRIDES: Record<string, string> = {
  hubspot: "HubSpot",
  github: "GitHub",
  gitlab: "GitLab",
  openai: "OpenAI",
  aws_s3: "AWS S3",
  azure_sql: "Azure SQL",
  bigquery: "BigQuery",
  microsoft_graph: "Microsoft Graph",
  browser: "Browser",
  bash: "Bash",
  system: "System",
};

/** Framework/core tools don't have a credential provider, so they fall
 *  through to this map. Authoritative names for multi-file core tool
 *  groups; unmatched names fall through to a first-underscore prefix
 *  grouping. Keeping this small is deliberate — the credential system
 *  owns the rest. */
const _FRAMEWORK_GROUPS: Record<string, string> = {
  read_file: "Filesystem",
  write_file: "Filesystem",
  edit_file: "Filesystem",
  list_files: "Filesystem",
  list_dir: "Filesystem",
  list_directory: "Filesystem",
  search_files: "Filesystem",
  grep_search: "Filesystem",
  hashline_edit: "Filesystem",
  replace_file_content: "Filesystem",
  apply_diff: "File edits",
  apply_patch: "File edits",
  web_scrape: "Web & research",
  search_wikipedia: "Web & research",
  search_papers: "Web & research",
  download_paper: "Web & research",
  pdf_read: "Web & research",
  send_email: "Email",
  dns_security_scan: "Security scans",
  http_headers_scan: "Security scans",
  port_scan: "Security scans",
  ssl_tls_scan: "Security scans",
  subdomain_enumerate: "Security scans",
  tech_stack_detect: "Security scans",
  risk_score: "Security scans",
  query_runtime_log_raw: "Runtime logs",
  query_runtime_log_details: "Runtime logs",
  query_runtime_logs: "Runtime logs",
};

interface ToolGroupData {
  key: string;
  label: string;
  items: ColonyTool[];
}

function labelFor(raw: string): string {
  const override = _LABEL_OVERRIDES[raw];
  if (override) return override;
  return raw
    .split("_")
    .map((w) => (w.length > 0 ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

function groupTools(tools: ColonyTool[]): ToolGroupData[] {
  const buckets = new Map<string, ColonyTool[]>();

  const put = (label: string, t: ColonyTool) => {
    const arr = buckets.get(label) ?? [];
    arr.push(t);
    buckets.set(label, arr);
  };

  for (const t of tools) {
    // Preferred: backend-provided credential provider key. This is the
    // authoritative grouping — it comes from the same CredentialSpec
    // table that declares which tools need which credentials.
    if (t.provider) {
      put(labelFor(t.provider), t);
      continue;
    }
    const explicit = _FRAMEWORK_GROUPS[t.name];
    if (explicit) {
      put(explicit, t);
      continue;
    }
    // Last-resort: first-underscore prefix. Keeps e.g. all browser_*
    // and bash_* tools together even though they have no credential.
    const underscore = t.name.indexOf("_");
    if (underscore > 0) {
      put(labelFor(t.name.slice(0, underscore)), t);
      continue;
    }
    put("Other", t);
  }

  // Collapse any single-item group into "Other" so the panel isn't
  // full of one-entry sections.
  const result: ToolGroupData[] = [];
  const other: ColonyTool[] = buckets.get("Other") ?? [];
  for (const [label, items] of buckets) {
    if (label === "Other") continue;
    if (items.length < 2) {
      other.push(...items);
      continue;
    }
    items.sort((a, b) => a.name.localeCompare(b.name));
    result.push({ key: label, label, items });
  }
  result.sort((a, b) => a.label.localeCompare(b.label));
  if (other.length) {
    other.sort((a, b) => a.name.localeCompare(b.name));
    result.push({ key: "Other", label: "Other", items: other });
  }
  return result;
}

function ToolGroup({ label, items }: { label: string; items: ColonyTool[] }) {
  // Default folded — 100+ tools across ~15 groups is only readable when
  // the user picks the one they want to inspect.
  const [open, setOpen] = useState(false);
  return (
    <section>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1.5 mb-1.5 text-[11px] uppercase tracking-wide font-semibold text-muted-foreground hover:text-foreground"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span>{label}</span>
        <span className="text-muted-foreground/60">({items.length})</span>
      </button>
      {open && (
        <ul className="flex flex-col gap-1.5">
          {items.map((t) => (
            <li
              key={t.name}
              className="rounded-lg border border-border/60 bg-background/40 px-3 py-2.5"
            >
              <div className="flex items-center gap-1.5 min-w-0 mb-1">
                <Wrench className="w-3 h-3 text-primary flex-shrink-0" />
                <code className="text-xs font-mono text-foreground truncate">{t.name}</code>
              </div>
              {t.description && (
                <p className="text-xs text-foreground/75 line-clamp-3">{t.description}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Sessions tab ───────────────────────────────────────────────────────

function SessionsTab({
  sessionId,
  colonyName,
}: {
  sessionId: string;
  colonyName: string | null;
}) {
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [stoppingAll, setStoppingAll] = useState(false);
  const { focusWorkerId, setFocusWorkerId } = useColonyWorkers();

  // Consume focus requests from avatar clicks in chat. Wait for the
  // initial fetch before deciding so a click that arrives before the
  // workers list has loaded still resolves. If the requested id is
  // present we drill into its detail view; if it's aged out we swallow
  // the request silently. Either way we clear the focus so it isn't
  // re-applied on every re-render.
  useEffect(() => {
    if (!focusWorkerId || loading) return;
    if (workers.some((w) => w.worker_id === focusWorkerId)) {
      setSelected(focusWorkerId);
    }
    setFocusWorkerId(null);
  }, [focusWorkerId, workers, loading, setFocusWorkerId]);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    colonyWorkersApi
      .list(sessionId)
      .then((r) => setWorkers(r.workers))
      .catch((e) => setError(e?.message ?? "Failed to load workers"))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Light poll so live workers tick their duration/status without the
  // user hitting refresh. 2s matches the cadence of the standalone
  // WorkersPanel this tab replaces.
  useEffect(() => {
    const id = setInterval(() => {
      colonyWorkersApi
        .list(sessionId)
        .then((r) => setWorkers(r.workers))
        .catch(() => {
          /* swallow poll-time errors; the next tick retries. */
        });
    }, 2000);
    return () => clearInterval(id);
  }, [sessionId]);

  const selectedWorker = useMemo(
    () => (selected ? workers.find((w) => w.worker_id === selected) : null),
    [selected, workers],
  );

  const stopOne = useCallback(
    async (workerId: string) => {
      setStoppingId(workerId);
      try {
        await workersApi.stopLive(sessionId, workerId);
      } catch {
        /* next poll reflects truth */
      } finally {
        setStoppingId(null);
        refresh();
      }
    },
    [sessionId, refresh],
  );

  const stopAll = useCallback(async () => {
    setStoppingAll(true);
    try {
      await workersApi.stopAllLive(sessionId);
    } catch {
      /* ignore */
    } finally {
      setStoppingAll(false);
      refresh();
    }
  }, [sessionId, refresh]);

  // Split into active / history buckets — active workers are hoisted
  // to the top and rendered with a primary-tinted card so the user's
  // attention lands there first. History stays visible but muted so
  // prior runs stay auditable without competing for focus.
  //
  // NB: this useMemo MUST run on every render (no conditional
  // early-return before it) — React's Rules of Hooks require a
  // stable hook order. Previously we returned early on `selected`
  // BEFORE calling useMemo, which produced React error #300 in
  // the minified prod build the moment the user drilled into a
  // worker detail view.
  const { activeWorkers, historyWorkers } = useMemo(() => {
    const act: WorkerSummary[] = [];
    const hist: WorkerSummary[] = [];
    for (const w of workers) {
      (isWorkerActive(w) ? act : hist).push(w);
    }
    const byRecent = (a: WorkerSummary, b: WorkerSummary) =>
      (b.started_at || 0) - (a.started_at || 0);
    act.sort(byRecent);
    hist.sort(byRecent);
    return { activeWorkers: act, historyWorkers: hist };
  }, [workers]);

  if (selected) {
    return (
      <WorkerDetail
        colonyName={colonyName}
        worker={selectedWorker}
        workerId={selected}
        onBack={() => setSelected(null)}
      />
    );
  }

  const activeCount = activeWorkers.length;

  const renderCard = (w: WorkerSummary, active: boolean) => (
    <li key={w.worker_id}>
      <div
        className={`rounded-lg border transition-colors ${
          active
            ? "border-primary/40 bg-primary/[0.06] ring-1 ring-primary/20 hover:bg-primary/10"
            : "border-border/40 bg-background/20 opacity-80 hover:bg-muted/20 hover:opacity-100"
        }`}
      >
        <button
          onClick={() => setSelected(w.worker_id)}
          className="w-full text-left px-3 py-2.5"
        >
          <div className="flex items-center justify-between mb-1 gap-2">
            <code
              className={`text-xs font-mono ${active ? "text-foreground" : "text-foreground/70"}`}
            >
              {shortId(w.worker_id)}
            </code>
            <div className="flex items-center gap-1">
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${statusClasses(w.status)}`}
              >
                {w.status}
              </span>
              <ChevronRight className="w-3 h-3 text-muted-foreground" />
            </div>
          </div>
          {w.task && (
            <p
              className={`text-xs line-clamp-2 mb-1 ${
                active ? "text-foreground/85" : "text-foreground/60"
              }`}
            >
              {w.task}
            </p>
          )}
          <div className="flex items-center justify-between text-[10px] text-muted-foreground">
            <span>{fmtStarted(w.started_at)}</span>
            {w.result && (
              <span>
                {w.result.duration_seconds ? `${w.result.duration_seconds.toFixed(1)}s` : ""}
                {w.result.tokens_used
                  ? ` · ${w.result.tokens_used.toLocaleString()} tok`
                  : ""}
              </span>
            )}
          </div>
        </button>
        {active && (
          <div className="border-t border-primary/20 px-3 py-1.5 flex justify-end">
            <button
              onClick={(e) => {
                e.stopPropagation();
                stopOne(w.worker_id);
              }}
              disabled={stoppingId === w.worker_id}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-destructive/40 text-destructive text-[10px] hover:bg-destructive/10 disabled:opacity-50 transition-colors"
              title="Stop this worker"
            >
              <Square className="w-2.5 h-2.5" />
              {stoppingId === w.worker_id ? "Stopping…" : "Stop"}
            </button>
          </div>
        )}
      </div>
    </li>
  );

  return (
    <TabShell
      loading={loading}
      error={error}
      onRefresh={refresh}
      empty={workers.length === 0 ? "No workers spawned yet." : null}
      headerRight={
        activeCount > 0 ? (
          <button
            onClick={stopAll}
            disabled={stoppingAll}
            className="text-[10px] px-2 py-0.5 rounded border border-destructive/40 text-destructive hover:bg-destructive/10 disabled:opacity-50 transition-colors"
            title={`Stop ${activeCount} active worker${activeCount === 1 ? "" : "s"}`}
          >
            {stoppingAll ? "Stopping…" : `Stop all (${activeCount})`}
          </button>
        ) : null
      }
    >
      <div className="flex flex-col gap-3">
        {activeWorkers.length > 0 && (
          <section>
            <h4 className="text-[10px] uppercase tracking-wide font-semibold text-primary mb-1.5 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              Active ({activeWorkers.length})
            </h4>
            <ul className="flex flex-col gap-1.5">
              {activeWorkers.map((w) => renderCard(w, true))}
            </ul>
          </section>
        )}
        {historyWorkers.length > 0 && (
          <section>
            <h4 className="text-[10px] uppercase tracking-wide font-semibold text-muted-foreground mb-1.5">
              History ({historyWorkers.length})
            </h4>
            <ul className="flex flex-col gap-1.5">
              {historyWorkers.map((w) => renderCard(w, false))}
            </ul>
          </section>
        )}
      </div>
    </TabShell>
  );
}

function isWorkerActive(w: WorkerSummary): boolean {
  const s = (w.status || "").toLowerCase();
  return s === "pending" || s === "running";
}

// ── Triggers tab ───────────────────────────────────────────────────────

function TriggersTab({ sessionId }: { sessionId: string }) {
  const { triggers } = useColonyWorkers();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useMemo(
    () => (selectedId ? triggers.find((t) => t.id === selectedId) ?? null : null),
    [selectedId, triggers],
  );

  if (selected) {
    return (
      <TriggerDetail
        sessionId={sessionId}
        trigger={selected}
        onBack={() => setSelectedId(null)}
      />
    );
  }

  return (
    <TabShell
      loading={false}
      error={null}
      onRefresh={() => {
        /* triggers come from SSE in the colony page — no pull-refresh needed */
      }}
      empty={
        triggers.length === 0
          ? "No triggers configured. Ask the queen to set a schedule or webhook."
          : null
      }
    >
      <ul className="flex flex-col gap-1.5">
        {triggers.map((t) => (
          <li key={t.id}>
            <TriggerCard trigger={t} onClick={() => setSelectedId(t.id)} />
          </li>
        ))}
      </ul>
    </TabShell>
  );
}

function triggerIsActive(t: GraphNode): boolean {
  return t.status === "running" || t.status === "complete";
}

function TriggerIcon({ type }: { type?: string }) {
  const cls = "w-3.5 h-3.5";
  switch (type) {
    case "webhook":
      return <Webhook className={cls} />;
    case "timer":
      return <Clock className={cls} />;
    case "api":
      return <ChevronRight className={cls} />;
    case "event":
      return <Activity className={cls} />;
    default:
      return <Zap className={cls} />;
  }
}

function scheduleLabel(config: Record<string, unknown> | undefined): string | null {
  if (!config) return null;
  const cron = config.cron as string | undefined;
  if (cron) return cronToLabel(cron);
  const interval = config.interval_minutes as number | undefined;
  if (interval != null) {
    if (interval >= 60) return `Every ${interval / 60}h`;
    return `Every ${interval}m`;
  }
  return null;
}

function countdownLabel(nextFireIn: number | undefined): string | null {
  if (nextFireIn == null || nextFireIn <= 0) return null;
  const h = Math.floor(nextFireIn / 3600);
  const m = Math.floor((nextFireIn % 3600) / 60);
  const s = Math.floor(nextFireIn % 60);
  return h > 0
    ? `next in ${h}h ${String(m).padStart(2, "0")}m`
    : `next in ${m}m ${String(s).padStart(2, "0")}s`;
}

function TriggerCard({ trigger, onClick }: { trigger: GraphNode; onClick: () => void }) {
  const isActive = triggerIsActive(trigger);
  const schedule = scheduleLabel(trigger.triggerConfig);
  const nextFireIn = trigger.triggerConfig?.next_fire_in as number | undefined;
  const countdown = isActive ? countdownLabel(nextFireIn) : null;

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-lg border border-border/60 bg-background/40 px-3 py-2.5 hover:bg-muted/30 transition-colors"
    >
      <div className="flex items-center gap-2">
        <span
          className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${
            isActive ? "bg-primary/15 text-primary" : "bg-muted/60 text-muted-foreground"
          }`}
        >
          <TriggerIcon type={trigger.triggerType} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-foreground truncate">{trigger.label}</p>
          {schedule && schedule !== trigger.label && (
            <p className="text-[10.5px] text-muted-foreground truncate mt-0.5">{schedule}</p>
          )}
        </div>
        <span
          className={`flex-shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
            isActive ? "bg-emerald-500/15 text-emerald-400" : "bg-muted/60 text-muted-foreground"
          }`}
        >
          {isActive ? "active" : "inactive"}
        </span>
      </div>
      {countdown && (
        <p className="text-[10px] text-muted-foreground mt-1.5 italic pl-8">{countdown}</p>
      )}
    </button>
  );
}

function formatCountdown(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function TriggerDetail({
  sessionId,
  trigger,
  onBack,
}: {
  sessionId: string;
  trigger: GraphNode;
  onBack: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isActive = triggerIsActive(trigger);
  const config = (trigger.triggerConfig || {}) as Record<string, unknown>;
  const cron = config.cron as string | undefined;
  const interval = config.interval_minutes as number | undefined;
  const nextFireIn = config.next_fire_in as number | undefined;
  const triggerId = trigger.id.replace(/^__trigger_/, "");

  const handleToggle = async () => {
    if (!sessionId || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (isActive) {
        await sessionsApi.deactivateTrigger(sessionId, triggerId);
      } else {
        await sessionsApi.activateTrigger(sessionId, triggerId);
      }
      // SSE TRIGGER_ACTIVATED / TRIGGER_DEACTIVATED flips the card
      // state in the context; we don't set local state.
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const schedule = cron
    ? cronToLabel(cron)
    : interval != null
      ? interval >= 60
        ? `Every ${interval / 60}h`
        : `Every ${interval}m`
      : null;

  // Hide UI-synthesised fields so the user sees only real operator config.
  const displayEntries = Object.entries(config).filter(
    ([k]) => k !== "next_fire_in" && k !== "entry_node",
  );

  return (
    <div className="px-4 py-3">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-3"
      >
        <ArrowLeft className="w-3 h-3" />
        All triggers
      </button>

      <div className="rounded-lg border border-border/60 bg-background/40 px-3 py-2.5 mb-3">
        <div className="flex items-start gap-2.5 mb-2">
          <div
            className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${
              isActive ? "bg-primary/15 text-primary" : "bg-muted/50 text-muted-foreground"
            }`}
          >
            <TriggerIcon type={trigger.triggerType} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-foreground leading-tight truncate">
              {trigger.label}
            </p>
            <div className="flex items-center gap-2 mt-1">
              <span
                className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
                  isActive
                    ? "bg-emerald-500/15 text-emerald-400"
                    : "bg-muted/60 text-muted-foreground"
                }`}
              >
                {isActive ? "active" : "inactive"}
              </span>
              {trigger.triggerType && (
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  {trigger.triggerType}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {schedule && (
        <Section label="Schedule">
          <p className="text-xs text-foreground">{schedule}</p>
          {cron && <p className="text-[10px] text-muted-foreground mt-1 font-mono">{cron}</p>}
        </Section>
      )}

      {isActive && nextFireIn != null && nextFireIn > 0 && (
        <Section label="Next fire">
          <p className="text-xs text-foreground italic">in {formatCountdown(nextFireIn)}</p>
        </Section>
      )}

      {displayEntries.length > 0 && (
        <Section label="Config">
          <div className="space-y-1">
            {displayEntries.map(([k, v]) => (
              <div key={k} className="flex items-start justify-between gap-3 text-[11px]">
                <span className="text-muted-foreground font-mono">{k}</span>
                <span className="text-foreground font-mono text-right truncate">
                  {typeof v === "object" ? JSON.stringify(v) : String(v)}
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section label="Trigger ID">
        <p className="text-[11px] text-muted-foreground font-mono break-all">{triggerId}</p>
      </Section>

      {error && (
        <p className="text-[10.5px] text-destructive leading-snug mb-2">{error}</p>
      )}
      <button
        type="button"
        onClick={handleToggle}
        disabled={busy || !sessionId}
        className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
          isActive
            ? "bg-muted/50 text-foreground hover:bg-muted/70 border border-border/30"
            : "bg-primary/15 text-primary hover:bg-primary/25 border border-primary/30"
        }`}
      >
        {busy ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : isActive ? (
          <Square className="w-3.5 h-3.5" />
        ) : (
          <Play className="w-3.5 h-3.5" />
        )}
        {busy ? "Working…" : isActive ? "Stop trigger" : "Start trigger"}
      </button>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
        {label}
      </p>
      <div className="rounded-lg border border-border/30 bg-background/60 px-3 py-2.5">
        {children}
      </div>
    </div>
  );
}

// ── Data tab (airtable-style view of progress.db tables) ──────────────

/** Table-list refresh cadence. Slower than the row poll because the
 *  overview only drives the row-count chips; the operator doesn't care
 *  if the count lags the live data by a few seconds. */
const TABLES_POLL_MS = 5000;

function DataTab({ colonyName }: { colonyName: string | null }) {
  const [tables, setTables] = useState<TableOverview[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loadingTables, setLoadingTables] = useState(true);
  const [tablesError, setTablesError] = useState<string | null>(null);

  const refreshTables = useCallback(
    (opts: { silent?: boolean } = {}) => {
      if (!colonyName) {
        setTables([]);
        setLoadingTables(false);
        return Promise.resolve();
      }
      if (!opts.silent) {
        setLoadingTables(true);
        setTablesError(null);
      }
      return colonyDataApi
        .listTables(colonyName)
        .then((r) => {
          setTables(r.tables);
          // Auto-select the first table when none chosen yet so the user
          // lands on data instead of an empty picker.
          setSelected((cur) => cur ?? r.tables[0]?.name ?? null);
          if (opts.silent) setTablesError(null);
        })
        .catch((e) => {
          // Only surface errors on user-initiated loads; silent polls
          // stay quiet and the next tick retries.
          if (!opts.silent) setTablesError(e?.message ?? "Failed to load tables");
        })
        .finally(() => {
          if (!opts.silent) setLoadingTables(false);
        });
    },
    [colonyName],
  );

  useEffect(() => {
    refreshTables();
  }, [refreshTables]);

  // Background poll for row-count freshness. Skipped when the browser
  // tab is hidden — there's no point burning DB reads for a view the
  // user isn't watching.
  useEffect(() => {
    const id = setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      void refreshTables({ silent: true });
    }, TABLES_POLL_MS);
    return () => clearInterval(id);
  }, [refreshTables]);

  if (!colonyName) {
    return (
      <p className="text-xs text-muted-foreground text-center py-8 px-4">
        This session isn't bound to a colony yet — no progress.db to view.
      </p>
    );
  }

  return (
    <div className="px-4 py-3">
      {tablesError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive mb-3">
          {tablesError}
        </div>
      )}

      {loadingTables && tables.length === 0 ? (
        <div className="flex justify-center py-10">
          <div className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      ) : tables.length === 0 ? (
        <p className="text-xs text-muted-foreground text-center py-8">
          No tables in progress.db (or the colony has no DB yet).
        </p>
      ) : (
        <>
          {/* Table picker — chips so we avoid a heavier select dropdown
              in the narrow sidebar. Row counts hint at scale before the
              user clicks in. */}
          <div className="flex flex-wrap gap-1.5 mb-3">
            {tables.map((t) => (
              <button
                key={t.name}
                onClick={() => setSelected(t.name)}
                className={`text-[10.5px] font-mono px-2 py-1 rounded border transition-colors ${
                  selected === t.name
                    ? "border-primary/60 bg-primary/10 text-foreground"
                    : "border-border/50 bg-background/40 text-muted-foreground hover:text-foreground hover:bg-muted/30"
                }`}
                title={`${t.row_count.toLocaleString()} rows · ${t.columns.length} columns`}
              >
                {t.name}
                <span className="ml-1 text-muted-foreground/70">
                  ({t.row_count.toLocaleString()})
                </span>
              </button>
            ))}
          </div>

          <p className="text-[10px] text-muted-foreground mb-2 italic">
            Live view — edits write directly to progress.db. A running worker
            may not notice until its next DB read.
          </p>

          {selected && (
            <TableView
              key={selected}
              colonyName={colonyName}
              table={selected}
              onAnyEdit={() => {
                // Row counts can change via cascading triggers or NULL→value
                // edits; re-pull so the chip stays truthful.
                void refreshTables();
              }}
            />
          )}
        </>
      )}
    </div>
  );
}

/** Page size for the Data tab grid. 100 is a sweet spot for the narrow
 *  sidebar — big enough that most real-world tables render in one page,
 *  small enough to keep edits responsive.  */
const DATA_PAGE_SIZE = 100;

/** Row-poll cadence. 2.5s balances "feels live" against server load
 *  and our edit/poll race window. Shorter intervals amplify the
 *  chance of a poll landing during a PATCH roundtrip. */
const ROWS_POLL_MS = 2500;

/** Returns true if the user is actively editing any cell inside the
 *  grid — we sniff for a focused textarea. The alternative (bubbling
 *  editing state up from every EditableCell) would force the grid
 *  prop to track a counter. DOM inspection is simpler and — since the
 *  grid is self-contained under `root` — equally reliable. */
function isEditingInside(root: HTMLElement | null): boolean {
  if (!root) return false;
  const active = document.activeElement;
  return !!active && root.contains(active) && active.tagName === "TEXTAREA";
}

/** Shallow-merge new rows on top of the previous page *by primary
 *  key*. Reuses unchanged row-object references so React can skip
 *  re-rendering those `<tr>`s — important when the user has the grid
 *  scrolled horizontally and we don't want jank at every poll. */
function mergeRowsByPk(
  prev: TableRowsResponse,
  next: TableRowsResponse,
): TableRowsResponse {
  if (prev.primary_key.length === 0) return next;
  const prevByKey = new Map<string, Record<string, CellValue>>();
  for (const r of prev.rows) {
    prevByKey.set(prev.primary_key.map((p) => String(r[p] ?? "")).join("|"), r);
  }
  const rows = next.rows.map((r) => {
    const key = next.primary_key.map((p) => String(r[p] ?? "")).join("|");
    const old = prevByKey.get(key);
    if (!old) return r;
    // Same key AND all columns identical → reuse the previous object
    // so React's reference check skips re-rendering.
    for (const col of Object.keys(r)) {
      if (r[col] !== old[col]) return r;
    }
    return old;
  });
  return { ...next, rows };
}

function TableView({
  colonyName,
  table,
  onAnyEdit,
}: {
  colonyName: string;
  table: string;
  onAnyEdit: () => void;
}) {
  const [data, setData] = useState<TableRowsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [orderBy, setOrderBy] = useState<string | null>(null);
  const [orderDir, setOrderDir] = useState<SortDir>("asc");

  // Request-id guard. Any in-flight request with a stale id is
  // discarded on return. Bumped on (a) every new request-start and
  // (b) successful edits, so a poll that started *before* a PATCH
  // cannot land *after* it and rollback the new value.
  const reqIdRef = useRef(0);
  const gridRef = useRef<HTMLDivElement | null>(null);

  const fetchOnce = useCallback(
    (opts: { silent: boolean }) => {
      const myId = ++reqIdRef.current;
      if (!opts.silent) {
        setLoading(true);
        setError(null);
      }
      colonyDataApi
        .listRows(colonyName, table, {
          limit: DATA_PAGE_SIZE,
          offset,
          orderBy,
          orderDir,
        })
        .then((next) => {
          // Discard stale responses — sort/offset changed, edit
          // happened, or a subsequent poll started.
          if (myId !== reqIdRef.current) return;
          setData((prev) => (prev ? mergeRowsByPk(prev, next) : next));
          if (opts.silent) setError(null);
        })
        .catch((e) => {
          if (myId !== reqIdRef.current) return;
          // Silent polls swallow errors; the next tick retries. User-
          // initiated loads surface so the operator sees the failure.
          if (!opts.silent) setError(e?.message ?? "Failed to load rows");
        })
        .finally(() => {
          if (!opts.silent && myId === reqIdRef.current) setLoading(false);
        });
    },
    [colonyName, table, offset, orderBy, orderDir],
  );

  // Initial + on-parameter-change load (user-initiated, shows spinner).
  useEffect(() => {
    fetchOnce({ silent: false });
  }, [fetchOnce]);

  // Background polling. Pauses when (a) the browser tab is hidden —
  // no point spending DB reads on an unwatched panel, and (b) the
  // user is mid-edit — a silent re-fetch would reorder rows or reset
  // the draft under their cursor.
  useEffect(() => {
    const id = setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      if (isEditingInside(gridRef.current)) return;
      fetchOnce({ silent: true });
    }, ROWS_POLL_MS);
    return () => clearInterval(id);
  }, [fetchOnce]);

  // Reset paging when switching tables (key prop on TableView takes care
  // of full unmount; this covers the sort-change case).
  useEffect(() => {
    setOffset(0);
  }, [orderBy, orderDir]);

  const handleSort = useCallback((col: string | null, dir: SortDir) => {
    setOrderBy(col);
    setOrderDir(dir);
  }, []);

  const handleEdit = useCallback(
    async (pk: Record<string, CellValue>, column: string, newValue: CellValue) => {
      await colonyDataApi.updateRow(colonyName, table, {
        pk,
        updates: { [column]: newValue },
      });
      // Bump the request-id so any poll that started before the PATCH
      // (and is about to return with pre-edit data) is discarded —
      // otherwise the grid would briefly revert the cell.
      reqIdRef.current++;
      // Optimistic patch of the local cache so the grid reflects the
      // edit instantly without a full re-fetch flash.
      setData((prev) => {
        if (!prev) return prev;
        const rows = prev.rows.map((r) => {
          const matches = prev.primary_key.every((p) => r[p] === pk[p]);
          return matches ? { ...r, [column]: newValue } : r;
        });
        return { ...prev, rows };
      });
      onAnyEdit();
    },
    [colonyName, table, onAnyEdit],
  );

  if (error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
        {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex justify-center py-10">
        <div className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  const pageEnd = Math.min(data.offset + data.rows.length, data.total);
  const canPrev = data.offset > 0;
  const canNext = pageEnd < data.total;

  return (
    <div className="flex flex-col gap-2" ref={gridRef}>
      <DataGrid
        columns={data.columns}
        rows={data.rows}
        primaryKey={data.primary_key}
        orderBy={orderBy}
        orderDir={orderDir}
        onSortChange={handleSort}
        onCellEdit={handleEdit}
        loading={loading}
        emptyMessage="Table is empty."
      />
      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span
            className="w-1.5 h-1.5 rounded-full bg-emerald-500/80 animate-pulse"
            title={`Auto-refreshing every ${ROWS_POLL_MS / 1000}s (paused while editing)`}
          />
          <span>
            {data.total === 0
              ? "0 rows"
              : `${data.offset + 1}–${pageEnd} of ${data.total.toLocaleString()}`}
          </span>
        </span>
        <div className="flex gap-1">
          <button
            onClick={() => setOffset(Math.max(0, offset - DATA_PAGE_SIZE))}
            disabled={!canPrev || loading}
            className="px-2 py-0.5 rounded border border-border/50 disabled:opacity-40 hover:bg-muted/30"
          >
            Prev
          </button>
          <button
            onClick={() => setOffset(offset + DATA_PAGE_SIZE)}
            disabled={!canNext || loading}
            className="px-2 py-0.5 rounded border border-border/50 disabled:opacity-40 hover:bg-muted/30"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Worker detail view (inside Sessions tab) ───────────────────────────

function WorkerDetail({
  colonyName,
  worker,
  workerId,
  onBack,
}: {
  colonyName: string | null;
  worker: WorkerSummary | null | undefined;
  workerId: string;
  onBack: () => void;
}) {
  // Historical workers (loaded from disk rather than live memory) have
  // no live progress.db stream to attach to — opening the SSE just
  // renders "No progress rows yet." forever, which is what the user
  // was calling "middle of nowhere". Skip the stream and show the
  // result summary + an archived-conversation hint instead.
  const isHistorical =
    worker?.status === "historical" ||
    (worker != null && !isWorkerActive(worker) && worker.result == null);

  return (
    <div className="px-4 py-3">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-3"
      >
        <ArrowLeft className="w-3 h-3" />
        All sessions
      </button>

      <div className="rounded-lg border border-border/60 bg-background/40 px-3 py-2.5 mb-3">
        <div className="flex items-center justify-between mb-1 gap-2">
          <code className="text-xs font-mono text-foreground">{shortId(workerId)}</code>
          {worker && (
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${statusClasses(worker.status)}`}
            >
              {worker.status}
            </span>
          )}
        </div>
        {worker?.task && <p className="text-xs text-foreground/80 mb-1">{worker.task}</p>}
        <div className="text-[10px] text-muted-foreground">
          {worker ? fmtStarted(worker.started_at) : ""}
          {worker?.result?.duration_seconds
            ? ` · ${worker.result.duration_seconds.toFixed(1)}s`
            : ""}
          {worker?.result?.tokens_used
            ? ` · ${worker.result.tokens_used.toLocaleString()} tok`
            : ""}
        </div>
        {worker?.result?.summary && (
          <p className="mt-2 text-xs text-foreground/90 border-t border-border/40 pt-2">
            {worker.result.summary}
          </p>
        )}
        {worker?.result?.error && (
          <p className="mt-2 text-xs text-destructive border-t border-destructive/30 pt-2">
            {worker.result.error}
          </p>
        )}
      </div>

      {isHistorical ? (
        <HistoricalWorkerPlaceholder workerId={workerId} />
      ) : (
        <LiveWorkerProgress colonyName={colonyName} workerId={workerId} />
      )}
    </div>
  );
}

function LiveWorkerProgress({
  colonyName,
  workerId,
}: {
  colonyName: string | null;
  workerId: string;
}) {
  const { snapshot, streamState, error } = useProgressStream(colonyName, workerId);
  return (
    <>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground/90">
          <Database className="w-3.5 h-3.5 text-primary" />
          Progress (progress.db)
        </div>
        <StreamBadge state={streamState} />
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive mb-2">
          {error}
        </div>
      )}

      <ProgressView snapshot={snapshot} />
    </>
  );
}

function HistoricalWorkerPlaceholder({ workerId }: { workerId: string }) {
  return (
    <div className="rounded-lg border border-border/40 bg-background/30 px-3 py-4 text-xs text-muted-foreground space-y-1.5">
      <p className="text-foreground/80">This worker has finished.</p>
      <p>
        Live progress is no longer streaming. The worker's full conversation is
        archived under{" "}
        <code className="text-[11px] font-mono text-foreground/80">
          workers/{shortId(workerId)}/conversations/
        </code>{" "}
        in the session data folder — use the{" "}
        <span className="text-foreground/80 font-medium">Data</span> button in
        the header to open it.
      </p>
    </div>
  );
}

function StreamBadge({ state }: { state: "connecting" | "open" | "closed" | "error" }) {
  const cls =
    state === "open"
      ? "bg-emerald-500/15 text-emerald-500"
      : state === "connecting"
        ? "bg-primary/15 text-primary"
        : state === "error"
          ? "bg-destructive/15 text-destructive"
          : "bg-muted text-muted-foreground";
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${cls}`}>{state}</span>
  );
}

function ProgressView({ snapshot }: { snapshot: ProgressSnapshot }) {
  const stepsByTask = useMemo(() => {
    const m = new Map<string, ProgressStep[]>();
    for (const step of snapshot.steps) {
      const arr = m.get(step.task_id) ?? [];
      arr.push(step);
      m.set(step.task_id, arr);
    }
    for (const arr of m.values()) arr.sort((a, b) => a.seq - b.seq);
    return m;
  }, [snapshot.steps]);

  if (snapshot.tasks.length === 0 && snapshot.steps.length === 0) {
    return (
      <p className="text-xs text-muted-foreground text-center py-6">
        No progress rows yet.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2">
      {snapshot.tasks.map((t) => (
        <li
          key={t.id}
          className="rounded-lg border border-border/60 bg-background/40 px-3 py-2"
        >
          <div className="flex items-start justify-between gap-2 mb-1">
            <span className="text-xs text-foreground/90 break-words flex-1">{t.goal}</span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium flex-shrink-0 ${statusClasses(t.status)}`}
            >
              {t.status}
            </span>
          </div>
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
            <code className="font-mono">{t.id.slice(0, 8)}</code>
            {t.updated_at && <span>· upd {fmtIso(t.updated_at)}</span>}
            {t.retry_count > 0 && (
              <span>
                · retry {t.retry_count}/{t.max_retries}
              </span>
            )}
          </div>

          {(() => {
            const steps = stepsByTask.get(t.id) ?? [];
            if (steps.length === 0) return null;
            return (
              <ul className="mt-2 pl-2 border-l border-border/40 flex flex-col gap-1">
                {steps.map((s) => (
                  <li key={s.id} className="flex items-start gap-1.5 text-[11px]">
                    <span
                      className={`mt-0.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                        s.status === "completed" || s.status === "done"
                          ? "bg-emerald-500"
                          : s.status === "failed"
                            ? "bg-destructive"
                            : s.status === "in_progress" || s.status === "running"
                              ? "bg-primary animate-pulse"
                              : "bg-muted-foreground/40"
                      }`}
                    />
                    <span className="text-foreground/80 flex-1 break-words">{s.title}</span>
                    {s.completed_at && (
                      <span className="text-[10px] text-muted-foreground flex-shrink-0">
                        {fmtIso(s.completed_at)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            );
          })()}
        </li>
      ))}
    </ul>
  );
}

// ── Hook: live progress via SSE ────────────────────────────────────────

function useProgressStream(colonyName: string | null, workerId: string) {
  const [snapshot, setSnapshot] = useState<ProgressSnapshot>({ tasks: [], steps: [] });
  const [streamState, setStreamState] = useState<"connecting" | "open" | "closed" | "error">(
    "connecting",
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSnapshot({ tasks: [], steps: [] });
    setError(null);
    setStreamState("connecting");

    // Skip the SSE connection entirely if the session isn't bound to a
    // colony — we'd just hit a 400 on every reconnect attempt.
    if (!colonyName) {
      setStreamState("closed");
      return;
    }

    const url = colonyWorkersApi.progressStreamUrl(colonyName, workerId);
    const es = new EventSource(url);

    es.addEventListener("open", () => setStreamState("open"));

    es.addEventListener("snapshot", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as ProgressSnapshot;
        setSnapshot(data);
        setStreamState("open");
      } catch (err) {
        setError(`snapshot parse failed: ${String(err)}`);
      }
    });

    es.addEventListener("upsert", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as ProgressSnapshot;
        setSnapshot((prev) => mergeSnapshot(prev, data));
      } catch (err) {
        setError(`upsert parse failed: ${String(err)}`);
      }
    });

    es.addEventListener("error", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as { message?: string };
        if (data.message) setError(data.message);
      } catch {
        /* EventSource raw error — state below handles it. */
      }
    });

    es.onerror = () => {
      // EventSource auto-retries; surface the transient state so the
      // badge reflects reality.
      setStreamState((s) => (s === "open" ? "error" : s));
    };

    return () => {
      es.close();
      setStreamState("closed");
    };
  }, [colonyName, workerId]);

  return { snapshot, streamState, error };
}

function mergeSnapshot(prev: ProgressSnapshot, upsert: ProgressSnapshot): ProgressSnapshot {
  const taskMap = new Map(prev.tasks.map((t) => [t.id, t]));
  for (const t of upsert.tasks) taskMap.set(t.id, t);
  const tasks = Array.from(taskMap.values()).sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );

  const stepMap = new Map(prev.steps.map((s) => [s.id, s]));
  for (const s of upsert.steps) stepMap.set(s.id, s);
  const steps = Array.from(stepMap.values()).sort((a, b) => {
    if (a.task_id !== b.task_id) return a.task_id.localeCompare(b.task_id);
    return a.seq - b.seq;
  });

  return { tasks, steps };
}

// ── Shared tab shell: loading / error / empty / refresh button ─────────

function TabShell({
  loading,
  error,
  onRefresh,
  empty,
  headerRight,
  children,
}: {
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  empty: string | null;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div>{headerRight}</div>
        <button
          onClick={onRefresh}
          className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive mb-3">
          {error}
        </div>
      )}

      {loading && !error ? (
        <div className="flex justify-center py-10">
          <div className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      ) : empty ? (
        <p className="text-xs text-muted-foreground text-center py-8">{empty}</p>
      ) : (
        children
      )}
    </div>
  );
}
