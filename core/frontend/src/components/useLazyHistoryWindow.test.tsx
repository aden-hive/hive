/**
 * DOM integration tests for the lazy older-history windowing hook.
 *
 * jsdom has no layout engine, so `./src/test/layout.ts` installs a
 * controllable one (scrollHeight = sum of `data-test-h` children,
 * clientHeight = `data-test-vh`, plus mockable ResizeObserver and
 * requestAnimationFrame). The harness below renders the same scroll-
 * container shape ChatPanel uses, so the REAL hook code runs against
 * deterministic layout maths.
 *
 * Core regression: when the rendered transcript is shorter than the
 * viewport there is no scrollbar and no scroll events — the auto-fill
 * effect must still reveal older messages so the "Loading older messages…"
 * indicator never hangs, and it must do so without an unbounded synchronous
 * setState cascade ("maximum update depth exceeded").
 */
import { useRef, useState } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import {
  flushAnimationFrames,
  flushResizeObservers,
  installLayoutShim,
  uninstallLayoutShim,
} from "@/test/layout";
import {
  INITIAL_VISIBLE_COUNT,
  useLazyHistoryWindow,
  type HistoryDay,
  type LazyHistoryWindow,
} from "@/components/useLazyHistoryWindow";

beforeAll(installLayoutShim);
afterAll(uninstallLayoutShim);
afterEach(cleanup);

const SPINNER_TEXT = "Loading older messages";

interface HarnessProps {
  total: number;
  rowHeight: number;
  viewport: number;
  sink: (w: LazyHistoryWindow) => void;
  /** Initial stick-to-bottom state. Default true (mount / parked at bottom).
   *  Pass false to model a user who has scrolled up — that's what activates
   *  the element-anchor capture/restore path. */
  stick?: boolean;
}

/** Mirrors ChatPanel's scroll container: a spinner, the visible message
 *  rows, and a bottom spacer — each carrying the `data-test-*` attrs the
 *  layout shim reads. Rows carry a STABLE `data-message-id`: the window shows
 *  the last `shown` of `total`, so render row `i` is message
 *  `total - shown + i` — its id is stable across reveals (more rows appear
 *  ABOVE it), which is what the scroll anchor keys on. */
function Harness(props: HarnessProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomSpacerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(props.stick ?? true);
  const win = useLazyHistoryWindow({
    scrollRef,
    bottomSpacerRef,
    stickToBottomRef: stickToBottom,
    resetKey: "session-1",
    totalMessages: props.total,
  });
  props.sink(win);
  const shown = Math.min(win.visibleCount, props.total);
  const firstShown = props.total - shown;
  return (
    <div ref={scrollRef} data-testid="scroll" data-test-vh={props.viewport}>
      {win.hasMoreOlder && (
        <div data-testid="spinner" data-test-h={16}>
          {SPINNER_TEXT}…
        </div>
      )}
      {Array.from({ length: shown }).map((_, i) => (
        <div
          key={firstShown + i}
          data-message-id={`m${firstShown + i}`}
          data-test-h={props.rowHeight}
          data-row
        />
      ))}
      <div ref={bottomSpacerRef} data-spacer style={{ height: "0px" }} />
    </div>
  );
}

/** Drain the auto-fill loop: each round flushes the queued frame inside
 *  `act()` so React commits the re-render that queues the next one.
 *  Returns the number of rounds (capped — a runaway loop fails fast). */
function settle(maxRounds = 600): number {
  let rounds = 0;
  for (; rounds < maxRounds; rounds++) {
    let ran = 0;
    act(() => {
      ran = flushAnimationFrames();
    });
    if (ran === 0) break;
  }
  return rounds;
}

/** Like `settle` but awaits microtasks each round so a page fetch's
 *  `Promise.finally` (which clears the in-flight guard) actually runs —
 *  synchronous `act` does not drain the microtask queue. Used by the paging
 *  tests, whose `onFetchOlderPage*` callbacks resolve on a microtask. */
async function settleAsync(maxRounds = 600): Promise<number> {
  let rounds = 0;
  for (; rounds < maxRounds; rounds++) {
    let ran = 0;
    // eslint-disable-next-line no-await-in-loop
    await act(async () => {
      ran = flushAnimationFrames();
      await Promise.resolve(); // flush the in-flight-clearing microtask
    });
    if (ran === 0) break;
  }
  return rounds;
}

