import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Check,
  ExternalLink,
  Loader2,
  Lock,
  Wrench,
  AlertCircle,
} from "lucide-react";
import type { ToolMeta, McpServerTools, ToolCategory } from "@/api/queens";
import { credentialsApi } from "@/api/credentials";
// The desktop build connected providers through the open-hive.com cloud
// dashboard. In local mode credentials are managed on the in-app Credentials
// page, so "Connect" affordances route there (HashRouter).
function openCredentialsPage() {
  window.location.hash = "#/credentials";
}
import { useGlobalEvents } from "@/hooks/use-sse";
import { isVisibleTool } from "@/lib/visible-tools";

/** Shape every Tools section (Queen / Colony) shares. */
export interface ToolsSnapshot {
  enabled_mcp_tools: string[] | null;
  stale: boolean;
  lifecycle: ToolMeta[];
  synthetic: ToolMeta[];
  mcp_servers: McpServerTools[];
  /** Optional: curated category groupings (queens only today). When
   * present, tools that belong to a category are grouped under that
   * category instead of their MCP server. */
  categories?: ToolCategory[];
  /** Optional: when true, the allowlist came from the role-based
   * default (no explicit save). Only queens surface this today. */
  is_role_default?: boolean;
  /** Optional: providers with at least one live OAuth account. */
  connected_providers?: string[];
}

/** Friendly label for the inline Connect button. Falls back to
 * Title-Casing the provider id when no curated label is registered. */
const PROVIDER_LABELS: Record<string, string> = {
  google: "Google",
  github: "GitHub",
  hubspot: "HubSpot",
  notion: "Notion",
  slack: "Slack",
};

function providerLabel(provider: string): string {
  return (
    PROVIDER_LABELS[provider] ??
    provider.charAt(0).toUpperCase() + provider.slice(1)
  );
}

type ToolWithEnabled = ToolMeta & { enabled: boolean };

interface RenderGroup {
  /** Stable key for expansion state and React keys. */
  key: string;
  /** Display title shown in the collapsible header. */
  title: string;
  tools: ToolWithEnabled[];
  /** True when this group's tools are always-enabled (loaded up front,
   * locked on). Drives the always-enabled vs searchable section split.
   * Only category groups can be always-enabled; raw MCP-server groups and
   * "Other tools" are always searchable. */
  alwaysEnabled: boolean;
}

/** Snake_case / kebab-case → Title Case for category labels so they
 * read naturally next to MCP server names. */
