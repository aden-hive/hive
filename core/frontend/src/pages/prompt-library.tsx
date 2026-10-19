import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Copy, Check, MessageCircle, Pencil, Plus, X, Trash2, ChevronDown, Upload, Rocket, Play } from "lucide-react";
import { promptCategories, categoryToQueen, type Prompt } from "@/data/prompts";
import { useCommunityPrompts, type CommunityPrompt } from "@/hooks/use-community-prompts";
import { assetPreviewSrc, type PromptAsset } from "@/data/prompt-assets";
import { SearchInput } from "@/components/SearchInput";
import { promptsApi, type CustomPrompt } from "@/api/prompts";
import { configApi } from "@/api/config";
import { userStorage } from "@/lib/userStorage";
import { useCreateColony } from "@/context/CreateColonyContext";
import {
  inferSkillCapsules,
  embedUseSkillTags,
  stripUseSkillTags,
  parseUseSkillTags,
  deriveDomain,
  type SkillCapsule,
} from "@/data/skill-capsules";
import { SkillCapsuleChip, SkillCapsuleRow } from "@/components/SkillComposer";
import { useSkillIndex } from "@/hooks/use-skill-index";

const PAGE_SIZE = 24;

// True when one of a prompt's inferred skill tags matches the search query —
// lets a click on a Skill Tag in the search dropdown filter the catalog down
// to the recipes that actually use that skill.
function matchesSkill(content: string, query: string): boolean {
  return inferSkillCapsules(content, 5).some(
    (c) => c.label.toLowerCase().includes(query) || c.name.includes(query),
  );
}

/**
 * Single source of truth for how a tag renders everywhere in the library —
 * prompt cards, the search dropdown, and the prompt form editor. Pass
 * `onSelect` for a clickable (add-to-search) chip, `onRemove` for an editable
 * chip with an × button, or neither for a plain display chip.
 */
function TagChip({
  label,
  onSelect,
  onRemove,
}: {
  label: string;
  onSelect?: () => void;
  onRemove?: () => void;
}) {
  const base =
    "inline-flex items-center gap-1 rounded-full bg-primary/10 text-primary px-2 py-0.5 text-[11px] font-medium";
  if (onSelect) {
    return (
      <button
        type="button"
        // onMouseDown fires before an input's blur, so a dropdown click lands
        // before the panel closes.
        onMouseDown={(e) => { e.preventDefault(); onSelect(); }}
        className={`${base} hover:bg-primary/20 transition-colors`}
      >
        #{label}
      </button>
    );
  }
  return (
    <span className={base}>
      #{label}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="rounded-full hover:bg-primary/20 -mr-0.5 p-0.5"
          aria-label={`Remove tag ${label}`}
        >
          <X className="w-2.5 h-2.5" />
        </button>
      )}
    </span>
  );
}