/** Render the harness, drain the auto-fill animation frames, and return
 *  the last hook result + render utilities. */
function mount(props: Omit<HarnessProps, "sink">) {
  let latest: LazyHistoryWindow | null = null;
  const utils = render(<Harness {...props} sink={(w) => (latest = w)} />);
  settle();
  return { win: () => latest as unknown as LazyHistoryWindow, ...utils };
}

/** Like `mount` but leaves the auto-fill loop un-flushed, so the
 *  scroll-driven `loadOlderStep` gate can be exercised in isolation
 *  without auto-fill racing it (auto-fill drains the current session
 *  fully — see the hook — which would otherwise swallow the manual
 *  increments these tests assert on). */
function mountNoAutoFill(props: Omit<HarnessProps, "sink">) {
  let latest: LazyHistoryWindow | null = null;
  // Model a scrolled-up user (stick=false) so the element-anchor path is live.
  const utils = render(
    <Harness stick={false} {...props} sink={(w) => (latest = w)} />,
  );
  return { win: () => latest as unknown as LazyHistoryWindow, ...utils };
}

describe("useLazyHistoryWindow — auto-fill", () => {
  it("grows the window until the viewport overflows (stuck-spinner fix)", () => {
    // 300 messages, 10px each, 2000px viewport. The initial 30-message
    // window (300px) is far shorter than the viewport — without auto-fill
    // no scrollbar exists and the window would freeze at 30.
    const { win, getByTestId } = mount({
      total: 300,
      rowHeight: 10,
      viewport: 2000,
    });
    expect(win().visibleCount).toBeGreaterThan(INITIAL_VISIBLE_COUNT);
    const scroll = getByTestId("scroll");
    // Auto-fill stops once a real scrollbar exists.
    expect(scroll.scrollHeight).toBeGreaterThan(scroll.clientHeight);
  });

  it("reveals the whole transcript when even all of it cannot overflow", () => {
    // 300 ultra-compact rows (2px — merged tool pills) never fill a 600px
    // viewport. The spinner must still clear: every message gets revealed.
    const { win, queryByTestId } = mount({
      total: 300,
      rowHeight: 2,
      viewport: 600,
    });
    expect(win().visibleCount).toBeGreaterThanOrEqual(300);
    expect(win().hiddenOlderCount).toBe(0);
    expect(win().hasMoreOlder).toBe(false);
    expect(queryByTestId("spinner")).toBeNull();
  });

  it("auto-fills the whole current session even when the window already overflows", () => {
    // 30 tall rows (200px) overflow a 400px viewport immediately — but the
    // current session's own messages must never be stranded in the hidden
    // window behind the "Loading older messages…" indicator. Auto-fill
    // drains all 300 regardless of overflow; the overflow gate applies
    // only to the (expensive) history-session cascade.
    const { win, queryByTestId } = mount({
      total: 300,
      rowHeight: 200,
      viewport: 400,
    });
    expect(win().visibleCount).toBeGreaterThanOrEqual(300);
    expect(win().hiddenOlderCount).toBe(0);
    expect(win().hasMoreOlder).toBe(false);
    expect(queryByTestId("spinner")).toBeNull();
  });

  it("settles immediately for a tiny session with no older history", () => {
    const { win, queryByTestId } = mount({
      total: 8,
      rowHeight: 10,
      viewport: 2000,
    });
    expect(win().hiddenOlderCount).toBe(0);
    expect(win().hasMoreOlder).toBe(false);
    expect(queryByTestId("spinner")).toBeNull();
  });
});