function formatCategoryTitle(name: string): string {
  return name
    .split(/[_-]+/)
    .filter((w) => w.length > 0)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** Plain-language display names for the backend category ids. Without
 * this map the ids leak into the UI as mechanically Title-Cased jargon
 * ("Context Core", "Web Core", "Browser Interaction") that a
 * non-technical user can't map to an outcome. Ids not listed here fall
 * back to Title Case via {@link categoryLabel}. Keep in sync with the
 * category table in the runtime (queen_tools_defaults.py). */
const CATEGORY_LABELS: Record<string, string> = {
  // Built-in, credential-less capabilities
  file_ops: "Files & documents",
  code_editing: "Read & edit code",
  files_core: "Files & documents",
  terminal_basic: "Terminal & commands",
  terminal_core: "Terminal & commands",
  terminal_advanced: "Terminal (advanced)",
  terminal_extended: "Terminal (advanced)",
  context_awareness: "Time, account & memory",
  context_core: "Time & account info",
  // The browser is driven via the hive-browser CLI; the four legacy browser_*
  // categories collapse to one capability toggle backed by browser_setup.
  browser_core: "Web browsing & automation",
  web_core: "Web research",
  research: "Web research",
  security: "Security scanning",
  charts: "Charts & diagrams",
  media: "Image generation",
  spreadsheet_advanced: "Spreadsheets & data",
  // Connected-account capabilities
  email_oauth: "Email",
  email_senders: "Campaign email",
  calendar_oauth: "Calendar",
  google_workspace: "Google Docs & Sheets",
  github_oauth: "GitHub",
  hubspot_oauth: "CRM (HubSpot)",
  notion_oauth: "Notion",
  slack_oauth: "Slack",
};

/** Friendly label for a backend category id, falling back to Title Case
 * for ids we haven't curated yet. */
function categoryLabel(name: string): string {
  return CATEGORY_LABELS[name] ?? formatCategoryTitle(name);
}

/** Build display groups with the priority: category → MCP server → "Other tools".
 * A tool that belongs to multiple categories lands in the first one (input order). */
function buildGroups(
  mcpServers: McpServerTools[],
  categories: ToolCategory[] | undefined,
): RenderGroup[] {
  const toolCategory = new Map<string, string>();
  const categoryAlwaysEnabled = new Map<string, boolean>();
  categories?.forEach((cat) => {
    categoryAlwaysEnabled.set(cat.name, cat.always_enabled === true);
    cat.tools.forEach((toolName) => {
      if (!toolCategory.has(toolName)) toolCategory.set(toolName, cat.name);
    });
  });

  const groupMap = new Map<string, RenderGroup>();
  // Pre-seed category groups in their original order so categories
  // come before MCP servers regardless of which tool we encounter first.
  categories?.forEach((cat) => {
    groupMap.set(`cat:${cat.name}`, {
      key: `cat:${cat.name}`,
      title: categoryLabel(cat.name),
      tools: [],
      alwaysEnabled: cat.always_enabled === true,
    });
  });

  mcpServers.forEach((srv) => {
    srv.tools.forEach((t) => {
      const cat = toolCategory.get(t.name);
      let key: string;
      let title: string;
      if (cat) {
        key = `cat:${cat}`;
        title = categoryLabel(cat);
      } else if (srv.name && srv.name !== "(unknown)") {
        key = `srv:${srv.name}`;
        title = formatCategoryTitle(srv.name);
      } else {
        key = "other";
        title = "Other tools";
      }
      let group = groupMap.get(key);
      if (!group) {
        group = {
          key,
          title,
          tools: [],
          alwaysEnabled: cat ? (categoryAlwaysEnabled.get(cat) ?? false) : false,
        };
        groupMap.set(key, group);
      }
      group.tools.push(t);
    });
  });

  return Array.from(groupMap.values()).filter((g) => g.tools.length > 0);
}

export interface ToolsEditorProps {
  /** Stable identifier — refetches when it changes. */
  subjectKey: string;
  /** Title shown above the controls. */
  title?: string;
  /** One-line caveat rendered under the header (e.g. "Changes apply …"). */
  caveat?: string;
  /** Load the current snapshot. */
  fetchSnapshot: () => Promise<ToolsSnapshot>;
  /** Persist an allowlist. ``null`` is an explicit "allow all" save.
   *
   * The result MAY be a fresh ToolsSnapshot (preferred — backend
   * returns it from PATCH so the editor stays in sync with concurrent
   * changes) or a minimal ``{enabled_mcp_tools}`` shape (legacy
   * routes). The editor handles both. */
  saveAllowlist: (
    enabled: string[] | null,
  ) => Promise<ToolsSnapshot | { enabled_mcp_tools: string[] | null }>;
  /** Optional: drop any saved allowlist so the subject falls back to
   * its role-based default. Shows a "Reset to role default" button
   * when provided. Same dual-return-shape contract as ``saveAllowlist``. */
  resetToRoleDefault?: () => Promise<
    ToolsSnapshot | { enabled_mcp_tools: string[] | null }
  >;
}

/** Type guard distinguishing a full ``ToolsSnapshot`` from the legacy
 * minimal save-result shape. */
function isFullSnapshot(
  v: ToolsSnapshot | { enabled_mcp_tools: string[] | null },
): v is ToolsSnapshot {
  return "mcp_servers" in v && Array.isArray((v as ToolsSnapshot).mcp_servers);
}

type TriState = "checked" | "unchecked" | "indeterminate";

function triStateForServer(
  toolNames: string[],
  allowed: Set<string> | null,
): TriState {
  if (allowed === null) return "checked";
  if (toolNames.length === 0) return "unchecked";
  const enabledCount = toolNames.reduce(
    (n, name) => n + (allowed.has(name) ? 1 : 0),
    0,
  );
  if (enabledCount === 0) return "unchecked";
  if (enabledCount === toolNames.length) return "checked";
  return "indeterminate";
}

function TriStateCheckbox({
  state,
  onChange,
  disabled,
}: {
  state: TriState;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "indeterminate";
  }, [state]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={state === "checked"}
      disabled={disabled}
      onChange={(e) => onChange(e.target.checked)}
      onClick={(e) => e.stopPropagation()}
      className="h-3.5 w-3.5 rounded border-border/70 text-primary focus:ring-primary/40"
    />
  );
}

