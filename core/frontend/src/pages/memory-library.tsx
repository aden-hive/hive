import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Brain,
  Crown,
  Globe,
  Pencil,
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  AlertCircle,
  Loader2,
  History,
  RotateCcw,
} from "lucide-react";
import { SearchInput } from "@/components/SearchInput";
import {
  memoriesApi,
  memoryAuthorLabel,
  memoryDisplayTitle,
  type Memory,
  type MemoryChange,
  type MemoryScope,
  type RetiredMemory,
} from "@/api/memories";
import { useColony } from "@/context/ColonyContext";
import { isQueenDecommissioned, useMe } from "@/lib/me";
import { orderQueens } from "@/lib/colony-registry";
import { QueenSelect } from "@/components/QueenSelect";

/** "2026-03-02" or an ISO time → "Mar 2, 2026"; the input as given when it isn't a date. */
function shortDay(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** "You · confirmed Mar 2, 2026" — whichever parts the memory has. */
function memoryMeta(memory: Memory): string {
  const parts = [memoryAuthorLabel(memory.author), memory.confirmed ? `confirmed ${shortDay(memory.confirmed)}` : null];
  return parts.filter(Boolean).join(" · ");
}

const CHANGE_VERB: Record<MemoryChange["op"], string> = {
  write: "wrote",
  retire: "removed",
  restore: "restored",
};

/** Every change to one memory, newest first; any version can be put back. */
function MemoryHistory({
  path,
  onRestore,
}: {
  path: string;
  onRestore: (n: number) => Promise<void>;
}) {
  const [changes, setChanges] = useState<MemoryChange[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    memoriesApi
      .history(path)
      .then((resp) => !cancelled && setChanges([...resp.changes].reverse()))
      .catch((e) => !cancelled && setError((e as Error)?.message || "Failed to load history"));
    return () => {
      cancelled = true;
    };
  }, [path]);

  const restore = async (n: number) => {
    setRestoring(n);
    setError(null);
    try {
      await onRestore(n);
    } catch (e) {
      setError((e as Error)?.message || "Failed to restore");
    } finally {
      setRestoring(null);
    }
  };

  if (error) {
    return (
      <p className="text-[11px] text-destructive mt-2 flex items-center gap-1">
        <AlertCircle className="w-3 h-3" /> {error}
      </p>
    );
  }
  if (changes === null) {
    return (
      <div className="flex items-center justify-center py-3">
        <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (changes.length === 0) {
    return <p className="text-[11px] text-muted-foreground/70 mt-2">No changes recorded yet.</p>;
  }
  return (
    <ul className="mt-2 flex flex-col gap-1" aria-label="History">
      {changes.map((change, i) => {
        // A retirement shows what was removed; any other change, what it left.
        const text = change.op === "retire" ? change.before : change.after;
        const current = i === 0 && change.op !== "retire";
        return (
          <li key={change.n} className="rounded-md border border-border/40 bg-muted/10">
            <div className="flex items-center gap-2 px-2.5 py-1.5">
              <button
                type="button"
                onClick={() => setOpen((prev) => (prev === change.n ? null : change.n))}
                className="flex-1 min-w-0 text-left text-[11px] text-muted-foreground"
              >
                <span className="text-foreground/80">{shortDay(change.at)}</span>
                {" · "}
                {memoryAuthorLabel(change.author) ?? change.author} {CHANGE_VERB[change.op] ?? change.op}
                {change.reason ? ` — ${change.reason}` : ""}
              </button>
              {current ? (
                <span className="text-[10px] text-muted-foreground/60">current</span>
              ) : (
                text && (
                  <button
                    type="button"
                    onClick={() => restore(change.n)}
                    disabled={restoring !== null}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium text-muted-foreground hover:text-primary hover:bg-primary/10 disabled:opacity-50"
                  >
                    {restoring === change.n ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
                    Restore
                  </button>
                )
              )}
            </div>
            {open === change.n && text && (
              <pre className="px-2.5 pb-2 text-[11px] font-sans text-foreground/80 leading-relaxed whitespace-pre-wrap break-words">
                {text}
              </pre>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Memories removed from this scope, newest first, each restorable. */
function RetiredMemories({
  items,
  onRestore,
}: {
  items: RetiredMemory[];
  onRestore: (item: RetiredMemory) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (items.length === 0) return null;

  const restore = async (item: RetiredMemory) => {
    setRestoring(item.path);
    setError(null);
    try {
      await onRestore(item);
    } catch (e) {
      setError((e as Error)?.message || "Failed to restore");
    } finally {
      setRestoring(null);
    }
  };

  return (
    <div className="mt-6">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground uppercase tracking-wider"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        Removed ({items.length})
      </button>
      {error && (
        <p className="text-[11px] text-destructive mt-2 flex items-center gap-1">
          <AlertCircle className="w-3 h-3" /> {error}
        </p>
      )}
      {open && (
        <ul className="mt-2 flex flex-col gap-1.5">
          {items.map((item) => (
            <li key={item.path} className="flex items-center gap-2 rounded-md border border-dashed border-border/60 px-3 py-2">
              <div className="flex-1 min-w-0">
                <p className="text-[12px] text-foreground/80 truncate">{item.filename}</p>
                <p className="text-[11px] text-muted-foreground/70 truncate">
                  {shortDay(item.at)} · {memoryAuthorLabel(item.author) ?? item.author}
                  {item.reason ? ` — ${item.reason}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => restore(item)}
                disabled={restoring !== null}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-primary hover:bg-primary/10 disabled:opacity-50"
              >
                {restoring === item.path ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
                Restore
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MemoryCard({
  memory,
  expanded,
  onToggle,
  onSave,
  onDelete,
  onRestore,
}: {
  memory: Memory;
  expanded: boolean;
  onToggle: () => void;
  onSave: (content: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onRestore: (n: number) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [draft, setDraft] = useState(memory.content ?? "");
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(memory.content ?? "");
  }, [memory.content]);

  // Collapsed preview: frontmatter description is the canonical one-liner;
  // fall back to a flattened content slice once content is loaded.
  const preview = useMemo(() => {
    if (memory.description?.trim()) return memory.description.trim();
    const body = memory.content ?? "";
    const flat = body.replace(/\s+/g, " ").trim();
    return flat.length > 140 ? `${flat.slice(0, 140)}…` : flat;
  }, [memory.description, memory.content]);

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(draft);
      setEditing(false);
    } catch (e) {
      setError((e as Error)?.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleCancelEdit = () => {
    setDraft(memory.content ?? "");
    setEditing(false);
    setError(null);
  };

  const handleConfirmDelete = async () => {
    setConfirmingDelete(false);
    try {
      await onDelete();
    } catch (e) {
      setError((e as Error)?.message || "Failed to delete");
    }
  };

  const title = memoryDisplayTitle(memory);
  const meta = memoryMeta(memory);
  const contentLoading = expanded && memory.content === undefined;

  return (
    <div
      className={`rounded-lg border bg-card transition-colors ${
        confirmingDelete
          ? "border-destructive/40"
          : expanded
            ? "border-primary/30"
            : "border-border/60 hover:border-border"
      }`}
    >
      {/* Header — clickable to expand */}
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-start gap-2 px-3 py-2.5 text-left"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground/60 flex-shrink-0 mt-0.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/60 flex-shrink-0 mt-0.5" />
        )}
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-medium text-foreground truncate">
            {title}
          </p>
          {!expanded && preview && (
            <p className="text-[11px] text-muted-foreground/80 line-clamp-1 mt-0.5">
              {preview}
            </p>
          )}
          {meta && (
            <p className="text-[10px] text-muted-foreground/60 mt-0.5">{meta}</p>
          )}
        </div>
        <span className="text-[10px] font-mono text-muted-foreground/50 ml-2 mt-0.5 truncate max-w-[140px]">
          {memory.filename}
        </span>
      </button>

      {/* Body */}
      {expanded && (
        <div className="px-3 pb-3 pt-0">
          <div className="border-t border-border/40 mb-2.5" />
          {contentLoading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
            </div>
          ) : editing ? (
            <>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={Math.min(20, Math.max(6, draft.split("\n").length + 1))}
                className="w-full bg-muted/30 border border-border/50 rounded-md px-2.5 py-2 text-xs font-mono text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 resize-y leading-relaxed"
                placeholder="Markdown content…"
                autoFocus
              />
              {error && (
                <p className="text-[11px] text-destructive mt-2 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" /> {error}
                </p>
              )}
              <div className="flex justify-end gap-2 mt-2">
                <button
                  onClick={handleCancelEdit}
                  disabled={saving}
                  className="px-2.5 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving || draft === (memory.content ?? "")}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                  {saving && <Loader2 className="w-3 h-3 animate-spin" />}
                  Save
                </button>
              </div>
            </>
          ) : (
            <>
              <pre className="text-[12px] font-sans text-foreground/90 leading-relaxed whitespace-pre-wrap break-words">
                {memory.content || (
                  <span className="text-muted-foreground/60 italic">
                    Empty memory
                  </span>
                )}
              </pre>
              {confirmingDelete ? (
                <div className="mt-3 flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5">
                  <AlertCircle className="w-3.5 h-3.5 text-destructive flex-shrink-0" />
                  <span className="text-xs text-destructive flex-1">
                    Delete this memory? It can be restored from Removed.
                  </span>
                  <button
                    onClick={() => setConfirmingDelete(false)}
                    className="px-2.5 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleConfirmDelete}
                    className="px-2.5 py-1 rounded-md text-xs font-medium bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors"
                  >
                    Delete
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-end gap-1.5 mt-3">
                  <button
                    onClick={() => setShowHistory((v) => !v)}
                    className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                      showHistory
                        ? "text-primary bg-primary/10"
                        : "text-muted-foreground hover:text-primary hover:bg-primary/10"
                    }`}
                  >
                    <History className="w-3 h-3" />
                    History
                  </button>
                  <button
                    onClick={() => setEditing(true)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
                  >
                    <Pencil className="w-3 h-3" />
                    Edit
                  </button>
                  <button
                    onClick={() => setConfirmingDelete(true)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                  >
                    <Trash2 className="w-3 h-3" />
                    Delete
                  </button>
                </div>
              )}
              {showHistory && (
                // Keyed by the content, so a restore or an edit reloads the list.
                <MemoryHistory key={memory.content ?? ""} path={memory.path} onRestore={onRestore} />
              )}
            </>
          )}
        </div>
      )}
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

type MemoryTab = "global" | "queens";

export default function MemoryLibrary() {
  const { queenProfiles: unsortedQueens } = useColony();
  const { me } = useMe();
  const queenProfiles = useMemo(
    () =>
      orderQueens(unsortedQueens, Object.keys(me?.preferences?.queens ?? {})).filter(
        (q) => !isQueenDecommissioned(me, q.id),
      ),
    [unsortedQueens, me],
  );

  // A queen's profile links here with ?queen=<id>: open on her memories.
  const [searchParams] = useSearchParams();
  const queenParam = searchParams.get("queen");
  const [tab, setTab] = useState<MemoryTab>(queenParam ? "queens" : "global");
  const [selectedQueenId, setSelectedQueenId] = useState<string | null>(queenParam);

  useEffect(() => {
    if (tab !== "queens") return;
    if (queenProfiles.length === 0) {
      if (selectedQueenId) setSelectedQueenId(null);
      return;
    }
    if (!selectedQueenId || !queenProfiles.some((q) => q.id === selectedQueenId)) {
      setSelectedQueenId(queenProfiles[0].id);
    }
  }, [tab, selectedQueenId, queenProfiles]);

  const scope: MemoryScope = tab === "global" ? "global" : "queen";

  // We hold every memory the runtime knows about — the list endpoint
  // doesn't filter by scope, so we slice client-side per tab/queen.
  const [allMemories, setAllMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [retired, setRetired] = useState<RetiredMemory[]>([]);

  const activeQueen = useMemo(
    () => queenProfiles.find((q) => q.id === selectedQueenId) ?? null,
    [queenProfiles, selectedQueenId],
  );

  const refreshList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await memoriesApi.list();
      setAllMemories(resp.memories);
      // The removed list is extra: the page works without it.
      memoriesApi
        .retired()
        .then((r) => setRetired(r.retired))
        .catch(() => setRetired([]));
    } catch (e) {
      setError((e as Error)?.message || "Failed to load memories");
      setAllMemories([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  // Slice the full list down to what the current tab cares about.
  const scopedMemories = useMemo(() => {
    if (scope === "global") {
      return allMemories.filter((m) => m.scope === "global");
    }
    if (!selectedQueenId) return [];
    return allMemories.filter(
      (m) => m.scope === "queen" && m.scope_name === selectedQueenId,
    );
  }, [allMemories, scope, selectedQueenId]);

  const scopedRetired = useMemo(
    () =>
      retired.filter((r) =>
        scope === "global" ? r.scope === "global" : r.scope === "queen" && r.scope_name === selectedQueenId,
      ),
    [retired, scope, selectedQueenId],
  );

  const filtered = useMemo(() => {
    if (!search.trim()) return scopedMemories;
    const q = search.toLowerCase();
    return scopedMemories.filter(
      (m) =>
        memoryDisplayTitle(m).toLowerCase().includes(q) ||
        m.filename.toLowerCase().includes(q) ||
        (m.description ?? "").toLowerCase().includes(q) ||
        (m.content ?? "").toLowerCase().includes(q),
    );
  }, [scopedMemories, search]);

  // Lazy-load full content when a card is expanded for the first time.
  useEffect(() => {
    if (!expandedKey) return;
    const target = allMemories.find((m) => m.path === expandedKey);
    if (!target || target.content !== undefined) return;
    let cancelled = false;
    (async () => {
      try {
        const fresh = await memoriesApi.read(target.path);
        if (cancelled) return;
        setAllMemories((prev) =>
          prev.map((m) =>
            m.path === target.path ? { ...m, ...fresh } : m,
          ),
        );
      } catch (e) {
        if (cancelled) return;
        setError((e as Error)?.message || "Failed to load memory contents");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [expandedKey, allMemories]);

  const handleSave = async (memory: Memory, content: string) => {
    const updated = await memoriesApi.update(memory.path, content);
    setAllMemories((prev) =>
      prev.map((m) => (m.path === memory.path ? { ...m, ...updated } : m)),
    );
  };

  const handleDelete = async (memory: Memory) => {
    await memoriesApi.delete(memory.path);
    setAllMemories((prev) => prev.filter((m) => m.path !== memory.path));
    if (expandedKey === memory.path) setExpandedKey(null);
    memoriesApi
      .retired()
      .then((r) => setRetired(r.retired))
      .catch(() => {});
  };

  const handleRestore = async (path: string, n: number) => {
    const restored = await memoriesApi.restore(path, n);
    setAllMemories((prev) =>
      prev.some((m) => m.path === path)
        ? prev.map((m) => (m.path === path ? { ...m, ...restored } : m))
        : [restored, ...prev],
    );
    setRetired((prev) => prev.filter((r) => r.path !== path));
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      <div className="px-6 py-4 border-b border-border/60">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
              <Brain className="w-5 h-5 text-primary" />
              Memory
            </h2>
            <span className="text-xs text-muted-foreground">
              Long-lived notes your queens reference each turn. Edit or remove them here.
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <TabButton
            active={tab === "global"}
            onClick={() => setTab("global")}
            icon={<Globe className="w-3.5 h-3.5" />}
          >
            Global
          </TabButton>
          <TabButton
            active={tab === "queens"}
            onClick={() => setTab("queens")}
            icon={<Crown className="w-3.5 h-3.5" />}
          >
            Queens
          </TabButton>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="px-6 py-5">
          {tab === "queens" && (
            <div className="mb-4">
              <label className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
                Queen
              </label>
              {queenProfiles.length === 0 ? (
                <p className="text-sm text-muted-foreground">No queens available.</p>
              ) : (
                <QueenSelect
                  queens={queenProfiles}
                  value={selectedQueenId}
                  onChange={setSelectedQueenId}
                  buttonClassName="w-full max-w-[320px]"
                />
              )}
            </div>
          )}

          <div className="max-w-3xl">
            <div className="flex items-center mb-4">
              <SearchInput
                className="flex-1 min-w-[200px] max-w-[360px]"
                value={search}
                onChange={setSearch}
                placeholder="Search memories…"
              />
            </div>

            {error && (
              <div className="mb-4 px-3 py-2 rounded-md border border-destructive/30 bg-destructive/5 text-xs text-destructive flex items-center gap-2">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span className="flex-1">{error}</span>
              </div>
            )}

            {loading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
              </div>
            ) : filtered.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border/60 bg-muted/10 px-6 py-12 text-center">
                <Brain className="w-8 h-8 text-muted-foreground/30 mb-3 mx-auto" />
                <p className="text-sm text-foreground/80">
                  {search.trim()
                    ? "No memories match your search."
                    : tab === "global"
                      ? "No global memories yet."
                      : activeQueen
                        ? `${activeQueen.name} hasn't recorded any memories yet.`
                        : "Pick a queen to view their memories."}
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {filtered.map((m) => (
                  <MemoryCard
                    key={m.path}
                    memory={m}
                    expanded={expandedKey === m.path}
                    onToggle={() =>
                      setExpandedKey((prev) =>
                        prev === m.path ? null : m.path,
                      )
                    }
                    onSave={(content) => handleSave(m, content)}
                    onDelete={() => handleDelete(m)}
                    onRestore={(n) => handleRestore(m.path, n)}
                  />
                ))}
              </div>
            )}

            {!loading && !search.trim() && (
              <RetiredMemories items={scopedRetired} onRestore={(item) => handleRestore(item.path, item.n)} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
