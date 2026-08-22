import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import ExternalSkillSources from "@/components/ExternalSkillSources";
import { useSearchParams } from "react-router-dom";
import {
  Library,
  BookOpen,
  Plus,
  Upload,
  X,
  Trash2,
  Lock,
  AlertCircle,
  Loader2,
  Wrench,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  Pencil,
  Globe,
  FileText,
  UploadCloud,
} from "lucide-react";
import type { Components } from "react-markdown";
import ToolLibrary from "./tool-library";
import MarkdownContent from "@/components/MarkdownContent";
import { BROWSER_EXT_STORE_URL } from "@/components/BrowserStatusBadge";
import { SearchInput } from "@/components/SearchInput";
import { Switch } from "@/components/Switch";
import { QueenSelect } from "@/components/QueenSelect";
import { cn } from "@/lib/utils";
import { queensApi } from "@/api/queens";
import { orderQueens } from "@/lib/colony-registry";
import { ApiError } from "@/api/client";
import { isQueenDecommissioned, useMe } from "@/lib/me";
import {
  skillsApi,
  type AggregatedSkillsResponse,
  type SkillDetailResponse,
  type SkillRow,
} from "@/api/skills";

type Tab = "skills" | "mcp";

// System skills that drive the browser via the Hive browser bridge (the
// `browser_*` tool family). Determined by a one-time scan of the default skills
// for `browser_*` references — labeled on the frontend only, no backend field.
// Match strips a leading `hive.` so it works whether names carry the prefix.
const BROWSER_SKILL_SLUGS = new Set([
  "browser-automation",
  "instagram-automation",
  "x-com-automation",
  "linkedin-core",
  "linkedin-discovery",
  "linkedin-messaging",
  "linkedin-connect",
  "linkedin-connection-outbound",
  "linkedin-sales-navigator",
  "slack-notifications-setup",
  "telegram-notifications-setup",
  "worker-delegation",
]);

function usesBrowser(skillName: string): boolean {
  return BROWSER_SKILL_SLUGS.has(skillName.replace(/^hive\./, "").toLowerCase());
}

function BrowserBadge() {
  return (
    <button
      type="button"
      onClick={(e) => {
        // Don't let the click bubble to the card (which opens the drawer).
        e.stopPropagation();
        window.open(BROWSER_EXT_STORE_URL, "_blank", "noopener");
      }}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-500/10 text-sky-500 hover:bg-sky-500/20"
      title="Controls the browser via the Hive browser bridge — click to connect"
    >
      <Globe className="w-3 h-3" /> Browser
    </button>
  );
}

// ---------------------------------------------------------------------------
// Page shell
// ---------------------------------------------------------------------------

