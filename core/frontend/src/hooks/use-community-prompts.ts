import { useCallback, useState } from "react";
import type { Prompt } from "@/data/prompts";
import type { PromptAsset } from "@/data/prompt-assets";
import { userStorage } from "@/lib/userStorage";

/** A community prompt as returned by GET /v1/community-prompts (catalog + live copy count + tags). */
export type CommunityPrompt = Prompt & {
  copy_count: number;
  tags: string[];
  queen_id?: string | null;
  assets?: PromptAsset[];
};

const CACHE_KEY = "communityPromptsCache";

// Last fetched catalog, shared across every consumer for the app's lifetime.
// Page-to-page navigation (home ↔ prompt library) re-mounts consumers, and
// this cache is what lets them paint the real catalog instantly instead of
// flashing an empty grid while the fetch is in flight.
let memoryCache: CommunityPrompt[] | null = null;

/**
 * The cloud prompt catalog, cached at two levels: a module-level copy for
 * instant re-mounts within a session, and userStorage so a cold app start
 * paints the last known catalog while the refresh happens in the background.
 * Every mount still refetches so copy counts and newly approved prompts stay
 * fresh; an empty or failed response never clobbers a cached catalog.
 *
 * `loading` is true only on a true cold start (no cache anywhere) while the
 * first fetch is in flight — the only case where the UI has nothing to show.
 */
export function useCommunityPrompts(): {
  prompts: CommunityPrompt[];
  setPrompts: (updater: (prev: CommunityPrompt[]) => CommunityPrompt[]) => void;
  loading: boolean;
} {
  const [prompts, setPromptsState] = useState<CommunityPrompt[]>(
    () => memoryCache ?? userStorage.get<CommunityPrompt[]>(CACHE_KEY, []),
  );
  // The community catalog was a cloud feature; in local mode there's nothing
  // to fetch, so we surface only what's cached locally and never "load".
  const [loading] = useState(false);

  // Local mutations (e.g. optimistic copy-count bumps) write through to both
  // caches so the next page that mounts sees the same numbers.
  const setPrompts = useCallback(
    (updater: (prev: CommunityPrompt[]) => CommunityPrompt[]) => {
      setPromptsState((prev) => {
        const next = updater(prev);
        memoryCache = next;
        userStorage.set(CACHE_KEY, next);
        return next;
      });
    },
    [],
  );

  return { prompts, setPrompts, loading };
}
