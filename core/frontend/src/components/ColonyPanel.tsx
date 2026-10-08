import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  X,
  Users,
  RefreshCw,
  Wrench,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  ArrowLeft,
  Square,
  Play,
  Clock,
  Webhook,
  Zap,
  Activity,
  Loader2,
  FolderOpen,
  Settings,
  Database,
  Cloud,
  Lock,
  Check,
  Plus,
  Maximize2,
  Minimize2,
  Download,
  ListChecks,
} from "lucide-react";
import {
  colonyWorkersApi,
  type ColonySkill,
  type ColonyTool,
  type WorkerDetailData,
  type WorkerMessage,
  type WorkerSummary,
} from "@/api/colonyWorkers";
import {
  colonyDataApi,
  type CellValue,
  type ChangedRow,
  type TableOverview,
  type TableRowsResponse,
} from "@/api/colonyData";
import { workersApi } from "@/api/workers";
import { sessionsApi } from "@/api/sessions";
import { coloniesApi } from "@/api/colonies";
import { SentinelSection } from "./SentinelSection";
import type { AgentEvent } from "@/api/types";
import { useSSE } from "@/hooks/use-sse";
import { cronToLabel } from "@/lib/graphUtils";
import type { GraphNode } from "@/components/graph-types";
import {
  useColonyWorkers,
  SESSION_GONE_404_LIMIT,
  type ColonyTabKey,
} from "@/context/ColonyWorkersContext";
import { ApiError } from "@/api/client";
import { saveCsv } from "@/lib/desktop-shims";
import { DataGrid, type SortDir } from "@/components/data-grid";
import { inferColumnOptions } from "@/components/data-grid/gridUtils";
import TaskListPanel, { ActionPlanControls } from "@/components/TaskListPanel";
import { TaskListProvider } from "@/context/TaskListContext";
import CreateSchedulerModal from "@/components/CreateSchedulerModal";
import { ToolActivityRow } from "@/components/ChatPanel";
import BrowserStatusBadge from "@/components/BrowserStatusBadge";
import { Tooltip } from "@/components/Tooltip";
import { workerIdFromStreamId } from "@/lib/chat-helpers";
import { userStorage } from "@/lib/userStorage";

interface ColonyPanelProps {
  sessionId: string;
  /** Colony directory name (e.g. ``linkedin_honeycomb_messaging``) for
   *  the colony-scoped progress + data endpoints. ``null`` when the
   *  attached session isn't bound to a colony — those tabs render
   *  empty rather than fire requests with an invalid name. */
  colonyName: string | null;
}

type TabKey = ColonyTabKey;

