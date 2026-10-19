import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { GraphNode } from "@/components/graph-types";
import { ApiError } from "@/api/client";
import { colonyWorkersApi } from "@/api/colonyWorkers";
import type { WorkerSummary } from "@/api/colonyWorkers";
import { userStorage } from "@/lib/userStorage";

/** Consecutive 404s from the workers poll before we declare the session
 *  gone and stop polling it. A 404 means the runtime's SessionManager no
 *  longer holds the session in memory (stopped, or the runtime process
 *  restarted) — it can only come back through a selectSession that also
 *  transitions the page's sessionId, which restarts the poll from
 *  scratch. >1 so a freak blip doesn't kill a healthy poll. */
export const SESSION_GONE_404_LIMIT = 3;

export type ColonyTabKey = "overview" | "workers" | "automations" | "data";

const TAB_TABS: readonly ColonyTabKey[] = ["overview", "workers", "automations", "data"];
// Persisted per-colony tab selection (per user, survives logout/login), so
// returning to a colony reopens the tab the user last had selected.
const COLONY_TAB_STORAGE_KEY = "colony-panel-selected-tab";
function loadStoredColonyTabs(): Map<string, ColonyTabKey> {
  const raw = userStorage.get<Record<string, string> | null>(COLONY_TAB_STORAGE_KEY, null);
  const map = new Map<string, ColonyTabKey>();
  if (raw && typeof raw === "object") {
    for (const [name, tab] of Object.entries(raw)) {
      if ((TAB_TABS as readonly string[]).includes(tab)) map.set(name, tab as ColonyTabKey);
    }
  }
  return map;
}

interface ColonyWorkersContextValue {
  /** The colony session the tabbed panel should attach to. Set by
   *  whichever page owns a colony session (colony-chat today). The
   *  panel auto-renders whenever this is non-null AND the user hasn't
   *  dismissed it for the current session. */
  sessionId: string | null;
  setSessionId: (sessionId: string | null) => void;

  /** The colony directory name (e.g. ``linkedin_honeycomb_messaging``)
   *  the panel is attached to. Comes from ``LiveSession.colony_id`` —
   *  legacy naming, but it's the on-disk directory under
   *  ``~/.hive/colonies/`` and the URL segment for the colony-scoped
   *  endpoints (progress + data). Required separately from sessionId
   *  because the URL slug is mangled by ``slugToColonyId`` and can't
   *  be reverse-derived. */
  colonyName: string | null;
  setColonyName: (colonyName: string | null) => void;

  /** User dismissal: flipped by the panel's close button. Reset when
   *  sessionId changes (so the panel re-opens on the next colony visit
   *  / tab-switch) or when the header toggle re-requests it. */
  dismissed: boolean;
  /** Toggles the panel. When the panel is currently visible we dismiss
   *  it; when hidden we un-dismiss. Both actions are no-ops if there's
   *  no active sessionId — the header button only matters inside a
   *  colony room. */
  toggleColonyWorkers: () => void;

  /** Worker the Sessions tab should auto-select on the next render.
   *  Set by ``openColonyWorkers(workerId)`` when a chat avatar is
   *  clicked; cleared by the panel after it consumes the value. */
  focusWorkerId: string | null;
  setFocusWorkerId: (workerId: string | null) => void;

  /** Open the panel and optionally pre-select a worker. Un-dismisses
   *  the panel even if it was previously closed. Passing no workerId
   *  just opens the panel without changing selection. */
  openColonyWorkers: (workerId?: string) => void;

  /** Current session's triggers, pushed from whichever page is active
   *  (colony-chat today). ``ColonyPanel`` reads these to render
   *  its Triggers tab without having to re-subscribe to SSE itself. */
  triggers: GraphNode[];
  setTriggers: (triggers: GraphNode[]) => void;

  /** Live worker list for the active session, polled every 2s. Source
   *  of truth for "is this worker still running?" — readers map their
   *  worker_id to ``workers`` and check ``status`` directly instead of
   *  inferring activity from chat-event heuristics (which break with
   *  parallel batches sharing or interleaving run_ids). Empty when no
   *  session is attached. */
  workers: WorkerSummary[];

  /** Per-colony memory of which drawer tab the user was last on. Persisted
   *  per-user (survives logout/login) so returning to a colony reopens the
   *  same tab, and so the brief sessionId→null→new shuffle triggered by
   *  Deploy-to-cloud doesn't bounce the user back to Overview. Returns null
   *  when this colony has no prior selection — consumers default to "data"
   *  in that case. */
  getTabForColony: (colonyName: string | null) => ColonyTabKey | null;
  setTabForColony: (colonyName: string | null, tab: ColonyTabKey) => void;

  /** Open the cloud-computer overlay for the active colony. Wired by
   *  whichever page owns the live session (colony-chat today) on
   *  mount, cleared on unmount. ``null`` when no colony page is
   *  mounted — consumers should guard before invoking. */
  openCloudView: (() => void) | null;
  setOpenCloudView: (fn: (() => void) | null) => void;

  /** Post a message into the active colony's queen as if the user typed
   *  it. Wired by the page that owns the live session (colony-chat) to
   *  its ``handleSend``, so panel surfaces (e.g. the Sentinel setup
   *  card's "Set this up with the agent" button) can hand the queen a
   *  task without the user retyping it. ``null`` when no colony session
   *  is mounted — guard before invoking. */
  requestQueenPrompt: ((text: string) => void) | null;
  setRequestQueenPrompt: (fn: ((text: string) => void) | null) => void;
}

const ColonyWorkersContext = createContext<ColonyWorkersContextValue | null>(null);

