import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Send, Copy, Check, Loader2 } from "lucide-react";
import { useColony } from "@/context/ColonyContext";
import { useMe, canMakeLLMCalls, resolvePreferredQueenId, isQueenDecommissioned } from "@/lib/me";
import { userStorage } from "@/lib/userStorage";
import { stageComposerHandoff } from "@/lib/composerHandoff";
import {
  prefillPlaceholders,
  resolvePlaceholders,
  collectPlaceholderValues,
  cachePlaceholderValues,
  readPlaceholderCache,
  normLabel,
} from "@/lib/placeholders";
import { promptsApi, type CustomPrompt } from "@/api/prompts";
import { categoryToQueen, type Prompt } from "@/data/prompts";
import { useCommunityPrompts, type CommunityPrompt } from "@/hooks/use-community-prompts";
import { PromptCard } from "@/components/PromptCard";
import { sessionsApi } from "@/api/sessions";
import { coloniesApi } from "@/api/colonies";
import { slugToColonyId, orderQueens } from "@/lib/colony-registry";
import { PromptDetailModal, type DeployArgs } from "@/components/PromptDetailModal";
import {
  SkillTextEditor,
  type SkillTextEditorHandle,
} from "@/components/SkillTextEditor";

// Ordering for community sections, matching the Prompt Library's default sort:
// most copied first, newest (higher id) breaking ties. Static/custom items with
// no copy_count fall back to 0.
function byPopularity(a: Prompt | CustomPrompt, b: Prompt | CustomPrompt): number {
  const ca = (a as CommunityPrompt).copy_count ?? 0;
  const cb = (b as CommunityPrompt).copy_count ?? 0;
  return cb - ca || Number(b.id) - Number(a.id);
}

/** A prompt title → colony name slug. Mirrors PromptDetailModal's slug exactly
 *  so the prompt-seeded fast path names colonies the same way the detail Deploy
 *  does (lowercase, non-alphanumerics → "_"). */
function titleToColonySlug(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9_]+/g, "_")
      .replace(/^_+|_+$/g, "") || "new_colony"
  );
}

/** Colony name for a hand-typed task when we can't classify (free users):
 *  the first few words of the prompt, slugified. */
function deriveColonyName(text: string): string {
  return titleToColonySlug(text.trim().split(/\s+/).slice(0, 6).join(" "));
}

