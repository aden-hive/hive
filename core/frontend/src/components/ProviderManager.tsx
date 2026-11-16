import { useCallback, useEffect, useState } from "react";
import { AlertCircle, BookmarkPlus, KeyRound, Loader2, Pencil, Plus, X } from "lucide-react";
import { configApi, type LlmRole, type LlmSection } from "@/api/config";
import { ApiError } from "@/api/client";

/**
 * Verbatim editor over configuration.json's provider slots
 * (llm / worker_llm / vision_fallback / judge). There is deliberately NO parallel
 * representation: read = the section as stored, save = the section as
 * typed (unknown keys included). The file and this UI cannot diverge
 * because there is nothing in between.
 *
 * The provider library ("provider_library" in the same file) is a set of
 * NAMED sections in the identical verbatim shape, shown as saved setups.
 * Applying one COPIES it into a slot through the same validated write path —
 * the slots stay the single source of truth for what the runtime uses.
 *
 * The slots, the saved setups and the JSON editor render in different places
 * on the Models page, so they share one state from useProviderConfig.
 */

const ROLES: LlmRole[] = ["llm", "worker_llm", "vision_fallback", "judge"];
const ROLE_TITLE: Record<LlmRole, string> = {
  llm: "LLM (main)",
  worker_llm: "Worker",
  vision_fallback: "Vision fallback",
  judge: "Judge",
};
const ROLE_HINT: Record<LlmRole, string> = {
  llm: "Powers every queen session. Always set.",
  worker_llm: "Colony workers. Cleared → workers use the main LLM.",
  vision_fallback: "Captions images when the main model has no vision.",
  judge: "Not a chat model: checks queen turns for Developer → Stall check.",
};

const TEMPLATE: LlmSection = {
  provider: "openai",
  model: "model-id",
  api_base: "https://api.example.com/v1",
  api_key: "sk-...",
  max_tokens: 8196,
  max_context_tokens: 100000,
};

// The judge speaks a judging protocol, not chat; fill in your judge vendor's values.
const JUDGE_TEMPLATE: LlmSection = {
  protocol: "typesafe",
  api_base: "https://judge.example.com/v1",
  model: "judge-model-id",
  api_key: "...",
  threshold: 0.5,
};

function keyLabel(s: LlmSection): string {
  const key = typeof s.api_key === "string" ? s.api_key : "";
  if (key) return "key ****" + key.slice(-4);
  if (s.api_key_env_var) return `key from $${s.api_key_env_var}`;
  return "no key";
}

function sectionSummary(s: LlmSection): string {
  return [s.model, s.api_base, keyLabel(s)].filter(Boolean).join(" · ");
}

/** A judge's setup names the judging protocol it speaks (framework/server/judge.py); a chat model's has none. */
export function isJudgeSetup(s: LlmSection): boolean {
  return typeof s.protocol === "string" && s.protocol !== "";
}

// Saved setups sit beside the page's other model sources, which say a key is kept but never show any of it.
function keyNote(s: LlmSection): string | null {
  if (typeof s.api_key === "string" && s.api_key) return "key saved";
  if (s.api_key_env_var) return `key from $${s.api_key_env_var}`;
  return null;
}

type Editor =
  | { kind: "role"; role: LlmRole; text: string }
  | { kind: "library"; name: string; originalName: string | null; text: string };

export type ProviderConfig = ReturnType<typeof useProviderConfig>;

