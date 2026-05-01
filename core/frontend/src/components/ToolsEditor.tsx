import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Check,
  Loader2,
  Lock,
  Wrench,
  AlertCircle,
} from "lucide-react";
import type { ToolMeta, McpServerTools, ToolCategory } from "@/api/queens";

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
}

type ToolWithEnabled = ToolMeta & { enabled: boolean };

interface RenderGroup {
  /** Stable key for expansion state and React keys. */
  key: string;
  /** Display title shown in the collapsible header. */
  title: string;
  tools: ToolWithEnabled[];
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

/** Build display groups with the priority: category → MCP server → "Other tools".
 * A tool that belongs to multiple categories lands in the first one (input order). */
function buildGroups(
  mcpServers: McpServerTools[],
  categories: ToolCategory[] | undefined,
): RenderGroup[] {
  const toolCategory = new Map<string, string>();
  categories?.forEach((cat) => {
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
      title: formatCategoryTitle(cat.name),
      tools: [],
    });
  });

  mcpServers.forEach((srv) => {
    srv.tools.forEach((t) => {
      const cat = toolCategory.get(t.name);
      let key: string;
      let title: string;
      if (cat) {
        key = `cat:${cat}`;
        title = formatCategoryTitle(cat);
      } else if (srv.name && srv.name !== "(unknown)") {
        key = `srv:${srv.name}`;
        title = srv.name;
      } else {
        key = "other";
        title = "Other tools";
      }
      let group = groupMap.get(key);
      if (!group) {
        group = { key, title, tools: [] };
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
  /** Persist an allowlist. ``null`` is an explicit "allow all" save. */
  saveAllowlist: (
    enabled: string[] | null,
  ) => Promise<{ enabled_mcp_tools: string[] | null }>;
  /** Optional: drop any saved allowlist so the subject falls back to
   * its role-based default. Shows a "Reset to role default" button
   * when provided. */
  resetToRoleDefault?: () => Promise<{ enabled_mcp_tools: string[] | null }>;
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
  onToggle,
}: {
  name: string;
  description: string;
  enabled: boolean;
  editable: boolean;
  onToggle?: (next: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-2 py-1.5 px-2 rounded hover:bg-muted/30">
      {editable ? (
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle?.(e.target.checked)}
          className="mt-0.5 h-3.5 w-3.5 rounded border-border/70 text-primary focus:ring-primary/40"
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
  children,
}: {
  title: string;
  count: number;
  badge?: string;
  expanded: boolean;
  onToggle: () => void;
  leading?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-2 rounded-lg border border-border/40 bg-muted/10 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left hover:bg-muted/30"
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
      {expanded && (
        <div className="border-t border-border/30 px-1 py-1">{children}</div>
      )}
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

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSnapshot()
      .then((d) => {
        if (cancelled) return;
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

  const allMcpNames = useMemo(() => {
    const s = new Set<string>();
    data?.mcp_servers.forEach((srv) => srv.tools.forEach((t) => s.add(t.name)));
    return s;
  }, [data]);

  const groups = useMemo(
    () => (data ? buildGroups(data.mcp_servers, data.categories) : []),
    [data],
  );

  const dirty = useMemo(() => {
    const a = draftAllowed;
    const b = baselineRef.current;
    if (a === null && b === null) return false;
    if (a === null || b === null) return true;
    if (a.size !== b.size) return true;
    for (const n of a) if (!b.has(n)) return true;
    return false;
  }, [draftAllowed]);

  const applyResult = (updated: string[] | null, isRoleDefault: boolean) => {
    baselineRef.current = updated === null ? null : new Set(updated);
    setDraftAllowed(updated === null ? null : new Set(updated));
    if (data) {
      const u = updated === null ? null : new Set(updated);
      setData({
        ...data,
        enabled_mcp_tools: updated,
        is_role_default: isRoleDefault,
        mcp_servers: data.mcp_servers.map((srv) => ({
          ...srv,
          tools: srv.tools.map((t) => ({
            ...t,
            enabled: u === null ? true : u.has(t.name),
          })),
        })),
      });
    }
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
      applyResult(result.enabled_mcp_tools, false);
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
      applyResult(result.enabled_mcp_tools, true);
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

  const draftEnabledCount =
    draftAllowed === null ? allMcpNames.size : draftAllowed.size;
  const totalMcpCount = allMcpNames.size;

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
          <Wrench className="w-3 h-3" /> {title}
        </h4>
        <span className="text-[11px] text-muted-foreground">
          {draftEnabledCount}/{totalMcpCount} MCP enabled
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

      {(data.lifecycle.length > 0 || data.synthetic.length > 0) && (
        <CollapsibleGroup
          title="System tools (always enabled)"
          count={data.lifecycle.length + data.synthetic.length}
          expanded={!!expanded["__system"]}
          onToggle={() =>
            setExpanded((p) => ({ ...p, __system: !p["__system"] }))
          }
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

      {groups.map((group) => {
        const toolNames = group.tools.map((t) => t.name);
        const state = triStateForServer(toolNames, draftAllowed);
        const enabledInGroup =
          draftAllowed === null
            ? toolNames.length
            : toolNames.reduce(
                (n, name) => n + (draftAllowed.has(name) ? 1 : 0),
                0,
              );
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
            leading={
              <TriStateCheckbox
                state={state}
                onChange={(next) => toggleServer(toolNames, next)}
              />
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
                    onToggle={(next) => toggleOne(t.name, next)}
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
              className="px-3 py-1.5 rounded-md border border-border/60 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Reset to defaults
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