function ToolRow({
  name,
  description,
  enabled,
  editable,
  provider,
  providerConnected,
  onToggle,
  onConnect,
}: {
  name: string;
  description: string;
  enabled: boolean;
  editable: boolean;
  /** OAuth provider this tool depends on. ``null``/``undefined`` for
   * credential-less tools (browser, terminal, etc). */
  provider?: string | null;
  /** True when the provider has at least one live OAuth account.
   * Defaults to true so credential-less tools don't get greyed. */
  providerConnected?: boolean;
  onToggle?: (next: boolean) => void;
  onConnect?: () => void;
}) {
  // Credentialed tool whose OAuth provider isn't authorized: keep the
  // checkbox visible (and "checked" so the user understands the tool
  // *would* fire once connected) but locked, and surface an inline
  // Connect <Provider> button. The bound queen default still treats
  // the row as enabled — the per-spawn filter drops it from the
  // worker's prompt at runtime, no UI churn needed.
  const needsAuth = editable && !!provider && providerConnected === false;
  const containerClasses = needsAuth
    ? "flex items-start gap-2 py-1.5 px-2 rounded hover:bg-muted/20 opacity-60"
    : "flex items-start gap-2 py-1.5 px-2 rounded hover:bg-muted/30";
  return (
    <div className={containerClasses}>
      {editable ? (
        <input
          type="checkbox"
          checked={enabled}
          disabled={needsAuth}
          onChange={(e) => onToggle?.(e.target.checked)}
          className={
            needsAuth
              ? "mt-0.5 h-3.5 w-3.5 rounded border-border/70 text-primary cursor-not-allowed"
              : "mt-0.5 h-3.5 w-3.5 rounded border-border/70 text-primary focus:ring-primary/40"
          }
          title={
            needsAuth
              ? `Connect ${providerLabel(provider!)} to enable this tool`
              : undefined
          }
        />
      ) : (
        <Lock className="mt-0.5 h-3 w-3 text-muted-foreground/60 flex-shrink-0" />
      )}
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium text-foreground font-mono">
          {name}
        </div>
        {description && (
          <div className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2">
            {description}
          </div>
        )}
      </div>
      {needsAuth && onConnect && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onConnect();
          }}
          className="flex-shrink-0 mt-0.5 inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border/60 text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/40"
        >
          <ExternalLink className="w-3 h-3" />
          Connect {providerLabel(provider!)}
        </button>
      )}
    </div>
  );
}

function CollapsibleGroup({
  title,
  count,
  badge,
  expanded,
  onToggle,
  leading,
  trailing,
  dimmed,
  children,
}: {
  title: string;
  count: number;
  badge?: string;
  expanded: boolean;
  onToggle: () => void;
  leading?: React.ReactNode;
  /** Optional content rendered to the right of the badge (e.g. a
   * group-level Connect button when every tool in the group is
   * gated on the same disconnected OAuth provider). */
  trailing?: React.ReactNode;
  /** When true, dim the header to mirror the row-level greyed state
   * — used for groups that are entirely unselectable. */
  dimmed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-2 rounded-lg border border-border/40 bg-muted/10 overflow-hidden">
      <div
        className={
          "w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-muted/30" +
          (dimmed ? " opacity-60" : "")
        }
      >
        <button
          onClick={onToggle}
          className="flex items-center gap-2 flex-1 min-w-0 text-left"
        >
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />
          )}
          {leading}
          <span className="text-xs font-medium text-foreground flex-1 truncate">
            {title}
          </span>
          <span className="text-[11px] text-muted-foreground">
            {badge ?? count}
          </span>
        </button>
        {trailing}
      </div>
      {expanded && (
        <div className="border-t border-border/30 px-1 py-1">{children}</div>
      )}
    </div>
  );
}

/** Tier divider — separates the always-enabled (loaded up front) tools from
 * the searchable (loaded on demand) tools, each with a one-line explainer so
 * it's unambiguous which tools the agent always has vs. loads when needed. */