export default function SkillsLibrary() {
  const [searchParams] = useSearchParams();
  // Deep-link target, e.g. from the queen profile panel's "Configure skills"
  // link: /skills-library?queen=<id> opens the Skills page with that queen
  // already selected as the configuration context.
  const initialQueenId = searchParams.get("queen");
  // ?tab=mcp opens the (demoted, advanced) "MCP Tools" tab directly — e.g.
  // from a queen's "Configure tools" deep link, which also carries ?queen=<id>.
  const tabParam = searchParams.get("tab");
  const [tab, setTab] = useState<Tab>(tabParam === "mcp" ? "mcp" : "skills");

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      <div className="px-6 py-4 border-b border-border/60">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
              <Library className="w-5 h-5 text-primary" />
              Skills
            </h2>
            <span className="text-xs text-muted-foreground">
              Browse every skill; pick a queen to configure her kit.
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <TabButton active={tab === "skills"} onClick={() => setTab("skills")} icon={<BookOpen className="w-3.5 h-3.5" />}>
            Skills
          </TabButton>
          <TabButton active={tab === "mcp"} onClick={() => setTab("mcp")} icon={<Wrench className="w-3.5 h-3.5" />}>
            MCP Tools
          </TabButton>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "skills" && <SkillsCatalog initialQueenId={initialQueenId} />}
        {tab === "mcp" && <ToolLibrary embedded />}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium ${
        active
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:text-foreground hover:bg-muted/30"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}


// ---------------------------------------------------------------------------
// Unified skills catalog (browse + per-queen config)
// ---------------------------------------------------------------------------

function SkillsCatalog({ initialQueenId }: { initialQueenId?: string | null }) {
  const { me } = useMe();
  const [queens, setQueens] = useState<Array<{ id: string; name: string; title: string }> | null>(
    null,
  );
  const [queensError, setQueensError] = useState<string | null>(null);
  const [context, setContext] = useState<string | null>(null);
  const [initApplied, setInitApplied] = useState(false);

  const [agg, setAgg] = useState<AggregatedSkillsResponse | null>(null);
  const [queenRows, setQueenRows] = useState<SkillRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"in" | "out">("in");
  const [createOpen, setCreateOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [detailName, setDetailName] = useState<string | null>(null);

  const visibleQueens = useMemo(
    () => (queens ?? []).filter((q) => !isQueenDecommissioned(me, q.id)),
    [queens, me],
  );

  // Load the queen list once for the context picker.
  useEffect(() => {
    queensApi
      .list()
      .then((r) => setQueens(orderQueens(r.queens, Object.keys(me?.preferences?.queens ?? {}))))
      .catch((e: Error) => setQueensError(e.message || "Failed to load queens"));
  }, []);

  // Apply a ?queen deep-link once queens are known (once only).
  useEffect(() => {
    if (initApplied || queens === null) return;
    if (initialQueenId && visibleQueens.some((q) => q.id === initialQueenId)) {
      setContext(initialQueenId);
    }
    setInitApplied(true);
  }, [initApplied, initialQueenId, queens, visibleQueens]);

  // If the selected queen is decommissioned out from under us, drop to browse.
  useEffect(() => {
    if (context && queens && !visibleQueens.some((q) => q.id === context)) {
      setContext(null);
    }
  }, [context, queens, visibleQueens]);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // listAll powers browse mode + the picker's per-queen skill counts.
      const a = await skillsApi.listAll();
      setAgg(a);
      if (context) {
        const r = await skillsApi.listForQueen(context);
        setQueenRows(r.skills);
      } else {
        setQueenRows(null);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    } finally {
      setLoading(false);
    }
  }, [context]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Default back to the Active segment when switching context.
  useEffect(() => {
    setFilter("in");
  }, [context]);

  // Per-queen enabled-skill counts, from the aggregated visibility map.
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of agg?.skills ?? []) {
      for (const qid of s.visible_to?.queens ?? []) m.set(qid, (m.get(qid) ?? 0) + 1);
    }
    return m;
  }, [agg]);

  const baseRows: SkillRow[] = context ? queenRows ?? [] : agg?.skills ?? [];
  const filtered = useMemo(() => {
    let list = baseRows;
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (r) => r.name.toLowerCase().includes(q) || r.description.toLowerCase().includes(q),
      );
    }
    if (context) {
      list = list.filter((r) => (filter === "in" ? r.enabled : !r.enabled));
    }
    return list;
  }, [baseRows, search, context, filter]);

  const remove = async (row: SkillRow) => {
    if (!context) return;
    if (!window.confirm(`Delete skill '${row.name}'? This removes its files.`)) return;
    try {
      await skillsApi.remove(context, row.name);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    }
  };

  if (queensError) return <ErrorBlock message={queensError} />;
  if (queens === null) return <LoadingBlock label="Loading…" />;

  return (
    <div className="px-6 py-5">
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <QueenSelect
          queens={visibleQueens}
          value={context}
          onChange={setContext}
          allowAll
          allMeta="browse"
          prefix="Configuring:"
          meta={(id) => `${counts.get(id) ?? 0} skills`}
          buttonClassName="py-1.5 text-xs"
        />
        <SearchInput
          className="flex-1 min-w-[200px] max-w-[360px]"
          value={search}
          onChange={setSearch}
          placeholder="Search skills…"
        />
        <div className="flex-1" />
        {context && (
          <button
            onClick={() => setCreateOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90"
          >
            <Plus className="w-3.5 h-3.5" /> New
          </button>
        )}
        <button
          onClick={() => setUploadOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20"
        >
          <Upload className="w-3.5 h-3.5" /> Upload
        </button>
      </div>

      <ExternalSkillSources onChanged={() => void reload()} />

      {context && (
        <div className="flex items-center gap-1 mb-4">
          {(
            [
              ["in", "Active"],
              ["out", "Inactive"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`px-2.5 py-1 rounded-md text-xs font-medium ${
                filter === key
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/30"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {loading && <LoadingBlock label="Loading skills…" />}
      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-destructive/10 text-destructive text-sm">
          {error}
        </div>
      )}
      {!loading && filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {context ? "No skills match your filter." : "No skills on this machine yet."}
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((row) => (
          <SkillCard
            key={row.name}
            row={row}
            onOpen={() => setDetailName(row.name)}
            onRemove={context && row.deletable ? () => remove(row) : undefined}
            configurable={Boolean(context)}
          />
        ))}
      </div>

      {context && (
        <CreateSkillModal
          open={createOpen}
          targetId={context}
          onClose={() => setCreateOpen(false)}
          onSaved={reload}
        />
      )}
      <UploadSkillModal
        open={uploadOpen}
        scopes={{ queens: visibleQueens }}
        onClose={() => setUploadOpen(false)}
        onUploaded={reload}
      />
      <SkillDetailDrawer
        skillName={detailName}
        onClose={() => setDetailName(null)}
        queenId={context ?? undefined}
        row={context ? (queenRows ?? []).find((r) => r.name === detailName) : undefined}
        onChanged={reload}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill card (shared across all three tabs)
// ---------------------------------------------------------------------------

function SkillCard({
  row,
  onOpen,
  onRemove,
  configurable,
}: {
  row: SkillRow;
  onOpen: () => void;
  onRemove?: () => void;
  // Queen context: reflect this skill's enabled state as a quiet accent. The
  // actual toggle lives in the detail drawer, not on the card.
  configurable?: boolean;
}) {
  const { me } = useMe();
  // Colony-scoped skill config was removed, so only queens matter. Count only
  // active (non-decommissioned) queens the skill is visible on.
  const activeQueenCount = row.visible_to
    ? row.visible_to.queens.filter((q) => !isQueenDecommissioned(me, q)).length
    : 0;
  const active = Boolean(configurable) && row.enabled;
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        // Only when the card itself is focused — not the delete button inside.
        if (e.currentTarget !== e.target) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={`group relative rounded-lg border bg-card p-4 flex flex-col text-left cursor-pointer transition-colors min-h-[136px] hover:border-primary/40 ${
        active ? "border-border/60 border-l-2 border-l-emerald-500/70" : "border-border/60"
      }`}
    >
      <div className="flex items-start gap-2">
        {configurable && (
          <span
            aria-hidden
            title={row.enabled ? "Active" : "Inactive"}
            className={`mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0 ${
              row.enabled ? "bg-emerald-500" : "bg-muted-foreground/30"
            }`}
          />
        )}
        <span
          title={row.name}
          className="min-w-0 flex-1 text-[13px] font-medium text-foreground group-hover:text-primary truncate"
        >
          {row.name}
        </span>
      </div>

      <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
        {usesBrowser(row.name) && <BrowserBadge />}
        {row.owner && (
          <span className="text-[10px] text-muted-foreground">@{row.owner.id}</span>
        )}
        {!row.editable && (
          <Lock className="w-3 h-3 text-muted-foreground/70" aria-label="Read-only">
            <title>Read-only</title>
          </Lock>
        )}
      </div>

      <p className="text-xs text-muted-foreground line-clamp-2 mt-2">{row.description}</p>

      <div className="flex items-center justify-between gap-2 mt-auto pt-2">
        {row.visible_to ? (
          <span className="text-[10px] text-muted-foreground">
            Used by {activeQueenCount} {activeQueenCount === 1 ? "queen" : "queens"}
          </span>
        ) : (
          <span />
        )}
        {onRemove && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            className="p-1 -m-1 rounded-md text-muted-foreground/60 hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
            title="Delete skill"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modals + drawer (shared)
// ---------------------------------------------------------------------------

function CreateSkillModal({
  open,
  targetId,
  onClose,
  onSaved,
}: {
  open: boolean;
  targetId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const submit = async () => {
    setError(null);
    if (!name.trim() || !description.trim() || !body.trim()) {
      setError("Name, description, and body are required.");
      return;
    }
    setSaving(true);
    try {
      await skillsApi.create(targetId, {
        name: name.trim(),
        description: description.trim(),
        body,
        enabled: true,
      });
      setName("");
      setDescription("");
      setBody("");
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    } finally {
      setSaving(false);
    }
  };

  const label = `Queen: ${targetId}`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-[640px] p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-lg font-semibold text-foreground">New Skill</h3>
            <p className="text-xs text-muted-foreground mt-0.5">Scope: {label}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex flex-col gap-4">
          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">
              Name <span className="text-primary">*</span>
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value.toLowerCase())}
              placeholder="e.g. vendor-api-protocol"
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Lowercase letters, digits, hyphens, dots. Max 64 chars.
            </p>
          </div>
          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">
              Description <span className="text-primary">*</span>
            </label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="One-line summary shown in the catalog picker"
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
            />
          </div>
          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">
              Body (SKILL.md content) <span className="text-primary">*</span>
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={14}
              placeholder={"## When to use\n\n...\n\n## Steps\n\n1. ..."}
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm font-mono text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 resize-none"
            />
          </div>
          {error && (
            <div className="px-3 py-2 rounded-lg bg-destructive/10 text-destructive text-xs">
              {error}
            </div>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30"
            >
              Cancel
            </button>
            <button
              onClick={submit}
              disabled={saving}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function UploadSkillModal({
  open,
  scopes,
  onClose,
  onUploaded,
}: {
  open: boolean;
  scopes: {
    queens: Array<{ id: string; name: string; title?: string }>;
  };
  onClose: () => void;
  onUploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [scopeKind, setScopeKind] = useState<"user" | "queen">("user");
  const [targetId, setTargetId] = useState<string>("");
  const [enabled, setEnabled] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set when the server reports a same-name collision (409). We surface a
  // Replace/Keep prompt instead of asking the user to predict it up front.
  const [conflict, setConflict] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (scopeKind === "queen" && scopes.queens.length > 0 && !targetId) {
      setTargetId(scopes.queens[0].id);
    } else if (scopeKind === "user") {
      setTargetId("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKind]);

  if (!open) return null;

  const pickFile = (f: File | null | undefined) => {
    if (!f) return;
    if (!/\.(md|zip)$/i.test(f.name)) {
      setError("Only .md or .zip files are supported.");
      return;
    }
    setError(null);
    setConflict(null);
    setFile(f);
  };

  const submit = async (replace = false) => {
    if (!file) {
      setError("Pick a .md or .zip file first.");
      return;
    }
    setError(null);
    setConflict(null);
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("scope", scopeKind);
      if (scopeKind !== "user") fd.append("target_id", targetId);
      fd.append("enabled", String(enabled));
      fd.append("replace_existing", String(replace));
      await skillsApi.upload(fd);
      onUploaded();
      onClose();
      setFile(null);
    } catch (e) {
      // A same-name collision isn't an error — offer to replace instead.
      if (e instanceof ApiError && e.status === 409) {
        setConflict(e.body.error);
      } else {
        setError(e instanceof ApiError ? e.body.error : String(e));
      }
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-[520px] p-6">
        <div className="flex items-start justify-between mb-5">
          <div>
            <h3 className="text-lg font-semibold text-foreground">Upload a skill</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Add a SKILL.md file or a zipped skill bundle to the library.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex flex-col gap-5">
          {/* Dropzone */}
          <div
            role="button"
            tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                inputRef.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              pickFile(e.dataTransfer.files?.[0]);
            }}
            className={`rounded-xl border border-dashed px-4 py-6 cursor-pointer transition-colors ${
              dragOver
                ? "border-primary bg-primary/5"
                : "border-border/70 hover:border-primary/40 hover:bg-muted/20"
            }`}
          >
            {file ? (
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                  <FileText className="w-4 h-4 text-primary" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground truncate">{file.name}</p>
                  <p className="text-[11px] text-muted-foreground">{formatBytes(file.size)}</p>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setFile(null);
                    if (inputRef.current) inputRef.current.value = "";
                  }}
                  className="p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 flex-shrink-0"
                  title="Remove file"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-1.5 text-center">
                <UploadCloud className="w-6 h-6 text-muted-foreground" />
                <p className="text-sm text-foreground">
                  Drop a file here, or <span className="text-primary font-medium">browse</span>
                </p>
                <p className="text-[11px] text-muted-foreground">SKILL.md or a .zip bundle</p>
              </div>
            )}
            <input
              ref={inputRef}
              type="file"
              accept=".md,.zip"
              onChange={(e) => pickFile(e.target.files?.[0])}
              className="hidden"
            />
          </div>

          {/* Scope */}
          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">Add to</label>
            <div className="inline-flex w-full rounded-lg border border-border/50 bg-muted/20 p-0.5">
              {(
                [
                  ["user", "All queens"],
                  ["queen", "Specific queen"],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setScopeKind(key)}
                  className={`flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                    scopeKind === key
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {scopeKind === "queen" && (
              <div className="mt-2">
                <QueenSelect
                  queens={scopes.queens}
                  value={targetId}
                  onChange={(id) => setTargetId(id ?? "")}
                  buttonClassName="w-full"
                />
              </div>
            )}
          </div>

          {/* Options */}
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm text-foreground">Enable immediately</p>
              <p className="text-[11px] text-muted-foreground">Turn the skill on right after upload.</p>
            </div>
            <Switch checked={enabled} onChange={setEnabled} />
          </div>

          {error && !conflict && (
            <div className="px-3 py-2 rounded-lg bg-destructive/10 text-destructive text-xs">
              {error}
            </div>
          )}

          {conflict ? (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
              <p className="flex items-start gap-1.5 text-xs font-medium text-amber-600 dark:text-amber-400">
                <AlertCircle className="w-3.5 h-3.5 mt-px flex-shrink-0" />
                {conflict}
              </p>
              <p className="text-[11px] text-muted-foreground mt-1">
                Replace the existing skill with this file? This overwrites its contents.
              </p>
              <div className="flex justify-end gap-2 mt-3">
                <button
                  onClick={() => setConflict(null)}
                  disabled={uploading}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30 disabled:opacity-50"
                >
                  Keep existing
                </button>
                <button
                  onClick={() => submit(true)}
                  disabled={uploading}
                  className="px-3 py-1.5 rounded-lg bg-amber-500 text-white text-xs font-medium hover:bg-amber-500/90 disabled:opacity-50"
                >
                  {uploading ? "Replacing…" : "Replace"}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={onClose}
                className="px-4 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30"
              >
                Cancel
              </button>
              <button
                onClick={() => submit(false)}
                disabled={uploading || !file}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {uploading ? "Uploading…" : "Upload"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Human-readable byte size for the upload dropzone.
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Strip a leading YAML frontmatter block so the rendered Markdown view shows
// the operational content, not the `--- name: … ---` header. The queen-scoped
// body endpoint already strips it; the scope-less catalog detail does not.
function stripFrontmatter(text: string): string {
  const match = text.match(/^\s*---\r?\n[\s\S]*?\r?\n---\r?\n?/);
  return match ? text.slice(match[0].length) : text;
}

// Clamp text to two lines with a "… more" toggle that only appears when the
// text actually overflows (measured against the clamped height).
function ClampedText({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [clamped, setClamped] = useState(false);

  // Reset to collapsed whenever the text changes (e.g. a different skill).
  useLayoutEffect(() => {
    setExpanded(false);
  }, [text]);

  // Only measure while collapsed; keep the toggle visible once expanded.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || expanded) return;
    setClamped(el.scrollHeight > el.clientHeight + 1);
  }, [text, expanded]);

  return (
    <div>
      <p ref={ref} className={cn(className, !expanded && "line-clamp-2")}>
        {text}
      </p>
      {(clamped || expanded) && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-0.5 text-[11px] font-medium text-primary/80 hover:text-primary"
        >
          {expanded ? "less" : "… more"}
        </button>
      )}
    </div>
  );
}

// Notion/Slack-style code rendering for the skill body — sizes relative to the
// container (no fixed px clash) and uses a soft chip / bordered block instead of
// the heavy chat-bubble styling. Overrides only `code`/`pre`; everything else
// falls through to MarkdownContent's defaults.
const SKILL_MD_COMPONENTS: Partial<Components> = {
  code: ({ className, children, ...props }) => {
    // A fenced block without an info string (``` with no language) gets no
    // `language-*` class, so also treat multi-line content as a block. Inline
    // code is single-line and gets the chip; block code stays transparent so
    // only the `pre` card shows a background (no patchy per-line fill).
    const isBlock =
      className?.includes("language-") || String(children).includes("\n");
    if (isBlock) {
      return (
        <code className={cn("bg-transparent p-0 font-mono text-[0.85em]", className)} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground/90">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg border border-border/50 bg-muted/40 p-3.5 font-mono text-[0.85em] leading-relaxed text-foreground/80 last:mb-0">
      {children}
    </pre>
  ),
};

function SkillDetailDrawer({
  skillName,
  onClose,
  queenId,
  row,
  onChanged,
}: {
  skillName: string | null;
  onClose: () => void;
  // Queen-scoped mode: when a queenId + row are supplied (drawer opened from a
  // specific queen), the skill can be enabled/disabled and edited for THAT
  // queen's copy. In scope-less catalog mode these are omitted and the drawer
  // stays read-only.
  queenId?: string;
  row?: SkillRow;
  onChanged?: () => void;
}) {
  const [detail, setDetail] = useState<SkillDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftBody, setDraftBody] = useState("");
  const [draftDesc, setDraftDesc] = useState("");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState("");
  const [bodyView, setBodyView] = useState<"markdown" | "raw">("markdown");

  const loadDetail = useCallback(() => {
    if (!skillName) return;
    setLoading(true);
    setError(null);
    setDetail(null);
    // Queen-scoped: fetch THIS queen's copy (frontmatter-stripped body that
    // round-trips through putBody). Scope-less catalog: the aggregated detail.
    const req = queenId
      ? skillsApi.getBody(queenId, skillName)
      : skillsApi.getDetail(skillName);
    req
      .then(setDetail)
      .catch((e) => setError(e instanceof ApiError ? e.body.error : String(e)))
      .finally(() => setLoading(false));
  }, [skillName, queenId]);

  useEffect(() => {
    if (!skillName) return;
    setExpanded(false);
    setCopied(false);
    setEditing(false);
    setRenaming(false);
    loadDetail();
  }, [skillName, loadDetail]);

  if (!skillName) return null;

  const canConfigure = Boolean(queenId && row);
  const canEdit = canConfigure && Boolean(row?.editable);

  const toggleEnabled = async () => {
    if (!queenId || !row) return;
    setBusy(true);
    setError(null);
    try {
      await skillsApi.patch(queenId, row.name, { enabled: !row.enabled });
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => {
    if (!detail) return;
    setDraftBody(detail.body);
    setDraftDesc(detail.description);
    setEditing(true);
  };

  const saveEdit = async () => {
    if (!queenId || !row) return;
    setSaving(true);
    setError(null);
    try {
      await skillsApi.putBody(queenId, row.name, { body: draftBody, description: draftDesc });
      setEditing(false);
      loadDetail();
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    } finally {
      setSaving(false);
    }
  };

  const startRename = () => {
    if (!row) return;
    setNewName(row.name);
    setRenaming(true);
  };

  const submitRename = async () => {
    if (!queenId || !row) return;
    const target = newName.trim();
    if (!target || target === row.name) {
      setRenaming(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await skillsApi.rename(queenId, row.name, target);
      onChanged?.();
      // The selected name no longer exists — close the drawer.
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative w-full max-w-[640px] h-full bg-card border-l border-border/60 overflow-y-auto p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-lg font-semibold text-foreground break-words">{skillName}</h3>
              {usesBrowser(skillName) && <BrowserBadge />}
            </div>
            {detail && !editing && (
              <ClampedText
                text={detail.description}
                className="text-xs text-muted-foreground mt-0.5"
              />
            )}
            {canConfigure && (
              <p className="text-[11px] text-muted-foreground mt-1">
                Configuring for queen <span className="text-foreground/70 font-medium">{queenId}</span>
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 flex-shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {canConfigure && row && (
          <div className="flex items-center gap-3 mb-4">
            <Switch checked={row.enabled} onChange={() => toggleEnabled()} disabled={busy} />
            <span
              className={`text-xs font-medium ${
                row.enabled ? "text-emerald-500" : "text-muted-foreground"
              }`}
            >
              {row.enabled ? "Active" : "Inactive"}
            </span>
            <div className="flex-1" />
            {canEdit && !editing && !renaming && (
              <button
                onClick={startEdit}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium bg-muted/50 text-muted-foreground hover:bg-muted"
              >
                <Pencil className="w-3.5 h-3.5" /> Edit
              </button>
            )}
            {canEdit && !editing && !renaming && (
              <button
                onClick={startRename}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium bg-muted/50 text-muted-foreground hover:bg-muted"
              >
                Rename
              </button>
            )}
            {!row.editable && (
              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <Lock className="w-3 h-3" /> Read-only
              </span>
            )}
          </div>
        )}

        {renaming && row && (
          <div className="mb-4 p-3 rounded-lg border border-border/40 bg-muted/20 space-y-2">
            <label className="block text-[11px] font-medium text-muted-foreground">
              Rename skill
            </label>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") submitRename();
                if (e.key === "Escape") setRenaming(false);
              }}
              placeholder="new-skill-name"
              className="w-full px-2.5 py-1.5 rounded-md bg-card border border-border/40 text-xs text-foreground focus:outline-none focus:border-primary/50"
            />
            <p className="flex items-start gap-1 text-[11px] text-amber-500/90">
              <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
              Renames only this queen's copy. The same skill on other queens keeps
              its current name.
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={submitRename}
                disabled={saving}
                className="px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {saving ? "Renaming…" : "Rename"}
              </button>
              <button
                onClick={() => setRenaming(false)}
                disabled={saving}
                className="px-3 py-1.5 rounded-md bg-muted/50 text-muted-foreground text-xs font-medium hover:bg-muted disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {!loading && error && <ErrorBlock message={error} />}
        {!loading && !error && !detail && (
          <EmptyBlock label="No details available for this skill." />
        )}
        {detail && (
          <div className="space-y-4">
            {!editing && detail.visibility && detail.visibility.length > 0 && (
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                <span>Visibility: {detail.visibility.join(", ")}</span>
              </div>
            )}

            {editing ? (
              <div className="space-y-3">
                <div>
                  <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                    Description
                  </label>
                  <input
                    value={draftDesc}
                    onChange={(e) => setDraftDesc(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-md bg-muted/30 border border-border/40 text-xs text-foreground focus:outline-none focus:border-primary/50"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                    SKILL.md
                  </label>
                  <textarea
                    value={draftBody}
                    onChange={(e) => setDraftBody(e.target.value)}
                    spellCheck={false}
                    className="w-full h-[50vh] px-3 py-2 rounded-md bg-muted/30 border border-border/40 text-xs font-mono text-foreground/90 focus:outline-none focus:border-primary/50 resize-y"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={saveEdit}
                    disabled={saving}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 disabled:opacity-50"
                  >
                    <Check className="w-3.5 h-3.5" /> {saving ? "Saving…" : "Save"}
                  </button>
                  <button
                    onClick={() => setEditing(false)}
                    disabled={saving}
                    className="px-3 py-1.5 rounded-md bg-muted/50 text-muted-foreground text-xs font-medium hover:bg-muted disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-border/40 overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 bg-muted/40 border-b border-border/40">
                  <div className="flex items-center gap-1 rounded-md bg-background/60 p-0.5">
                    <button
                      onClick={() => setBodyView("markdown")}
                      className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                        bodyView === "markdown"
                          ? "bg-card text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      Markdown
                    </button>
                    <button
                      onClick={() => setBodyView("raw")}
                      className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                        bodyView === "raw"
                          ? "bg-card text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      Raw
                    </button>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(detail.body);
                        setCopied(true);
                        window.setTimeout(() => setCopied(false), 1500);
                      }}
                      className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted/60"
                      title="Copy skill body"
                    >
                      {copied ? (
                        <Check className="w-3 h-3 text-emerald-500" />
                      ) : (
                        <Copy className="w-3 h-3" />
                      )}
                      {copied ? "Copied" : "Copy"}
                    </button>
                    <button
                      onClick={() => setExpanded((v) => !v)}
                      className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted/60"
                    >
                      {expanded ? (
                        <ChevronUp className="w-3 h-3" />
                      ) : (
                        <ChevronDown className="w-3 h-3" />
                      )}
                      {expanded ? "Collapse" : "Expand"}
                    </button>
                  </div>
                </div>
                {bodyView === "raw" ? (
                  <pre
                    className={`whitespace-pre-wrap text-xs font-mono p-4 text-foreground/80 overflow-y-auto ${
                      expanded ? "max-h-[80vh]" : "max-h-[52vh]"
                    }`}
                  >
                    {detail.body}
                  </pre>
                ) : (
                  <div
                    className={`p-4 text-[13px] leading-relaxed overflow-y-auto ${
                      expanded ? "max-h-[80vh]" : "max-h-[52vh]"
                    }`}
                  >
                    <MarkdownContent
                      content={stripFrontmatter(detail.body)}
                      components={SKILL_MD_COMPONENTS}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Primitives (match tool-library style)
// ---------------------------------------------------------------------------


function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground px-6 py-6">
      <Loader2 className="w-3 h-3 animate-spin" />
      {label}
    </div>
  );
}

function EmptyBlock({ label }: { label: string }) {
  return (
    <div className="flex items-start gap-2 text-xs text-muted-foreground px-6 py-6">
      <AlertCircle className="w-3.5 h-3.5 mt-0.5" />
      <span>{label}</span>
    </div>
  );
}

function ErrorBlock({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 text-xs text-destructive px-6 py-6">
      <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
      <span>{message}</span>
    </div>
  );
}