export function ColonyWorkersProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionIdState] = useState<string | null>(null);
  const [colonyName, setColonyName] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [focusWorkerId, setFocusWorkerId] = useState<string | null>(null);
  const [triggers, setTriggers] = useState<GraphNode[]>([]);
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  // Per-colony tab memory. A ref + a tick state forces re-renders on
  // change without making the whole Map a state object (we never want
  // a structural-equal re-mount of every consumer just because someone
  // else's tab changed). Seeded from persisted storage so a returning
  // user lands on the tab they left each colony on.
  const tabByColonyRef = useRef<Map<string, ColonyTabKey> | null>(null);
  if (tabByColonyRef.current === null) tabByColonyRef.current = loadStoredColonyTabs();
  const [, bumpTabTick] = useState(0);
  // Serialized snapshot — skip setState when the poll returns an
  // identical payload so consumers (WorkerRunBubble etc.) don't
  // re-render every 2s with the same data.
  const lastWorkersJsonRef = useRef<string>("");

  const setSessionId = useCallback((next: string | null) => {
    setSessionIdState((prev) => {
      if (prev !== next) {
        // Reset dismissal whenever the active session changes so
        // entering a new colony opens the panel again even if the user
        // closed it in the previous room.
        setDismissed(false);
        // Drop the previous colony's per-session caches eagerly. The
        // owning page (colony-chat) re-publishes triggers as SSE events
        // arrive, but there's a render window during navigation where
        // the new colony is mounted before the previous mirror effect
        // has pushed an empty list — without this, the triggers panel
        // briefly (and sometimes permanently, after B→C→B→A) shows the
        // previous colony's triggers.
        setTriggers([]);
      }
      return next;
    });
  }, []);

  const toggleColonyWorkers = useCallback(() => {
    setDismissed((d) => !d);
  }, []);

  const openColonyWorkers = useCallback((workerId?: string) => {
    setDismissed(false);
    setFocusWorkerId(workerId ?? null);
  }, []);

  const getTabForColony = useCallback(
    (colonyName: string | null): ColonyTabKey | null =>
      colonyName ? tabByColonyRef.current!.get(colonyName) ?? null : null,
    [],
  );
  const setTabForColony = useCallback(
    (colonyName: string | null, tab: ColonyTabKey) => {
      if (!colonyName) return;
      const map = tabByColonyRef.current!;
      if (map.get(colonyName) === tab) return;
      map.set(colonyName, tab);
      userStorage.set(COLONY_TAB_STORAGE_KEY, Object.fromEntries(map));
      bumpTabTick((t) => t + 1);
    },
    [],
  );

  // useState invokes a passed function as an updater, so to STORE a
  // function we have to wrap it in another arrow. Centralising the
  // wrap here lets callers just pass the bare callback.
  const [openCloudView, _setOpenCloudView] = useState<(() => void) | null>(null);
  const setOpenCloudView = useCallback(
    (fn: (() => void) | null) => _setOpenCloudView(() => fn),
    [],
  );

  const [requestQueenPrompt, _setRequestQueenPrompt] = useState<
    ((text: string) => void) | null
  >(null);
  const setRequestQueenPrompt = useCallback(
    (fn: ((text: string) => void) | null) => _setRequestQueenPrompt(() => fn),
    [],
  );

  // Poll the colony workers endpoint while a session is attached.
  // 2s cadence matches the WorkersTab's own poll. Clearing the
  // serialization ref + the list on sessionId change avoids leaking
  // the previous session's workers into the next one's first paint.
  useEffect(() => {
    lastWorkersJsonRef.current = "";
    if (!sessionId) {
      setWorkers([]);
      return;
    }
    let cancelled = false;
    // Circuit breaker: consecutive 404s mean the session is gone from the
    // runtime for good (see SESSION_GONE_404_LIMIT). Without this the poll
    // hammers a dead endpoint every 2s forever — and each miss prints a
    // main-process log line, since the quiet-polling suppression in
    // src/main/ipc.ts only mutes 2xx responses on this path.
    let misses = 0;
    const commit = (next: WorkerSummary[]) => {
      if (cancelled) return;
      const serialized = JSON.stringify(next);
      if (serialized === lastWorkersJsonRef.current) return;
      lastWorkersJsonRef.current = serialized;
      setWorkers(next);
    };
    const tick = () => {
      colonyWorkersApi
        .list(sessionId)
        .then((r) => {
          misses = 0;
          commit(r.workers);
        })
        .catch((e) => {
          if (!(e instanceof ApiError && e.status === 404)) {
            // Transient/other failure — keep full cadence; next tick retries.
            misses = 0;
            return;
          }
          misses += 1;
          if (misses < SESSION_GONE_404_LIMIT) return;
          clearInterval(id);
          // A dead session has no live workers; clear so readers don't
          // keep acting on stale "running" statuses.
          commit([]);
          console.warn(
            `[colony-workers] session ${sessionId} not found (404 ×${misses}); stopping workers poll`,
          );
        });
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [sessionId]);

  return (
    <ColonyWorkersContext.Provider
      value={{
        sessionId,
        setSessionId,
        colonyName,
        setColonyName,
        dismissed,
        toggleColonyWorkers,
        focusWorkerId,
        setFocusWorkerId,
        openColonyWorkers,
        triggers,
        setTriggers,
        workers,
        getTabForColony,
        setTabForColony,
        openCloudView,
        setOpenCloudView,
        requestQueenPrompt,
        setRequestQueenPrompt,
      }}
    >
      {children}
    </ColonyWorkersContext.Provider>
  );
}

export function useColonyWorkers() {
  const ctx = useContext(ColonyWorkersContext);
  if (!ctx)
    throw new Error("useColonyWorkers must be used within ColonyWorkersProvider");
  return ctx;
}
