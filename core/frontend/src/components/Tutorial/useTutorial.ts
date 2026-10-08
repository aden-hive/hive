import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { userStorage } from "@/lib/userStorage";
import { TUTORIAL_STEPS, type TutorialStep } from "./steps";
import { isIndiaTimezone } from "./tutorialEnv";

/** Per-user flag — flipped to true once the user has dismissed or finished the
 *  tour at least once. Exported so the onboarding orchestrator
 *  (NewUserOnboarding) can decide whether to auto-play the tour. */
export const TUTORIAL_SEEN_KEY = "tutorial-seen-v1";
const SEEN_KEY = TUTORIAL_SEEN_KEY;

interface TutorialContextValue {
  /** True while the overlay is mounted and walking the user through steps. */
  active: boolean;
  /** Current step index when active. */
  index: number;
  /** Static list of steps the tour walks through. */
  steps: TutorialStep[];
  /** Start the tour from step 0. */
  start: () => void;
  /** Advance to the next step, or finish if already on the last one. */
  next: () => void;
  /** Step backwards. No-op at index 0. */
  prev: () => void;
  /** Close the overlay and mark the tour as seen (skip + finish both end up here). */
  finish: () => void;
}

export const TutorialContext = createContext<TutorialContextValue | null>(null);

export function useTutorial(): TutorialContextValue {
  const ctx = useContext(TutorialContext);
  if (!ctx) throw new Error("useTutorial must be used within TutorialProvider");
  return ctx;
}

/** Pure state hook — wired into the provider in TutorialOverlay.tsx so we keep one mount point. */
export function useTutorialState(): TutorialContextValue {
  const [active, setActive] = useState(false);
  const [index, setIndex] = useState(0);

  // The finale ("You're ready" + Calendly CTA) is dropped for users in an
  // India timezone. Computed once — timezone doesn't change mid-session.
  const steps = useMemo<TutorialStep[]>(
    () =>
      isIndiaTimezone()
        ? TUTORIAL_STEPS.filter((s) => s.id !== "done")
        : TUTORIAL_STEPS,
    [],
  );

  // First-login auto-play now lives in NewUserOnboarding (the single first-run
  // orchestrator), which calls start() — so "when the tour opens" sits next to
  // the other new-user setup instead of being split across two hooks.

  const start = useCallback(() => {
    setIndex(0);
    setActive(true);
  }, []);

  const finish = useCallback(() => {
    setActive(false);
    userStorage.set(SEEN_KEY, true);
  }, []);

  const next = useCallback(() => {
    setIndex((i) => {
      if (i >= steps.length - 1) {
        // Defer finish to next tick so callers reading the state mid-update see a clean transition.
        window.setTimeout(() => {
          setActive(false);
          userStorage.set(SEEN_KEY, true);
        }, 0);
        return i;
      }
      return i + 1;
    });
  }, [steps.length]);

  const prev = useCallback(() => {
    setIndex((i) => Math.max(0, i - 1));
  }, []);

  return useMemo(
    () => ({ active, index, steps, start, next, prev, finish }),
    [active, index, steps, start, next, prev, finish],
  );
}