export default function Home() {
  const navigate = useNavigate();
  const { userProfile, queenProfiles, colonies, refresh } = useColony();
  const { me } = useMe();
  const [inputValue, setInputValue] = useState("");
  const editorRef = useRef<SkillTextEditorHandle>(null);
  // Double-send guard: a colony launch can take a few seconds to create.
  const sendingRef = useRef(false);
  const [sending, setSending] = useState(false);
  // A hand-typed message awaiting its hand-picked queen (dialog open while
  // non-null). Replaces the deprecated /queen-routing LLM classification.
  const [queenPick, setQueenPick] = useState<string | null>(null);
  const [detailPrompt, setDetailPrompt] = useState<Prompt | CustomPrompt | null>(null);
  // When a prompt seeds the box, remember the queen it deploys to (and the
  // colony name) so submitting skips the classify LLM call. Cleared when the
  // box is emptied or the message is sent.
  const [promptOrigin, setPromptOrigin] = useState<{ queenId: string; colonyName: string } | null>(null);

  // Resolve a placeholder label to a prefill value: the local cache first
  // (what the user last entered), then their /me profile (email + company
  // website). Returns undefined → the pill stays empty (shows the label hint).
  const phLookup = useCallback(
    (label: string): string | undefined => {
      const key = normLabel(label);
      const cache = readPlaceholderCache();
      // What the user filled before (keyed by exact label) always wins.
      if (cache[key]) return cache[key];
      // /me fallback — only for the two things we actually know, matched
      // precisely. Deliberately NOT a loose "url"/"site" match: a label like
      // "your linkedin url" must NOT inherit the company website. Anything we
      // can't confidently resolve stays empty (the pill shows the label hint).
      if (key.includes("email")) return me?.user?.email || undefined;
      if (key.includes("your linkedin url")) return "https://www.linkedin.com/";
      if (key.includes("website") || key.includes("company url") || key.includes("domain")) {
        const w = me?.preferences?.company_website;
        return typeof w === "string" && w ? w : undefined;
      }
      return undefined;
    },
    [me],
  );
  const prefill = useCallback(
    (text: string) => prefillPlaceholders(text, phLookup),
    [phLookup],
  );

  // Queens offered in the detail/deploy popup: same list (and order) as the
  // sidebar's New Colony picker — decommissioned queens filtered out, GTM order.
  const deployQueens = useMemo(
    () =>
      orderQueens(
        queenProfiles.filter((q) => !isQueenDecommissioned(me, q.id)),
        Object.keys(me?.preferences?.queens ?? {}),
      ),
    [queenProfiles, me],
  );

  // Library browser sits permanently below the search bar so users can
  // start from a saved or built-in prompt without remembering to focus
  // the textarea. Items are paginated globally — scrolling near the
  // bottom grows visibleCount in PAGE_SIZE chunks.
  const [customPrompts, setCustomPrompts] = useState<CustomPrompt[]>([]);
  const PAGE_SIZE = 30;
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  useEffect(() => {
    let cancelled = false;
    void promptsApi
      .list()
      .then((r) => {
        if (!cancelled) setCustomPrompts(r.prompts || []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Featured catalog from the cloud DB — the same cached source the Prompt
  // Library page uses, so navigating between the two never refetches from
  // scratch or flashes a different list.
  const { prompts: communityPrompts } = useCommunityPrompts();

  // Mirror the Prompt Library exactly: a leading "My Prompts" section (the
  // user's own prompts, in API order) followed by a single flat "Community
  // Prompts" section sourced from the cloud catalog and sorted most-copied
  // first (newest breaking ties). No category grouping, no pinned playbook.
  // Items are paginated globally via visibleCount.
  type PromptItem = Prompt | CustomPrompt;
  const promptSections = useMemo(() => {
    const sections: { id: string; name: string; items: PromptItem[] }[] = [];
    if (customPrompts.length > 0) {
      sections.push({ id: "_mine", name: "My Prompts", items: customPrompts });
    }
    sections.push({
      id: "_community",
      name: "Featured Prompts",
      // Only show community prompts that carry a picture (image/video asset).
      items: communityPrompts
        .filter((p) => (p.assets?.length ?? 0) > 0)
        .sort(byPopularity),
    });
    return sections;
  }, [customPrompts, communityPrompts]);

  // Distribute the visibleCount budget across sections in order. Each
  // section keeps its header always visible; items under it appear as
  // the budget reaches them while scrolling.
  const totalPrompts = useMemo(
    () => promptSections.reduce((n, s) => n + s.items.length, 0),
    [promptSections],
  );
  const sectionsToRender = useMemo(() => {
    let remaining = visibleCount;
    return promptSections.map((s) => {
      const slice = s.items.slice(0, Math.max(0, remaining));
      remaining -= s.items.length;
      return { ...s, visibleItems: slice };
    });
  }, [promptSections, visibleCount]);
  const handleLibraryScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 100) {
      setVisibleCount((c) => Math.min(c + PAGE_SIZE, totalPrompts));
    }
  };

  const displayName = userProfile.displayName || "there";

  // Stash the prompt and bounce to /queen-routing immediately. The classify
  // LLM call (2-5s) runs on the routing screen rather than blocking nav, so
  // the user never watches a spinner on the home page.
  //
  // No-credit branch: classification itself is an LLM call, so a 0/negative
  // balance would just 402. Skip routing, send the user straight to their
  // preferred queen with the prompt stashed for the queen-DM composer —
  // queen-dm will defer session bootstrap and show the upgrade popup.
  // Spin up a colony deployed to an explicit queen, uniquifying the name
  // against existing colonies so we never silently reuse one (mirrors the
  // queen-routing uniquifier), then land on its page. Shared by the
  // prompt-detail Deploy and the prompt-seeded fast path — neither hits the
  // classify LLM call because both already know their queen.
  const deployColony = async ({
    queenId,
    colonyName,
    goal,
  }: {
    queenId: string;
    colonyName: string;
    goal: string;
  }) => {
    const taken = new Set(colonies.map((c) => c.id));
    let slug = colonyName;
    let colonyId = slugToColonyId(slug);
    for (let n = 2; taken.has(colonyId); n++) {
      slug = `${colonyName}_${n}`;
      colonyId = slugToColonyId(slug);
    }
    const created = await sessionsApi.create({
      colonyId: slug,
      colonyGoal: goal,
      queenName: queenId,
      initialPhase: "colony",
    });
    refresh();
    const actualColonyId = slugToColonyId(created.colony_id ?? slug);
    navigate(`/colony/${actualColonyId}`, { state: { initialGoal: goal } });
  };

  const startQueenSession = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    // Guard against double-sends: creating a colony can take a few seconds, and
    // an unguarded button would let the user fire several launches (and several
    // colonies) before the first navigates away.
    if (sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    try {
    // Persist whatever the user filled into the placeholder pills, then collapse
    // the `{{label::value}}` tokens to their values so the agent gets the real
    // text. Skills already ride along inline as <read_skill> markers.
    cachePlaceholderValues(collectPlaceholderValues(trimmed));
    const steered = resolvePlaceholders(trimmed);
    // A prompt-seeded message already knows its queen (the card carried a
    // queen_id, or its category mapped to one). Deploy straight there — same
    // path as the prompt-detail Deploy — skipping the classify LLM round-trip
    // and the routing spinner. Consume the hint here (it's also cleared when
    // the box is emptied); a hand-typed task has no origin and classifies.
    const origin = promptOrigin;
    setPromptOrigin(null);
    // A prompt-seeded message already carries an explicitly chosen queen —
    // deploy straight there. Everything hand-typed opens the queen picker:
    // starting a conversation is the user's call, so they hand-pick who to
    // talk to. (The /queen-routing LLM classification is deprecated — a
    // classifier guessing the counterpart was the wrong design for
    // conversations.)
    const target: { queenId: string; colonyName: string } | null =
      origin && deployQueens.some((q) => q.id === origin.queenId) ? origin : null;
    if (target) {
      await deployColony({ ...target, goal: steered });
      return;
    }
    setQueenPick(steered);
    } finally {
      // Navigation usually unmounts this page; reset for the error/stay path.
      sendingRef.current = false;
      setSending(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim()) return;
    void startQueenSession(inputValue);
  };

  // Resolve the queen a prompt should deploy to without an LLM call, mirroring
  // PromptDetailModal's precedence exactly: its DB queen_id (featured prompts),
  // then the category→queen mapping, then Head of Growth as the catch-all, then
  // any deployable queen. This way a prompt with a category that maps to a
  // hidden/decommissioned queen still deploys instantly instead of falling
  // through to the classify spinner. Returns null only when the user has no
  // deployable queens at all (classify wouldn't help there either).
  const resolveQueenHint = (item: PromptItem): string | null => {
    const avail = (id?: string | null): id is string =>
      !!id && deployQueens.some((q) => q.id === id);
    const fromDb = (item as { queen_id?: string | null }).queen_id;
    if (avail(fromDb)) return fromDb;
    const wanted = categoryToQueen[item.category];
    if (avail(wanted)) return wanted;
    if (avail("queen_growth")) return "queen_growth";
    return deployQueens[0]?.id ?? null;
  };

  const handlePromptHint = (item: PromptItem) => {
    // Seed the editor with the prompt — inline <read_skill> markers render as
    // chips, and `{{…}}` placeholders are prefilled (cache → /me) so emails /
    // websites show real values in editable pills.
    setInputValue(prefill(item.content));
    // Remember the prompt's queen + colony name so submitting deploys straight
    // there, skipping classification. Cleared when the box is emptied or sent.
    const queenId = resolveQueenHint(item);
    setPromptOrigin(
      queenId ? { queenId, colonyName: titleToColonySlug(item.title) } : null,
    );
    setTimeout(() => editorRef.current?.focus(), 0);
  };

  const handleInputChange = (value: string) => {
    setInputValue(value);
    // A fully-cleared box means the user is starting fresh — drop the prompt's
    // queen hint so a hand-typed task classifies normally instead of inheriting
    // the old queen.
    if (!value.trim()) setPromptOrigin(null);
  };

  // Deploy a prompt from its detail popup: spin up a colony session seeded with
  // the (possibly edited) goal. Placeholder pill values are cached and resolved
  // to their real text before the colony is created.
  const handleDeployFromDetail = async ({ queenId, colonyName, goal }: DeployArgs): Promise<boolean> => {
    cachePlaceholderValues(collectPlaceholderValues(goal));
    await deployColony({ queenId, colonyName, goal: resolvePlaceholders(goal) });
    return true;
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-start pt-6 px-6 pb-10 relative overflow-hidden">
      {detailPrompt && (
        <PromptDetailModal
          prompt={detailPrompt}
          queens={deployQueens}
          prefill={prefill}
          onClose={() => setDetailPrompt(null)}
          onDeploy={handleDeployFromDetail}
        />
      )}
      {/* Decorative hexagons scattered around the edges */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
        {(() => {
          const clusters: { x: string; y: string; scale: number; opacity: number; rotate: number }[] = [
            { x: "5%",  y: "8%",  scale: 1.2, opacity: 0.13, rotate: 12 },
            { x: "85%", y: "5%",  scale: 0.9, opacity: 0.10, rotate: -8 },
            { x: "92%", y: "35%", scale: 1.0, opacity: 0.11, rotate: 15 },
            { x: "88%", y: "75%", scale: 1.3, opacity: 0.09, rotate: -20 },
            { x: "8%",  y: "80%", scale: 1.1, opacity: 0.10, rotate: 5 },
            { x: "3%",  y: "45%", scale: 0.8, opacity: 0.14, rotate: -12 },
            { x: "20%", y: "3%",  scale: 0.7, opacity: 0.09, rotate: 30 },
            { x: "75%", y: "90%", scale: 0.85, opacity: 0.10, rotate: -5 },
            { x: "50%", y: "2%",  scale: 0.6, opacity: 0.07, rotate: 18 },
            { x: "45%", y: "92%", scale: 0.7, opacity: 0.07, rotate: -15 },
          ];
          const size = 40;
          const h = size * Math.sqrt(3);
          // 7-hex flower: center + 6 surrounding
          const flower = [
            [0, 0],
            [1.5 * size, h / 2], [-1.5 * size, h / 2],
            [1.5 * size, -h / 2], [-1.5 * size, -h / 2],
            [0, h], [0, -h],
          ];
          return clusters.map((cluster, ci) => (
            <svg
              key={ci}
              className="absolute text-primary"
              style={{
                left: cluster.x,
                top: cluster.y,
                transform: `translate(-50%, -50%) scale(${cluster.scale}) rotate(${cluster.rotate}deg)`,
                opacity: cluster.opacity,
              }}
              width="260" height="260" viewBox="-130 -130 260 260"
              fill="none" xmlns="http://www.w3.org/2000/svg"
            >
              {flower.map(([dx, dy], fi) => {
                const pts = Array.from({ length: 6 }, (_, k) => {
                  const angle = (Math.PI / 3) * k - Math.PI / 6;
                  return `${dx + size * Math.cos(angle)},${dy + size * Math.sin(angle)}`;
                }).join(" ");
                return (
                  <polygon
                    key={fi}
                    points={pts}
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinejoin="round"
                    fill={fi === 0 ? "currentColor" : "none"}
                    fillOpacity={fi === 0 ? 0.12 : 0}
                  />
                );
              })}
            </svg>
          ));
        })()}
        {/* Radial fade — transparent center, solid background at edges */}
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,var(--background)_25%,transparent_70%)]" />
      </div>

      <div className="w-full max-w-3xl flex flex-col relative z-30 flex-shrink-0">
        {/* Personalized greeting */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-foreground mb-2">
            Hey {displayName}, what can I help you with?
          </h1>
          <p className="text-sm text-muted-foreground">
            Describe a task and I'll deploy an agent to handle it
          </p>
        </div>

        {/* Chat input */}
        <form onSubmit={handleSubmit} className="mb-6 relative">
          <div className="relative border border-border/60 rounded-xl bg-card/50 hover:border-primary/30 focus-within:border-primary/40 transition-colors shadow-sm">
            <SkillTextEditor
              ref={editorRef}
              value={inputValue}
              onChange={handleInputChange}
              onSubmit={() => startQueenSession(inputValue)}
              placeholder="Describe a task for the hive...  (type / to add a skill)"
              suggestionPlacement="down"
              maxHeightPx={320}
              className="px-5 py-4 pr-12 text-sm text-foreground"
            />
            <div className="absolute right-3 bottom-2.5">
              <button
                type="submit"
                disabled={!inputValue.trim() || sending}
                className="w-8 h-8 rounded-lg bg-primary/90 hover:bg-primary text-primary-foreground flex items-center justify-center transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {sending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>
        </form>
      </div>

      {/* Prompt library, inline card grid. Click a card to seed the
          textarea above; Copy / Deploy work the same as on the full
          library page. Sections render in the canonical order ("My
          Prompts" first, then categories); cards are paginated
          globally — scroll near the bottom and the next 30 mount.
          Lives in its own wider column (~30% wider than the search
          column) so three cards fit comfortably side by side. */}
      {totalPrompts > 0 && (
        <div className="w-full max-w-5xl flex-1 min-h-0 flex flex-col relative z-20">
          <div
            className="rounded-xl overflow-y-auto flex-1 min-h-0 -mx-2 px-2"
            aria-label="Prompt library"
            onScroll={handleLibraryScroll}
          >
            {sectionsToRender.map((section) => (
              section.visibleItems.length === 0 ? null : (
                <div key={section.id} className="mb-5">
                  <div className="sticky top-0 z-10 bg-background/90 backdrop-blur py-1.5 flex items-center justify-between text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                    <span>{section.name}</span>
                    {section.id === "_community" && (
                      <button
                        onClick={() => navigate("/prompt-library")}
                        className="font-medium normal-case tracking-normal text-muted-foreground/70 hover:text-foreground transition-colors"
                      >
                        View all →
                      </button>
                    )}
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-2">
                    {section.visibleItems.map((item, i) => (
                      // The first card doubles as the onboarding tour's
                      // "pick a playbook" spotlight target (see Tutorial/steps.ts).
                      <div
                        key={item.id}
                        // `grid` so the card stretches to fill the cell exactly
                        // as it did when it was the grid item itself.
                        className="grid"
                        data-tour={i === 0 && section === sectionsToRender[0] ? "tour-playbook-card" : undefined}
                      >
                        <PromptCard
                          prompt={item}
                          onSelect={() => handlePromptHint(item)}
                          onDetail={() => setDetailPrompt(item)}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )
            ))}
            {visibleCount < totalPrompts && (
              <div className="py-3 text-[10px] text-muted-foreground/60 text-center">
                Scroll for more ({totalPrompts - visibleCount} remaining)
              </div>
            )}
          </div>
        </div>
        )}

      {/* Hand-pick the queen for a hand-typed message (replaces the
          deprecated /queen-routing LLM classification). */}
      {queenPick !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onMouseDown={() => setQueenPick(null)}
        >
          <div
            className="w-[24rem] max-w-[92vw] rounded-xl border border-border/60 bg-card p-4 shadow-xl"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="text-sm font-semibold text-foreground mb-1">
              Who do you want to talk to?
            </div>
            <div className="text-[11px] text-muted-foreground mb-3">
              Your message is sent to the queen you pick.
            </div>
            <div className="max-h-[50vh] overflow-y-auto flex flex-col gap-1.5">
              {deployQueens.map((q) => (
                <button
                  key={q.id}
                  onClick={() => {
                    stageComposerHandoff(q.id, queenPick, []);
                    setQueenPick(null);
                    setInputValue("");
                    // ?new=1 is load-bearing: queen-dm consumes the staged
                    // handoff ONLY on the bootstrap path (isBootstrap), and
                    // without the flag the page redirects to the last
                    // session and silently drops the message.
                    navigate(`/queen/${q.id}?new=1`);
                  }}
                  className="w-full text-left rounded-lg border border-border/60 px-3 py-2 text-xs transition-colors hover:border-primary/40 hover:bg-primary/5"
                >
                  <span className="font-semibold text-foreground">{q.name}</span>
                  {q.title && (
                    <span className="ml-2 text-muted-foreground">{q.title}</span>
                  )}
                </button>
              ))}
              {deployQueens.length === 0 && (
                <div className="text-[11px] text-muted-foreground">
                  No active queens — enable one in the Org Chart&apos;s leader
                  catalog.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