// Remembered drawer width (per user, survives logout/login). Absent until the
// user drags the resize handle; while absent the panel auto-sizes to a ratio.
const COLONY_PANEL_WIDTH_KEY = "colony-panel-width";
function loadStoredPanelWidth(): number | null {
  const raw = userStorage.get<number | null>(COLONY_PANEL_WIDTH_KEY, null);
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

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

// Convert a 1-based batch ordinal into a spreadsheet-column letter
// (1→A, 2→B, …, 26→Z, 27→AA, …). The display shows "Worker A-01"
// instead of "Batch 1 · #1" so each card reads as a single worker
// identity rather than a path through two hierarchies.
function batchLetter(n: number): string {
  let s = "";
  let x = n;
  while (x > 0) {
    const r = (x - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    x = Math.floor((x - 1) / 26);
  }
  return s || "A";
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

export default function ColonyPanel({
  sessionId,
  colonyName,
}: ColonyPanelProps) {
  const { focusWorkerId, getTabForColony, setTabForColony, requestQueenPrompt } =
    useColonyWorkers();
  // "Pushed to a cloud computer" was a cloud feature (removed). Every colony
  // is local now, so the local-folder actions are always available.
  const onCloud = false;

  // Tab lives in ColonyWorkersContext keyed by colonyName so it survives
  // the brief unmount/remount that Deploy-to-cloud triggers (when the
  // session is dropped + rebound to a fresh remote one). Defaults to
  // "data" for a colony we haven't seen yet.
  const tab: TabKey = getTabForColony(colonyName) ?? "data";
  const setTab = useCallback(
    (next: TabKey) => setTabForColony(colonyName, next),
    [colonyName, setTabForColony],
  );

  // When an external caller (e.g. clicking a worker avatar in chat)
  // requests focus on a specific worker, jump to the Workers tab so
  // the pre-select in WorkersTab is visible. The actual select +
  // focus-clear happens inside WorkersTab.
  useEffect(() => {
    if (focusWorkerId) setTab("workers");
  }, [focusWorkerId, setTab]);

  // ── Resizable width (mirrors QueenProfilePanel) ─────────────────────
  const MIN_WIDTH = 280;
  const MAX_WIDTH = 720;
  // Seed from a remembered width if the user has dragged before; otherwise a
  // ResizeObserver targets ≈42.5% of the content area (clamped to [MIN, MAX]).
  // Once dragged, the chosen width is persisted and wins over the auto-ratio.
  const [width, setWidth] = useState(() => loadStoredPanelWidth() ?? 640);
  const asideRef = useRef<HTMLElement | null>(null);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);
  const latestWidth = useRef(width);
  const hasManualWidth = useRef(loadStoredPanelWidth() != null);

  useEffect(() => {
    const el = asideRef.current?.parentElement;
    if (!el) return;
    const apply = () => {
      // A remembered manual width takes precedence — don't snap back to ratio.
      if (hasManualWidth.current) return;
      // Target ≈42.5% of the content area (the prior 50/50 split, 15%
      // narrower), clamped to [MIN, MAX]. The drag handle still lets
      // the user push it back out toward MAX_WIDTH.
      setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, el.clientWidth * 0.425)));
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
    // Re-attach when MIN/MAX would change. They're constants today, so
    // this effect runs once on mount.
  }, []);

  const onDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragging.current = true;
      startX.current = e.clientX;
      startWidth.current = width;

      const onMove = (ev: MouseEvent) => {
        if (!dragging.current) return;
        const delta = startX.current - ev.clientX;
        const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth.current + delta));
        latestWidth.current = next;
        setWidth(next);
      };
      const onUp = () => {
        dragging.current = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        // Remember this width so it persists across sessions.
        hasManualWidth.current = true;
        userStorage.set<number>(COLONY_PANEL_WIDTH_KEY, latestWidth.current);
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
      ref={asideRef}
      className="flex-shrink-0 border-l border-border/60 bg-card overflow-hidden relative flex flex-col"
      style={{ width }}
    >
      <div
        onMouseDown={onDragStart}
        className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
      />
      {/* Tab bar — horizontal scroll when the drawer is narrow so all four
          tabs stay reachable instead of getting clipped on the right. */}
      <div className="flex border-b border-border/60 flex-shrink-0 overflow-x-auto scrollbar-thin">
        <TabButton
          active={tab === "data"}
          onClick={() => setTab("data")}
          label="Data"
          tip="The data agent collects for you"
        />
        <TabButton
          active={tab === "overview"}
          onClick={() => setTab("overview")}
          label="Plan"
          tip="The queen's task list for this colony"
        />
        <TabButton
          active={tab === "automations"}
          onClick={() => setTab("automations")}
          label="Automations"
          tip="Advanced configuration to keep it running without you"
        />
        <TabButton
          active={tab === "workers"}
          onClick={() => setTab("workers")}
          label="Workers"
          tip="Advanced details of what each worker is doing right now"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "overview" && <OverviewTab sessionId={sessionId} />}
        {tab === "data" && <DataTab key={colonyName ?? "none"} colonyName={colonyName} />}
        {tab === "automations" && (
          <>
            <SentinelSection colonyName={colonyName} />
            <TriggersTab sessionId={sessionId} />
          </>
        )}
        {tab === "workers" && (
          // Keyed by sessionId so a colony switch fully remounts the tab:
          // the drilled-in worker selection and cached roster reset, and any
          // in-flight worker fetch from the previous session lands on an
          // unmounted component (a no-op) instead of showing "worker not
          // found" for a worker that belongs to the colony we just left.
          <WorkersTab
            key={sessionId ?? "none"}
            sessionId={sessionId}
            colonyName={colonyName}
          />
        )}
      </div>

      {/* Drawer footer — always present when bound to a colony. Carries the
          low-emphasis status/actions row (browser connection + folder reveal)
          so they don't compete with the COLONY header or tabs for focus.
          The folder button is Data-tab-only since it's a data action. */}
      {colonyName && (
        <div className="flex-shrink-0 border-t border-border/40 bg-card px-3 py-2 flex items-center justify-between gap-2">
          {/* Wrapper carries the hover-tooltip group: a disabled <button>
              swallows hover so a native `title` never appears, but the
              span still receives :hover and drives group-hover/reveal. */}
          {tab === "data" ? (
            <span className="group/reveal relative inline-flex">
              <button
                onClick={() => coloniesApi.revealFolder(colonyName).catch(() => {})}
                disabled={onCloud}
                className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs transition-colors ${
                  onCloud
                    ? "text-muted-foreground/40 cursor-not-allowed pointer-events-none"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                }`}
                title={onCloud ? undefined : "Open the colony folder in the OS file manager"}
              >
                <FolderOpen className="w-3.5 h-3.5" />
                Open colony folder
              </button>
              {onCloud && (
                <span
                  role="tooltip"
                  className="pointer-events-none absolute left-0 bottom-full mb-1.5 z-20 w-52 whitespace-normal leading-snug rounded border border-border/60 bg-card px-2 py-1.5 text-[10px] font-medium text-foreground opacity-0 invisible group-hover/reveal:opacity-100 group-hover/reveal:visible shadow-sm"
                >
                  This colony runs on a cloud computer — its folder isn't on this machine.
                </span>
              )}
            </span>
          ) : (
            <span />
          )}
          {/* Right rail: action-plan controls (History + Update plan) join the
              browser status on the Plan tab. Wrapped in their own
              TaskListProvider so they read the queen session's live tasks. */}
          <div
            className={`flex items-center gap-2${
              tab === "overview" ? " flex-1 min-w-0" : ""
            }`}
          >
            {tab === "overview" && (
              <TaskListProvider sessionId={sessionId}>
                <div className="flex items-center gap-1.5 flex-1 min-w-0">
                  <ActionPlanControls
                    sessionId={sessionId}
                    sendPrompt={requestQueenPrompt ?? undefined}
                  />
                </div>
              </TaskListProvider>
            )}
            <BrowserStatusBadge sessionId={sessionId} />
          </div>
        </div>
      )}
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  label,
  tip,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  /** One line on what the tab holds — these names don't all explain themselves
   *  ("Plan" is a task list), and a tab is exactly where a user won't click to
   *  find out. */
  tip: string;
}) {
  return (
    // `atCursor` (portalled) rather than the default trigger-anchored box: the
    // tab bar is `overflow-x-auto`, which clips BOTH axes, so an absolutely
    // positioned tooltip would be cut off below the bar. The portal also wraps
    // long labels instead of forcing one nowrap line wider than the drawer.
    <Tooltip label={tip} atCursor className="flex-1">
      <button
        onClick={onClick}
        className={`flex-1 whitespace-nowrap px-3 py-2 text-xs font-medium transition-colors border-b-2 ${
          active
            ? "border-primary text-foreground"
            : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/30"
        }`}
      >
        {label}
      </button>
    </Tooltip>
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

/** Collapsible chevron · label · count header wrapping a `<ul>`; shared by
 *  the Skills and Tools groups (identical chrome, only the rows differ). */
function CollapsibleGroup({
  label,
  count,
  defaultOpen,
  children,
}: {
  label: string;
  count: number;
  defaultOpen: boolean;
  children: React.ReactNode;
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
        <span className="text-muted-foreground/60">({count})</span>
      </button>
      {open && <ul className="flex flex-col gap-1.5">{children}</ul>}
    </section>
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
  return (
    <CollapsibleGroup label={label} count={items.length} defaultOpen={defaultOpen}>
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
    </CollapsibleGroup>
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
  return (
    <CollapsibleGroup label={label} count={items.length} defaultOpen={false}>
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
    </CollapsibleGroup>
  );
}

// ── Per-worker tool tracking (SSE-driven) ──────────────────────────────

interface ToolProgress {
  tools: { name: string; done: boolean; callKey: string }[];
  allDone: boolean;
}

const TOOL_EVENT_TYPES = [
  "tool_call_started",
  "tool_call_completed",
  "execution_started",
] as const;

/**
 * Live tool progress for the ONE worker the user has expanded.
 *
 * This used to subscribe panel-wide and key on every worker's stream, which
 * meant the server had to ship every worker's tool calls to every client for
 * the whole run. With the runtime potentially on another machine that is a
 * firehose nobody reads: a human looks at one worker at a time.
 *
 * So the subscription is now scoped — `?watch=worker:<id>` asks the server for
 * exactly that worker's chatter, and passing `null` (nothing expanded) opens no
 * stream at all. The collapsed worker list shows task progress from the workers
 * poll instead, which needs no stream.
 */
function useWorkerToolProgress(
  sessionId: string | null,
  watchedWorkerId: string | null,
): Map<string, ToolProgress> {
  const toolsRef = useRef<Map<string, ToolProgress>>(new Map());
  const [, tick] = useState(0);

  const onEvent = useCallback((ev: AgentEvent) => {
    const streamId = ev.stream_id;
    const workerId = workerIdFromStreamId(streamId);
    if (!workerId) return;

    switch (ev.type) {
      case "execution_started": {
        toolsRef.current.set(workerId, { tools: [], allDone: false });
        tick((n) => n + 1);
        break;
      }
      case "tool_call_started": {
        const toolName = (ev.data?.tool_name as string) || "unknown";
        const toolUseId = (ev.data?.tool_use_id as string) || "";
        const cur = toolsRef.current.get(workerId) ?? { tools: [], allDone: false };
        cur.tools.push({ name: toolName, done: false, callKey: toolUseId });
        cur.allDone = false;
        toolsRef.current.set(workerId, cur);
        tick((n) => n + 1);
        break;
      }
      case "tool_call_completed": {
        const toolUseId = (ev.data?.tool_use_id as string) || "";
        const cur = toolsRef.current.get(workerId);
        if (!cur) break;
        const entry = cur.tools.find((t) => t.callKey === toolUseId && !t.done);
        if (entry) entry.done = true;
        cur.allDone = cur.tools.length > 0 && cur.tools.every((t) => t.done);
        tick((n) => n + 1);
        break;
      }
    }
  }, []);

  useSSE({
    sessionId: sessionId ?? "",
    eventTypes: TOOL_EVENT_TYPES as unknown as AgentEvent["type"][],
    enabled: Boolean(sessionId) && Boolean(watchedWorkerId),
    watch: watchedWorkerId ? `worker:${watchedWorkerId}` : undefined,
    onEvent,
  });

  return toolsRef.current;
}

// ── Overview tab ───────────────────────────────────────────────────────

function OverviewTab({ sessionId }: { sessionId: string }) {
  return (
    <div className="flex flex-col h-full">
      {/* Queen's session task list — the single source of tasks now that
          colony-template lists are gone. The History + Update plan controls
          live in the drawer footer (next to "Open colony folder"), not here. */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <TaskListPanel sessionId={sessionId} title="Tasks" variant="embedded" />
      </div>
    </div>
  );
}

// ── Workers tab ────────────────────────────────────────────────────────

function WorkersTab({
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
  const [capabilitiesOpen, setCapabilitiesOpen] = useState(false);
  const { focusWorkerId, setFocusWorkerId } = useColonyWorkers();
  // Serialized form of the most recently committed workers list, used
  // to short-circuit setWorkers when a poll returns an identical
  // payload. Without this the 2s poll re-renders every memo'd
  // WorkerCard on every tick even when nothing changed.
  const lastWorkersJsonRef = useRef<string>("");

  const commitWorkers = useCallback((next: WorkerSummary[]) => {
    const serialized = JSON.stringify(next);
    if (serialized === lastWorkersJsonRef.current) return;
    lastWorkersJsonRef.current = serialized;
    setWorkers(next);
  }, []);

  // Discard the dedup snapshot when the session changes so the first
  // fetch under a new session always commits (otherwise an identical
  // serialization across sessions — empty lists in particular — would
  // be swallowed).
  useEffect(() => {
    lastWorkersJsonRef.current = "";
  }, [sessionId]);

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
      .then((r) => commitWorkers(r.workers))
      .catch((e) => setError(e?.message ?? "Failed to load workers"))
      .finally(() => setLoading(false));
  }, [sessionId, commitWorkers]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Light poll so live workers tick their duration/status without the
  // user hitting refresh. 2s matches the cadence of the standalone
  // WorkersPanel this tab replaces. Consecutive 404s trip the same
  // circuit breaker as the context's poll — the session is gone from
  // the runtime and can only return via a sessionId transition, which
  // re-runs this effect. The last-known list stays on screen.
  useEffect(() => {
    let misses = 0;
    const id = setInterval(() => {
      colonyWorkersApi
        .list(sessionId)
        .then((r) => {
          misses = 0;
          commitWorkers(r.workers);
        })
        .catch((e) => {
          if (!(e instanceof ApiError && e.status === 404)) {
            misses = 0;
            return;
          }
          misses += 1;
          if (misses >= SESSION_GONE_404_LIMIT) clearInterval(id);
        });
    }, 2000);
    return () => clearInterval(id);
  }, [sessionId, commitWorkers]);

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
  const { activeWorkers, historyWorkers, labelByWorkerId } = useMemo(() => {
    const act: WorkerSummary[] = [];
    const hist: WorkerSummary[] = [];
    for (const w of workers) {
      (isWorkerActive(w) ? act : hist).push(w);
    }
    const byRecent = (a: WorkerSummary, b: WorkerSummary) =>
      (b.started_at || 0) - (a.started_at || 0);
    act.sort(byRecent);
    hist.sort(byRecent);

    // Group batched workers by batch_id and assign each batch a 1-based
    // batch number ordered by the batch's earliest started_at, so the
    // first batch the queen kicked off is "Batch 1" regardless of how
    // many solo workers ran alongside it. Numbering is by min
    // started_at (not the timestamp embedded in batch_id) so the rule
    // survives any future batch_id format change.
    const batchFirstSeen = new Map<string, number>();
    for (const w of workers) {
      const id = w.batch?.batch_id;
      if (!id || !w.batch || w.batch.batch_size <= 0) continue;
      const prev = batchFirstSeen.get(id);
      const t = w.started_at || 0;
      if (prev == null || t < prev) batchFirstSeen.set(id, t);
    }
    const batchNumberById = new Map<string, number>();
    [...batchFirstSeen.entries()]
      .sort((a, b) => a[1] - b[1])
      .forEach(([id], i) => batchNumberById.set(id, i + 1));

    // Playbook runs dispatch every worker as its own size-1 batch sharing one
    // batch_id, so batch_index is always 1. The runner instead stamps a
    // run-scoped worker_seq; track the largest seq per batch so the padding
    // width is stable as the run grows ("C-01".."C-12", not a width that
    // jumps when worker 10 arrives).
    const batchMaxSeq = new Map<string, number>();
    for (const w of workers) {
      const id = w.batch?.batch_id;
      const seq = w.batch?.worker_seq || 0;
      if (!id || seq <= 0) continue;
      const prev = batchMaxSeq.get(id) || 0;
      if (seq > prev) batchMaxSeq.set(id, seq);
    }

    // Solo workers (no batch info) get a fallback "Worker #N" numbered
    // by ascending started_at so their labels stay stable as new
    // workers spawn. This also covers the case where the runtime list
    // endpoint hasn't yet been updated to send the ``batch`` field.
    const soloByOldest = [...workers]
      .filter((w) => !w.batch || !w.batch.batch_id || w.batch.batch_size <= 0)
      .sort((a, b) => (a.started_at || 0) - (b.started_at || 0));
    const soloIdx = new Map<string, number>();
    soloByOldest.forEach((w, i) => soloIdx.set(w.worker_id, i + 1));

    const labels = new Map<string, string>();
    for (const w of workers) {
      const b = w.batch;
      if (b && b.batch_id && b.batch_size > 0) {
        const n = batchNumberById.get(b.batch_id);
        if (n != null) {
          // Playbook workers (worker_seq > 0) index by their run-scoped seq;
          // padding tracks the largest seq seen so far in the run. Ordinary
          // fan-out indexes by batch_index, with width from batch_size so a
          // 100-worker batch reads as "A-001" not "A-100" beside "A-1".
          const seq = b.worker_seq || 0;
          const ordinal = seq > 0 ? seq : b.batch_index;
          const widthBasis = seq > 0 ? batchMaxSeq.get(b.batch_id) || seq : b.batch_size;
          const width = Math.max(2, String(widthBasis).length);
          const padded = String(ordinal).padStart(width, "0");
          labels.set(w.worker_id, `Worker ${batchLetter(n)}-${padded}`);
          continue;
        }
      }
      const i = soloIdx.get(w.worker_id);
      if (i != null) labels.set(w.worker_id, `Worker #${i}`);
    }
    return { activeWorkers: act, historyWorkers: hist, labelByWorkerId: labels };
  }, [workers]);

  // Hooks below this point MUST stay above the `if (selected)` early
  // return — same rules-of-hooks reason as the useMemo a few lines up.
  //
  // Only the selected worker is watched: opening a worker's detail view is
  // what asks the server to start streaming that worker's tool calls. Nothing
  // selected → no stream. The collapsed list still shows progress, sourced
  // from the workers poll (`task_summary`) rather than from tool events.
  const toolProgress = useWorkerToolProgress(sessionId, selected);

  if (selected) {
    return (
      <WorkerDetail
        colonyName={colonyName}
        sessionId={sessionId}
        worker={selectedWorker}
        workerId={selected}
        workerLabel={labelByWorkerId.get(selected)}
        onBack={() => setSelected(null)}
      />
    );
  }

  const activeCount = activeWorkers.length;

  return (
    <>
    <TabShell
      loading={loading}
      error={error}
      onRefresh={refresh}
      empty={null}
      headerRight={
        <div className="flex items-center gap-1.5">
          {activeCount > 0 && (
            <button
              onClick={stopAll}
              disabled={stoppingAll}
              className="text-[10px] px-2 py-0.5 rounded border border-destructive/40 text-destructive hover:bg-destructive/10 disabled:opacity-50 transition-colors"
              title={`Stop ${activeCount} active worker${activeCount === 1 ? "" : "s"}`}
            >
              {stoppingAll ? "Stopping…" : `Stop all (${activeCount})`}
            </button>
          )}
        </div>
      }
    >
      {workers.length === 0 ? (
        <WorkersEmptyState />
      ) : (
        <div className="flex flex-col gap-3">
          {activeWorkers.length > 0 && (
            <section>
              <h4 className="text-[10px] uppercase tracking-wide font-semibold text-primary mb-1.5 flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                Active ({activeWorkers.length})
              </h4>
              <ul className="flex flex-col gap-1.5">
                {activeWorkers.map((w) => (
                  <WorkerCard
                    key={w.worker_id}
                    w={w}
                    label={labelByWorkerId.get(w.worker_id)}
                    active
                    stoppingId={stoppingId}
                    onSelect={() => setSelected(w.worker_id)}
                    onStop={() => stopOne(w.worker_id)}
                    toolProgress={toolProgress.get(w.worker_id)}
                  />
                ))}
              </ul>
            </section>
          )}
          {historyWorkers.length > 0 && (
            <section>
              <h4 className="text-[10px] uppercase tracking-wide font-semibold text-muted-foreground mb-1.5">
                History ({historyWorkers.length})
              </h4>
              <ul className="flex flex-col gap-1.5">
                {historyWorkers.map((w) => (
                  <WorkerCard
                    key={w.worker_id}
                    w={w}
                    label={labelByWorkerId.get(w.worker_id)}
                    active={false}
                    stoppingId={stoppingId}
                    onSelect={() => setSelected(w.worker_id)}
                    onStop={() => stopOne(w.worker_id)}
                    toolProgress={toolProgress.get(w.worker_id)}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </TabShell>
    <CapabilitiesModal
      open={capabilitiesOpen}
      sessionId={sessionId}
      onClose={() => setCapabilitiesOpen(false)}
    />
    </>
  );
}

function isWorkerActive(w: WorkerSummary): boolean {
  const s = (w.status || "").toLowerCase();
  return s === "pending" || s === "running";
}

/** Centered icon-badge / headline / body (+ optional action) empty state,
 *  shared by the Workers, Data, Triggers, and cloud-deploy empty views. */
function EmptyState({
  icon,
  title,
  body,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center text-center px-2 py-10">
      <div className="w-10 h-10 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center text-primary mb-3">
        {icon}
      </div>
      <h3 className="text-sm font-semibold text-foreground mb-1.5">{title}</h3>
      <p
        className={`text-[11.5px] text-muted-foreground leading-relaxed max-w-[260px]${
          children ? " mb-4" : ""
        }`}
      >
        {body}
      </p>
      {children}
    </div>
  );
}

function WorkersEmptyState() {
  return (
    <EmptyState
      icon={<Users className="w-4 h-4" />}
      title="No workers spawned yet"
      body="Workers are background subagents your queen spawns to handle work at scale — queen stays responsive while workers execute."
    />
  );
}

// ── Worker card (memo'd component for tool expansion) ─────────────────

const WorkerCard = memo(function WorkerCard({
  w,
  label,
  active,
  stoppingId,
  onSelect,
  onStop,
  toolProgress,
}: {
  w: WorkerSummary;
  label: string | undefined;
  active: boolean;
  stoppingId: string | null;
  onSelect: () => void;
  onStop: () => void;
  toolProgress: ToolProgress | undefined;
}) {
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const toolCount = toolProgress?.tools.length ?? 0;
  const doneCount = toolProgress?.tools.filter((t) => t.done).length ?? 0;

  return (
    <li>
      <div
        className={`rounded-lg border transition-colors ${
          active
            ? "border-primary/40 bg-primary/[0.06] ring-1 ring-primary/20 hover:bg-primary/10"
            : "border-border/40 bg-background/20 opacity-80 hover:bg-muted/20 hover:opacity-100"
        }`}
      >
        <button
          onClick={onSelect}
          className="w-full text-left px-3 py-2.5"
        >
          <div className="flex items-center justify-between mb-1 gap-2">
            <div className="flex items-center gap-1.5 min-w-0">
              <span
                className={`text-xs font-medium ${active ? "text-foreground" : "text-foreground/70"}`}
              >
                {label ?? shortId(w.worker_id)}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${statusClasses(w.status)}`}
              >
                {w.status}
              </span>
              <ChevronRight className="w-3 h-3 text-muted-foreground" />
            </div>
          </div>
          {(w.goal || w.task) && (
            <p
              className={`text-xs line-clamp-2 mb-1 ${
                active ? "text-foreground/85" : "text-foreground/60"
              }`}
            >
              {/* Queen-authored goal (plain language) beats the raw task prompt. */}
              {w.goal || w.task}
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

        {/* Progress for a worker we are NOT watching. No tool events arrive for
            it (that chatter is only streamed for the selected worker), so show
            its task list from the workers poll instead. Same information, and
            it costs nothing on the wire. */}
        {toolCount === 0 && (w.task_summary?.total ?? 0) > 0 && (
          <div className="border-t border-border/30 px-3 py-1.5">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <ListChecks className="w-3 h-3 flex-shrink-0" />
              <span className="tabular-nums">
                {w.task_summary?.completed ?? 0}/{w.task_summary?.total ?? 0}{" "}
                tasks
              </span>
              {(w.task_summary?.in_progress ?? 0) > 0 && (
                <span className="text-primary ml-0.5">(running)</span>
              )}
            </div>
          </div>
        )}

        {toolCount > 0 && (
          <div className="border-t border-border/30 px-3 py-1.5">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setToolsExpanded((v) => !v);
              }}
              className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors w-full"
            >
              <Wrench className="w-3 h-3 flex-shrink-0" />
              <span className="tabular-nums">
                {doneCount}/{toolCount} tools
              </span>
              {!toolProgress?.allDone && (
                <span className="text-primary ml-0.5">(running)</span>
              )}
              <span className="ml-auto">
                {toolsExpanded ? (
                  <ChevronUp className="w-3 h-3" />
                ) : (
                  <ChevronDown className="w-3 h-3" />
                )}
              </span>
            </button>
            {toolsExpanded && toolProgress && (
              <div className="mt-1.5">
                <ToolActivityRow
                  content={JSON.stringify({
                    tools: toolProgress.tools.map((t) => ({
                      name: t.name,
                      done: t.done,
                    })),
                    allDone: toolProgress.allDone,
                  })}
                />
              </div>
            )}
          </div>
        )}

        {active && (
          <div className="border-t border-primary/20 px-3 py-1.5 flex justify-end">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onStop();
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
});


// ── Triggers tab ───────────────────────────────────────────────────────

function TriggersTab({ sessionId }: { sessionId: string }) {
  const { triggers } = useColonyWorkers();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
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

  const newButton = (
    <button
      type="button"
      onClick={() => setShowCreate(true)}
      disabled={!sessionId}
      className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium bg-primary/15 text-primary hover:bg-primary/25 border border-primary/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      title="Create a new schedule"
    >
      <Plus className="w-3 h-3" />
      New
    </button>
  );

  return (
    <>
      <TabShell
        loading={false}
        error={null}
        empty={null}
        headerRight={triggers.length > 0 ? newButton : undefined}
      >
        {triggers.length === 0 ? (
          <TriggersEmptyState onCreate={() => setShowCreate(true)} />
        ) : (
          <ul className="flex flex-col gap-1.5">
            {triggers.map((t) => (
              <li key={t.id}>
                <TriggerCard trigger={t} onClick={() => setSelectedId(t.id)} />
              </li>
            ))}
          </ul>
        )}
      </TabShell>
      {showCreate && sessionId && (
        <CreateSchedulerModal
          sessionId={sessionId}
          onClose={() => setShowCreate(false)}
        />
      )}
    </>
  );
}

/** Empty state for the Triggers tab. Its job is to get the user to the one
 *  move that makes the first card appear: creating a schedule. We surface a
 *  primary call-to-action that opens the same Create-schedule popup as the
 *  header "New" button. */
function TriggersEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <EmptyState
      icon={<Clock className="w-4 h-4" />}
      title="Put this colony on a schedule"
      body="Run this colony automatically — every day, on specific weekdays, or at a set interval. You choose the time; it fires on its own."
    >
      <button
        type="button"
        onClick={onCreate}
        className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
      >
        <Plus className="w-3.5 h-3.5" />
        Create schedule
      </button>
    </EmptyState>
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

/** Tick a live countdown against the server-provided absolute `next_fire_at`
 *  (epoch ms). Falls back to converting `next_fire_in` (seconds delta) if
 *  the absolute form is absent. Rolls forward by interval_minutes when
 *  zero is crossed so the UI keeps counting between server pushes. */
function useLiveCountdown(
  nextFireAt: number | undefined,
  nextFireIn: number | undefined,
  isActive: boolean,
  intervalMinutes: number | undefined,
): { remainingSec: number | null; firesAtMs: number | null } {
  const [firesAtMs, setFiresAtMs] = useState<number | null>(null);
  const [remainingSec, setRemainingSec] = useState<number | null>(null);

  useEffect(() => {
    if (typeof nextFireAt === "number" && nextFireAt > 0) {
      setFiresAtMs(nextFireAt);
    } else if (typeof nextFireIn === "number" && nextFireIn >= 0) {
      setFiresAtMs(Date.now() + nextFireIn * 1000);
    } else {
      setFiresAtMs(null);
    }
  }, [nextFireAt, nextFireIn]);

  useEffect(() => {
    if (!isActive || firesAtMs == null) {
      setRemainingSec(null);
      return;
    }
    const tick = () => {
      const diff = (firesAtMs - Date.now()) / 1000;
      if (diff > 0) {
        setRemainingSec(diff);
      } else if (intervalMinutes) {
        setFiresAtMs((prev) => (prev != null ? prev + intervalMinutes * 60 * 1000 : prev));
      } else {
        setRemainingSec(0);
      }
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [firesAtMs, isActive, intervalMinutes]);

  return { remainingSec, firesAtMs };
}

function TriggerCard({ trigger, onClick }: { trigger: GraphNode; onClick: () => void }) {
  const isActive = triggerIsActive(trigger);
  const schedule = scheduleLabel(trigger.triggerConfig);
  const nextFireIn = trigger.triggerConfig?.next_fire_in as number | undefined;
  const nextFireAt = trigger.triggerConfig?.next_fire_at as number | undefined;
  const interval = trigger.triggerConfig?.interval_minutes as number | undefined;
  const fireCount = trigger.triggerConfig?.fire_count as number | undefined;
  const lastFiredAt = trigger.triggerConfig?.last_fired_at as number | undefined;
  const { remainingSec } = useLiveCountdown(nextFireAt, nextFireIn, isActive, interval);
  const now = useNow(1000);
  const countdown = isActive && remainingSec != null ? countdownLabel(remainingSec) : null;
  const agoLabel = lastFiredAt ? formatAgo(lastFiredAt, now) : null;

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
      {(fireCount != null && fireCount > 0) || agoLabel ? (
        <p className="text-[10px] text-muted-foreground mt-0.5 pl-8">
          {fireCount != null && fireCount > 0 ? `fired ${fireCount}×` : null}
          {fireCount != null && fireCount > 0 && agoLabel ? " · " : null}
          {agoLabel ? `last ${agoLabel}` : null}
        </p>
      ) : null}
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

/** Human-readable "X ago" for a wall-clock epoch ms. */
function formatAgo(epochMs: number, nowMs: number): string {
  const diff = Math.max(0, Math.floor((nowMs - epochMs) / 1000));
  if (diff < 5) return "just now";
  if (diff < 60) return `${diff}s ago`;
  const m = Math.floor(diff / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

/** Reactive Date.now() that re-renders on an interval. 1s default keeps
 *  countdowns smooth; consumers that only need "ago" can pass a coarser
 *  interval. */
function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
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
  const [runBusy, setRunBusy] = useState(false);
  const [runNotice, setRunNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isActive = triggerIsActive(trigger);
  const config = (trigger.triggerConfig || {}) as Record<string, unknown>;
  const interval = config.interval_minutes as number | undefined;
  const nextFireIn = config.next_fire_in as number | undefined;
  const nextFireAt = config.next_fire_at as number | undefined;
  const fireCount = config.fire_count as number | undefined;
  const lastFiredAt = config.last_fired_at as number | undefined;
  const triggerId = trigger.id.replace(/^__trigger_/, "");

  const { remainingSec, firesAtMs } = useLiveCountdown(nextFireAt, nextFireIn, isActive, interval);
  const now = useNow(1000);
  const lastFiredAgo = lastFiredAt ? formatAgo(lastFiredAt, now) : null;

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

  const handleForceRun = async () => {
    if (!sessionId || runBusy) return;
    setRunBusy(true);
    setError(null);
    setRunNotice(null);
    try {
      await sessionsApi.runTrigger(sessionId, triggerId);
      setRunNotice("Trigger fired");
      // Clear the notice after a few seconds so it doesn't linger.
      setTimeout(() => setRunNotice(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunBusy(false);
    }
  };

  const schedule = scheduleLabel(config);

  // Hide UI-synthesised fields plus anything already surfaced as a
  // friendlier render above (cron/interval_minutes show up as the
  // "Schedule" line). What's left in Config is the long tail of
  // trigger-type-specific knobs the user actually needs to inspect.
  const displayEntries = Object.entries(config).filter(
    ([k]) =>
      k !== "next_fire_in" &&
      k !== "next_fire_at" &&
      k !== "fire_count" &&
      k !== "last_fired_at" &&
      k !== "entry_node" &&
      k !== "cron" &&
      k !== "interval_minutes",
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
        </Section>
      )}

      {isActive && remainingSec != null && remainingSec > 0 && (
        <Section label="Next fire">
          <p className="text-xs text-foreground italic">in {formatCountdown(remainingSec)}</p>
          {firesAtMs != null && (
            <p className="text-[10px] text-muted-foreground mt-1">
              at {new Date(firesAtMs).toLocaleTimeString()}
            </p>
          )}
        </Section>
      )}

      {(fireCount != null && fireCount > 0) || lastFiredAgo ? (
        <Section label="Last fire">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-xs text-foreground">{lastFiredAgo ?? "—"}</span>
            {fireCount != null && fireCount > 0 && (
              <span className="text-[10px] text-muted-foreground">fired {fireCount}×</span>
            )}
          </div>
          {lastFiredAt && (
            <p className="text-[10px] text-muted-foreground mt-1">
              at {new Date(lastFiredAt).toLocaleTimeString()}
            </p>
          )}
        </Section>
      ) : null}

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

      {error && (
        <p className="text-[10.5px] text-destructive leading-snug mb-2">{error}</p>
      )}
      {runNotice && (
        <p className="text-[10.5px] text-emerald-400 leading-snug mb-2">{runNotice}</p>
      )}
      <button
        type="button"
        onClick={handleForceRun}
        disabled={runBusy || !sessionId}
        title="Fire this trigger once, bypassing the schedule"
        className="w-full flex items-center justify-center gap-1.5 px-3 py-2 mb-2 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 border border-amber-500/30"
      >
        {runBusy ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Zap className="w-3.5 h-3.5" />
        )}
        {runBusy ? "Firing…" : "Force Run"}
      </button>
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

// ── Data tab (airtable-style view of tracker.db tables) ──────────────

function DataEmptyState() {
  return (
    <EmptyState
      icon={<Database className="w-4 h-4" />}
      title="No data recorded yet"
      body="Queen manages a tracker table inside colony to track the progress."
    />
  );
}

/** Table-list refresh cadence. Slower than the row poll because the
 *  overview only drives the row-count chips; the operator doesn't care
 *  if the count lags the live data by a few seconds. */
const TABLES_POLL_MS = 5000;

/** How long a changed-row highlight stays tinted in the grid. */
const HIGHLIGHT_FADE_MS = 6000;

/** Serialise a cell for CSV (RFC 4180). null/undefined → empty; booleans →
 *  true/false; everything else stringified. Fields containing a comma,
 *  double-quote, or newline are wrapped in quotes with embedded quotes
 *  doubled. */
function csvCell(v: CellValue): string {
  if (v === null || v === undefined) return "";
  const s = typeof v === "boolean" ? (v ? "true" : "false") : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Per-user, per-colony persisted order of the data-table tabs, so a
 *  user-arranged layout survives colony switches and full logout/login. */
function tabOrderKey(colonyName: string): string {
  return `colony-data-tab-order:${colonyName}`;
}

function selectedTableKey(colonyName: string): string {
  return `colony-data-selected-table:${colonyName}`;
}

/** Order `tables` by the user's saved arrangement. Tables absent from the
 *  saved order (e.g. newly created) fall to the end in their server order —
 *  Array.sort is stable, so unranked ties keep that order. */
function applyTabOrder(tables: TableOverview[], order: string[]): TableOverview[] {
  if (order.length === 0) return tables;
  const rank = new Map(order.map((name, i) => [name, i]));
  return [...tables].sort(
    (a, b) => (rank.get(a.name) ?? Infinity) - (rank.get(b.name) ?? Infinity),
  );
}

function DataTab({ colonyName }: { colonyName: string | null }) {
  const [tables, setTables] = useState<TableOverview[]>([]);
  // Seed the last-viewed table from storage (DataTab is keyed by colony, so
  // this initializer re-runs per colony). Validated against the live table
  // list once it loads — a stored name that no longer exists falls back to
  // the first table.
  const [selected, setSelected] = useState<string | null>(() =>
    colonyName ? userStorage.get<string | null>(selectedTableKey(colonyName), null) : null,
  );
  const selectTable = useCallback(
    (name: string) => {
      setSelected(name);
      if (colonyName) userStorage.set<string>(selectedTableKey(colonyName), name);
    },
    [colonyName],
  );
  // User-arranged tab order (loaded once; DataTab is keyed by colony so this
  // initializer re-runs per colony) plus in-flight drag state.
  const [tabOrder, setTabOrder] = useState<string[]>(() =>
    colonyName ? userStorage.get<string[]>(tabOrderKey(colonyName), []) : [],
  );
  // Name of the pill currently being pointer-dragged (for lifted styling).
  const [dragName, setDragName] = useState<string | null>(null);
  const [loadingTables, setLoadingTables] = useState(true);
  const [tablesError, setTablesError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  // "Expand" is an in-app focus mode — the Data tab overlays the app window
  // rather than taking over the whole screen. Esc exits.
  const [fullscreen, setFullscreen] = useState(false);
  // Attention state: workers often fill table B while the user watches
  // table A, and without a signal the new data goes unnoticed.
  //
  // Two sources feed the chip badges:
  //  - `changedRows` — row-level entries from the tracker change log
  //    (registered tables have triggers logging every insert/update with
  //    its pk). Badge = distinct changed rows; on selecting the table the
  //    entries become row highlights so the user sees WHICH rows moved.
  //  - `unseen` — net row-count growth, the fallback for tables without
  //    trigger coverage (unregistered queen-scratch tables), where
  //    updates are undetectable and only inserts show.
  const [unseen, setUnseen] = useState<Record<string, number>>({});
  const [changedRows, setChangedRows] = useState<Record<string, ChangedRow[]>>({});
  const [covered, setCovered] = useState<Set<string>>(new Set());
  // Recently-changed rows of the *selected* table, tinted in the grid and
  // faded out after a few seconds.
  const [highlights, setHighlights] = useState<{ pk: Record<string, CellValue>; ts: number }[]>([]);
  // Refs mirror state the poll callbacks need without retriggering them.
  // prevCounts is null until the first poll lands so the initial load
  // doesn't count every existing row as "new".
  const prevCountsRef = useRef<Record<string, number> | null>(null);
  const selectedRef = useRef<string | null>(null);
  const cursorRef = useRef(-1);
  const changedRowsRef = useRef<Record<string, ChangedRow[]>>({});
  useEffect(() => {
    changedRowsRef.current = changedRows;
  }, [changedRows]);

  // On viewing a table: clear its badges and promote its pending changed
  // rows into grid highlights — covers both chip clicks and auto-select.
  useEffect(() => {
    selectedRef.current = selected;
    if (!selected) {
      setHighlights([]);
      return;
    }
    setUnseen((u) => {
      if (!(selected in u)) return u;
      const next = { ...u };
      delete next[selected];
      return next;
    });
    const pending = changedRowsRef.current[selected];
    const now = Date.now();
    setHighlights(pending?.length ? pending.map((r) => ({ pk: r.pk, ts: now })) : []);
    if (pending?.length) {
      setChangedRows((prev) => {
        const next = { ...prev };
        delete next[selected];
        return next;
      });
    }
  }, [selected]);

  // Switching colonies invalidates the baselines and any badges.
  useEffect(() => {
    prevCountsRef.current = null;
    cursorRef.current = -1;
    setUnseen({});
    setChangedRows({});
    setCovered(new Set());
    setHighlights([]);
  }, [colonyName]);

  // Highlights fade after a few seconds so the tint reads as "recently
  // changed", not a permanent mark.
  useEffect(() => {
    if (highlights.length === 0) return;
    const id = setInterval(() => {
      const cutoff = Date.now() - HIGHLIGHT_FADE_MS;
      setHighlights((h) => {
        const next = h.filter((x) => x.ts > cutoff);
        return next.length === h.length ? h : next;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [highlights.length]);

  // Poll the row-level change log. First call (cursor -1) only initializes
  // the cursor + coverage so history isn't reported as new.
  const pollChanges = useCallback(() => {
    if (!colonyName) return;
    colonyDataApi
      .listChanges(colonyName, cursorRef.current)
      .then((r) => {
        cursorRef.current = r.cursor;
        setCovered((prev) => {
          const same = prev.size === r.covered.length && r.covered.every((t) => prev.has(t));
          return same ? prev : new Set(r.covered);
        });
        const entries = Object.entries(r.tables);
        if (entries.length === 0) return;
        const sel = selectedRef.current;
        const now = Date.now();
        // Changes on the table being viewed become row highlights directly.
        const selRows = sel ? r.tables[sel]?.rows : undefined;
        if (selRows?.length) {
          setHighlights((h) => {
            const byKey = new Map(h.map((x) => [JSON.stringify(x.pk), x]));
            for (const row of selRows) byKey.set(JSON.stringify(row.pk), { pk: row.pk, ts: now });
            return [...byKey.values()];
          });
        }
        // Everything else accumulates as per-table badges (dedup by pk).
        setChangedRows((prev) => {
          let next: Record<string, ChangedRow[]> | null = null;
          for (const [name, tc] of entries) {
            if (name === sel || tc.rows.length === 0) continue;
            next = next ?? { ...prev };
            const byKey = new Map((next[name] ?? []).map((x) => [JSON.stringify(x.pk), x]));
            for (const row of tc.rows) {
              const k = JSON.stringify(row.pk);
              if (!byKey.has(k)) byKey.set(k, row);
            }
            next[name] = [...byKey.values()];
          }
          return next ?? prev;
        });
      })
      .catch(() => {
        // Silent — the next tables poll retries.
      });
  }, [colonyName]);

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
          // Diff row counts against the previous poll to accumulate
          // "unseen rows" badges for tables the user is not looking at.
          // A table absent from the baseline (just created) counts all
          // its rows — the new chip alone is easy to miss mid-read.
          const prev = prevCountsRef.current;
          prevCountsRef.current = Object.fromEntries(
            r.tables.map((t) => [t.name, t.row_count]),
          );
          if (prev) {
            const deltas: Record<string, number> = {};
            for (const t of r.tables) {
              const delta = t.row_count - (prev[t.name] ?? 0);
              if (delta > 0 && t.name !== selectedRef.current) {
                deltas[t.name] = delta;
              }
            }
            if (Object.keys(deltas).length > 0) {
              setUnseen((u) => {
                const next = { ...u };
                for (const [name, d] of Object.entries(deltas)) {
                  next[name] = (next[name] ?? 0) + d;
                }
                return next;
              });
            }
          }
          // Keep the current/remembered selection when it still exists;
          // otherwise land on the first table so the user isn't left on an
          // empty picker (covers first load and a since-deleted stored table).
          setSelected((cur) =>
            cur && r.tables.some((t) => t.name === cur)
              ? cur
              : r.tables[0]?.name ?? null,
          );
          if (opts.silent) setTablesError(null);
          // Piggyback the row-level change poll on the tables poll.
          pollChanges();
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
    [colonyName, pollChanges],
  );

  useEffect(() => {
    refreshTables();
  }, [refreshTables]);

  const orderedTables = useMemo(
    () => applyTabOrder(tables, tabOrder),
    [tables, tabOrder],
  );

  // Commit a new tab arrangement to state + per-user storage so it persists
  // across colony switches and logout/login.
  const persistTabOrder = useCallback(
    (names: string[]) => {
      setTabOrder(names);
      if (colonyName) userStorage.set<string[]>(tabOrderKey(colonyName), names);
    },
    [colonyName],
  );

  // FLIP animation for tab reordering: when the order changes, each pill
  // slides from where it was to where it now is instead of jumping. We
  // measure positions every layout, but only "play" when the name sequence
  // actually changed (so row-count/badge polls don't animate).
  const tabRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const prevTabLefts = useRef<Map<string, number>>(new Map());
  const prevOrderSig = useRef<string>("");
  const flipRaf = useRef<number | null>(null);
  const flipTimeout = useRef<number | null>(null);

  // Wipe any in-flight FLIP transforms and cancel their scheduled cleanup, so
  // a fresh drag measures true layout positions (offsetLeft/rect ignore, but
  // an animating pill's rect would be mid-glide) and no styles get stuck.
  const resetTabStyles = useCallback(() => {
    if (flipRaf.current != null) {
      cancelAnimationFrame(flipRaf.current);
      flipRaf.current = null;
    }
    if (flipTimeout.current != null) {
      clearTimeout(flipTimeout.current);
      flipTimeout.current = null;
    }
    for (const el of tabRefs.current.values()) {
      el.style.transition = "";
      el.style.transform = "";
    }
  }, []);

  // ── Pointer-based tab drag ────────────────────────────────────────────
  // Native HTML5 drag proved unreliable in Electron (a composited pill
  // refuses to re-initiate a drag; the first drag needed a prior click).
  // Pointer events sidestep all of that: on pointerdown we snapshot each
  // pill's on-screen center as a *fixed* slot boundary, so the target index
  // stays stable while tabs shuffle. We reorder live (the FLIP effect
  // animates the shuffle) and only write to storage on release.
  const dragRef = useRef<{
    name: string;
    pointerId: number;
    startX: number;
    centers: number[];
    baseOrder: string[];
    moved: boolean;
  } | null>(null);
  const pendingOrderRef = useRef<string[] | null>(null);
  const suppressClickRef = useRef(false);

  const handleTabPointerDown = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>, name: string) => {
      if (e.button !== 0) return; // primary button only
      const names = orderedTables.map((t) => t.name);
      if (names.length < 2) return; // nothing to reorder
      resetTabStyles(); // clear any mid-flight FLIP so the rect snapshot is true
      const centers = names.map((n) => {
        const r = tabRefs.current.get(n)?.getBoundingClientRect();
        return r ? r.left + r.width / 2 : Number.POSITIVE_INFINITY;
      });
      dragRef.current = {
        name,
        pointerId: e.pointerId,
        startX: e.clientX,
        centers,
        baseOrder: names,
        moved: false,
      };
      pendingOrderRef.current = null;
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [orderedTables, resetTabStyles],
  );

  const handleTabPointerMove = useCallback((e: React.PointerEvent<HTMLButtonElement>) => {
    const d = dragRef.current;
    if (!d || e.pointerId !== d.pointerId) return;
    const dx = e.clientX - d.startX;
    if (!d.moved) {
      if (Math.abs(dx) < 4) return; // below threshold — leave it as a click
      d.moved = true;
      setDragName(d.name);
    }
    // Target index = how many fixed slot centers sit left of the pointer.
    let idx = 0;
    for (const c of d.centers) if (e.clientX > c) idx++;
    const without = d.baseOrder.filter((n) => n !== d.name);
    without.splice(Math.max(0, Math.min(idx, without.length)), 0, d.name);
    const prev = pendingOrderRef.current ?? d.baseOrder;
    if (without.join("|") !== prev.join("|")) {
      pendingOrderRef.current = without;
      setTabOrder(without); // state-only; storage write waits for release
    }
  }, []);

  const endTabDrag = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      const d = dragRef.current;
      if (!d || e.pointerId !== d.pointerId) return;
      try {
        e.currentTarget.releasePointerCapture(d.pointerId);
      } catch {
        /* capture already released */
      }
      if (d.moved) {
        suppressClickRef.current = true; // swallow the click that trails a drag
        if (pendingOrderRef.current) persistTabOrder(pendingOrderRef.current);
      }
      dragRef.current = null;
      pendingOrderRef.current = null;
      setDragName(null);
    },
    [persistTabOrder],
  );

  useLayoutEffect(() => {
    const sig = orderedTables.map((t) => t.name).join("|");
    const orderChanged = prevOrderSig.current !== "" && sig !== prevOrderSig.current;
    const newLefts = new Map<string, number>();
    for (const t of orderedTables) {
      const el = tabRefs.current.get(t.name);
      if (el) newLefts.set(t.name, el.offsetLeft);
    }
    if (orderChanged) {
      // Invert: pin each moved pill at its old spot with no transition.
      let animating = false;
      for (const [name, newLeft] of newLefts) {
        const el = tabRefs.current.get(name);
        const oldLeft = prevTabLefts.current.get(name);
        if (!el || oldLeft == null) continue;
        const delta = oldLeft - newLeft;
        if (Math.abs(delta) < 1) continue;
        el.style.transition = "none";
        el.style.transform = `translateX(${delta}px)`;
        animating = true;
      }
      if (animating) {
        if (flipRaf.current != null) cancelAnimationFrame(flipRaf.current);
        // Play: next frame, release everything so it glides to its new spot.
        flipRaf.current = requestAnimationFrame(() => {
          flipRaf.current = null;
          for (const el of tabRefs.current.values()) {
            if (!el.style.transform) continue;
            el.style.transition = "transform 260ms cubic-bezier(0.22, 1, 0.36, 1)";
            el.style.transform = "";
          }
          // Fallback cleanup once the glide is done: strip the inline styles
          // so no pill is left composited (and thus undraggable). Runs on a
          // timer rather than per-element `transitionend`, which can be
          // dropped if a drag interrupts the animation.
          if (flipTimeout.current != null) clearTimeout(flipTimeout.current);
          flipTimeout.current = window.setTimeout(() => {
            flipTimeout.current = null;
            for (const el of tabRefs.current.values()) {
              el.style.transition = "";
              el.style.transform = "";
            }
          }, 320);
        });
      }
    }
    prevTabLefts.current = newLefts;
    prevOrderSig.current = sig;
  }, [orderedTables]);

  // Drop any lingering FLIP styles/timers on unmount.
  useEffect(() => resetTabStyles, [resetTabStyles]);

  // Export the selected table as CSV. Pulls *every* row (not just the
  // grid's 100-row page) by walking offsets — the server caps a page at
  // 500 — then hands the serialised text to main for a native Save dialog.
  const handleDownload = useCallback(async () => {
    if (!colonyName || !selected) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const PAGE = 500; // server enforces limit ≤ 500
      let offset = 0;
      let columns: TableRowsResponse["columns"] = [];
      const rows: TableRowsResponse["rows"] = [];
      for (;;) {
        const page = await colonyDataApi.listRows(colonyName, selected, {
          limit: PAGE,
          offset,
        });
        if (offset === 0) columns = page.columns;
        rows.push(...page.rows);
        offset += page.rows.length;
        // Stop on a short page (last one) or once we've covered the total.
        if (page.rows.length < PAGE || offset >= page.total) break;
      }
      const header = columns.map((c) => csvCell(c.name)).join(",");
      const body = rows
        .map((r) => columns.map((c) => csvCell(r[c.name])).join(","))
        .join("\r\n");
      const csv = rows.length ? `${header}\r\n${body}` : header;
      const res = saveCsv(csv, `${colonyName}-${selected}`);
      if (!res.ok && !res.cancelled) {
        setDownloadError(res.error ?? "Download failed");
      }
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  }, [colonyName, selected]);

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [fullscreen]);

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
        This session isn't linked to a colony yet, so there's no data to show.
      </p>
    );
  }

  return (
    // Fills the tab body so the grid can flex to the remaining height
    // and keep the pagination row in view however many tables exist.
    <div
      className={`flex min-h-0 flex-col bg-background px-4 py-3 ${
        fullscreen ? "fixed inset-0 z-50 overflow-auto" : "h-full"
      }`}
    >
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
        <DataEmptyState />
      ) : (
        <>
          {/* Table picker — chips so we avoid a heavier select dropdown
              in the narrow sidebar. Row counts hint at scale before the
              user clicks in. */}
          <div className="flex items-start justify-between gap-2 mb-3">
            {/* Single scrollable line — wrapping orphaned the selected chip
                on row 2; counts live in the tooltip (and on the selected
                chip) so the row stays short enough to rarely scroll. */}
            <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto">
              {orderedTables.map((t) => {
                // Registered tables report distinct changed rows from the
                // change log (catches updates); others fall back to net
                // row-count growth (inserts only).
                const isCovered = covered.has(t.name);
                const newRows = isCovered
                  ? (changedRows[t.name]?.length ?? 0)
                  : (unseen[t.name] ?? 0);
                const badgeNoun = isCovered ? "changed" : "new";
                const isDragging = dragName === t.name;
                return (
                  <button
                    key={t.name}
                    ref={(el) => {
                      if (el) tabRefs.current.set(t.name, el);
                      else tabRefs.current.delete(t.name);
                    }}
                    onPointerDown={(e) => handleTabPointerDown(e, t.name)}
                    onPointerMove={handleTabPointerMove}
                    onPointerUp={endTabDrag}
                    onPointerCancel={endTabDrag}
                    onClick={() => {
                      // A trailing click fires after a drag release; swallow it
                      // so reordering doesn't also switch the selected table.
                      if (suppressClickRef.current) {
                        suppressClickRef.current = false;
                        return;
                      }
                      selectTable(t.name);
                    }}
                    className={`inline-flex items-center shrink-0 whitespace-nowrap text-[10.5px] font-mono px-2 py-1 rounded border cursor-grab active:cursor-grabbing transition-all ${
                      isDragging ? "opacity-40" : ""
                    } ${
                      selected === t.name
                        ? "border-primary bg-primary/15 text-foreground font-medium"
                        : newRows > 0
                          ? "border-amber-500/50 bg-background/40 text-muted-foreground hover:text-foreground hover:bg-muted/30"
                          : "border-border/50 bg-background/40 text-muted-foreground hover:text-foreground hover:bg-muted/30"
                    }`}
                    title={
                      `${t.row_count.toLocaleString()} rows · ${t.columns.length} columns` +
                      (newRows > 0
                        ? ` · ${newRows.toLocaleString()} ${badgeNoun} since you last looked`
                        : "")
                    }
                  >
                    {t.name}
                    <span className="ml-1 font-normal text-muted-foreground/70">
                      ({t.row_count.toLocaleString()})
                    </span>
                    {newRows > 0 && (
                      <span className="ml-1.5 inline-flex items-center gap-1 font-semibold text-amber-600 dark:text-amber-400">
                        {/* Static dot — the footer's auto-refresh pulse is the
                            one animated indicator; a ping here as well read
                            as noise. Amber = "new/changed data", matching the
                            changed-row flash; green stays reserved for
                            success semantics. */}
                        <span className="inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
                        +{newRows.toLocaleString()}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
            <div className="flex flex-shrink-0 items-center gap-0.5">
              <button
                onClick={handleDownload}
                disabled={downloading || !selected}
                title={`Download "${selected ?? ""}" as CSV`}
                aria-label="Download table as CSV"
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors disabled:opacity-40"
              >
                {downloading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Download className="w-3.5 h-3.5" />
                )}
              </button>
              <button
                onClick={() => setFullscreen((f) => !f)}
                title={fullscreen ? "Exit expanded view (Esc)" : "Expand view"}
                aria-label={fullscreen ? "Exit expanded view" : "Expand view"}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
              >
                {fullscreen ? (
                  <Minimize2 className="w-3.5 h-3.5" />
                ) : (
                  <Maximize2 className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
          </div>

          {downloadError && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive mb-2">
              {downloadError}
            </div>
          )}

          {selected && (
            <TableView
              key={selected}
              colonyName={colonyName}
              table={selected}
              highlights={highlights}
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

/** Inline cell editing in the Data tab — OFF for now: the tab reads as what the
 *  agents collected, and hand-editing a cell underneath a running colony has no
 *  defined meaning yet (the agent owns the table and may overwrite it on its
 *  next pass).
 *
 *  A flag rather than a deletion: `handleEdit` below still carries the PATCH,
 *  the request-id bump that beats the poll race, and the optimistic patch —
 *  none of which is obvious to reconstruct. Flip this to bring it all back. */
const CELL_EDITING_ENABLED = false;

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

/** Per-user, per-(colony, table) persisted sort so a column ordering the user
 *  set survives table/colony switches and full logout/login. */
type StoredSort = { by: string | null; dir: SortDir };

function sortStorageKey(colonyName: string, table: string): string {
  return `colony-data-sort:${colonyName}:${table}`;
}

function loadStoredSort(colonyName: string, table: string): StoredSort {
  const raw = userStorage.get<StoredSort | null>(sortStorageKey(colonyName, table), null);
  if (
    raw &&
    (raw.by === null || typeof raw.by === "string") &&
    (raw.dir === "asc" || raw.dir === "desc")
  ) {
    return raw;
  }
  return { by: null, dir: "asc" };
}

function colOrderStorageKey(colonyName: string, table: string): string {
  return `colony-data-col-order:${colonyName}:${table}`;
}

function loadStoredColOrder(colonyName: string, table: string): string[] {
  const raw = userStorage.get<string[] | null>(colOrderStorageKey(colonyName, table), null);
  return Array.isArray(raw) && raw.every((n) => typeof n === "string") ? raw : [];
}

/** Order `columns` by the user's saved arrangement. Columns absent from the
 *  saved order (e.g. a newly added column) fall to the end in schema order —
 *  Array.sort is stable, so unranked ties keep that order. */
function applyColumnOrder<T extends { name: string }>(columns: T[], order: string[]): T[] {
  if (order.length === 0) return columns;
  const rank = new Map(order.map((name, i) => [name, i] as const));
  return [...columns].sort(
    (a, b) => (rank.get(a.name) ?? Infinity) - (rank.get(b.name) ?? Infinity),
  );
}

function TableView({
  colonyName,
  table,
  highlights,
  onAnyEdit,
}: {
  colonyName: string;
  table: string;
  /** Recently-changed rows (from the tracker change log) to tint. */
  highlights: { pk: Record<string, CellValue>; ts: number }[];
  onAnyEdit: () => void;
}) {
  const [data, setData] = useState<TableRowsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [orderBy, setOrderBy] = useState<string | null>(() => loadStoredSort(colonyName, table).by);
  const [orderDir, setOrderDir] = useState<SortDir>(() => loadStoredSort(colonyName, table).dir);
  const [colOrder, setColOrder] = useState<string[]>(() => loadStoredColOrder(colonyName, table));

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

  const handleSort = useCallback(
    (col: string | null, dir: SortDir) => {
      setOrderBy(col);
      setOrderDir(dir);
      userStorage.set<StoredSort>(sortStorageKey(colonyName, table), { by: col, dir });
    },
    [colonyName, table],
  );

  const handleColumnReorder = useCallback(
    (names: string[]) => {
      setColOrder(names);
      userStorage.set<string[]>(colOrderStorageKey(colonyName, table), names);
    },
    [colonyName, table],
  );

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

  // Map highlight pk objects to the grid's row keys. Skips entries whose
  // pk doesn't cover the table's primary key (registered key_columns can
  // in principle be a UNIQUE index instead of the PK).
  const highlightKeys = useMemo(() => {
    if (!data || data.primary_key.length === 0 || highlights.length === 0) return undefined;
    const keys = new Set<string>();
    for (const h of highlights) {
      if (data.primary_key.every((p) => p in h.pk)) {
        keys.add(data.primary_key.map((p) => String(h.pk[p] ?? "")).join("|"));
      }
    }
    return keys.size > 0 ? keys : undefined;
  }, [data, highlights]);

  // Colony tables have no lookup schema to drive value colors; infer
  // enum-like columns (status etc.) from the loaded page. Display-only —
  // editing stays free-text (see optionsEditable below).
  const inferredOptions = useMemo(
    () =>
      data ? inferColumnOptions(data.columns, data.rows, data.primary_key) : {},
    [data],
  );

  const orderedColumns = useMemo(
    () => (data ? applyColumnOrder(data.columns, colOrder) : []),
    [data, colOrder],
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
    <div className="flex min-h-0 flex-1 flex-col gap-2" ref={gridRef}>
      <DataGrid
        columns={orderedColumns}
        rows={data.rows}
        primaryKey={data.primary_key}
        orderBy={orderBy}
        orderDir={orderDir}
        onSortChange={handleSort}
        onColumnReorder={handleColumnReorder}
        onCellEdit={CELL_EDITING_ENABLED ? handleEdit : undefined}
        columnOptions={inferredOptions}
        optionsEditable={false}
        highlightKeys={highlightKeys}
        loading={loading}
        emptyMessage="Table is empty."
      />
      <div className="flex flex-shrink-0 items-center justify-between text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span
            className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-pulse"
            title={
              CELL_EDITING_ENABLED
                ? `Auto-refreshing every ${ROWS_POLL_MS / 1000}s (paused while editing)`
                : `Auto-refreshing every ${ROWS_POLL_MS / 1000}s`
            }
          />
          <span>
            {data.total === 0
              ? "0 rows"
              : !canPrev && !canNext
                ? // Single page: the whole table is on screen, so a range
                  // reading ("1–57 of 57") is just noise.
                  `${data.total.toLocaleString()} row${data.total === 1 ? "" : "s"}`
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

// ── Worker detail view (inside Workers tab) ────────────────────────────

function WorkerDetail({
  colonyName,
  sessionId,
  worker,
  workerId,
  workerLabel,
  onBack,
}: {
  colonyName: string | null;
  sessionId: string;
  worker: WorkerSummary | null | undefined;
  workerId: string;
  workerLabel: string | undefined;
  onBack: () => void;
}) {
  const [detail, setDetail] = useState<WorkerDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch the full per-worker record. The list summary (``worker``)
  // renders immediately as a fallback so there's no flash; once this
  // resolves the view upgrades with the profile name, batch
  // coordinates, and — crucially for terminated workers — the result
  // read from result.json on disk, which the list endpoint omits.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    colonyWorkersApi
      .get(sessionId, workerId)
      .then((r) => {
        if (!cancelled) setDetail(r.worker);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? "Failed to load worker");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, workerId]);

  const view = detail ?? worker;
  const batch = detail?.batch;
  const inBatch = !!batch && batch.batch_size > 0;

  return (
    <div className="px-4 py-3">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-3"
      >
        <ArrowLeft className="w-3 h-3" />
        All workers
      </button>

      <div className="rounded-lg border border-border/60 bg-background/40 px-3 py-2.5 mb-3">
        <div className="flex items-center justify-between mb-1 gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-xs font-medium text-foreground">
              {workerLabel ?? shortId(workerId)}
            </span>
            {loading && (
              <Loader2 className="w-3 h-3 text-muted-foreground animate-spin flex-shrink-0" />
            )}
          </div>
          {view && (
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${statusClasses(view.status)}`}
            >
              {view.status}
            </span>
          )}
        </div>
        {detail?.profile_name && (
          <div className="text-[10px] text-muted-foreground mb-1">
            Profile: <span className="text-foreground/80">{detail.profile_name}</span>
          </div>
        )}
        {(view?.goal || view?.task) && <p className="text-xs text-foreground/80 mb-1">{view.goal || view.task}</p>}
        <div className="text-[10px] text-muted-foreground">
          {view ? fmtStarted(view.started_at) : ""}
          {view?.result?.duration_seconds
            ? ` · ${view.result.duration_seconds.toFixed(1)}s`
            : ""}
          {view?.result?.tokens_used
            ? ` · ${view.result.tokens_used.toLocaleString()} tok`
            : ""}
        </div>
        {inBatch && (
          <div className="text-[10px] text-muted-foreground mt-0.5">
            {batch!.worker_seq && batch!.worker_seq > 0
              ? `Playbook worker #${batch!.worker_seq}`
              : `Batch worker ${batch!.batch_index} of ${batch!.batch_size}`}
          </div>
        )}
        {view?.result?.summary && (
          <p className="mt-2 text-xs text-foreground/90 border-t border-border/40 pt-2">
            {view.result.summary}
          </p>
        )}
        {view?.result?.error && (
          <p className="mt-2 text-xs text-destructive border-t border-destructive/30 pt-2">
            {view.result.error}
          </p>
        )}
        {error && !view && (
          <p className="mt-2 text-xs text-destructive">{error}</p>
        )}
      </div>

      {/* Worker session task list — embedded; collapses out when the
          worker never created a task list (most do not). */}
      <div className="mb-3">
        <WorkerTaskList workerId={workerId} colonyName={colonyName} />
      </div>

      {/* Full message transcript from the worker's run. */}
      <WorkerTranscript sessionId={sessionId} workerId={workerId} />
    </div>
  );
}

function WorkerTaskList({
  workerId,
  colonyName: _colonyName,
}: {
  workerId: string;
  colonyName: string | null;
}) {
  // Workers' session_id == their worker_id (ColonyRuntime.spawn). The SSE
  // events for the worker's task list ride on the colony's bus, which we
  // subscribe to via the queen's session id (already streaming in this view).
  const { sessionId: queenSessionId } = useColonyWorkers();
  return (
    <TaskListPanel
      sessionId={workerId}
      eventSessionId={queenSessionId ?? undefined}
      title="Worker session"
      variant="embedded"
      hideWhenEmpty
    />
  );
}

// ── Worker conversation transcript ─────────────────────────────────────

/** Fetches and renders a worker's full message transcript. The parts
 *  are written incrementally during the run, so this works for live and
 *  terminated workers alike. */
function WorkerTranscript({
  sessionId,
  workerId,
}: {
  sessionId: string;
  workerId: string;
}) {
  const [messages, setMessages] = useState<WorkerMessage[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    colonyWorkersApi
      .getConversation(sessionId, workerId)
      .then((r) => {
        if (cancelled) return;
        setMessages(r.messages);
        setTruncated(r.truncated);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? "Failed to load transcript");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, workerId]);

  if (loading) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground px-1 py-2">
        <Loader2 className="w-3 h-3 animate-spin" />
        Loading transcript…
      </div>
    );
  }
  if (error) {
    return <p className="text-xs text-destructive px-1 py-2">{error}</p>;
  }
  if (messages.length === 0) {
    return (
      <p className="text-xs text-muted-foreground px-1 py-2">
        No conversation recorded for this worker.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <h4 className="text-[10px] uppercase tracking-wide font-semibold text-muted-foreground">
        Transcript ({messages.length}
        {truncated ? "+" : ""})
      </h4>
      {messages.map((m) => (
        <TranscriptMessage key={m.seq} msg={m} />
      ))}
    </div>
  );
}

/** One transcript row. Tool-result messages render as a collapsed
 *  disclosure; user / assistant messages render as bordered cards. */
function TranscriptMessage({ msg }: { msg: WorkerMessage }) {
  if (msg.role === "tool") {
    return <TranscriptToolResult content={msg.content} />;
  }
  const isUser = msg.role === "user";
  return (
    <div
      className={`rounded-md border px-2.5 py-1.5 ${
        isUser
          ? "border-primary/30 bg-primary/[0.06]"
          : "border-border/40 bg-background/30"
      }`}
    >
      <div className="text-[10px] uppercase tracking-wide font-semibold text-muted-foreground mb-0.5">
        {isUser ? "User" : "Assistant"}
      </div>
      {msg.content && (
        <p className="text-xs text-foreground/85 whitespace-pre-wrap break-words">
          {msg.content}
        </p>
      )}
      {msg.tool_calls?.map((tc, i) => (
        <div
          key={i}
          className={`flex items-start gap-1 ${msg.content ? "mt-1.5" : ""}`}
        >
          <Wrench className="w-3 h-3 text-muted-foreground mt-0.5 flex-shrink-0" />
          <div className="min-w-0">
            <code className="text-[11px] font-mono text-foreground/80">
              {tc.name}
            </code>
            {tc.arguments && (
              <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-words line-clamp-3">
                {tc.arguments}
              </pre>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Collapsed tool-result disclosure — tool output is verbose, so it
 *  stays folded behind a one-line preview until clicked. */
function TranscriptToolResult({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const firstLine = content.split("\n", 1)[0];
  return (
    <div className="rounded-md border border-border/30 bg-muted/20 px-2.5 py-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground w-full text-left"
      >
        {open ? (
          <ChevronDown className="w-3 h-3 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-3 h-3 flex-shrink-0" />
        )}
        <span className="font-medium flex-shrink-0">Tool result</span>
        {!open && (
          <span className="truncate font-mono text-foreground/45">
            {firstLine}
          </span>
        )}
      </button>
      {open && (
        <pre className="mt-1 text-[10px] font-mono text-foreground/70 whitespace-pre-wrap break-words max-h-60 overflow-y-auto">
          {content}
        </pre>
      )}
    </div>
  );
}

// ── Colony capabilities modal (skills + tools) ─────────────────────────

function CapabilitiesModal({
  open,
  sessionId,
  onClose,
}: {
  open: boolean;
  sessionId: string;
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-lg pointer-events-auto flex flex-col max-h-[85vh]">
          <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/15 border border-primary/30 flex items-center justify-center text-primary">
                <Settings className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">
                  Colony capabilities
                </h2>
                <p className="text-[11px] text-muted-foreground">
                  Skills and tools shared by every worker in this colony.
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto">
            <div className="px-5 pt-3 pb-1 text-[10px] uppercase tracking-wide font-semibold text-muted-foreground">
              Skills
            </div>
            <SkillsTab sessionId={sessionId} />
            <div className="px-5 pt-2 pb-1 text-[10px] uppercase tracking-wide font-semibold text-muted-foreground border-t border-border/60 mt-2">
              Tools
            </div>
            <ToolsTab sessionId={sessionId} />
          </div>
        </div>
      </div>
    </>
  );
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
  /** Omit when the tab is fed by SSE and pull-refresh is meaningless —
   *  the refresh button then isn't rendered at all (no dead affordance). */
  onRefresh?: () => void;
  empty: React.ReactNode;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
}) {
  const showHeader = onRefresh != null || headerRight != null;
  return (
    <div className="px-4 py-3">
      {showHeader && (
        <div className="flex items-center justify-between gap-2 mb-2">
          <div>{headerRight}</div>
          {onRefresh && (
            <button
              onClick={onRefresh}
              className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
              title="Refresh"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`}
              />
            </button>
          )}
        </div>
      )}

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
        <div className="text-xs text-muted-foreground text-center py-8 px-4 leading-relaxed">
          {empty}
        </div>
      ) : (
        children
      )}
    </div>
  );
}
