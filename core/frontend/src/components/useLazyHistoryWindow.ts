/**
 * Lazy older-history windowing for the chat transcript.
 *
 * The chat panel renders only the most recent `visibleCount` messages and
 * reveals older ones on demand. Older history has two sources, walked in
 * order:
 *   1. the current session's own hidden messages (`hiddenOlderCount` of
 *      the full list are above the window);
 *   2. once that's exhausted, older *sessions* in the history timeline
 *      (queen-DM only — those props are undefined for colony chat).
 *
 * Reveals are driven by two callers:
 *   • `loadOlderStep({ pin: true })` from the scroll handler when the user
 *     nears the top — `pin` stamps a scroll anchor so the pin
 *     ResizeObserver preserves their visual position across the prepend;
 *   • the built-in auto-fill layout effect, which fires whenever the
 *     rendered transcript is too short to overflow the viewport. Without
 *     it a tool-pill-heavy recent turn renders shorter than the viewport,
 *     no scrollbar exists, no scroll events fire, and the "Loading older
 *     messages…" indicator hangs forever with the real conversation stuck
 *     in the hidden window. Auto-fill repeats until the viewport overflows
 *     or all history is exhausted.
 *
 * Extracted from ChatPanel so the windowing logic is unit-testable in
 * isolation (it touches the DOM but none of ChatPanel's context tree).
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MutableRefObject,
  type RefObject,
} from "react";
import type { ChatMessage } from "@/components/ChatPanel";

/** One day-bucket of the history timeline (older sessions, grouped). */
export interface HistoryDay {
  key: string;
  label: string;
  sessions: Array<{
    session_id: string;
    created_at: number;
    last_message?: string | null;
    live?: boolean;
  }>;
}

interface UseLazyHistoryWindowArgs {
  /** The scrollable transcript container. */
  scrollRef: RefObject<HTMLDivElement | null>;
  /** Spacer at the bottom of the transcript; the session-switch pin
   *  effect inflates it for short replies — auto-fill discounts it so
   *  that inflation isn't mistaken for real message overflow. */
  bottomSpacerRef: RefObject<HTMLDivElement | null>;
  /** Shared "user is parked at the bottom" flag. Auto-fill sets it so the
   *  viewport stays pinned to the latest message as older content lands. */
  stickToBottomRef: MutableRefObject<boolean>;
  /** Changing this string resets the window to its initial size (used on
   *  session / thread switch). */
  resetKey: string;
  /** Length of the full (post-filter) message list the window slices. */
  totalMessages: number;
  historyTimeline?: HistoryDay[];
  expandedHistoryDays?: Set<string>;
  onToggleHistoryDay?: (dayKey: string) => void;
  expandedHistorySessions?: Set<string>;
  onToggleHistorySession?: (sessionId: string) => void;
  historySessionMessages?: Record<string, ChatMessage[]>;
  /** True while the CURRENT session has older event pages on disk not yet
   *  fetched (infinite scroll). Paged before the previous-session cascade. */
  currentSessionHasMoreOlder?: boolean;
  /** Fetch the current session's next older page. Returns a promise so the
   *  window can serialize page loads. */
  onFetchOlderPage?: () => Promise<void> | void;
  /** Whether an already-loaded history session still has older pages on disk
   *  — lets the cascade page each previous session fully before revealing the
   *  next older one. */
  historySessionHasMoreOlder?: (sessionId: string) => boolean;
  /** Fetch the next older page of an already-loaded history session. */
  onFetchOlderPageForSession?: (sessionId: string) => Promise<void> | void;
}

export interface LazyHistoryWindow {
  /** How many of the most-recent messages to render. */
  visibleCount: number;
  /** Messages above the window (`totalMessages - visibleCount`, clamped). */
  hiddenOlderCount: number;
  /** True while any older content is still un-revealed — the current
   *  session's hidden window, an un-expanded history day, or a history
   *  session whose messages haven't been fetched. Gates the indicator. */
  hasMoreOlder: boolean;
  /** Reveal one older chunk (or fetch the next page). Returns true if a step
   *  was triggered. Scroll position is preserved automatically by the element
   *  anchor — callers no longer pass a pin flag. */
  loadOlderStep: () => boolean;
}

