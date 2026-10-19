import { useEffect, useRef } from "react";
import { userStorage } from "@/lib/userStorage";
import { useRuntime } from "@/context/RuntimeContext";
import { useColony } from "@/context/ColonyContext";
import { useTutorial, TUTORIAL_SEEN_KEY } from "@/components/Tutorial/useTutorial";
import { STARTER_COLONY_ID } from "@/components/Tutorial/demoColony";

/**
 * Single home for brand-new-user setup. Consolidates what used to be two
 * unrelated hooks with drifting "new user" definitions — the starter-colony
 * seed (was `useDefaultColonyInstall`) and the tour auto-play (was inline in
 * `useTutorialState`) — into one mount point so the sequence and its once-only
 * gating live together. Add future first-run behaviour here, not in a new
 * scattered hook.
 *
 * Renders nothing. Mounted inside `TutorialProvider` (see AppLayout) so it can
 * drive the tour, while still reading colony/runtime state from the providers
 * above.
 */

/** Per-user flag — set once the colony seed has been decided (seeded, or the
 *  user already had colonies) so it never runs again for them. */
const COLONY_SEEDED_KEY = "default-colony-installed-v1";

export default function NewUserOnboarding(): null {
  const { status } = useRuntime();
  const { colonies, loading, refresh } = useColony();
  const { start: startTour } = useTutorial();
  const colonyDecided = useRef(false);
  const tourDecided = useRef(false);

  // 1. First-run data — drop the populated demo colony into HIVE_HOME for
  //    brand-new users (no colonies yet). Main owns the copy (idempotent); we
  //    just gate it to genuinely new accounts and record that we've decided.
  useEffect(() => {
    if (colonyDecided.current) return;
    if (userStorage.get<boolean>(COLONY_SEEDED_KEY, false)) {
      colonyDecided.current = true;
      return;
    }
    // Wait until the colony list is trustworthy: runtime up, first fetch done.
    if (status !== "ready" || loading) return;

    colonyDecided.current = true;

    // Existing account — nothing to seed; persist so we never seed over it.
    if (colonies.length > 0) {
      userStorage.set(COLONY_SEEDED_KEY, true);
      return;
    }

    // No native seeding bridge in web mode — the runtime provisions any
    // starter content itself. Just mark onboarding's seed step as handled.
    userStorage.set(COLONY_SEEDED_KEY, true);
    refresh();
  }, [status, loading, colonies.length, refresh]);

  // 2. Onboarding UI — auto-play the tour once for users who haven't seen it.
  //    Deferred so the tour's target elements mount before the spotlight
  //    measures them. (The tour uses a scripted demo colony, so it's
  //    independent of the seed above.)
  useEffect(() => {
    if (tourDecided.current) return;
    tourDecided.current = true;
    if (userStorage.get<boolean>(TUTORIAL_SEEN_KEY, false)) return;
    const handle = window.setTimeout(startTour, 800);
    return () => window.clearTimeout(handle);
  }, [startTour]);

  return null;
}