function PromptCard({
  prompt,
  onUse,
  onEdit,
  onDelete,
  onCustomize,
  onCopy,
  onDeploy,
  onSubmitToCommunity,
  copyCount,
}: {
  prompt: Prompt | CustomPrompt;
  onUse: (content: string, category: string) => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onCustomize?: () => void;
  onCopy?: (id: string) => void;
  /** Deploy this prompt as a new colony (opens the Create Colony modal). */
  onDeploy?: () => void;
  /** Submit this (custom) prompt to the community review queue. */
  onSubmitToCommunity?: () => Promise<void>;
  /** Live community copy count. Shown only when provided (community prompts). */
  copyCount?: number;
}) {
  const [copied, setCopied] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmitToCommunity = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (submitting || submitted || !onSubmitToCommunity) return;
    setSubmitting(true);
    try {
      await onSubmitToCommunity();
      setSubmitted(true);
      setTimeout(() => setSubmitted(false), 2500);
    } catch {
      // Leave the button un-submitted so the user can retry.
    } finally {
      setSubmitting(false);
    }
  };
  const isCustom = "custom" in prompt && prompt.custom;
  // Retired: freeform #tag chips on cards are replaced by skill capsules.
  // const promptTags = (prompt as { tags?: string[] }).tags ?? [];
  // Clicking the card body opens a modal: "Edit" for the user's own prompts,
  // "Customize" (fork into a new custom prompt) for community prompts. While
  // a delete is being confirmed, swallow the click so the card doesn't open
  // on top of the confirmation.
  const cardAction = !confirmingDelete
    ? isCustom
      ? onEdit
      : onCustomize
    : undefined;

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await navigator.clipboard.writeText(prompt.content);
    const key = isCustom ? String(prompt.id) : `builtin-${prompt.id}`;
    onCopy?.(key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleConfirmDelete = () => {
    setConfirmingDelete(false);
    onDelete?.();
  };

  // Hand-picked skills the prompt references. Custom prompts carry them in
  // `tags`; for any prompt we also recover them from the inline
  // `<use_skill>` markers embedded in the content. The clean body (markers
  // stripped) is what the card preview shows.
  const cleanContent = stripUseSkillTags(prompt.content);
  const usedSkills =
    ((prompt as CustomPrompt).skills ?? []).length > 0
      ? (prompt as CustomPrompt).skills!
      : parseUseSkillTags(prompt.content);

  // Resolve the skill names to live capsules so the card renders chips that
  // match the home grid + detail popup. Fall back to keyword inference for
  // prompts that carry no hand-picked skills (same as the home card).
  const { capsules: liveSkills } = useSkillIndex();
  const skillCapsules: SkillCapsule[] = useMemo(() => {
    if (usedSkills.length) {
      return usedSkills.map(
        (n) =>
          liveSkills.find((c) => c.name === n) ?? {
            name: n,
            label: n.replace(/^hive\./, ""),
            domain: deriveDomain(n),
          },
      );
    }
    return inferSkillCapsules(prompt.content, 6);
  }, [usedSkills, liveSkills, prompt.content]);

  // Featured prompts may carry content assets; the card shows the first as a
  // thumbnail (same treatment as the home grid card).
  const firstAsset = (prompt as { assets?: PromptAsset[] }).assets?.[0];
  const firstAssetSrc = firstAsset ? assetPreviewSrc(firstAsset) : "";

  return (
    <div
      role={cardAction ? "button" : undefined}
      tabIndex={cardAction ? 0 : undefined}
      onClick={cardAction}
      onKeyDown={cardAction ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); cardAction(); } } : undefined}
      className={`group rounded-lg border bg-card p-4 hover:shadow-sm transition-all flex flex-col ${cardAction ? "cursor-pointer" : ""} ${confirmingDelete ? "border-destructive/40" : "border-border/60 hover:border-primary/30"}`}>
      {firstAsset && (
        <div className="relative -mt-1 mb-3 aspect-video w-full overflow-hidden rounded-md bg-muted">
          {firstAssetSrc ? (
            <>
              {/* Blurred zoomed copy fills the letterbox bars so off-ratio
                  screenshots aren't cropped or left with empty bars. */}
              <img
                src={firstAssetSrc}
                alt=""
                aria-hidden="true"
                loading="lazy"
                className="absolute inset-0 h-full w-full scale-110 object-cover blur-xl"
              />
              <img
                src={firstAssetSrc}
                alt=""
                loading="lazy"
                className="relative h-full w-full object-contain"
              />
            </>
          ) : (
            <div className="h-full w-full bg-muted" />
          )}
          {firstAsset.type === "video" && (
            <span className="absolute inset-0 flex items-center justify-center">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-black/55 text-white">
                <Play className="h-4 w-4 translate-x-0.5 fill-current" />
              </span>
            </span>
          )}
        </div>
      )}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <h3 className="text-[13px] font-medium text-foreground line-clamp-1">{prompt.title}</h3>
          {isCustom && (
            <span className="flex-shrink-0 px-1 py-px rounded text-[9px] font-medium bg-muted/50 text-muted-foreground/70">My Prompt</span>
          )}
        </div>
        {isCustom && !confirmingDelete && (
          <div className="flex items-center gap-0.5 flex-shrink-0 opacity-0 group-hover:opacity-100">
            {onSubmitToCommunity && (
              <button
                onClick={handleSubmitToCommunity}
                disabled={submitting}
                className="p-1.5 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10 disabled:opacity-50"
                title={submitted ? "Submitted — pending review" : "Submit prompt for review"}
              >
                {submitted ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Upload className="w-3.5 h-3.5" />}
              </button>
            )}
            {onEdit && (
              <button
                onClick={(e) => { e.stopPropagation(); onEdit(); }}
                className="p-1.5 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10"
                title="Edit prompt"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            )}
            {onDelete && (
              <button
                onClick={(e) => { e.stopPropagation(); setConfirmingDelete(true); }}
                className="p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                title="Delete prompt"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
        {!isCustom && copyCount !== undefined && (
          <span
            className="flex-shrink-0 flex items-center gap-1 text-[10px] text-muted-foreground/70 tabular-nums"
            title={`Copied ${copyCount.toLocaleString()} ${copyCount === 1 ? "time" : "times"}`}
          >
            <Copy className="w-3 h-3" />
            {copyCount.toLocaleString()}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed mb-3">{cleanContent}</p>
      <SkillCapsuleRow capsules={skillCapsules} size="xs" />
      {/* --- Retired: user/community freeform #tag chips on cards. Skill
          capsules above replace them as the "what this prompt uses" signal.
      {promptTags.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 mb-3">
          {promptTags.slice(0, 4).map((t) => (
            <TagChip key={t} label={t} />
          ))}
          {promptTags.length > 4 && (
            <span className="text-[11px] font-medium text-muted-foreground/60 px-1">
              +{promptTags.length - 4}
            </span>
          )}
        </div>
      )} */}
      {confirmingDelete ? (
        <div className="mt-auto flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5">
          <span className="text-xs text-destructive flex-1 truncate">Delete this prompt?</span>
          <button
            onClick={(e) => { e.stopPropagation(); setConfirmingDelete(false); }}
            className="px-2.5 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); handleConfirmDelete(); }}
            className="px-2.5 py-1 rounded-md text-xs font-medium bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors"
          >
            Delete
          </button>
        </div>
      ) : (
        <div className="mt-auto flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="flex-1 flex items-center justify-center gap-1.5 rounded-md border border-gray-200 bg-white py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-500" />
                Copied
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                Copy prompt
              </>
            )}
          </button>
          {onDeploy && (
            <button
              onClick={(e) => { e.stopPropagation(); onDeploy(); }}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-md border border-primary/20 bg-primary/[0.04] py-1.5 text-xs font-medium text-primary hover:bg-primary/[0.08]"
              title="Deploy as a new colony"
            >
              <Rocket className="w-3.5 h-3.5" />
              Deploy
            </button>
          )}
        </div>
      )}
    </div>
  );
}

interface PromptFormInitial {
  title: string;
  category: string;
  content: string;
  /** Hand-picked skill names to pre-fill the skill picker. */
  skills?: string[];
}

// --- Retired: user-created freeform tagging. Skill capsules (auto-derived
// from prompt content) replace hand-authored tags. Kept commented for
// reference in case manual tagging is reinstated.
// const MAX_TAGS = 10;
// const MAX_TAG_LEN = 24;
//
// Mirrors the runtime's _normalize_tags so the chips we render match the
// shape the server will persist (lowercased, trimmed, deduped, capped).
// function normalizeTagInput(raw: string, existing: string[]): string | null {
//   const tag = raw.trim().toLowerCase().slice(0, MAX_TAG_LEN);
//   if (!tag) return null;
//   if (existing.includes(tag)) return null;
//   if (existing.length >= MAX_TAGS) return null;
//   return tag;
// }

function PromptFormModal({
  open,
  onClose,
  onSave,
  initial,
  heading,
  submitLabel,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (title: string, category: string, content: string, skills: string[]) => Promise<void>;
  /** When provided, the modal opens pre-filled with these values. */
  initial?: PromptFormInitial | null;
  /** Overrides the default modal heading. */
  heading?: string;
  /** Overrides the default submit button label. */
  submitLabel?: string;
}) {
  const editMode = !!initial;
  const [title, setTitle] = useState(initial?.title ?? "");
  const [category, setCategory] = useState(initial?.category ?? "");
  // The editor works on clean text; inline <use_skill> markers are stripped
  // on open and re-embedded on save so the picker stays the source of truth.
  const [content, setContent] = useState(stripUseSkillTags(initial?.content ?? ""));
  // Skills are stored in the prompt's `skills` column (and mirrored inline in
  // content). They're picked by hand from the live skill library below — never
  // auto-detected. Recover from inline markers if a skills list isn't supplied.
  const [skillNames, setSkillNames] = useState<string[]>(
    initial?.skills ?? parseUseSkillTags(initial?.content ?? ""),
  );
  const [skillPickerOpen, setSkillPickerOpen] = useState(false);
  const [skillQuery, setSkillQuery] = useState("");
  const [saving, setSaving] = useState(false);

  const { capsules: liveSkills } = useSkillIndex();

  // Re-seed when the modal opens with a different prompt (re-using a single
  // modal instance across edits is what keeps focus / animation behaving).
  useEffect(() => {
    if (!open) return;
    setTitle(initial?.title ?? "");
    setCategory(initial?.category ?? "");
    setContent(stripUseSkillTags(initial?.content ?? ""));
    setSkillNames(initial?.skills ?? parseUseSkillTags(initial?.content ?? ""));
    setSkillPickerOpen(false);
    setSkillQuery("");
    setSaving(false);
  }, [open, initial]);

  // Resolve picked skill names to live capsules for chip display; fall back to
  // a minimal capsule when a saved name is no longer in the library.
  const selectedCapsules: SkillCapsule[] = skillNames.map(
    (n) =>
      liveSkills.find((c) => c.name === n) ?? {
        name: n,
        label: n,
        domain: "general",
      },
  );
  const q = skillQuery.trim().toLowerCase();
  const availableSkills = liveSkills.filter(
    (c) =>
      !skillNames.includes(c.name) &&
      (q === "" ||
        c.label.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q)),
  );

  const addSkill = (name: string) => {
    setSkillNames((prev) => (prev.includes(name) ? prev : [...prev, name]));
    setSkillQuery("");
  };
  const removeSkill = (name: string) =>
    setSkillNames((prev) => prev.filter((n) => n !== name));

  if (!open) return null;

  // --- Retired: user-created freeform tagging helpers ---
  // const commitTagDraft = () => {
  //   const next = normalizeTagInput(tagDraft, tags);
  //   if (next) setTags((prev) => [...prev, next]);
  //   setTagDraft("");
  // };
  // const finishAdding = () => { commitTagDraft(); setAddingTag(false); };
  // const startAdding = () => {
  //   setAddingTag(true);
  //   requestAnimationFrame(() => tagInputRef.current?.focus());
  // };
  // const handleTagKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
  //   if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commitTagDraft(); }
  //   else if (e.key === "Escape") { e.preventDefault(); setTagDraft(""); setAddingTag(false); }
  //   else if (e.key === "Backspace" && tagDraft === "") {
  //     if (tags.length > 0) setTags((prev) => prev.slice(0, -1));
  //     else setAddingTag(false);
  //   }
  // };

  const handleSubmit = async () => {
    if (!title.trim() || !content.trim()) return;
    setSaving(true);
    try {
      // Picked skills are persisted two ways: as the prompt's tags (structured
      // column) and inline in the content as <use_skill> markers.
      const finalContent = embedUseSkillTags(content.trim(), skillNames);
      await onSave(title.trim(), category.trim(), finalContent, skillNames);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-[650px] p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-lg font-semibold text-foreground">
            {heading ?? (editMode ? "Edit Prompt" : "Add Custom Prompt")}
          </h3>
          <button onClick={onClose} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex flex-col gap-4">
          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">Title <span className="text-primary">*</span></label>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Weekly Report Generator"
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40" />
          </div>

          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">Category</label>
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40">
              <option value="">Custom</option>
              {promptCategories.map((cat) => (
                <option key={cat.id} value={cat.id}>{cat.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">Prompt Content <span className="text-primary">*</span></label>
            <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={13}
              placeholder="Enter your prompt..."
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 resize-none" />
          </div>

          <div className="flex items-end justify-between gap-4 pt-1">
            {/* Skills are picked by hand from the live skill library and saved
                as the prompt's tags — no auto-detection. */}
            <div className="flex-1 min-w-0 max-w-[320px]">
              <label className="text-[11px] font-medium text-muted-foreground/80 mb-1 block">Skills</label>
              <div className="flex flex-wrap items-center gap-1">
                {selectedCapsules.map((c) => (
                  <SkillCapsuleChip
                    key={c.name}
                    capsule={c}
                    size="xs"
                    onRemove={() => removeSkill(c.name)}
                  />
                ))}
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setSkillPickerOpen((v) => !v)}
                    className="inline-flex items-center gap-0.5 rounded-full border border-dashed border-border/60 text-muted-foreground hover:border-primary/50 hover:text-primary px-2 py-0.5 text-[11px] font-medium transition-colors"
                    aria-label="Add a skill"
                  >
                    <Plus className="w-3 h-3" />
                    <span>Add a skill</span>
                  </button>
                  {skillPickerOpen && (
                    <>
                      <div className="fixed inset-0 z-10" onClick={() => setSkillPickerOpen(false)} />
                      <div className="absolute left-0 top-full mt-1 z-20 w-64 rounded-lg border border-border/60 bg-popover shadow-lg overflow-hidden">
                        <div className="p-1.5 border-b border-border/50">
                          <input
                            autoFocus
                            type="text"
                            value={skillQuery}
                            onChange={(e) => setSkillQuery(e.target.value)}
                            placeholder="Search skills…"
                            className="w-full bg-muted/30 border border-border/50 rounded-md px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
                          />
                        </div>
                        <ul className="max-h-56 overflow-y-auto py-1">
                          {availableSkills.length === 0 ? (
                            <li className="px-3 py-2 text-[11px] text-muted-foreground/70">
                              {liveSkills.length === 0 ? "Loading skills…" : "No matching skills"}
                            </li>
                          ) : (
                            availableSkills.map((c) => (
                              <li key={c.name}>
                                <button
                                  type="button"
                                  onClick={() => addSkill(c.name)}
                                  className="w-full px-3 py-1.5 text-left text-xs text-foreground hover:bg-primary/10 transition-colors"
                                >
                                  {c.label}
                                </button>
                              </li>
                            ))
                          )}
                        </ul>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30">Cancel</button>
              <button onClick={handleSubmit} disabled={saving || !title.trim() || !content.trim()}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed">
                {saving ? "Saving…" : submitLabel ?? (editMode ? "Save changes" : "Add Prompt")}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

type SortKey = "date" | "name" | "popular";

const SORT_LABELS: Record<SortKey, string> = {
  date: "Newest",
  name: "Name",
  popular: "Most copied",
};

// Guarded read so a hand-edited or stale localStorage value can't make
// the dropdown render with no selected option.
function readSortPref(key: string, fallback: SortKey): SortKey {
  const raw = userStorage.get<string>(key, fallback);
  return raw in SORT_LABELS ? (raw as SortKey) : fallback;
}

function SortDropdown({
  value,
  onChange,
}: {
  value: SortKey;
  onChange: (next: SortKey) => void;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as SortKey)}
        className="appearance-none bg-muted/40 hover:bg-muted/60 border border-border/40 rounded-md pl-2.5 pr-7 py-1 text-[11px] font-medium text-foreground/80 focus:outline-none focus:ring-1 focus:ring-primary/40 cursor-pointer"
        aria-label="Sort prompts"
      >
        {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
          <option key={k} value={k}>{SORT_LABELS[k]}</option>
        ))}
      </select>
      <ChevronDown className="w-3 h-3 text-muted-foreground absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none" />
    </div>
  );
}

// Prompt-library-specific wrapper around SearchInput: same field chrome,
// but a Skill Tags suggestion panel anchors below the input when it has
// focus. Clicking a skill commits its label to the search query (which
// matches against inferred skills as well as title/content). Outside-click
// or Escape closes.
function PromptSearch({
  value,
  onChange,
  skills,
  loading,
}: {
  value: string;
  onChange: (next: string) => void;
  skills: SkillCapsule[];
  loading?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handleDoc = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleDoc);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleDoc);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  // Surface the skills whose label matches what the user has already typed,
  // otherwise show the full ranked list (most-used first).
  const visibleSkills = useMemo(() => {
    const q = value.trim().toLowerCase();
    return q
      ? skills.filter(
          (s) => s.label.toLowerCase().includes(q) || s.name.includes(q),
        )
      : skills;
  }, [skills, value]);

  return (
    <div ref={wrapperRef} className="relative">
      <SearchInput
        value={value}
        onChange={onChange}
        loading={loading}
        placeholder="Search prompts by title, skill, or content…"
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
      />
      {open && skills.length > 0 && (
        <div className="absolute left-0 right-0 mt-1 z-30 rounded-lg border border-border/60 bg-popover shadow-lg overflow-hidden">
          <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground bg-muted/30 border-b border-border/40">
            Filter by skill
          </div>
          {visibleSkills.length === 0 ? (
            <div className="px-3 py-3 text-xs text-muted-foreground/70">
              No skills match "{value}".
            </div>
          ) : (
            <div className="flex flex-wrap gap-1.5 p-2 max-h-[180px] overflow-y-auto">
              {visibleSkills.map((s) => (
                <button
                  key={s.name}
                  type="button"
                  onClick={() => {
                    onChange(s.label);
                    setOpen(false);
                  }}
                >
                  <SkillCapsuleChip capsule={s} size="xs" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function PromptLibrary() {
  const navigate = useNavigate();
  const { openCreateColony } = useCreateColony();
  const [searchQuery, setSearchQuery] = useState("");
  // Search is instant (client-side), so flash a brief spinner while the user
  // types — without it the results just snap and the search feels like it
  // never ran. Settles ~250ms after the last keystroke.
  const [isSearching, setIsSearching] = useState(false);
  useEffect(() => {
    if (!searchQuery.trim()) {
      setIsSearching(false);
      return;
    }
    setIsSearching(true);
    const t = setTimeout(() => setIsSearching(false), 250);
    return () => clearTimeout(t);
  }, [searchQuery]);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [editing, setEditing] = useState<CustomPrompt | null>(null);
  const [customizing, setCustomizing] = useState<CommunityPrompt | null>(null);
  const [customPrompts, setCustomPrompts] = useState<CustomPrompt[]>([]);
  const [myPromptsSort, setMyPromptsSortState] = useState<SortKey>(() =>
    readSortPref("promptLibrarySort.my", "date"),
  );
  const [communitySort, setCommunitySortState] = useState<SortKey>(() =>
    readSortPref("promptLibrarySort.community", "popular"),
  );
  const setMyPromptsSort = useCallback((next: SortKey) => {
    setMyPromptsSortState(next);
    userStorage.set("promptLibrarySort.my", next);
    // Persist server-side so the preference follows the user across
    // reinstalls / devices. Local userStorage stays as the fast-path
    // cache so the first paint never waits on the network.
    configApi
      .setProfile(undefined, undefined, undefined, undefined, { my: next })
      .catch(() => {});
  }, []);
  const setCommunitySort = useCallback((next: SortKey) => {
    setCommunitySortState(next);
    userStorage.set("promptLibrarySort.community", next);
    configApi
      .setProfile(undefined, undefined, undefined, undefined, { community: next })
      .catch(() => {});
  }, []);
  const [copyCounts, setCopyCounts] = useState<Record<string, number>>(() =>
    userStorage.get<Record<string, number>>("promptCopyCounts", {}),
  );
  // The featured catalog + its live copy counts come from the backend, cached
  // in memory and userStorage so navigation and cold starts paint the last
  // known catalog instantly while a background refetch keeps it fresh.
  const {
    prompts: communityPrompts,
    setPrompts: setCommunityPrompts,
    loading: catalogLoading,
  } = useCommunityPrompts();

  const handleCopyRecorded = useCallback((id: string) => {
    setCopyCounts((prev) => {
      const next = { ...prev, [id]: (prev[id] ?? 0) + 1 };
      userStorage.set("promptCopyCounts", next);
      return next;
    });
  }, []);

  // Record a community-prompt copy: bump the visible count locally. The
  // server-side authoritative copy count was a cloud feature (removed).
  const handleCommunityCopy = useCallback((id: number) => {
    setCommunityPrompts((prev) =>
      prev.map((p) => (p.id === id ? { ...p, copy_count: p.copy_count + 1 } : p)),
    );
  }, []);

  useEffect(() => {
    promptsApi.list().then((r) => setCustomPrompts(r.prompts)).catch(() => {});
  }, []);

  // One-shot hydration from the server-side user_profile. localStorage is
  // the fast-render source (already read in useState above); this pulls the
  // cross-device value and adopts it if the server has one. Only runs once
  // — after this, local toggles are authoritative until the next mount.
  useEffect(() => {
    let cancelled = false;
    configApi
      .getProfile()
      .then((p) => {
        if (cancelled) return;
        const remote = p.prompt_library_sort;
        if (!remote) return;
        if (remote.my && remote.my in SORT_LABELS) {
          const next = remote.my as SortKey;
          setMyPromptsSortState(next);
          userStorage.set("promptLibrarySort.my", next);
        }
        if (remote.community && remote.community in SORT_LABELS) {
          const next = remote.community as SortKey;
          setCommunitySortState(next);
          userStorage.set("promptLibrarySort.community", next);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Filtered + sorted custom (my) prompts. "date" parses the unix-ms
  // suffix of the ``custom_<ms>`` id pattern (ids that don't match sink
  // to the bottom). "name" sorts by title. "popular" uses the locally
  // tracked copy-count map keyed by the raw custom id.
  const filteredCustom = useMemo(() => {
    const tsOf = (id: string) => {
      const match = /custom_(\d+)/.exec(id);
      return match ? Number(match[1]) : 0;
    };
    const sortBy = (a: Prompt | CustomPrompt, b: Prompt | CustomPrompt) => {
      if (myPromptsSort === "name") return a.title.localeCompare(b.title);
      if (myPromptsSort === "popular") {
        return (copyCounts[String(b.id)] ?? 0) - (copyCounts[String(a.id)] ?? 0);
      }
      return tsOf(String(b.id)) - tsOf(String(a.id));
    };
    let result: (Prompt | CustomPrompt)[] = [...customPrompts].sort(sortBy);
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (p) =>
          p.title.toLowerCase().includes(query) ||
          p.content.toLowerCase().includes(query) ||
          matchesSkill(p.content, query),
      );
    }
    return result;
  }, [customPrompts, searchQuery, myPromptsSort, copyCounts]);

  // Filtered + sorted built-in (community) prompts. Built-in ids are
  // numeric and roughly chronological — higher id = added later — so
  // we use id descending as the "date" proxy.
  const filteredBuiltIn = useMemo(() => {
    const sortBy = (a: CommunityPrompt, b: CommunityPrompt) => {
      if (communitySort === "name") return a.title.localeCompare(b.title);
      // "popular" = most copied first, newest (higher id) breaking ties — the
      // default ordering, matching the prompt page.
      if (communitySort === "popular") return b.copy_count - a.copy_count || b.id - a.id;
      return b.id - a.id;
    };
    let result: CommunityPrompt[] = [...communityPrompts].sort(sortBy);
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (p) =>
          p.title.toLowerCase().includes(query) ||
          p.content.toLowerCase().includes(query) ||
          matchesSkill(p.content, query),
      );
    }
    return result;
  }, [searchQuery, communitySort, communityPrompts]);

  // Reset page when filters or community sort change — the new ordering
  // could put a completely different slice on page 0.
  useEffect(() => setVisibleCount(PAGE_SIZE), [searchQuery, communitySort]);

  const pagedBuiltIn = filteredBuiltIn.slice(0, visibleCount);

  // Infinite scroll: grow the rendered slice as the sentinel nears the
  // viewport. The full catalog is already in memory (one fetch), so this only
  // controls how many cards we mount — no extra network calls.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    const root = scrollRef.current;
    if (!sentinel || !root) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setVisibleCount((c) => Math.min(c + PAGE_SIZE, filteredBuiltIn.length));
        }
      },
      { root, rootMargin: "600px" },
    );
    io.observe(sentinel);
    return () => io.disconnect();
  }, [filteredBuiltIn.length]);

  const handleUsePrompt = (content: string, category: string) => {
    const queenId = categoryToQueen[category];
    if (!queenId) return;
    userStorage.session.set(`queenFirstMessage:${queenId}`, content);
    navigate(`/queen/${queenId}?new=1`);
  };

  // Open the sidebar's Create Colony modal with this prompt's title as the
  // colony name and its content as the goal. Sidebar slugifies the name itself.
  // The prompt's category picks the default queen (categoryToQueen).
  const handleDeployPrompt = useCallback(
    (prompt: Prompt | CustomPrompt) => {
      openCreateColony({
        name: prompt.title,
        goal: prompt.content,
        queenId: categoryToQueen[prompt.category],
      });
    },
    [openCreateColony],
  );

  const handleAddPrompt = useCallback(async (title: string, category: string, content: string, skills: string[]) => {
    const created = await promptsApi.create(title, category, content, skills);
    setCustomPrompts((prev) => [created, ...prev]);
  }, []);

  const handleDeletePrompt = useCallback(async (id: string) => {
    await promptsApi.delete(id);
    setCustomPrompts((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const handleUpdatePrompt = useCallback(
    async (id: string, title: string, category: string, content: string, skills: string[]) => {
      const updated = await promptsApi.update(id, title, category, content, skills);
      setCustomPrompts((prev) =>
        prev.map((p) => (p.id === id ? updated : p)),
      );
    },
    [],
  );

  // Submitting a prompt to the shared community catalog was a cloud feature;
  // it has no local equivalent, so the affordance is removed.

  // Unique skill tags across every prompt, inferred from content and ordered
  // by frequency desc then alphabetically — the search dropdown surfaces the
  // most common skills first so a single click filters down to the recipes
  // that use it. Replaces the retired user-authored tag list.
  const allSkills = useMemo(() => {
    const counts = new Map<string, number>();
    const byName = new Map<string, SkillCapsule>();
    const tally = (content: string) => {
      for (const c of inferSkillCapsules(content, 5)) {
        counts.set(c.name, (counts.get(c.name) ?? 0) + 1);
        if (!byName.has(c.name)) byName.set(c.name, c);
      }
    };
    for (const p of customPrompts) tally(p.content);
    for (const p of communityPrompts) tally(p.content);
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([name]) => byName.get(name)!)
      .filter(Boolean);
  }, [customPrompts, communityPrompts]);

  const customCount = customPrompts.length;

  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/60">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-baseline gap-3">
              <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
                <MessageCircle className="w-5 h-5 text-primary" />
                Prompt Library
              </h2>
              <span className="text-xs text-muted-foreground">
                {customCount > 0 ? `${customCount} custom · ` : ""}{communityPrompts.length} featured prompts
              </span>
            </div>
            <button onClick={() => setAddModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90">
              <Plus className="w-3.5 h-3.5" />
              Add Prompt
            </button>
          </div>

          <PromptSearch
            value={searchQuery}
            onChange={setSearchQuery}
            skills={allSkills}
            loading={isSearching}
          />
        </div>

        {/* Prompts grid */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-6">
          {filteredCustom.length === 0 && pagedBuiltIn.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <MessageCircle className="w-10 h-10 text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">
                {catalogLoading ? "Loading prompts…" : "No prompts found"}
              </p>
              {!catalogLoading && (
                <p className="text-xs text-muted-foreground/60 mt-1">Try adjusting your search</p>
              )}
            </div>
          ) : (
            <>
              {/* My Prompts section */}
              {filteredCustom.length > 0 && (
                <div className="mb-8">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">My Prompts</h3>
                    <SortDropdown value={myPromptsSort} onChange={setMyPromptsSort} />
                  </div>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {filteredCustom.map((prompt) => (
                      <PromptCard
                        key={prompt.id as string}
                        prompt={prompt}
                        onUse={handleUsePrompt}
                        onCopy={handleCopyRecorded}
                        onDeploy={() => handleDeployPrompt(prompt)}
                        onEdit={
                          "custom" in prompt && prompt.custom
                            ? () => setEditing(prompt as CustomPrompt)
                            : undefined
                        }
                        onDelete={"custom" in prompt && prompt.custom ? () => handleDeletePrompt(prompt.id as string) : undefined}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Featured Prompts section */}
              {pagedBuiltIn.length > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Featured Prompts</h3>
                    <SortDropdown value={communitySort} onChange={setCommunitySort} />
                  </div>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {pagedBuiltIn.map((prompt) => (
                      <PromptCard
                        key={`builtin-${prompt.id}`}
                        prompt={prompt}
                        onUse={handleUsePrompt}
                        copyCount={prompt.copy_count}
                        onCopy={() => handleCommunityCopy(prompt.id)}
                        onDeploy={() => handleDeployPrompt(prompt)}
                        onCustomize={() => setCustomizing(prompt)}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
          {/* Infinite-scroll sentinel — reveals the next slice as it nears view */}
          <div ref={sentinelRef} aria-hidden className="h-px" />
        </div>

        {/* Featured prompts count */}
        {filteredBuiltIn.length > 0 && (
          <div className="px-6 py-3 border-t border-border/60">
            <span className="text-xs text-muted-foreground">
              Showing {Math.min(visibleCount, filteredBuiltIn.length)} of {filteredBuiltIn.length}
            </span>
          </div>
        )}
      </div>

      <PromptFormModal
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        onSave={handleAddPrompt}
      />
      <PromptFormModal
        open={!!editing}
        onClose={() => setEditing(null)}
        initial={editing}
        onSave={(t, c, ct, skills) =>
          editing ? handleUpdatePrompt(editing.id, t, c, ct, skills) : Promise.resolve()
        }
      />
      <PromptFormModal
        open={!!customizing}
        onClose={() => setCustomizing(null)}
        initial={
          customizing
            ? { title: customizing.title, category: customizing.category, content: customizing.content }
            : null
        }
        heading="Customize Prompt"
        submitLabel="Save as my prompt"
        onSave={handleAddPrompt}
      />
    </div>
  );
}