export const INITIAL_VISIBLE_COUNT = 30;
const LOAD_OLDER_INCREMENT = 30;
// Hard ceiling on auto-fill reveal steps per session — far above any real
// transcript. Pure safety net: every step strictly reduces hiddenOlderCount
// or advances the history cascade, so termination is already guaranteed;
// this only bounds a hypothetical measurement bug.
const AUTO_FILL_STEP_CEILING = 400;
// Below this much overflow the container effectively can't scroll, so the
// scroll handler would never fire — auto-fill must take over.
const OVERFLOW_EPSILON_PX = 24;

/**
 * Distance from the scroll content's top to `el`'s top, summed from the
 * `offsetHeight` of every preceding sibling up the parent chain to `root`.
 *
 * This deliberately avoids `getBoundingClientRect`/`offsetTop`: it depends only
 * on `offsetHeight` + DOM traversal, so it's independent of CSS positioning and
 * works identically in real DOM and under the jsdom test layout shim. The same
 * function records and restores an anchor, so it's self-consistent — any height
 * change *above* `el` (a reveal, a streaming counter, an image decoding) shifts
 * its result by exactly that amount, which is what makes the anchor hold.
 */
function contentTop(el: HTMLElement, root: HTMLElement): number {
  let top = 0;
  let node: HTMLElement | null = el;
  while (node && node !== root) {
    let sib = node.previousElementSibling as HTMLElement | null;
    while (sib) {
      top += sib.offsetHeight;
      sib = sib.previousElementSibling as HTMLElement | null;
    }
    node = node.parentElement;
  }
  return top;
}