/** Slots and saved setups as configuration.json holds them; `onSlotChanged` runs after a slot is written. */
export function useProviderConfig(onSlotChanged: () => Promise<void>) {
  const [sections, setSections] = useState<Record<LlmRole, LlmSection | null>>({
    llm: null,
    worker_llm: null,
    vision_fallback: null,
    judge: null,
  });
  const [library, setLibrary] = useState<Record<string, LlmSection>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [slotError, setSlotError] = useState<string | null>(null);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [busyRole, setBusyRole] = useState<LlmRole | null>(null);
  const [busyEntry, setBusyEntry] = useState<string | null>(null);
  // Editor over ONE slot's or ONE library entry's JSON. null = closed.
  const [editor, setEditor] = useState<Editor | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [secs, lib] = await Promise.all([
        configApi.getLlmSections(),
        configApi.getProviderLibrary(),
      ]);
      setSections(secs);
      setLibrary(lib.library);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Failed to load config");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  // configuration.json is hand-editable — mirror out-of-band edits whenever
  // the window regains focus (edit in your editor, switch back, current).
  // Skipped while the JSON editor is open so a refetch can't clobber text.
  useEffect(() => {
    const onFocus = () => {
      if (!editor) void load();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load, editor]);

  const openEditor = (role: LlmRole) => {
    const current = sections[role];
    // A fresh slot starts from the main LLM section (same endpoint is the
    // common case) or the generic template.
    const base = current ?? (role === "judge" ? JUDGE_TEMPLATE : (sections.llm ?? TEMPLATE));
    setEditorError(null);
    setEditor({ kind: "role", role, text: JSON.stringify(base, null, 2) });
  };

  const openLibraryEditor = (name: string | null, seed: LlmSection) => {
    setEditorError(null);
    setEditor({
      kind: "library",
      name: name ?? "",
      originalName: name,
      text: JSON.stringify(seed, null, 2),
    });
  };

  const handleSave = async () => {
    if (!editor || saving) return;
    setEditorError(null);
    let parsed: LlmSection;
    try {
      parsed = JSON.parse(editor.text);
    } catch (e) {
      setEditorError(`Invalid JSON: ${e instanceof Error ? e.message : e}`);
      return;
    }
    if (editor.kind === "library" && !editor.name.trim()) {
      setEditorError("A name is required");
      return;
    }
    setSaving(true);
    try {
      if (editor.kind === "role") {
        // Backend validates structure and health-checks api_key against
        // api_base before committing; a bad key is rejected right here.
        const r = await configApi.putLlmSection(editor.role, parsed);
        setSections((prev) => ({ ...prev, [editor.role]: r.section }));
        setEditor(null);
        await onSlotChanged();
      } else {
        const name = editor.name.trim();
        const r = await configApi.putProviderLibraryEntry(name, parsed);
        // Rename = save under the new name, then drop the old entry.
        if (editor.originalName && editor.originalName !== name) {
          await configApi.putProviderLibraryEntry(editor.originalName, null);
        }
        setLibrary((prev) => {
          const next = { ...prev };
          if (editor.originalName && editor.originalName !== name) {
            delete next[editor.originalName];
          }
          next[name] = r.section as LlmSection;
          return next;
        });
        setEditor(null);
      }
    } catch (e) {
      setEditorError(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async (role: LlmRole) => {
    if (role === "llm") return; // runtime always needs a main model
    setBusyRole(role);
    setSlotError(null);
    try {
      await configApi.putLlmSection(role, null);
      setSections((prev) => ({ ...prev, [role]: null }));
      await onSlotChanged();
    } catch (e) {
      setSlotError(e instanceof ApiError ? e.message : "Clear failed");
    } finally {
      setBusyRole(null);
    }
  };

  // Throws on failure, for callers that show the reason themselves (the model pickers).
  const applySaved = async (name: string, role: LlmRole) => {
    const r = await configApi.applyProviderLibraryEntry(name, role);
    setSections((prev) => ({ ...prev, [role]: r.section }));
    await onSlotChanged();
  };

  const handleApply = async (name: string, role: LlmRole) => {
    setBusyRole(role);
    setSlotError(null);
    try {
      await applySaved(name, role);
    } catch (e) {
      setSlotError(e instanceof ApiError ? e.message : `Failed to apply "${name}"`);
    } finally {
      setBusyRole(null);
    }
  };

  const handleDeleteEntry = async (name: string) => {
    setBusyEntry(name);
    setLibraryError(null);
    try {
      await configApi.putProviderLibraryEntry(name, null);
      setLibrary((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    } catch (e) {
      setLibraryError(e instanceof ApiError ? e.message : "Delete failed");
    } finally {
      setBusyEntry(null);
    }
  };

  return {
    reload: load,
    sections,
    library,
    libraryNames: Object.keys(library).sort(),
    loading,
    loadError,
    slotError,
    libraryError,
    busyRole,
    busyEntry,
    editor,
    setEditor,
    editorError,
    saving,
    openEditor,
    openLibraryEditor,
    handleSave,
    handleClear,
    applySaved,
    handleApply,
    handleDeleteEntry,
  };
}

function ErrorText({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="mt-2 text-[11px] text-red-500 inline-flex items-start gap-1">
      <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" /> {message}
    </p>
  );
}

function LoadingText() {
  return (
    <p className="mt-2 text-[11px] text-muted-foreground inline-flex items-center gap-1">
      <Loader2 className="w-3 h-3 animate-spin" /> Loading…
    </p>
  );
}

/** Each slot as configuration.json writes it, with "Use saved…" to copy a saved setup in. */
export function ProviderSlots({ cfg }: { cfg: ProviderConfig }) {
  const { sections, libraryNames, busyRole, reload } = cfg;
  // The page's pickers write the same slots, so read them afresh each time this opens.
  useEffect(() => {
    void reload();
  }, [reload]);
  return (
    <div className="rounded-lg border border-border/60 bg-card p-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[13px] font-semibold text-foreground">Provider Slots</span>
        <span className="text-[10.5px] text-muted-foreground">
          configuration.json, verbatim — what you see is exactly what the file says
        </span>
      </div>

      {cfg.loading ? (
        <LoadingText />
      ) : (
        <div className="mt-2 flex flex-col gap-1.5">
          {ROLES.map((role) => {
            const s = sections[role];
            const busy = busyRole === role;
            return (
              <div
                key={role}
                className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 ${
                  s ? "border-border/60" : "border-dashed border-border/60"
                }`}
              >
                <div className="flex-1 min-w-0">
                  <span className="text-xs font-semibold text-foreground">
                    {ROLE_TITLE[role]}
                  </span>
                  {s ? (
                    <div className="text-[10.5px] text-muted-foreground truncate">
                      {sectionSummary(s)}
                    </div>
                  ) : (
                    <div className="text-[10.5px] text-muted-foreground/70">
                      Not configured — {ROLE_HINT[role]}
                    </div>
                  )}
                </div>
                <div className="ml-auto flex items-center gap-1.5 flex-shrink-0">
                  {busy && <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />}
                  {libraryNames.length > 0 && (
                    <select
                      value=""
                      disabled={busy}
                      onChange={(e) => {
                        if (e.target.value) void cfg.handleApply(e.target.value, role);
                      }}
                      title="Load a saved setup into this slot"
                      className="text-[10.5px] rounded-md border border-border/60 bg-background text-muted-foreground px-1 py-0.5 outline-none focus:border-primary/50 max-w-[7rem]"
                    >
                      <option value="">Use saved…</option>
                      {libraryNames.map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  )}
                  {s ? (
                    <>
                      <button
                        onClick={() => cfg.openLibraryEditor(null, s)}
                        title="Save this slot's config as a saved setup"
                        className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
                      >
                        <BookmarkPlus className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => cfg.openEditor(role)}
                        title={`Edit the ${role} section as JSON`}
                        className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                      {role !== "llm" && (
                        <button
                          onClick={() => void cfg.handleClear(role)}
                          disabled={busy}
                          title={`Clear ${role} — ${ROLE_HINT[role]}`}
                          className="p-1 rounded text-muted-foreground hover:text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      )}
                    </>
                  ) : (
                    <button
                      onClick={() => cfg.openEditor(role)}
                      className="text-[11px] font-medium px-2 py-1 rounded-md border border-primary/30 text-primary hover:bg-primary/10 transition-colors inline-flex items-center gap-1"
                    >
                      <Plus className="w-3 h-3" /> Configure
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ErrorText message={cfg.loadError ?? cfg.slotError} />
    </div>
  );
}

/** The provider library as cards like the page's endpoints and keys: name, model, address, and whether a key is kept. */
export function SavedSetups({ cfg }: { cfg: ProviderConfig }) {
  const { library, libraryNames, busyEntry } = cfg;
  if (cfg.loading) return <LoadingText />;
  return (
    <div className="grid gap-2">
      {libraryNames.map((name) => {
        const s = library[name];
        const busy = busyEntry === name;
        const key = keyNote(s);
        return (
          <div key={name} className="rounded-lg border border-border/60 bg-card px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium truncate">{name}</span>
              {key && (
                <span className="text-[11px] text-muted-foreground inline-flex items-center gap-1 shrink-0">
                  <KeyRound className="w-3 h-3" /> {key}
                </span>
              )}
              <div className="ml-auto flex items-center gap-1 shrink-0">
                <button
                  type="button"
                  onClick={() => cfg.openLibraryEditor(name, s)}
                  title={`Edit saved setup "${name}"`}
                  aria-label={`Edit ${name}`}
                  className="p-1 text-muted-foreground hover:text-foreground"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => void cfg.handleDeleteEntry(name)}
                  disabled={busy}
                  title={`Delete saved setup "${name}" (slots already using it keep their copy)`}
                  aria-label={`Delete ${name}`}
                  className="p-1 text-muted-foreground hover:text-destructive disabled:opacity-50"
                >
                  {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <X className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
            <div className="mt-0.5 text-xs text-muted-foreground break-all">
              {[s.model, s.api_base].filter(Boolean).join(" · ")}
            </div>
          </div>
        );
      })}
      <button
        type="button"
        onClick={() => cfg.openLibraryEditor(null, cfg.sections.llm ?? TEMPLATE)}
        className="flex items-center gap-1.5 rounded-lg border border-dashed border-border/80 px-3 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:border-primary/40"
      >
        <Plus className="w-3.5 h-3.5" /> Add a saved setup
      </button>
      <ErrorText message={cfg.loadError ?? cfg.libraryError} />
    </div>
  );
}

/** The JSON editor over one slot or one saved setup; open while `cfg.editor` is set. */
export function ProviderConfigEditor({ cfg }: { cfg: ProviderConfig }) {
  const { editor, setEditor, editorError, saving } = cfg;
  if (!editor) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onMouseDown={() => setEditor(null)}
    >
      <div
        className="w-[34rem] max-w-[94vw] rounded-xl border border-border/60 bg-card p-4 shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="text-sm font-semibold text-foreground mb-0.5">
          {editor.kind === "role"
            ? ROLE_TITLE[editor.role]
            : editor.originalName
              ? `Saved setup: ${editor.originalName}`
              : "New saved setup"}
        </div>
        <p className="text-[10.5px] text-muted-foreground mb-2">
          {editor.kind === "role"
            ? `Saved verbatim to configuration.json » ${editor.role}. The api_key is health-checked against api_base before committing.`
            : "Saved verbatim to configuration.json » provider_library. The key is health-checked when the config is applied to a slot."}
        </p>
        {editor.kind === "library" && (
          <input
            value={editor.name}
            onChange={(e) => setEditor({ ...editor, name: e.target.value })}
            placeholder="Name (e.g. deepseek-prod, local-vllm)"
            spellCheck={false}
            className="w-full mb-2 rounded-md border border-border/60 bg-background px-2.5 py-1.5 text-[11.5px] text-foreground outline-none focus:border-primary/50"
          />
        )}
        <textarea
          value={editor.text}
          onChange={(e) => setEditor({ ...editor, text: e.target.value })}
          rows={12}
          spellCheck={false}
          className="w-full rounded-md border border-border/60 bg-background px-2.5 py-2 text-[11.5px] font-mono text-foreground outline-none focus:border-primary/50 resize-y"
        />
        <ErrorText message={editorError} />
        <div className="mt-3 flex items-center justify-end gap-2">
          <button
            onClick={() => setEditor(null)}
            className="text-[11px] font-medium px-2.5 py-1.5 rounded-md border border-border/60 text-muted-foreground hover:text-foreground transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => void cfg.handleSave()}
            disabled={saving}
            className="text-[11px] font-medium px-2.5 py-1.5 rounded-md bg-primary text-primary-foreground disabled:opacity-50 inline-flex items-center gap-1"
          >
            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
