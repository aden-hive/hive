import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { X, Crown, Rocket, Loader2, Maximize2, ChevronLeft, ChevronRight } from "lucide-react";
import type { Prompt } from "@/data/prompts";
import type { CustomPrompt } from "@/api/prompts";
import { categoryToQueen } from "@/data/prompts";
import {
  parseUseSkillTags,
  inferSkillCapsules,
  stripUseSkillTags,
  embedUseSkillTags,
  deriveDomain,
  type SkillCapsule,
} from "@/data/skill-capsules";
import { useSkillIndex } from "@/hooks/use-skill-index";
import { SkillCapsuleChip } from "@/components/SkillComposer";
import { SkillTextEditor, type SkillTextEditorHandle } from "@/components/SkillTextEditor";
import { assetPreviewSrc, type PromptAsset } from "@/data/prompt-assets";

type PromptItem = Prompt | CustomPrompt;

/** Head of Growth — the catch-all default when a prompt's queen can't be matched. */
const HEAD_OF_GROWTH = "queen_growth";

/** Minimal queen shape the picker needs (matches QueenProfile). */
export interface DeployQueen {
  id: string;
  name: string;
  title: string;
}

export interface DeployArgs {
  queenId: string;
  colonyName: string;
  /** The (possibly edited) prompt body, with inline <read_skill> markers. */
  goal: string;
}

/**
 * A prompt "Detail" popup, opened from a home prompt card. Shows the prompt's
 * skills once (a Skills row), the editable goal as clean prose, plus a deploy
 * form (queen + colony name) so the user can personalize and deploy a colony
 * without leaving the popup. Skills are re-embedded into the goal on deploy.
 *
 * `onDeploy` returns whether the deploy went through (false = the caller
 * cancelled, e.g. an unfilled-placeholder warning) so the modal only closes on
 * success.
 */
