import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Library,
  Crown,
  Network,
  BookOpen,
  Search,
  Plus,
  Upload,
  X,
  Trash2,
  Lock,
  AlertCircle,
  Loader2,
  CheckCircle2,
  Circle,
} from "lucide-react";
import { queensApi } from "@/api/queens";
import { coloniesApi, type ColonySummary } from "@/api/colonies";
import { slugToDisplayName } from "@/lib/colony-registry";
import { ApiError } from "@/api/client";
import {
  skillsApi,
  type AggregatedSkillsResponse,
  type ScopeSkillsResponse,
  type SkillDetailResponse,
  type SkillProvenance,
  type SkillRow,
} from "@/api/skills";

type Tab = "queens" | "colonies" | "catalog";

const PROVENANCE_LABEL: Record<SkillProvenance, string> = {
  framework: "Framework",
  preset: "Preset",
  user_dropped: "User",
  user_ui_created: "User (UI)",
  queen_created: "Queen",
  learned_runtime: "Learned",
  project_dropped: "Colony",
  other: "Other",
};

function ProvenanceBadge({ provenance }: { provenance: SkillProvenance }) {
  const tone =
    provenance === "framework"
      ? "bg-slate-400/10 text-slate-400"
      : provenance === "preset"
        ? "bg-teal-500/10 text-teal-500"
        : provenance === "queen_created"
          ? "bg-amber-500/10 text-amber-500"
          : provenance === "learned_runtime"
            ? "bg-purple-500/10 text-purple-500"
            : "bg-primary/10 text-primary";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${tone}`}>
      {PROVENANCE_LABEL[provenance]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page shell
// ---------------------------------------------------------------------------

export default function SkillsLibrary() {
  const [tab, setTab] = useState<Tab>("queens");

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      <div className="px-6 py-4 border-b border-border/60">
        <div className="flex items-baseline gap-3 mb-3">
          <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
            <Library className="w-5 h-5 text-primary" />
            Skills Library
          </h2>
          <span className="text-xs text-muted-foreground">
            Curate which skills each queen and colony exposes, upload your own, or browse the full catalog.
          </span>
        </div>
        <div className="flex items-center gap-1">
          <TabButton active={tab === "queens"} onClick={() => setTab("queens")} icon={<Crown className="w-3.5 h-3.5" />}>
            Queens
          </TabButton>
          <TabButton active={tab === "colonies"} onClick={() => setTab("colonies")} icon={<Network className="w-3.5 h-3.5" />}>
            Colonies
          </TabButton>
          <TabButton active={tab === "catalog"} onClick={() => setTab("catalog")} icon={<BookOpen className="w-3.5 h-3.5" />}>
            Catalog
          </TabButton>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "queens" && <QueensTab />}
        {tab === "colonies" && <ColoniesTab />}
        {tab === "catalog" && <CatalogTab />}
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
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium ${
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
// Queens tab
// ---------------------------------------------------------------------------

function QueensTab() {
  const [queens, setQueens] = useState<Array<{ id: string; name: string; title: string }> | null>(
    null,
  );
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    queensApi
      .list()
      .then((r) => {
        setQueens(r.queens);
        if (r.queens.length > 0) setSelected((prev) => prev ?? r.queens[0].id);
      })
      .catch((e: Error) => setError(e.message || "Failed to load queens"));
  }, []);

  if (error) return <ErrorBlock message={error} />;
  if (queens === null) return <LoadingBlock label="Loading queens…" />;
  if (queens.length === 0) return <EmptyBlock label="No queens yet." />;

  return (
    <div className="flex h-full">
      <SidePicker>
        {queens.map((q) => (
          <PickerItem
            key={q.id}
            active={selected === q.id}
            onClick={() => setSelected(q.id)}
            primary={q.name}
            secondary={q.title}
          />
        ))}
      </SidePicker>
      <div className="flex-1 overflow-y-auto px-6 py-5 min-w-0">
        {selected ? (
          <>
            {(() => {
              const q = queens.find((x) => x.id === selected);
              return q ? (
                <div className="mb-4 pb-3 border-b border-border/40">
                  <h3 className="text-base font-semibold text-foreground">{q.name}</h3>
                  <p className="text-xs text-muted-foreground mt-0.5">{q.title}</p>
                </div>
              ) : null;
            })()}
            <SkillsPerScopeSection scopeKind="queen" targetId={selected} />
          </>
        ) : (
          <EmptyBlock label="Pick a queen to edit her skill catalog." />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Colonies tab
// ---------------------------------------------------------------------------

function ColoniesTab() {
  const [colonies, setColonies] = useState<ColonySummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    coloniesApi
      .list()
      .then((r) => {
        setColonies(r.colonies);
        if (r.colonies.length > 0) setSelected((prev) => prev ?? r.colonies[0].name);
      })
      .catch((e: Error) => setError(e.message || "Failed to load colonies"));
  }, []);

  const sorted = useMemo(() => {
    if (!colonies) return null;
    return [...colonies].sort((a, b) => a.name.localeCompare(b.name));
  }, [colonies]);

  if (error) return <ErrorBlock message={error} />;
  if (sorted === null) return <LoadingBlock label="Loading colonies…" />;
  if (sorted.length === 0)
    return (
      <EmptyBlock label="No colonies yet. Ask a queen to incubate one and its skills will show up here." />
    );

  return (
    <div className="flex h-full">
      <SidePicker>
        {sorted.map((c) => (
          <PickerItem
            key={c.name}
            active={selected === c.name}
            onClick={() => setSelected(c.name)}
            primary={slugToDisplayName(c.name)}
            secondary={c.queen_name ? `@${c.queen_name}` : undefined}
            tertiary={c.name}
          />
        ))}
      </SidePicker>
      <div className="flex-1 overflow-y-auto px-6 py-5 min-w-0">
        {selected ? (
          <>
            <div className="mb-4 pb-3 border-b border-border/40">
              <h3 className="text-base font-semibold text-foreground">
                {slugToDisplayName(selected)}
              </h3>
              <p className="text-[11px] text-muted-foreground font-mono mt-0.5">{selected}</p>
            </div>
            <SkillsPerScopeSection scopeKind="colony" targetId={selected} />
          </>
        ) : (
          <EmptyBlock label="Pick a colony to edit its skill catalog." />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-scope section (shared body for Queens + Colonies tabs)
// ---------------------------------------------------------------------------

function SkillsPerScopeSection({
  scopeKind,
  targetId,
}: {
  scopeKind: "queen" | "colony";
  targetId: string;
}) {
  const [resp, setResp] = useState<ScopeSkillsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [detailName, setDetailName] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r =
        scopeKind === "queen"
          ? await skillsApi.listForQueen(targetId)
          : await skillsApi.listForColony(targetId);
      setResp(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    } finally {
      setLoading(false);
    }
  }, [scopeKind, targetId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const rows = resp?.skills ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) => r.name.toLowerCase().includes(q) || r.description.toLowerCase().includes(q),
    );
  }, [rows, search]);

  const toggle = async (row: SkillRow) => {
    try {
      await skillsApi.patch(scopeKind, targetId, row.name, { enabled: !row.enabled });
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    }
  };

  const remove = async (row: SkillRow) => {
    if (!window.confirm(`Delete skill '${row.name}'? This removes its files.`)) return;
    try {
      await skillsApi.remove(scopeKind, targetId, row.name);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    }
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 min-w-[200px] max-w-[320px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or description"
            className="w-full pl-9 pr-3 py-1.5 rounded-md border border-border/60 bg-muted/30 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
          />
        </div>
        <div className="flex-1" />
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary/10 text-primary text-sm font-medium hover:bg-primary/20"
        >
          <Plus className="w-3.5 h-3.5" /> New Skill
        </button>
      </div>

      {resp?.inherited_from_queen?.length ? (
        <div className="mb-3 text-xs text-muted-foreground">
          Inherited from queen{resp.queen_id ? ` (${resp.queen_id})` : ""}:{" "}
          {resp.inherited_from_queen.join(", ")}
        </div>
      ) : null}

      {loading && <LoadingBlock label="Loading skills…" />}
      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-destructive/10 text-destructive text-sm">
          {error}
        </div>
      )}
      {!loading && filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">No skills match your filter.</p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {filtered.map((row) => (
          <SkillCard
            key={row.name}
            row={row}
            onToggle={() => toggle(row)}
            onOpen={() => setDetailName(row.name)}
            onRemove={row.deletable ? () => remove(row) : undefined}
          />
        ))}
      </div>

      <CreateSkillModal
        open={createOpen}
        scopeKind={scopeKind}
        targetId={targetId}
        onClose={() => setCreateOpen(false)}
        onSaved={reload}
      />
      <SkillDetailDrawer skillName={detailName} onClose={() => setDetailName(null)} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Catalog tab
// ---------------------------------------------------------------------------

function CatalogTab() {
  const [resp, setResp] = useState<AggregatedSkillsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [detailName, setDetailName] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setResp(await skillsApi.listAll());
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const rows = resp?.skills ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) => r.name.toLowerCase().includes(q) || r.description.toLowerCase().includes(q),
    );
  }, [rows, search]);

  return (
    <div className="px-6 py-5">
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 min-w-[200px] max-w-[360px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search every skill on this machine"
            className="w-full pl-9 pr-3 py-1.5 rounded-md border border-border/60 bg-muted/30 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
          />
        </div>
        <div className="flex-1" />
        <button
          onClick={() => setUploadOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border/60 bg-card text-sm font-medium text-foreground hover:bg-muted/50"
        >
          <Upload className="w-3.5 h-3.5" /> Upload
        </button>
      </div>

      {loading && <LoadingBlock label="Loading catalog…" />}
      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-destructive/10 text-destructive text-sm">
          {error}
        </div>
      )}
      {!loading && filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">No skills match your filter.</p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((row) => (
          <SkillCard
            key={row.name}
            row={row}
            onOpen={() => setDetailName(row.name)}
            // Catalog view is read-only for toggle/delete — all mutations
            // happen in the scoped tabs.
          />
        ))}
      </div>

      <UploadSkillModal
        open={uploadOpen}
        scopes={{
          queens: resp?.queens ?? [],
          colonies: resp?.colonies ?? [],
        }}
        onClose={() => setUploadOpen(false)}
        onUploaded={reload}
      />
      <SkillDetailDrawer skillName={detailName} onClose={() => setDetailName(null)} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill card (shared across all three tabs)
// ---------------------------------------------------------------------------

function SkillCard({
  row,
  onOpen,
  onToggle,
  onRemove,
}: {
  row: SkillRow;
  onOpen: () => void;
  onToggle?: () => void;
  onRemove?: () => void;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-card p-4 hover:border-primary/30 transition-colors flex flex-col">
      <div className="flex items-start gap-2 mb-1">
        {onToggle ? (
          <button
            onClick={onToggle}
            title={row.enabled ? "Disable" : "Enable"}
            className="flex-shrink-0 mt-0.5"
          >
            {row.enabled ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-500" />
            ) : (
              <Circle className="w-4 h-4 text-muted-foreground" />
            )}
          </button>
        ) : (
          <div className="flex-shrink-0 mt-0.5" aria-hidden>
            {row.enabled ? (
              <CheckCircle2 className="w-4 h-4 text-muted-foreground/40" />
            ) : (
              <Circle className="w-4 h-4 text-muted-foreground/40" />
            )}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <button
            onClick={onOpen}
            className="text-sm font-medium text-foreground text-left hover:text-primary line-clamp-1"
          >
            {row.name}
          </button>
          <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
            <ProvenanceBadge provenance={row.provenance} />
            {row.owner && (
              <span className="text-[10px] text-muted-foreground">@{row.owner.id}</span>
            )}
            {!row.editable && (
              <Lock
                className="w-3 h-3 text-muted-foreground"
                aria-label="Read-only"
              >
                <title>Read-only</title>
              </Lock>
            )}
          </div>
        </div>
        {onRemove && (
          <button
            onClick={onRemove}
            className="p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10"
            title="Delete skill"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      <p className="text-xs text-muted-foreground line-clamp-2 mb-2">{row.description}</p>
      {row.visible_to && (
        <p className="text-[10px] text-muted-foreground mt-auto">
          Visible on {row.visible_to.queens.length} queens, {row.visible_to.colonies.length}{" "}
          colonies
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modals + drawer (shared)
// ---------------------------------------------------------------------------

function CreateSkillModal({
  open,
  scopeKind,
  targetId,
  onClose,
  onSaved,
}: {
  open: boolean;
  scopeKind: "queen" | "colony";
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
      await skillsApi.create(scopeKind, targetId, {
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

  const label = scopeKind === "queen" ? `Queen: ${targetId}` : `Colony: ${targetId}`;

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
    queens: Array<{ id: string; name: string }>;
    colonies: Array<{ name: string; queen_id: string | null }>;
  };
  onClose: () => void;
  onUploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [scopeKind, setScopeKind] = useState<"user" | "queen" | "colony">("user");
  const [targetId, setTargetId] = useState<string>("");
  const [enabled, setEnabled] = useState(true);
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (scopeKind === "queen" && scopes.queens.length > 0 && !targetId) {
      setTargetId(scopes.queens[0].id);
    } else if (scopeKind === "colony" && scopes.colonies.length > 0 && !targetId) {
      setTargetId(scopes.colonies[0].name);
    } else if (scopeKind === "user") {
      setTargetId("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKind]);

  if (!open) return null;

  const submit = async () => {
    if (!file) {
      setError("Pick a .md or .zip file first.");
      return;
    }
    setError(null);
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("scope", scopeKind);
      if (scopeKind !== "user") fd.append("target_id", targetId);
      fd.append("enabled", String(enabled));
      fd.append("replace_existing", String(replaceExisting));
      await skillsApi.upload(fd);
      onUploaded();
      onClose();
      setFile(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.body.error : String(e));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-[520px] p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-lg font-semibold text-foreground">Upload Skill</h3>
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
              File (.md or .zip)
            </label>
            <input
              type="file"
              accept=".md,.zip"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="w-full text-sm text-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary/10 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary hover:file:bg-primary/20"
            />
          </div>
          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">Scope</label>
            <select
              value={scopeKind}
              onChange={(e) => setScopeKind(e.target.value as typeof scopeKind)}
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
            >
              <option value="user">User library (available to all queens)</option>
              <option value="queen">Queen</option>
              <option value="colony">Colony</option>
            </select>
          </div>
          {scopeKind === "queen" && (
            <div>
              <label className="text-sm font-medium text-foreground mb-1.5 block">Queen</label>
              <select
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
                className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
              >
                {scopes.queens.map((q) => (
                  <option key={q.id} value={q.id}>
                    {q.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {scopeKind === "colony" && (
            <div>
              <label className="text-sm font-medium text-foreground mb-1.5 block">Colony</label>
              <select
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
                className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
              >
                {scopes.colonies.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name} {c.queen_id ? `(${c.queen_id})` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              Enable immediately
            </label>
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={replaceExisting}
                onChange={(e) => setReplaceExisting(e.target.checked)}
              />
              Replace if exists
            </label>
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
              disabled={uploading || !file}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              {uploading ? "Uploading…" : "Upload"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function SkillDetailDrawer({
  skillName,
  onClose,
}: {
  skillName: string | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<SkillDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!skillName) return;
    setLoading(true);
    skillsApi
      .getDetail(skillName)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [skillName]);

  if (!skillName) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative w-full max-w-[640px] h-full bg-card border-l border-border/60 overflow-y-auto p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-foreground">{skillName}</h3>
            {detail && (
              <p className="text-xs text-muted-foreground mt-0.5">{detail.description}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {detail && (
          <pre className="whitespace-pre-wrap text-xs font-mono bg-muted/30 border border-border/40 rounded-lg p-4 text-foreground/80">
            {detail.body}
          </pre>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Primitives (match tool-library style)
// ---------------------------------------------------------------------------

function SidePicker({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-[260px] flex-shrink-0 border-r border-border/60 overflow-y-auto py-3 px-2 flex flex-col gap-1">
      {children}
    </div>
  );
}

function PickerItem({
  active,
  onClick,
  primary,
  secondary,
  tertiary,
}: {
  active: boolean;
  onClick: () => void;
  primary: string;
  secondary?: string;
  tertiary?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`text-left px-3 py-2 rounded-md text-sm ${
        active ? "bg-primary/15 text-primary" : "text-foreground hover:bg-muted/30"
      }`}
    >
      <div className="font-medium truncate">{primary}</div>
      {secondary && (
        <div className="text-[11px] text-muted-foreground truncate">{secondary}</div>
      )}
      {tertiary && (
        <div className="text-[10px] text-muted-foreground/60 font-mono truncate">{tertiary}</div>
      )}
    </button>
  );
}

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