describe("useLazyHistoryWindow — scroll-driven loadOlderStep", () => {
  it("reveals one increment per pinned step and applies the pin offset", () => {
    // Auto-fill is left un-flushed, so every window growth here is
    // scroll-driven. Consecutive pinned steps are NOT blocked: each step
    // resolves the previous step's pin anchor (applying its height growth to
    // scrollTop) before revealing the next chunk.
    const { win, getByTestId } = mountNoAutoFill({
      total: 300,
      rowHeight: 200,
      viewport: 400,
    });
    const scroll = getByTestId("scroll");
    expect(win().visibleCount).toBe(30);

    // Each pinned reveal shifts scrollTop by the exact height of the newly
    // shown (older) messages, synchronously the same frame — so the prepend is
    // invisible. 30→60 rows × 200px = +6000.
    act(() => {
      win().loadOlderStep();
    });
    expect(win().visibleCount).toBe(60);
    expect(scroll.scrollTop).toBe(6000);

    // A second step is not blocked; its pin adds another 6000 (60→90 rows).
    let allowed: boolean | undefined;
    act(() => {
      allowed = win().loadOlderStep();
    });
    expect(allowed).toBe(true);
    expect(win().visibleCount).toBe(90);
    expect(scroll.scrollTop).toBe(12000);
  });

  it("does NOT block when a reveal adds zero height (worker-bubble collapse)", () => {
    // Rows of height 0 model a page of events that collapses into a worker
    // bubble's "+N tools" counter without growing the container. The pin
    // ResizeObserver never fires (no growth), but consecutive steps must keep
    // revealing — the old time-based block froze loading for half a second on
    // every such step, forcing the user to "vibrate" the scrollbar.
    const { win } = mountNoAutoFill({ total: 300, rowHeight: 0, viewport: 400 });
    expect(win().visibleCount).toBe(30);

    for (let i = 2; i <= 6; i++) {
      let stepped: boolean | undefined;
      act(() => {
        stepped = win().loadOlderStep();
      });
      expect(stepped).toBe(true);
      expect(win().visibleCount).toBe(i * 30);
    }
  });
});

/** Anchoring harness: renders a fixed set of messages (no windowing — all
 *  fit), each with a stable `data-message-id` and an individually controllable
 *  height. Lets a test scroll to a position, then change the canvas length
 *  *anywhere* and fire the ResizeObserver to prove the anchored element holds
 *  its on-screen position. */