export function PromptDetailModal({
  prompt,
  queens,
  prefill,
  onClose,
  onDeploy,
}: {
  prompt: PromptItem;
  queens: DeployQueen[];
  /** Prefill `{{…}}` placeholders (cache → /me) when seeding the goal. */
  prefill?: (text: string) => string;
  onClose: () => void;
  onDeploy: (args: DeployArgs) => Promise<boolean>;
}) {
  const { capsules: liveSkills } = useSkillIndex();

  // The prompt's hand-picked skills (custom `skills` column, else inline
  // <read_skill> markers). These are the ones re-embedded into the goal on
  // deploy — empty for community prompts that carry no markers.
  const skillNames = useMemo(() => {
    const col = (prompt as CustomPrompt).skills ?? [];
    return col.length ? col : parseUseSkillTags(prompt.content);
  }, [prompt]);

  // Capsules for the single Skills row: real picks resolved to live capsules,
  // else indicative inferred ones (display-only — not deployed).
  const skills: SkillCapsule[] = useMemo(() => {
    if (skillNames.length) {
      return skillNames.map(
        (n) =>
          liveSkills.find((c) => c.name === n) ?? {
            name: n,
            label: n.replace(/^hive\./, ""),
            domain: deriveDomain(n),
          },
      );
    }
    return inferSkillCapsules(prompt.content, 8);
  }, [skillNames, prompt.content, liveSkills]);

  // Goal = clean prose only. Skills live in the Skills row above (re-embedded
  // on deploy), so they're not duplicated as trailing pills here; the editor
  // still highlights `{{placeholders}}` for the user to fill.
  const [goal, setGoal] = useState(() => {
    const clean = stripUseSkillTags(prompt.content);
    return prefill ? prefill(clean) : clean;
  });
  const goalRef = useRef<SkillTextEditorHandle>(null);

  // Editable, human-friendly name (prefilled from the prompt title) shown in
  // the header — it doubles as the colony name, slugified on deploy. Keeping it
  // in the header means the name isn't shown twice.
  const [colonyTitle, setColonyTitle] = useState(prompt.title);
  const colonyName = useMemo(() => {
    const slug = colonyTitle
      .toLowerCase()
      .replace(/[^a-z0-9_]+/g, "_")
      .replace(/^_+|_+$/g, "");
    return slug || "new_colony";
  }, [colonyTitle]);
  // Default queen: the prompt's DB queen_id (featured prompts), then the
  // category→queen mapping, then Head of Growth as a catch-all when the backend
  // names a queen that isn't one of the available ones (e.g. decommissioned /
  // unknown id). Only ever resolves to a queen actually in the picker.
  const [queenId, setQueenId] = useState(() => {
    const has = (id?: string | null): id is string => !!id && queens.some((q) => q.id === id);
    const fromDb = (prompt as { queen_id?: string | null }).queen_id;
    if (has(fromDb)) return fromDb;
    const wanted = categoryToQueen[prompt.category];
    if (has(wanted)) return wanted;
    return has(HEAD_OF_GROWTH) ? HEAD_OF_GROWTH : (queens[0]?.id ?? "");
  });

  // Public content assets (screenshots / videos) shown as a gallery.
  const assets = (prompt as { assets?: PromptAsset[] }).assets ?? [];

  // Click an image to expand it full-screen (raw, full-resolution url).
  const [lightbox, setLightbox] = useState<string | null>(null);
  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setLightbox(null);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [lightbox]);

  // Horizontal gallery nav — arrow buttons (scroll can be fiddly). Each is shown
  // only while there's room to scroll that way.
  const galleryRef = useRef<HTMLDivElement>(null);
  const [galleryNav, setGalleryNav] = useState({ left: false, right: false });
  const updateGalleryNav = useCallback(() => {
    const el = galleryRef.current;
    if (!el) return;
    setGalleryNav({
      left: el.scrollLeft > 4,
      right: el.scrollLeft + el.clientWidth < el.scrollWidth - 4,
    });
  }, []);
  useEffect(() => {
    // Recompute now, next frame, and shortly after — images gain width as they
    // load, which is what grows scrollWidth (and reveals the right arrow).
    updateGalleryNav();
    const raf = requestAnimationFrame(updateGalleryNav);
    const t = setTimeout(updateGalleryNav, 250);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(t);
    };
  }, [assets.length, updateGalleryNav]);
  const scrollGallery = (dir: -1 | 1) => {
    const el = galleryRef.current;
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.85, behavior: "smooth" });
  };

  const [deploying, setDeploying] = useState(false);

  const canDeploy = !!colonyName.trim() && !!queenId && !deploying;

  const handleDeploy = async () => {
    if (!canDeploy) return;
    setDeploying(true);
    try {
      // Re-attach the skills (stripped from the editor view) so the deployed
      // colony goal still carries them as <read_skill> markers.
      const ok = await onDeploy({
        queenId,
        colonyName: colonyName.trim(),
        goal: embedUseSkillTags(goal, skillNames),
      });
      if (ok) onClose();
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={() => !deploying && onClose()} />
      <div className="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-[640px] max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-6 pt-5 pb-3 border-b border-border/60">
          <div className="min-w-0 flex-1">
            <input
              value={colonyTitle}
              onChange={(e) => setColonyTitle(e.target.value)}
              aria-label="Colony name"
              placeholder="Colony name"
              className="w-full bg-transparent text-base font-semibold text-foreground outline-none rounded px-1 -mx-1 focus:bg-muted/40 placeholder:text-muted-foreground/50"
            />
            <p className="text-[11px] text-muted-foreground mt-0.5 px-1 -mx-1">
              Deploys as colony <span className="font-mono text-foreground/70">{colonyName}</span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body (scrolls) */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {assets.length > 0 && (
            <div className="group/gallery relative">
              {galleryNav.left && (
                <button
                  type="button"
                  onClick={() => scrollGallery(-1)}
                  aria-label="Scroll left"
                  className="absolute left-1.5 top-1/2 z-10 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-border/60 bg-card/95 text-foreground shadow-md backdrop-blur transition-colors hover:bg-card"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
              )}
              {galleryNav.right && (
                <button
                  type="button"
                  onClick={() => scrollGallery(1)}
                  aria-label="Scroll right"
                  className="absolute right-1.5 top-1/2 z-10 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-border/60 bg-card/95 text-foreground shadow-md backdrop-blur transition-colors hover:bg-card"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              )}
              <div
                ref={galleryRef}
                onScroll={updateGalleryNav}
                className="flex gap-2 overflow-x-auto pb-1"
              >
              {assets.map((a, i) =>
                a.type === "video" ? (
                  <video
                    key={i}
                    src={a.url}
                    poster={a.thumbnail}
                    controls
                    preload="metadata"
                    className="h-56 w-auto max-w-[480px] flex-shrink-0 rounded-lg border border-border/50 bg-black object-contain"
                  />
                ) : (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setLightbox(a.url)}
                    className="group relative h-56 flex-shrink-0 overflow-hidden rounded-lg border border-border/50 bg-muted cursor-zoom-in"
                    title="Click to expand"
                  >
                    <img
                      src={assetPreviewSrc(a) || a.url}
                      alt=""
                      loading="lazy"
                      onLoad={updateGalleryNav}
                      className="h-full w-auto"
                    />
                    <span className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-md bg-black/55 text-white opacity-0 transition-opacity group-hover:opacity-100">
                      <Maximize2 className="h-3.5 w-3.5" />
                    </span>
                  </button>
                ),
              )}
              </div>
            </div>
          )}
          {skills.length > 0 && (
            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1.5">Skills</label>
              <div className="flex flex-wrap gap-1.5">
                {skills.map((c) => (
                  <SkillCapsuleChip key={c.name} capsule={c} size="xs" />
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1.5">Goal</label>
            <div className="rounded-lg border border-border/60 bg-background px-3 py-2 focus-within:ring-1 focus-within:ring-primary">
              <SkillTextEditor
                ref={goalRef}
                value={goal}
                onChange={setGoal}
                minHeightPx={96}
                maxHeightPx={260}
                className="text-sm text-foreground"
              />
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1.5">
              Queen Bee <span className="text-primary">*</span>
            </label>
            <div className="grid grid-cols-2 gap-1.5 max-h-[156px] overflow-y-auto pr-1">
              {queens.map((q) => (
                <button
                  key={q.id}
                  onClick={() => setQueenId(q.id)}
                  className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                    queenId === q.id
                      ? "border-primary/40 bg-primary/[0.06] text-primary"
                      : "border-border/50 text-foreground hover:border-primary/30"
                  }`}
                >
                  <Crown className="w-3 h-3 flex-shrink-0" />
                  <div className="min-w-0">
                    <p className="font-medium truncate">{q.name}</p>
                    <p className="text-[10px] text-muted-foreground truncate">{q.title}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-border/60">
          <button
            onClick={onClose}
            disabled={deploying}
            className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleDeploy}
            disabled={!canDeploy}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deploying ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Deploying…
              </>
            ) : (
              <>
                <Rocket className="w-3.5 h-3.5" /> Deploy
              </>
            )}
          </button>
        </div>
      </div>

      {lightbox && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/85 p-6"
          onClick={() => setLightbox(null)}
        >
          <img
            src={lightbox}
            alt=""
            className="max-h-[92vh] max-w-[92vw] rounded-md object-contain"
            onClick={(e) => e.stopPropagation()}
          />
          <button
            onClick={() => setLightbox(null)}
            className="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-full bg-black/60 text-white hover:bg-black/80"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}