function SectionHeader({
  icon,
  title,
  count,
  blurb,
}: {
  icon: React.ReactNode;
  title: string;
  count: string;
  blurb: string;
}) {
  return (
    <div className="mt-3 mb-1.5 first:mt-0">
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="text-[11px] font-semibold uppercase tracking-wider text-foreground">
          {title}
        </span>
        <span className="text-[11px] text-muted-foreground">· {count}</span>
      </div>
      <p className="mt-0.5 text-[11px] text-muted-foreground leading-relaxed">
        {blurb}
      </p>
    </div>
  );
}

export default function ToolsEditor({
  subjectKey,
  title = "Tools",
  caveat,
  fetchSnapshot,
  saveAllowlist,
  resetToRoleDefault,
}: ToolsEditorProps) {
  const [data, setData] = useState<ToolsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [draftAllowed, setDraftAllowed] = useState<Set<string> | null>(null);
  const baselineRef = useRef<Set<string> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedRecently, setSavedRecently] = useState(false);

  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  // Refetch helper used by both the initial mount and the various
  // realtime-refresh triggers (global SSE events + window focus).
  // ``silent`` skips the loading spinner so background refreshes
  // don't flash an empty state. Returns a cancel-flag setter so the
  // caller can opt out of stale results.
  const lastFetchAtRef = useRef(0);
  const fetchSnapshotRef = useRef(fetchSnapshot);
  fetchSnapshotRef.current = fetchSnapshot;
  // The editor isn't remounted when the subject (queen/colony) changes, so a
  // silent refresh triggered by an SSE event or window focus can resolve after
  // the user switched subjects. Capture the subject at call time and drop the
  // result if it changed, so subject A's catalog can't land on subject B.
  const subjectKeyRef = useRef(subjectKey);
  subjectKeyRef.current = subjectKey;

  const refresh = useCallback(
    async (opts?: { silent?: boolean }) => {
      const silent = opts?.silent === true;
      const startedSubject = subjectKeyRef.current;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const d = await fetchSnapshotRef.current();
        if (subjectKeyRef.current !== startedSubject) return;
        lastFetchAtRef.current = Date.now();
        setData((prev) => {
          // Preserve in-progress edits when a silent refresh lands
          // mid-typing — we only update the SHAPE (server catalog,
          // provider connectivity), not the user's draft choices.
          if (silent && prev) {
            return d;
          }
          return d;
        });
        // Only reset baseline on a non-silent (initial) load. Silent
        // refreshes from SSE events shouldn't clobber the user's
        // pending draft.
        if (!silent) {
          const baseline =
            d.enabled_mcp_tools === null
              ? null
              : new Set<string>(d.enabled_mcp_tools);
          baselineRef.current = baseline === null ? null : new Set(baseline);
          setDraftAllowed(baseline);
        }
      } catch (e) {
        if (!silent) {
          setError((e as Error)?.message || "Failed to load tools");
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSnapshot()
      .then((d) => {
        if (cancelled) return;
        lastFetchAtRef.current = Date.now();
        setData(d);
        const baseline =
          d.enabled_mcp_tools === null
            ? null
            : new Set<string>(d.enabled_mcp_tools);
        baselineRef.current = baseline === null ? null : new Set(baseline);
        setDraftAllowed(baseline);
      })
      .catch((e) => {
        if (cancelled) return;
        setError((e as Error)?.message || "Failed to load tools");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [subjectKey, fetchSnapshot]);

  // F1 — subscribe to the global SSE bus so credential connect /
  // disconnect, catalog refreshes, and sibling-tab edits trigger a
  // silent refetch. Without this, the editor would show stale
  // ``provider_connected`` flags until the user manually closes and
  // reopens the panel.
  useGlobalEvents({
    enabled: !!subjectKey,
    onEvent: (event) => {
      // Filter cross-tab tools-config events to this subject. Other
      // queens / colonies don't concern us. Credential / catalog
      // events are always relevant — they affect the catalog shape.
      if (event.type === "tools_config_changed") {
        const data = event.data as { scope?: string; scope_id?: string };
        const subject = subjectKey.split(":");
        const sameSubject =
          subject.length === 2 &&
          subject[0] === data.scope &&
          subject[1] === data.scope_id;
        if (!sameSubject) return;
      }
      // Silent refresh — preserves in-flight edits while the user
      // is mid-toggle.
      void refresh({ silent: true });
    },
  });

  // F2 — refetch on window/tab focus. Backstop for environments
  // where the SSE connection drops between authorize-in-browser and
  // tab-back-to-app. Resync first so the backend picks up any new
  // OAuth account the user just minted on hive.adenhq.com — without
  // this, ``getTools`` returns stale ``provider_connected: false`` and
  // the tools stay locked until an app restart. Cooldown so we don't
  // hammer the API on every micro-focus event.
  useEffect(() => {
    const FOCUS_COOLDOWN_MS = 5000;
    const onFocus = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastFetchAtRef.current < FOCUS_COOLDOWN_MS) return;
      void (async () => {
        try {
          await credentialsApi.resync();
        } catch (err) {
          // Resync failures shouldn't block the refetch — the catalog
          // may still have updated for other reasons (e.g. sibling tab).
          console.warn("[tools] credential resync failed:", err);
        }
        await refresh({ silent: true });
      })();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [refresh]);

  // Curated visibility filter — drop tools whose provider isn't in the
  // shipped allowlist (Google subset / GitHub / Slack / Notion). The
  // runtime serves a wider catalog (Drive, Sheets, terminal, browser,
  // charts, …) but only this subset is exposed to the user today.
  const filteredMcpServers = useMemo(() => {
    if (!data) return [] as McpServerTools[];
    return data.mcp_servers
      .map((srv) => ({
        ...srv,
        tools: srv.tools.filter((t) => isVisibleTool(t.provider, t.name)),
      }))
      .filter((srv) => srv.tools.length > 0);
  }, [data]);

  const allMcpNames = useMemo(() => {
    const s = new Set<string>();
    filteredMcpServers.forEach((srv) =>
      srv.tools.forEach((t) => s.add(t.name)),
    );
    return s;
  }, [filteredMcpServers]);

  const groups = useMemo(
    () => (data ? buildGroups(filteredMcpServers, data.categories) : []),
    [filteredMcpServers, data],
  );
  // Split into the two tiers the screen is organized around: always-enabled
  // categories (loaded up front, locked) vs everything else (searchable,
  // loaded on demand and toggleable for availability).
  const alwaysEnabledGroups = useMemo(
    () => groups.filter((g) => g.alwaysEnabled),
    [groups],
  );
  const searchableGroups = useMemo(
    () => groups.filter((g) => !g.alwaysEnabled),
    [groups],
  );
  // Tool groups stay collapsed until the user expands them — switching
  // into this screen should never auto-open anything. The previous F4
  // auto-expansion (open any group with provider-connected + tool
  // unenabled rows) was removed by request.

  // Aggregate disconnected providers across visible groups so the
  // editor can render a single "Connect X to enable Y tools" banner
  // at the top, instead of forcing the user to scout each category
  // for missing auth.
  const disconnectedProvidersSummary = useMemo(() => {
    const byProvider = new Map<string, number>();
    for (const g of groups) {
      for (const t of g.tools) {
        if (t.provider && t.provider_connected === false) {
          byProvider.set(t.provider, (byProvider.get(t.provider) ?? 0) + 1);
        }
      }
    }
    return byProvider;
  }, [groups]);

  const dirty = useMemo(() => {
    const a = draftAllowed;
    const b = baselineRef.current;
    if (a === null && b === null) return false;
    if (a === null || b === null) return true;
    if (a.size !== b.size) return true;
    for (const n of a) if (!b.has(n)) return true;
    return false;
  }, [draftAllowed]);

  // "Active" = ticked in the draft AND the underlying provider is
  // currently authorized. A tool whose provider is disconnected can't
  // actually be called even when the box stays checked, so it must
  // not contribute to the headline count or per-group badge — that
  // would overstate the queen's real capability surface. Lives above
  // the loading/error early-returns so the hook order is stable.
  const activeToolNames = useMemo(() => {
    const s = new Set<string>();
    for (const g of groups) {
      for (const t of g.tools) {
        const ticked = draftAllowed === null ? true : draftAllowed.has(t.name);
        const reachable = t.provider_connected !== false;
        if (ticked && reachable) s.add(t.name);
      }
    }
    return s;
  }, [groups, draftAllowed]);

  const applyResult = (
    result: ToolsSnapshot | { enabled_mcp_tools: string[] | null },
    fallbackIsRoleDefault: boolean,
  ) => {
    // Prefer the full snapshot when the backend returns one (queen
    // PATCH/DELETE post-B4): replaces ``data`` wholesale so a
    // concurrent catalog change (e.g. provider just connected) is
    // reflected in the editor without a follow-up GET.
    if (isFullSnapshot(result)) {
      const updated = result.enabled_mcp_tools;
      baselineRef.current = updated === null ? null : new Set(updated);
      setDraftAllowed(updated === null ? null : new Set(updated));
      setData(result);
    } else {
      const updated = result.enabled_mcp_tools;
      baselineRef.current = updated === null ? null : new Set(updated);
      setDraftAllowed(updated === null ? null : new Set(updated));
      if (data) {
        const u = updated === null ? null : new Set(updated);
        setData({
          ...data,
          enabled_mcp_tools: updated,
          is_role_default: fallbackIsRoleDefault,
          mcp_servers: data.mcp_servers.map((srv) => ({
            ...srv,
            tools: srv.tools.map((t) => ({
              ...t,
              enabled: u === null ? true : u.has(t.name),
            })),
          })),
        });
      }
    }
    lastFetchAtRef.current = Date.now();
    setSavedRecently(true);
    setTimeout(() => setSavedRecently(false), 2500);
  };

  const toggleOne = (name: string, next: boolean) => {
    setDraftAllowed((prev) => {
      const base =
        prev === null ? new Set<string>(allMcpNames) : new Set<string>(prev);
      if (next) base.add(name);
      else base.delete(name);
      return base;
    });
  };

  const toggleServer = (serverNames: string[], next: boolean) => {
    setDraftAllowed((prev) => {
      const base =
        prev === null ? new Set<string>(allMcpNames) : new Set<string>(prev);
      if (next) serverNames.forEach((n) => base.add(n));
      else serverNames.forEach((n) => base.delete(n));
      return base;
    });
  };

  const handleAllowAll = () => setDraftAllowed(null);

  const handleCancel = () => {
    const baseline = baselineRef.current;
    setDraftAllowed(baseline === null ? null : new Set(baseline));
    setSaveError(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      // Only send tool names the server knows about (MCP tools).
      // The draft may contain lifecycle/synthetic names from the
      // baseline — strip those to avoid "Unknown MCP tool name" errors.
      const payload =
        draftAllowed === null
          ? null
          : Array.from(draftAllowed)
              .filter((name) => allMcpNames.has(name))
              .sort();
      const result = await saveAllowlist(payload);
      applyResult(result, false);
    } catch (e: unknown) {
      const err = e as { body?: { error?: string; unknown?: string[] } };
      const extra = err.body?.unknown
        ? ` (${err.body.unknown.join(", ")})`
        : "";
      setSaveError((err.body?.error || "Save failed") + extra);
    } finally {
      setSaving(false);
    }
  };

  const handleResetToRoleDefault = async () => {
    if (!resetToRoleDefault) return;
    setSaving(true);
    setSaveError(null);
    try {
      const result = await resetToRoleDefault();
      applyResult(result, true);
    } catch (e: unknown) {
      const err = e as { body?: { error?: string } };
      setSaveError(err.body?.error || "Reset failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground py-3">
        <Loader2 className="w-3 h-3 animate-spin" />
        Loading tools…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-start gap-2 text-xs text-destructive py-3">
        <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
        <span>{error || "Could not load tools"}</span>
      </div>
    );
  }

  // Tier counts for the header + section labels. "Always on" = system tools
  // (lifecycle + synthetic) + always-enabled category tools; these are loaded
  // up front and can't be turned off. "Searchable" = everything else, with
  // the toggle gating availability (whether the agent can load it at all).
  const systemCount = data.lifecycle.length + data.synthetic.length;
  const alwaysEnabledMcpCount = alwaysEnabledGroups.reduce(
    (n, g) => n + g.tools.length,
    0,
  );
  const alwaysOnCount = systemCount + alwaysEnabledMcpCount;
  const searchableTotal = searchableGroups.reduce(
    (n, g) => n + g.tools.length,
    0,
  );
  const searchableEnabled = searchableGroups.reduce(
    (n, g) =>
      n + g.tools.reduce((m, t) => m + (activeToolNames.has(t.name) ? 1 : 0), 0),
    0,
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
          <Wrench className="w-3 h-3" /> {title}
        </h4>
        <span className="text-[11px] text-muted-foreground">
          {alwaysOnCount} always on · {searchableEnabled}/{searchableTotal}{" "}
          searchable
        </span>
      </div>

      {caveat && (
        <div className="flex items-start gap-1.5 text-[11px] text-muted-foreground mb-2 px-2 py-1.5 rounded bg-muted/20 border border-border/40">
          <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
          <span>{caveat}</span>
        </div>
      )}

      {data.stale && (
        <div className="flex items-start gap-1.5 text-[11px] text-muted-foreground mb-3 px-2 py-1.5 rounded bg-muted/30">
          <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
          <span>
            Catalog is unavailable. Start a session once to populate the tool list.
          </span>
        </div>
      )}

      {/* Single aggregate banner for disconnected providers — one
          obvious affordance to authorize ALL of them rather than
          discovering Connect buttons row-by-row. */}
      {disconnectedProvidersSummary.size > 0 && (
        <div className="flex items-center justify-between gap-2 mb-3 px-2.5 py-2 rounded-md border border-border/50 bg-muted/20">
          <div className="text-[11px] text-muted-foreground leading-relaxed">
            <span className="font-medium text-foreground">
              {Array.from(disconnectedProvidersSummary.keys())
                .map(providerLabel)
                .join(", ")}
            </span>{" "}
            not connected —{" "}
            {Array.from(disconnectedProvidersSummary.values()).reduce(
              (a, b) => a + b,
              0,
            )}{" "}
            tool
            {Array.from(disconnectedProvidersSummary.values()).reduce(
              (a, b) => a + b,
              0,
            ) === 1
              ? ""
              : "s"}{" "}
            unavailable until you authorize.
          </div>
          <button
            type="button"
            onClick={() => openCredentialsPage()}
            className="flex-shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border/60 bg-background text-[11px] font-medium text-foreground hover:bg-muted/40"
          >
            <ExternalLink className="w-3 h-3" />
            Connect
          </button>
        </div>
      )}

      {/* ===== Tier 1: Always enabled (loaded up front, locked) ===== */}
      <SectionHeader
        icon={<Lock className="w-3 h-3 text-muted-foreground" />}
        title="Built-in capabilities"
        count={`${alwaysOnCount} tools`}
        blurb="The agent always has these built-in capabilities — they're on by default and can't be turned off."
      />

      {(data.lifecycle.length > 0 || data.synthetic.length > 0) && (
        <CollapsibleGroup
          title="System & control"
          count={data.lifecycle.length + data.synthetic.length}
          expanded={!!expanded["__system"]}
          onToggle={() =>
            setExpanded((p) => ({ ...p, __system: !p["__system"] }))
          }
          leading={<Lock className="w-3 h-3 text-muted-foreground/60" />}
        >
          <div className="flex flex-col">
            {data.synthetic.map((t) => (
              <ToolRow
                key={`syn-${t.name}`}
                name={t.name}
                description={t.description}
                enabled={true}
                editable={false}
              />
            ))}
            {data.lifecycle.map((t) => (
              <ToolRow
                key={`lc-${t.name}`}
                name={t.name}
                description={t.description}
                enabled={true}
                editable={false}
              />
            ))}
          </div>
        </CollapsibleGroup>
      )}

      {/* Always-enabled categories (file ops, terminal, context): locked on,
          no toggle — these bypass the allowlist on the backend. */}
      {alwaysEnabledGroups.map((group) => (
        <CollapsibleGroup
          key={group.key}
          title={group.title}
          count={group.tools.length}
          expanded={!!expanded[group.key]}
          onToggle={() =>
            setExpanded((p) => ({ ...p, [group.key]: !p[group.key] }))
          }
          leading={<Lock className="w-3 h-3 text-muted-foreground/60" />}
        >
          <div className="flex flex-col">
            {group.tools.map((t) => (
              <ToolRow
                key={`${group.key}-${t.name}`}
                name={t.name}
                description={t.description}
                enabled={true}
                editable={false}
              />
            ))}
          </div>
        </CollapsibleGroup>
      ))}

      {/* ===== Tier 2: Searchable (loaded on demand, toggleable) ===== */}
      {searchableGroups.length > 0 && (
        <SectionHeader
          icon={<Wrench className="w-3 h-3 text-muted-foreground" />}
          title="Searchable"
          count={`${searchableEnabled}/${searchableTotal} available`}
          blurb="Shown to the agent by name only; it loads the full tool with search_tools when a task needs one. Turn a tool off to hide it from the agent entirely."
        />
      )}

      {searchableGroups.map((group) => {
        const toolNames = group.tools.map((t) => t.name);
        const state = triStateForServer(toolNames, draftAllowed);
        // Same "active" semantics as the headline count — tools whose
        // provider isn't connected don't contribute even when ticked.
        const enabledInGroup = toolNames.reduce(
          (n, name) => n + (activeToolNames.has(name) ? 1 : 0),
          0,
        );
        // A group is entirely unselectable when every tool inside it is
        // bound to an OAuth provider that the user hasn't authorized yet.
        // In that case the master checkbox AND the group's bulk-toggle
        // affordance must be disabled — otherwise the user can flip a
        // row "on" via the category checkbox even though the underlying
        // tool can't actually be called.
        const allUnselectable =
          group.tools.length > 0 &&
          group.tools.every(
            (t) => !!t.provider && t.provider_connected === false,
          );
        // When every disconnected tool in the group shares a single
        // provider, surface one Connect <Provider> button at the group
        // header instead of one per row — scales better when a queen's
        // entire OAuth category is locked behind a single auth step.
        const disconnectedProviders = new Set(
          group.tools
            .filter((t) => !!t.provider && t.provider_connected === false)
            .map((t) => t.provider as string),
        );
        const groupConnectProvider =
          allUnselectable && disconnectedProviders.size === 1
            ? Array.from(disconnectedProviders)[0]
            : null;
        return (
          <CollapsibleGroup
            key={group.key}
            title={group.title}
            count={group.tools.length}
            badge={`${enabledInGroup}/${group.tools.length}`}
            expanded={!!expanded[group.key]}
            onToggle={() =>
              setExpanded((p) => ({ ...p, [group.key]: !p[group.key] }))
            }
            dimmed={allUnselectable}
            leading={
              <TriStateCheckbox
                state={state}
                disabled={allUnselectable}
                onChange={(next) => toggleServer(toolNames, next)}
              />
            }
            trailing={
              groupConnectProvider ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    openCredentialsPage();
                  }}
                  className="flex-shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border/60 text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/40"
                >
                  <ExternalLink className="w-3 h-3" />
                  Connect {providerLabel(groupConnectProvider)}
                </button>
              ) : null
            }
          >
            <div className="flex flex-col">
              {group.tools.map((t) => {
                const enabled =
                  draftAllowed === null ? true : draftAllowed.has(t.name);
                return (
                  <ToolRow
                    key={`${group.key}-${t.name}`}
                    name={t.name}
                    description={t.description}
                    enabled={enabled}
                    editable={true}
                    provider={t.provider ?? null}
                    providerConnected={t.provider_connected ?? true}
                    // When the group already shows a single Connect
                    // button at the header, suppress the per-row one so
                    // the affordance doesn't repeat on every disabled
                    // row inside the same provider bucket.
                    onToggle={(next) => toggleOne(t.name, next)}
                    onConnect={
                      groupConnectProvider
                        ? undefined
                        : () => {
                            openCredentialsPage();
                          }
                    }
                  />
                );
              })}
            </div>
          </CollapsibleGroup>
        );
      })}

      <div className="flex items-center gap-2 pt-3 flex-wrap">
        {/* Primary actions */}
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          onClick={handleCancel}
          disabled={!dirty || saving}
          className="px-3 py-1.5 rounded-md border border-border/60 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Cancel
        </button>

        {/* Status */}
        {savedRecently && !dirty && (
          <span className="text-[11px] text-green-500 flex items-center gap-1">
            <Check className="w-3 h-3" /> Saved
          </span>
        )}
        {dirty && !saving && (
          <span className="text-[11px] text-amber-500">Unsaved changes</span>
        )}

        {/* Quick actions */}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={handleAllowAll}
            disabled={saving || draftAllowed === null}
            className="px-3 py-1.5 rounded-md border border-border/60 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Allow all
          </button>
          {resetToRoleDefault && (
            <button
              onClick={handleResetToRoleDefault}
              disabled={saving || !!data.is_role_default}
              title={
                data.is_role_default
                  ? "Already using the recommended tools for this role"
                  : "Restore the recommended tools for this role"
              }
              className="px-3 py-1.5 rounded-md border border-border/60 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Reset to recommended
            </button>
          )}
        </div>
      </div>

      {saveError && (
        <div className="flex items-start gap-1.5 mt-2 text-[11px] text-destructive">
          <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
          <span>{saveError}</span>
        </div>
      )}
    </div>
  );
}
