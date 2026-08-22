import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Check, ChevronDown, FolderInput, Loader2, Plus, X } from "lucide-react";
import { configApi, type ExternalSkillSource } from "@/api/config";
import { ApiError } from "@/api/client";

/**
 * Editor over configuration.json's "external_skills" — extra skill roots
 * imported from other agent ecosystems (Claude Code's ~/.claude/skills,
 * Codex's ~/.codex/skills, ...). SKILL.md is a cross-agent standard, so
 * imported directories are scanned by the normal discovery, at user scope
 * below HIVE_HOME/skills (a Hive copy of the same name wins collisions).
 * Verbatim principle: this list IS the config key, nothing in between.
 */
export default function ExternalSkillSources({ onChanged }: { onChanged?: () => void }) {
  const [open, setOpen] = useState(false);
  const [paths, setPaths] = useState<string[]>([]);
  const [resolved, setResolved] = useState<ExternalSkillSource[]>([]);
  const [suggestions, setSuggestions] = useState<ExternalSkillSource[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await configApi.getExternalSkills();
      setPaths(r.paths);
      setResolved(r.resolved);
      setSuggestions(r.suggestions ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load sources");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const save = async (next: string[]) => {
    setSaving(true);
    setError(null);
    try {
      const r = await configApi.setExternalSkills(next);
      setPaths(r.paths);
      setResolved(r.resolved);
      // Adding/removing changes which known dirs remain suggestable.
      setSuggestions((prev) => prev.filter((s) => !r.paths.includes(s.path)));
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const addDraft = async () => {
    const p = draft.trim();
    if (!p || paths.includes(p)) return;
    await save([...paths, p]);
    setDraft("");
  };

  const totalSkills = resolved.reduce((n, r) => n + (r.skills || 0), 0);

  return (
    <div className="mb-4 rounded-lg border border-border/60 bg-card/60">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        <FolderInput className="w-3.5 h-3.5 text-primary flex-shrink-0" />
        <span className="text-xs font-medium text-foreground">External skill sources</span>
        <span className="text-[10.5px] text-muted-foreground">
          {loading
            ? "loading…"
            : paths.length === 0
              ? "none — import skills from Claude Code, Codex, …"
              : `${paths.length} ${paths.length === 1 ? "dir" : "dirs"} · ${totalSkills} skills`}
        </span>
        <ChevronDown
          className={`w-3.5 h-3.5 text-muted-foreground ml-auto transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="px-3 pb-3 flex flex-col gap-1.5">
          {resolved.map((r, i) => (
            <div
              key={`${r.path}-${i}`}
              className="flex items-center gap-2 rounded-md border border-border/60 bg-background px-2.5 py-1.5"
            >
              <div className="flex-1 min-w-0">
                <div className="text-[11.5px] font-mono text-foreground truncate">{r.path}</div>
                <div className="text-[10px] text-muted-foreground truncate">
                  {r.exists ? (
                    <span className="inline-flex items-center gap-1">
                      <Check className="w-2.5 h-2.5 text-emerald-500" />
                      {r.skills} {r.skills === 1 ? "skill" : "skills"} found
                      {r.resolved ? ` · ${r.resolved}` : ""}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-amber-500">
                      <AlertCircle className="w-2.5 h-2.5" />
                      {r.error || "directory not found"}
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => void save(paths.filter((p) => p !== r.path))}
                disabled={saving}
                title="Remove this source"
                className="p-1 rounded text-muted-foreground hover:text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-50 flex-shrink-0"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}

          <form
            className="flex items-center gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              void addDraft();
            }}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={"Add a directory, e.g. ~/.claude/skills or ~/.codex/skills"}
              className="flex-1 min-w-0 rounded-md border border-border/60 bg-background px-2.5 py-1.5 text-[11.5px] font-mono text-foreground outline-none focus:border-primary/50"
            />
            <button
              type="submit"
              disabled={!draft.trim() || saving}
              className="text-[11px] font-medium px-2.5 py-1.5 rounded-md border border-primary/30 text-primary hover:bg-primary/10 transition-colors disabled:opacity-50 inline-flex items-center gap-1"
            >
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
              Add
            </button>
          </form>

          {suggestions.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[10px] text-muted-foreground">Detected:</span>
              {suggestions.map((s) => (
                <button
                  key={s.path}
                  onClick={() => void save([...paths, s.path])}
                  disabled={saving}
                  title={s.resolved}
                  className="text-[10.5px] font-mono px-2 py-0.5 rounded-full border border-primary/30 text-primary hover:bg-primary/10 transition-colors disabled:opacity-50 inline-flex items-center gap-1"
                >
                  <Plus className="w-2.5 h-2.5" />
                  {s.path} · {s.skills}
                </button>
              ))}
            </div>
          )}

          {error && (
            <p className="text-[11px] text-red-500 inline-flex items-start gap-1">
              <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" /> {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
