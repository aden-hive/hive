import { useMemo, useState } from "react";
import { Pencil, Trash2, Maximize2, Play } from "lucide-react";
import type { Prompt } from "@/data/prompts";
import type { CustomPrompt } from "@/api/prompts";
import { assetPreviewSrc, type PromptAsset } from "@/data/prompt-assets";
import {
  inferSkillCapsules,
  parseUseSkillTags,
  stripUseSkillTags,
  deriveDomain,
  type SkillCapsule,
} from "@/data/skill-capsules";
import { SkillCapsuleRow } from "@/components/SkillComposer";
import { useSkillIndex } from "@/hooks/use-skill-index";

/**
 * Shared prompt card used by the Prompt Library page and the home page's
 * inline "what can I help you with?" quick-start grid. The card surface
 * itself is non-interactive unless one of ``onEdit`` / ``onCustomize`` /
 * ``onSelect`` is provided — that lets the home page wire ``onSelect``
 * to "seed the textarea" while the library wires ``onEdit`` / ``onCustomize``
 * to open form modals.
 */
export interface PromptCardProps {
  prompt: Prompt | CustomPrompt;
  /** Optional: explicit card-body click action. Takes precedence over
   *  the default Edit (custom) / Customize (community) behavior so other
   *  surfaces can repurpose the card. */
  onSelect?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onCustomize?: () => void;
  /** Open the prompt detail popup (review skills + deploy). */
  onDetail?: () => void;
}

export function PromptCard({
  prompt,
  onSelect,
  onEdit,
  onDelete,
  onCustomize,
  onDetail,
}: PromptCardProps) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const isCustom = "custom" in prompt && prompt.custom;
  // onSelect wins when provided; otherwise fall back to Edit (custom)
  // or Customize (community). Confirmation flow swallows the click so
  // a body click doesn't open the editor on top of the prompt.
  const cardAction = !confirmingDelete
    ? onSelect ?? (isCustom ? onEdit : onCustomize)
    : undefined;

  const handleConfirmDelete = () => {
    setConfirmingDelete(false);
    onDelete?.();
  };

  // Show the prompt's ACTUAL hand-picked skills (its <read_skill> markers,
  // resolved to live capsules) so the card matches the detail popup / editor.
  // Only fall back to keyword inference when a prompt carries no markers.
  const { capsules: liveSkills } = useSkillIndex();
  const skillCapsules = useMemo<SkillCapsule[]>(() => {
    const explicit = parseUseSkillTags(prompt.content);
    if (explicit.length) {
      return explicit.map(
        (n) =>
          liveSkills.find((c) => c.name === n) ?? {
            name: n,
            label: n.replace(/^hive\./, ""),
            domain: deriveDomain(n),
          },
      );
    }
    return inferSkillCapsules(prompt.content, 6);
  }, [prompt.content, liveSkills]);

  // Card preview shows clean prose — strip the inline markers so a trailing
  // <read_skill> blob never leaks into the text.
  const previewText = stripUseSkillTags(prompt.content);

  // Featured prompts may carry a few content assets; the card shows the first.
  const firstAsset = (prompt as { assets?: PromptAsset[] }).assets?.[0];
  const firstAssetSrc = firstAsset ? assetPreviewSrc(firstAsset) : "";

  return (
    <div
      role={cardAction ? "button" : undefined}
      tabIndex={cardAction ? 0 : undefined}
      onClick={cardAction}
      onKeyDown={cardAction ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); cardAction(); } } : undefined}
      className={`group rounded-lg border bg-card p-4 hover:shadow-sm transition-all flex flex-col ${cardAction ? "cursor-pointer" : ""} ${confirmingDelete ? "border-destructive/40" : "border-border/60 hover:border-primary/30"}`}
    >
      {firstAsset && (
        <div className="relative -mt-1 mb-3 aspect-video w-full overflow-hidden rounded-md bg-muted">
          {firstAssetSrc ? (
            <>
              {/* Blurred, zoomed copy fills the letterbox bars so off-ratio
                  screenshots aren't cropped (object-contain) or left with empty
                  bars — the "frontend gaussian" backdrop. */}
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
        {!confirmingDelete && (isCustom || onDetail) && (
          <div className="flex items-center gap-0.5 flex-shrink-0">
            {isCustom && onEdit && (
              <button
                onClick={(e) => { e.stopPropagation(); onEdit(); }}
                className="p-1 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10 opacity-0 group-hover:opacity-100 transition-opacity"
                title="Edit prompt"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            )}
            {isCustom && onDelete && (
              <button
                onClick={(e) => { e.stopPropagation(); setConfirmingDelete(true); }}
                className="p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 transition-opacity"
                title="Delete prompt"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
            {onDetail && (
              <button
                onClick={(e) => { e.stopPropagation(); onDetail(); }}
                className="p-1 rounded-md text-muted-foreground/60 hover:text-primary hover:bg-primary/10 transition-colors"
                title="View details and deploy"
              >
                <Maximize2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
      <p className="text-xs text-muted-foreground line-clamp-1 leading-relaxed mb-3">{previewText}</p>
      <SkillCapsuleRow capsules={skillCapsules} size="xs" />
      {confirmingDelete && (
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
      )}
    </div>
  );
}
