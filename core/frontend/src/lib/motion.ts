import { useSyncExternalStore } from "react";

/** The user's motion preference. "system" follows the OS
 *  prefers-reduced-motion setting. */
export type MotionPref = "system" | "full" | "reduced";

// The resolved value lives on <html data-motion>, so CSS can gate effects with
// `:root[data-motion="full"]` and components can read it without the theme
// context. A tree without ThemeProvider (tests, isolated renders) never sets it
// and therefore gets every effect's final, static state.
const listeners = new Set<() => void>();

function osPrefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function resolveMotion(pref: MotionPref): "full" | "reduced" {
  if (pref === "system") return osPrefersReducedMotion() ? "reduced" : "full";
  return pref;
}

export function applyMotion(resolved: "full" | "reduced"): void {
  document.documentElement.dataset.motion = resolved;
  listeners.forEach((notify) => notify());
}

function subscribe(notify: () => void): () => void {
  listeners.add(notify);
  return () => listeners.delete(notify);
}

export function isFullMotion(): boolean {
  return document.documentElement.dataset.motion === "full";
}

/** True when decorative motion is on (preference "full", or "system" without
 *  an OS reduced-motion request). */
export function useFullMotion(): boolean {
  return useSyncExternalStore(subscribe, isFullMotion, () => false);
}

/** A pointy-topped hexagon as a CSS polygon(): the honeycomb cell the theme
 *  sweep grows from the click point. */
function hexagon(x: number, y: number, r: number): string {
  const points = Array.from({ length: 6 }, (_, k) => {
    const angle = (Math.PI / 3) * k - Math.PI / 2;
    return `${(x + r * Math.cos(angle)).toFixed(1)}px ${(y + r * Math.sin(angle)).toFixed(1)}px`;
  });
  return `polygon(${points.join(", ")})`;
}

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => { ready: Promise<void> };
};

/** Run `update` (a synchronous DOM change, e.g. swapping the theme class)
 *  inside a view transition that reveals the new page through a honeycomb
 *  cell growing from `origin`. Falls back to a plain update when motion is
 *  reduced or the browser has no View Transitions. */
export function hexReveal(update: () => void, origin: { x: number; y: number } | null): void {
  const doc = document as ViewTransitionDocument;
  if (!doc.startViewTransition || !isFullMotion()) {
    update();
    return;
  }
  const x = origin?.x ?? window.innerWidth / 2;
  const y = origin?.y ?? window.innerHeight / 2;
  // A hexagon's inscribed circle is cos(30°) of its circumradius, so grow the
  // circumradius past the farthest corner by that factor to cover the page.
  const farthest = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  const radius = farthest / Math.cos(Math.PI / 6);
  const transition = doc.startViewTransition(update);
  transition.ready
    .then(() => {
      document.documentElement.animate(
        { clipPath: [hexagon(x, y, 0), hexagon(x, y, radius)] },
        {
          // Ease in-out: a hard ease-out covers the page within the first
          // third and the honeycomb outline never reads.
          duration: 900,
          easing: "cubic-bezier(0.55, 0, 0.25, 1)",
          pseudoElement: "::view-transition-new(root)",
        },
      );
    })
    .catch(() => {});
}