function AnchorHarness(props: {
  sink: (w: LazyHistoryWindow) => void;
  heights: number[];
  viewport: number;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomSpacerRef = useRef<HTMLDivElement>(null);
  const stick = useRef(false); // user has scrolled up → anchoring is live
  const win = useLazyHistoryWindow({
    scrollRef,
    bottomSpacerRef,
    stickToBottomRef: stick,
    resetKey: "session-1",
    totalMessages: props.heights.length,
  });
  props.sink(win);
  return (
    <div ref={scrollRef} data-testid="scroll" data-test-vh={props.viewport}>
      {props.heights.map((h, i) => (
        <div key={i} data-message-id={`m${i}`} data-test-h={h} />
      ))}
      <div ref={bottomSpacerRef} style={{ height: "0px" }} />
    </div>
  );
}

describe("useLazyHistoryWindow — deterministic anchoring on any canvas change", () => {
  it("holds the anchored element when content GROWS ABOVE it (in-place, no reveal)", () => {
    // 10 rows × 100px. Scroll so m3 sits at the viewport top, then grow m0 by
    // 50px (e.g. a worker bubble streaming) and fire the ResizeObserver. The
    // anchored row must keep its exact on-screen position: scrollTop shifts by
    // precisely the 50px added above it — no teleport.
    let latest: LazyHistoryWindow | null = null;
    const base = Array(10).fill(100);
    const { getByTestId, rerender } = render(
      <AnchorHarness heights={base} viewport={400} sink={(w) => (latest = w)} />,
    );
    const scroll = getByTestId("scroll");
    // Scrolling captures the anchor (m3's top at the viewport top → offset 0).
    act(() => {
      scroll.scrollTop = 300;
    });
    const grown = [...base];
    grown[0] = 150;
    act(() => {
      rerender(
        <AnchorHarness heights={grown} viewport={400} sink={(w) => (latest = w)} />,
      );
    });
    act(() => flushResizeObservers()); // RO fires after the grown DOM commits
    expect(scroll.scrollTop).toBe(350);
    void latest;
  });

  it("does NOT move when content grows BELOW the anchor (live append while reading)", () => {
    // Same setup; grow m8 (well below the anchored m3). The reader must not be
    // disturbed — scrollTop stays put.
    let latest: LazyHistoryWindow | null = null;
    const base = Array(10).fill(100);
    const { getByTestId, rerender } = render(
      <AnchorHarness heights={base} viewport={400} sink={(w) => (latest = w)} />,
    );
    const scroll = getByTestId("scroll");
    act(() => {
      scroll.scrollTop = 300;
    });
    const grown = [...base];
    grown[8] = 400;
    act(() => {
      rerender(
        <AnchorHarness heights={grown} viewport={400} sink={(w) => (latest = w)} />,
      );
    });
    act(() => flushResizeObservers());
    expect(scroll.scrollTop).toBe(300);
    void latest;
  });
});

/** History harness: the current session fits the viewport, so the only
 *  thing left to reveal is the timeline. Day/session expansion + message
 *  "loading" are real React state with REAL TOGGLE semantics (delete when
 *  present) — exactly like queen-dm's handlers — so the cascade is proven
 *  not to ping-pong an already-open item back closed. */
function HistoryHarness(props: {
  timeline: HistoryDay[];
  sink: (w: LazyHistoryWindow) => void;
  /** Current-session message count. 0 models "session still loading". */
  totalMessages?: number;
}) {
  const total = props.totalMessages ?? 5;
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomSpacerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [days, setDays] = useState<Set<string>>(new Set());
  const [sessions, setSessions] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState<Record<string, never[]>>({});
  const toggle = (set: Set<string>, key: string): Set<string> => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  };
  const win = useLazyHistoryWindow({
    scrollRef,
    bottomSpacerRef,
    stickToBottomRef: stickToBottom,
    resetKey: "session-1",
    totalMessages: total,
    historyTimeline: props.timeline,
    expandedHistoryDays: days,
    onToggleHistoryDay: (k) => setDays((p) => toggle(p, k)),
    expandedHistorySessions: sessions,
    onToggleHistorySession: (id) => {
      setSessions((p) => toggle(p, id));
      setLoaded((p) => (id in p ? p : { ...p, [id]: [] }));
    },
    historySessionMessages: loaded,
  });
  props.sink(win);
  return (
    <div ref={scrollRef} data-testid="scroll" data-test-vh={2000}>
      {win.hasMoreOlder && (
        <div data-testid="spinner" data-test-h={16}>
          {SPINNER_TEXT}…
        </div>
      )}
      {Array.from({ length: Math.min(win.visibleCount, total) }).map((_, i) => (
        <div key={i} data-test-h={10} data-row />
      ))}
      <div ref={bottomSpacerRef} style={{ height: "0px" }} />
    </div>
  );
}

describe("useLazyHistoryWindow — history timeline auto-expand", () => {
  it("cascades through collapsed days and sessions without ping-ponging", () => {
    const timeline: HistoryDay[] = [
      { key: "d1", label: "Mon", sessions: [{ session_id: "s1", created_at: 1 }] },
      { key: "d2", label: "Tue", sessions: [{ session_id: "s2", created_at: 2 }] },
    ];
    let latest: LazyHistoryWindow | null = null;
    const { queryByTestId } = render(
      <HistoryHarness timeline={timeline} sink={(w) => (latest = w)} />,
    );
    // Drain the deferred auto-fill steps. A ping-pong (toggling an already-
    // open item back closed) would never settle and `settle` would hit its
    // round cap; a monotonic cascade settles in a handful of rounds.
    const rounds = settle();
    expect(rounds).toBeLessThan(100);
    const win = latest as unknown as LazyHistoryWindow;
    // Every day expanded and every session loaded, purely from auto-fill.
    expect(win.hasMoreOlder).toBe(false);
    expect(queryByTestId("spinner")).toBeNull();
  });

  it("does NOT cascade into history while the current session is still empty", () => {
    // totalMessages: 0 models the active session still loading. The history
    // cascade must stay put — loading a days-old session before today's
    // session has restored is the bug this guards.
    const timeline: HistoryDay[] = [
      { key: "d1", label: "Mon", sessions: [{ session_id: "s1", created_at: 1 }] },
      { key: "d2", label: "Tue", sessions: [{ session_id: "s2", created_at: 2 }] },
    ];
    let latest: LazyHistoryWindow | null = null;
    render(
      <HistoryHarness
        timeline={timeline}
        totalMessages={0}
        sink={(w) => (latest = w)}
      />,
    );
    settle();
    const win = latest as unknown as LazyHistoryWindow;
    // No history day/session was expanded — loadOlderStep refused to run.
    expect(win.loadOlderStep()).toBe(false);
  });
});

