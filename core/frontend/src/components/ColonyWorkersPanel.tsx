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
} from "lucide-react";
import {
  colonyWorkersApi,
  type ColonySkill,
  type ColonyTool,
  type ProgressSnapshot,
  type ProgressStep,
  type WorkerSummary,
} from "@/api/colonyWorkers";

interface ColonyWorkersPanelProps {
  sessionId: string;
  onClose: () => void;
}

type TabKey = "skills" | "tools" | "sessions";

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
  onClose,
}: ColonyWorkersPanelProps) {
  const [tab, setTab] = useState<TabKey>("skills");

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
        <TabButton active={tab === "skills"} onClick={() => setTab("skills")} label="Skills" />
        <TabButton active={tab === "tools"} onClick={() => setTab("tools")} label="Tools" />
        <TabButton active={tab === "sessions"} onClick={() => setTab("sessions")} label="Sessions" />
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "skills" && <SkillsTab sessionId={sessionId} />}
        {tab === "tools" && <ToolsTab sessionId={sessionId} />}
        {tab === "sessions" && <SessionsTab sessionId={sessionId} />}
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

function SessionsTab({ sessionId }: { sessionId: string }) {
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

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

  const selectedWorker = useMemo(
    () => (selected ? workers.find((w) => w.worker_id === selected) : null),
    [selected, workers],
  );

  if (selected) {
    return (
      <WorkerDetail
        sessionId={sessionId}
        worker={selectedWorker}
        workerId={selected}
        onBack={() => setSelected(null)}
      />
    );
  }

  return (
    <TabShell loading={loading} error={error} onRefresh={refresh} empty={workers.length === 0 ? "No workers spawned yet." : null}>
      <ul className="flex flex-col gap-1.5">
        {workers.map((w) => (
          <li key={w.worker_id}>
            <button
              onClick={() => setSelected(w.worker_id)}
              className="w-full text-left rounded-lg border border-border/60 bg-background/40 px-3 py-2.5 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-center justify-between mb-1 gap-2">
                <code className="text-xs font-mono text-foreground">{shortId(w.worker_id)}</code>
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
                <p className="text-xs text-foreground/80 line-clamp-2 mb-1">{w.task}</p>
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
          </li>
        ))}
      </ul>
    </TabShell>
  );
}

// ── Worker detail view (inside Sessions tab) ───────────────────────────

function WorkerDetail({
  sessionId,
  worker,
  workerId,
  onBack,
}: {
  sessionId: string;
  worker: WorkerSummary | null | undefined;
  workerId: string;
  onBack: () => void;
}) {
  const { snapshot, streamState, error } = useProgressStream(sessionId, workerId);

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
        </div>
      </div>

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

function useProgressStream(sessionId: string, workerId: string) {
  const [snapshot, setSnapshot] = useState<ProgressSnapshot>({ tasks: [], steps: [] });
  const [streamState, setStreamState] = useState<"connecting" | "open" | "closed" | "error">(
    "connecting",
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSnapshot({ tasks: [], steps: [] });
    setError(null);
    setStreamState("connecting");

    const url = colonyWorkersApi.progressStreamUrl(sessionId, workerId);
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
  }, [sessionId, workerId]);

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
  children,
}: {
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  empty: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="px-4 py-3">
      <div className="flex justify-end mb-2">
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