export function useLazyHistoryWindow(
  args: UseLazyHistoryWindowArgs,
): LazyHistoryWindow {
  const {
    scrollRef,
    bottomSpacerRef,
    stickToBottomRef,
    resetKey,
    totalMessages,
    historyTimeline,
    expandedHistoryDays,
    onToggleHistoryDay,
    expandedHistorySessions,
    onToggleHistorySession,
    historySessionMessages,
    currentSessionHasMoreOlder,
    onFetchOlderPage,
    historySessionHasMoreOlder,
    onFetchOlderPageForSession,
  } = args;

  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE_COUNT);
  // Scroll anchor: a concrete message element whose on-screen position we hold
  // across any canvas-length change. `offset` is its top's distance below the
  // viewport's top edge at capture time. Null when parked at the bottom (the
  // stick-to-bottom path owns position there) or before the first scroll-up.
  const anchorRef = useRef<{ id: string; offset: number } | null>(null);
  // Set just before `restoreAnchor` writes scrollTop, so the resulting scroll
  // event isn't mistaken for a user scroll (which would re-capture the anchor).
  const programmaticScrollRef = useRef(false);
  // Auto-fill step counter — a circuit breaker (see AUTO_FILL_STEP_CEILING).
  const autoFillStepsRef = useRef(0);
  // requestAnimationFrame id of the in-flight auto-fill step, or 0.
  const autoFillFrameRef = useRef(0);
  // True while an older-page fetch (current session or a history session) is
  // in flight, so a burst of scroll/auto-fill steps doesn't stack fetches.
  const olderPageInFlightRef = useRef(false);

  useLayoutEffect(() => {
    setVisibleCount(INITIAL_VISIBLE_COUNT);
    autoFillStepsRef.current = 0;
    olderPageInFlightRef.current = false;
    anchorRef.current = null;
    programmaticScrollRef.current = false;
    if (autoFillFrameRef.current !== 0) {
      cancelAnimationFrame(autoFillFrameRef.current);
      autoFillFrameRef.current = 0;
    }
  }, [resetKey]);

  const hiddenOlderCount = Math.max(0, totalMessages - visibleCount);

  const historyHasMore =
    !!historyTimeline &&
    historyTimeline.some(
      (d) =>
        !expandedHistoryDays?.has(d.key) ||
        d.sessions.some(
          (s) => historySessionMessages?.[s.session_id] === undefined,
        ),
    );
  // A loaded history session with un-fetched older pages also counts as
  // "more to show" so the indicator stays up while its pages stream in.
  const loadedHistorySessionHasMore =
    !!historyTimeline &&
    !!historySessionHasMoreOlder &&
    historyTimeline.some((d) =>
      d.sessions.some(
        (s) =>
          historySessionMessages?.[s.session_id] !== undefined &&
          historySessionHasMoreOlder(s.session_id),
      ),
    );
  const hasMoreOlder =
    hiddenOlderCount > 0 ||
    !!currentSessionHasMoreOlder ||
    historyHasMore ||
    loadedHistorySessionHasMore;

  // Record the anchor: the topmost message at least partially in view, and how
  // far its top sits below the viewport's top edge. No-op (clears) while parked
  // at the bottom — there the stick-to-bottom path owns the position.
  const captureAnchor = useCallback(() => {
    const root = scrollRef.current;
    if (!root || stickToBottomRef.current) {
      anchorRef.current = null;
      return;
    }
    const scrollTop = root.scrollTop;
    const rows = root.querySelectorAll<HTMLElement>("[data-message-id]");
    for (const el of Array.from(rows)) {
      const top = contentTop(el, root);
      // First message whose bottom is below the viewport top.
      if (top + el.offsetHeight > scrollTop + 1) {
        const id = el.getAttribute("data-message-id");
        if (id) anchorRef.current = { id, offset: top - scrollTop };
        return;
      }
    }
    anchorRef.current = null;
  }, [scrollRef, stickToBottomRef]);

  // Re-assert the anchor: put the anchored element back at its recorded offset
  // below the viewport top. Runs on every canvas-length change, so it holds the
  // user's position no matter why the content grew/shrank (reveal, prepend,
  // streaming counter, image decode, expand). Below-anchor growth doesn't move
  // it. A `programmaticScrollRef` flag stops the write from re-capturing.
  const restoreAnchor = useCallback(() => {
    const root = scrollRef.current;
    const a = anchorRef.current;
    if (!root || !a || stickToBottomRef.current) return;
    let el: HTMLElement | null = null;
    for (const node of Array.from(
      root.querySelectorAll<HTMLElement>("[data-message-id]"),
    )) {
      if (node.getAttribute("data-message-id") === a.id) {
        el = node;
        break;
      }
    }
    if (!el) return; // anchored message scrolled out of the rendered window
    const desired = contentTop(el, root) - a.offset;
    if (Math.abs(root.scrollTop - desired) > 0.5) {
      programmaticScrollRef.current = true;
      root.scrollTop = desired;
    }
  }, [scrollRef, stickToBottomRef]);

  // Capture on genuine user scroll so the anchor tracks wherever the user is.
  // Scrolls that `restoreAnchor` itself triggers are skipped via the flag.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const onScroll = () => {
      if (programmaticScrollRef.current) {
        programmaticScrollRef.current = false;
        return;
      }
      captureAnchor();
    };
    root.addEventListener("scroll", onScroll, { passive: true });
    return () => root.removeEventListener("scroll", onScroll);
  }, [scrollRef, captureAnchor]);

  // Restore on ANY size change of the container or its descendants — this is
  // what catches arbitrary async growth (streaming `+N` counters, image decode,
  // collapsible expand) that lands without a React render here.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const observer = new ResizeObserver(() => restoreAnchor());
    observer.observe(root);
    for (const child of Array.from(root.children)) observer.observe(child);
    const mut = new MutationObserver(() => {
      for (const child of Array.from(root.children)) observer.observe(child);
    });
    mut.observe(root, { childList: true });
    return () => {
      observer.disconnect();
      mut.disconnect();
    };
  }, [scrollRef, restoreAnchor]);

  // Frame-accurate restore on the reveal path: a `visibleCount` bump (or a
  // prepended older page raising `totalMessages`) renders synchronously, so
  // re-assert the anchor in a layout effect before paint — no async lag.
  useLayoutEffect(() => {
    restoreAnchor();
  }, [visibleCount, totalMessages, restoreAnchor]);

  const loadOlderStep = (): boolean => {
    const el = scrollRef.current;
    if (!el) return false;
    // Seed an anchor if we don't have one yet (programmatic reveals / tests
    // where no scroll event preceded this). The scroll listener keeps it
    // updated as the user moves; the restore effects then hold it across the
    // growth this step is about to cause.
    if (anchorRef.current === null) captureAnchor();
    // 1. Current session's hidden window.
    if (hiddenOlderCount > 0) {
      setVisibleCount((c) => c + LOAD_OLDER_INCREMENT);
      return true;
    }
    // 1.5 Current session has more older pages on disk — fetch the next page
    //     before cascading into previous sessions. The page lands in the
    //     hidden window (sliced off above `visibleCount`); step 1 reveals it on
    //     subsequent steps, and the anchor holds the user's position throughout.
    //     `olderPageInFlightRef` serializes fetches.
    if (currentSessionHasMoreOlder && onFetchOlderPage) {
      if (olderPageInFlightRef.current) return false;
      olderPageInFlightRef.current = true;
      Promise.resolve(onFetchOlderPage()).finally(() => {
        olderPageInFlightRef.current = false;
      });
      return true;
    }
    // Never cascade into older sessions until the CURRENT session has
    // messages. When `totalMessages === 0` the session is still loading;
    // `hiddenOlderCount` is 0 only because there's nothing yet — not
    // because the current session is fully shown. Without this guard the
    // history cascade would load a days-old session before today's
    // session has finished restoring.
    if (totalMessages === 0) {
      return false;
    }
    // 2. History timeline cascade (queen-DM only). `historyTimeline` is
    //    ordered oldest-first, so walk it newest-first — scrolling up
    //    reveals progressively older days, each landing directly above the
    //    current session for a continuous transcript. Expand the next
    //    collapsed day, else load the next not-yet-loaded session.
    if (historyTimeline && historyTimeline.length > 0) {
      // 2a. Page the FRONTIER (oldest already-loaded) previous session to
      //     exhaustion before revealing the next older session — so the
      //     scroll order is: prev #1 last page → prev #1 earlier pages →
      //     prev #1 done → prev #2 last page → … A history session's
      //     messages render inline immediately (not via the slice window),
      //     so the prepend grows DOM height — pin it.
      if (onFetchOlderPageForSession && historySessionHasMoreOlder) {
        if (olderPageInFlightRef.current) return false;
        let frontierSid: string | null = null;
        let frontierCreatedAt = Number.POSITIVE_INFINITY;
        for (const day of historyTimeline) {
          for (const s of day.sessions) {
            if (historySessionMessages?.[s.session_id] === undefined) continue;
            if (
              historySessionHasMoreOlder(s.session_id) &&
              s.created_at < frontierCreatedAt
            ) {
              frontierCreatedAt = s.created_at;
              frontierSid = s.session_id;
            }
          }
        }
        if (frontierSid) {
          olderPageInFlightRef.current = true;
          Promise.resolve(onFetchOlderPageForSession(frontierSid)).finally(
            () => {
              olderPageInFlightRef.current = false;
            },
          );
          return true;
        }
      }
      if (onToggleHistoryDay) {
        for (let i = historyTimeline.length - 1; i >= 0; i--) {
          const day = historyTimeline[i];
          if (!expandedHistoryDays?.has(day.key)) {
            onToggleHistoryDay(day.key);
            return true;
          }
        }
      }
      if (onToggleHistorySession) {
        // Serialize history-session loading: one session at a time, newest
        // first. If a previously-expanded session's `eventsHistory` fetch
        // is still in flight (it's open but its messages haven't landed),
        // don't expand another — wait for it. Each session's event log can
        // be large, so a burst of concurrent fetches would replay
        // thousands of events at once. The auto-fill effect re-runs when
        // `historySessionMessages` updates, so the next session loads as
        // soon as the current one resolves.
        const loadInFlight = historyTimeline.some((day) =>
          (expandedHistoryDays?.has(day.key) ?? false) &&
          day.sessions.some(
            (s) =>
              (expandedHistorySessions?.has(s.session_id) ?? false) &&
              historySessionMessages?.[s.session_id] === undefined,
          ),
        );
        if (loadInFlight) return false;

        // Only ever expand a COLLAPSED session. `onToggleHistorySession`
        // is a toggle — calling it on an already-open session would
        // collapse it, and the cascade would ping-pong forever (a
        // "Maximum update depth exceeded" crash).
        let pendingSession: string | null = null;
        for (let i = historyTimeline.length - 1; i >= 0 && !pendingSession; i--) {
          const day = historyTimeline[i];
          if (!expandedHistoryDays?.has(day.key)) continue;
          for (let j = day.sessions.length - 1; j >= 0; j--) {
            const s = day.sessions[j];
            const open = expandedHistorySessions?.has(s.session_id) ?? false;
            if (!open) {
              pendingSession = s.session_id;
              break;
            }
          }
        }
        if (pendingSession) {
          onToggleHistorySession(pendingSession);
          return true;
        }
      }
    }
    return false;
  };

  // Auto-fill: load older content the scroll handler can't, in two modes.
  //
  //  • Parked at the bottom (mount / short transcript): there's no scroll
  //    position to preserve, so reveal the current session's in-memory window
  //    in full (never strand its middle behind the spinner) and fetch/cascade
  //    until the viewport fills — keeping the view pinned to the bottom.
  //  • Scrolled up reading history: position is held by the scroll anchor
  //    (NOT stick-to-bottom, which would yank them down). This only "unsticks"
  //    dense zero-height sections — a page of 500 events that collapses into a
  //    worker bubble's "+N" counter adds no height, so the user gets pinned at
  //    the very top with no way to scroll further; here we chain pages until
  //    real content (with height) appears, then the scroll handler takes over.
  //
  // Each step is deferred onto its own animation frame: revealing a long
  // history timeline (sessions add no height until their async fetch lands)
  // would otherwise be a synchronous setState cascade that trips React's
  // "maximum update depth" guard. One frame is kept in flight
  // (`autoFillFrameRef`) so renders coalesce; the deps below re-arm it
  // whenever content changes.
  useLayoutEffect(() => {
    if (autoFillFrameRef.current !== 0) return; // a step is already queued
    autoFillFrameRef.current = requestAnimationFrame(() => {
      autoFillFrameRef.current = 0;
      const root = scrollRef.current;
      if (!root) return;
      if (!hasMoreOlder) return; // nothing left to load anywhere
      if (autoFillStepsRef.current > AUTO_FILL_STEP_CEILING) return;

      const parkedAtBottom = stickToBottomRef.current;
      let shouldLoad: boolean;
      if (parkedAtBottom) {
        // Discount the bottom spacer: the session-switch effect inflates it
        // to pin a short last reply, and that inflation is not real overflow.
        const spacer = bottomSpacerRef.current?.offsetHeight ?? 0;
        const realOverflow = root.scrollHeight - root.clientHeight - spacer;
        // Drain the in-memory window fully; only fetch/cascade (hidden===0)
        // while the viewport isn't yet filled.
        shouldLoad =
          hiddenOlderCount > 0 || realOverflow <= OVERFLOW_EPSILON_PX;
      } else {
        // The user scrolled up. Normal scrolling is driven by the scroll
        // handler (loads at scrollTop < 240); auto-fill must NOT also fire
        // there or it loads ahead of the user. It only "unsticks" the user
        // when pinned against the very top with more to load — a zero-height
        // page adds no height, leaving scrollTop at ~0 with no scroll event to
        // fire — chaining just enough to surface real content. The anchor
        // holds position throughout; once a reveal adds height the user is no
        // longer at the top and the scroll handler resumes.
        shouldLoad = root.scrollTop <= OVERFLOW_EPSILON_PX;
      }
      if (!shouldLoad) return;

      if (parkedAtBottom) {
        // Keep the viewport pinned to the latest message as content reveals
        // above it, and drop the now-stale short-reply spacer.
        stickToBottomRef.current = true;
        if (bottomSpacerRef.current)
          bottomSpacerRef.current.style.height = "0px";
      }
      if (loadOlderStep()) {
        autoFillStepsRef.current += 1;
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    visibleCount,
    hiddenOlderCount,
    totalMessages,
    historyTimeline,
    expandedHistoryDays,
    expandedHistorySessions,
    historySessionMessages,
    currentSessionHasMoreOlder,
    loadedHistorySessionHasMore,
  ]);

  // Cancel any in-flight auto-fill frame on unmount.
  useEffect(
    () => () => {
      if (autoFillFrameRef.current !== 0) {
        cancelAnimationFrame(autoFillFrameRef.current);
        autoFillFrameRef.current = 0;
      }
    },
    [],
  );

  return { visibleCount, hiddenOlderCount, hasMoreOlder, loadOlderStep };
}