/** Serialized-loading harness. `onToggleHistorySession` only OPENS a
 *  session — it does not load it. The test drives `resolve(id)` to land a
 *  session's messages, modelling the async `eventsHistory` fetch, so the
 *  one-at-a-time gate can be observed. */
interface SerialControls {
  win: LazyHistoryWindow;
  open: string[];
  resolve: (id: string) => void;
}
function SerialHistoryHarness(props: {
  timeline: HistoryDay[];
  sink: (c: SerialControls) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomSpacerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [days, setDays] = useState<Set<string>>(new Set());
  const [sessions, setSessions] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState<Record<string, never[]>>({});
  const win = useLazyHistoryWindow({
    scrollRef,
    bottomSpacerRef,
    stickToBottomRef: stickToBottom,
    resetKey: "session-1",
    totalMessages: 5,
    historyTimeline: props.timeline,
    expandedHistoryDays: days,
    onToggleHistoryDay: (k) =>
      setDays((p) => {
        const n = new Set(p);
        n.add(k);
        return n;
      }),
    expandedHistorySessions: sessions,
    // Open only — the fetch is modelled separately via `resolve`.
    onToggleHistorySession: (id) =>
      setSessions((p) => {
        const n = new Set(p);
        n.add(id);
        return n;
      }),
    historySessionMessages: loaded,
  });
  props.sink({
    win,
    open: [...sessions],
    resolve: (id) => setLoaded((p) => ({ ...p, [id]: [] })),
  });
  return (
    <div ref={scrollRef} data-testid="scroll" data-test-vh={2000}>
      {win.hasMoreOlder && <div data-testid="spinner" data-test-h={16} />}
      {Array.from({ length: Math.min(win.visibleCount, 5) }).map((_, i) => (
        <div key={i} data-test-h={10} data-row />
      ))}
      <div ref={bottomSpacerRef} style={{ height: "0px" }} />
    </div>
  );
}

/** Current-session paging harness. Models infinite scroll: the newest page
 *  seeds `base` messages; each `onFetchOlderPage` "lands" another page by
 *  growing `totalMessages`, and `currentSessionHasMoreOlder` stays true until
 *  `maxPages` have been fetched. `fetchCalls` records the network fetches. */
function CurrentPagingHarness(props: {
  sink: (w: LazyHistoryWindow & { fetchCalls: number }) => void;
  base: number;
  pageSize: number;
  maxPages: number;
  rowHeight: number;
  viewport: number;
  /** When true, a fetch records the call but does NOT grow the transcript —
   *  models an in-flight network round-trip so the in-flight guard can be
   *  observed before the page lands. */
  deferLanding?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomSpacerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [pagesLoaded, setPagesLoaded] = useState(0);
  // State (not a ref) so the sink snapshot always reflects the latest count,
  // even in deferLanding mode where the transcript size doesn't change.
  const [fetchCalls, setFetchCalls] = useState(0);
  const total = props.base + pagesLoaded * props.pageSize;
  const hasMore = pagesLoaded < props.maxPages;
  const win = useLazyHistoryWindow({
    scrollRef,
    bottomSpacerRef,
    stickToBottomRef: stickToBottom,
    resetKey: "session-1",
    totalMessages: total,
    currentSessionHasMoreOlder: hasMore,
    onFetchOlderPage: () => {
      setFetchCalls((c) => c + 1);
      if (!props.deferLanding) setPagesLoaded((p) => p + 1);
    },
  });
  props.sink({ ...win, fetchCalls });
  const shown = Math.min(win.visibleCount, total);
  return (
    <div ref={scrollRef} data-testid="scroll" data-test-vh={props.viewport}>
      {win.hasMoreOlder && <div data-testid="spinner" data-test-h={16} />}
      {Array.from({ length: shown }).map((_, i) => (
        <div key={i} data-test-h={props.rowHeight} data-row />
      ))}
      <div ref={bottomSpacerRef} style={{ height: "0px" }} />
    </div>
  );
}

describe("useLazyHistoryWindow — current-session paging", () => {
  it("auto-fetches older pages until the session is fully loaded (nothing can overflow)", async () => {
    // Tiny rows in a tall viewport never overflow, so auto-fill drives the
    // whole session in: it reveals the in-memory window, then fetches the
    // next page, repeating until `maxPages` pages are loaded and shown.
    let latest: (LazyHistoryWindow & { fetchCalls: number }) | null = null;
    const { queryByTestId } = render(
      <CurrentPagingHarness
        sink={(w) => (latest = w)}
        base={5}
        pageSize={50}
        maxPages={3}
        rowHeight={2}
        viewport={2000}
      />,
    );
    await settleAsync();
    const w = latest as unknown as LazyHistoryWindow & { fetchCalls: number };
    expect(w.fetchCalls).toBe(3);
    expect(w.hasMoreOlder).toBe(false);
    expect(w.hiddenOlderCount).toBe(0);
    expect(queryByTestId("spinner")).toBeNull();
  });

  it("fetches at most one more page once the viewport overflows", async () => {
    // After the first page lands the transcript overflows the viewport, so
    // auto-fill must stop fetching further disk pages (the overflow gate).
    let latest: (LazyHistoryWindow & { fetchCalls: number }) | null = null;
    render(
      <CurrentPagingHarness
        sink={(w) => (latest = w)}
        base={5}
        pageSize={200}
        maxPages={5}
        rowHeight={20}
        viewport={400}
      />,
    );
    await settleAsync();
    const w = latest as unknown as LazyHistoryWindow & { fetchCalls: number };
    // One page is enough to overflow 400px (205 rows × 20px); no more fetched.
    expect(w.fetchCalls).toBe(1);
    expect(w.hasMoreOlder).toBe(true); // more remain, reachable by scrolling
  });

  it("serializes scroll-driven page fetches (no stacking while in flight)", async () => {
    // A current session that fits the viewport (hiddenOlderCount 0) but has
    // more pages on disk: a scroll step fires exactly one fetch; a second
    // step while the fetch is in flight is refused.
    let latest: (LazyHistoryWindow & { fetchCalls: number }) | null = null;
    render(
      <CurrentPagingHarness
        sink={(w) => (latest = w)}
        base={5}
        pageSize={50}
        maxPages={2}
        rowHeight={10}
        viewport={2000}
        deferLanding
      />,
    );
    const w = () =>
      latest as unknown as LazyHistoryWindow & { fetchCalls: number };

    // First scroll step: hidden window is empty, so step 1.5 fetches a page.
    let first: boolean | undefined;
    act(() => {
      first = w().loadOlderStep();
    });
    expect(first).toBe(true);
    expect(w().fetchCalls).toBe(1);

    // A second step while the fetch is still in flight is refused (no
    // microtask has run yet to clear the in-flight guard).
    let second: boolean | undefined;
    act(() => {
      second = w().loadOlderStep();
    });
    expect(second).toBe(false);
    expect(w().fetchCalls).toBe(1);
  });
});

/** Frontier-paging harness: previous (history) sessions are each paged fully
 *  before the next older one is revealed. Records an ordered ops log of
 *  loads and per-session page fetches so the scroll order can be asserted. */
function FrontierHarness(props: {
  timeline: HistoryDay[];
  sink: (c: { win: LazyHistoryWindow; ops: string[] }) => void;
  maxPagesPerSession: number;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomSpacerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [days, setDays] = useState<Set<string>>(new Set());
  const [sessions, setSessions] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState<Record<string, never[]>>({});
  const [pages, setPages] = useState<Record<string, number>>({});
  const opsRef = useRef<string[]>([]);
  const win = useLazyHistoryWindow({
    scrollRef,
    bottomSpacerRef,
    stickToBottomRef: stickToBottom,
    resetKey: "session-1",
    totalMessages: 5,
    historyTimeline: props.timeline,
    expandedHistoryDays: days,
    onToggleHistoryDay: (k) =>
      setDays((p) => {
        const n = new Set(p);
        n.add(k);
        return n;
      }),
    expandedHistorySessions: sessions,
    onToggleHistorySession: (id) => {
      opsRef.current.push(`load:${id}`);
      setSessions((p) => {
        const n = new Set(p);
        n.add(id);
        return n;
      });
      setLoaded((p) => (id in p ? p : { ...p, [id]: [] }));
      setPages((p) => (id in p ? p : { ...p, [id]: 0 }));
    },
    historySessionMessages: loaded,
    historySessionHasMoreOlder: (id) =>
      id in pages && pages[id] < props.maxPagesPerSession,
    onFetchOlderPageForSession: (id) => {
      opsRef.current.push(`page:${id}`);
      setPages((p) => ({ ...p, [id]: (p[id] ?? 0) + 1 }));
      // Mirror queen-dm: a landed page replaces the session's message array
      // with a new reference, which re-arms the auto-fill effect (its deps
      // include `historySessionMessages`).
      setLoaded((p) => ({ ...p, [id]: [] }));
    },
  });
  props.sink({ win, ops: opsRef.current });
  return (
    <div ref={scrollRef} data-testid="scroll" data-test-vh={2000}>
      {win.hasMoreOlder && <div data-testid="spinner" data-test-h={16} />}
      {Array.from({ length: Math.min(win.visibleCount, 5) }).map((_, i) => (
        <div key={i} data-test-h={10} data-row />
      ))}
      <div ref={bottomSpacerRef} style={{ height: "0px" }} />
    </div>
  );
}

describe("useLazyHistoryWindow — frontier previous-session paging", () => {
  it("pages each previous session fully before revealing the next older one", async () => {
    // One day, two sessions (s1 older, s2 newer). Required scroll order:
    // load s2 → page s2 to exhaustion → load s1 → page s1 to exhaustion.
    const timeline: HistoryDay[] = [
      {
        key: "d1",
        label: "Mon",
        sessions: [
          { session_id: "s1", created_at: 1 },
          { session_id: "s2", created_at: 2 },
        ],
      },
    ];
    let ctl: { win: LazyHistoryWindow; ops: string[] } | null = null;
    render(
      <FrontierHarness
        timeline={timeline}
        maxPagesPerSession={2}
        sink={(c) => (ctl = c)}
      />,
    );
    const rounds = await settleAsync();
    expect(rounds).toBeLessThan(100);
    const c = ctl as unknown as { win: LazyHistoryWindow; ops: string[] };
    expect(c.ops).toEqual([
      "load:s2",
      "page:s2",
      "page:s2",
      "load:s1",
      "page:s1",
      "page:s1",
    ]);
    expect(c.win.hasMoreOlder).toBe(false);
  });
});

describe("useLazyHistoryWindow — serialized history loading", () => {
  it("loads one history session at a time, newest first", () => {
    // historyTimeline is oldest-first; the cascade walks newest-first, so
    // the load order is s4, s3, s2, s1.
    const timeline: HistoryDay[] = [
      {
        key: "d1",
        label: "Mon",
        sessions: [
          { session_id: "s1", created_at: 1 },
          { session_id: "s2", created_at: 2 },
        ],
      },
      {
        key: "d2",
        label: "Tue",
        sessions: [
          { session_id: "s3", created_at: 3 },
          { session_id: "s4", created_at: 4 },
        ],
      },
    ];
    let ctl: SerialControls | null = null;
    render(
      <SerialHistoryHarness timeline={timeline} sink={(c) => (ctl = c)} />,
    );
    const c = () => ctl as unknown as SerialControls;

    // After the first drain only the newest session is open — the gate
    // blocks every other session while its fetch is in flight.
    settle();
    expect(c().open).toEqual(["s4"]);

    // Each resolved load lets exactly one more session open, in order.
    for (const [resolved, nextOpen] of [
      ["s4", ["s4", "s3"]],
      ["s3", ["s4", "s3", "s2"]],
      ["s2", ["s4", "s3", "s2", "s1"]],
    ] as const) {
      act(() => c().resolve(resolved));
      settle();
      expect([...c().open].sort()).toEqual([...nextOpen].sort());
    }

    // Resolving the last one clears the indicator entirely.
    act(() => c().resolve("s1"));
    settle();
    expect(c().win.hasMoreOlder).toBe(false);
  });
});
