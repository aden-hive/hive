import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { subscribeSse } from "@/api/client";
import { publishConnectivity } from "@/lib/connectivity-bus";
import { slugToColonyId } from "@/lib/colony-registry";
import React from "react";

/**
 * One row from the /api/sessions/live SSE feed. Mirrors
 * ``_live_session_summary`` in routes_sessions.py — keep the two in
 * sync if you add fields.
 */
export interface LiveSessionRow {
  session_id: string;
  colony_id: string | null;
  queen_id: string | null;
  queen_name: string | null;
  phase: string | null;
  is_executing: boolean;
  awaiting_input: boolean;
  interrupted: boolean;
  interrupt_cause: string | null;
  queen_busy_reason: "tool" | "llm" | "awaiting_input" | "interrupted" | null;
  park_reason: string | null;
  current_tool_name: string | null;
  current_tool_count: number;
  /** Workers still in flight (queued/pending/running) for this session's
   *  colony. The overseer parks its own loop while it waits for dispatched
   *  workers to report, so `is_executing` goes false mid-fan-out — this is
   *  what keeps the colony reading as active while the work is real.
   *  Optional: an older runtime won't send it (treated as 0). */
  active_worker_count?: number;
  last_event_at: string | null;
  snapshot_seq: number;
}

/** Coalesced per-queen liveness derived from one or more sessions
 * mapped to the same queen_id. ``executing``/``awaiting`` are OR'd
 * across sessions; ``current_tool_name`` is the first non-null. */
export interface QueenLiveness {
  is_executing: boolean;
  awaiting_input: boolean;
  interrupted: boolean;
  interrupt_cause: string | null;
  current_tool_name: string | null;
  queen_busy_reason: "tool" | "llm" | "awaiting_input" | "interrupted" | null;
  park_reason: string | null;
  session_ids: string[];
  last_event_at: string | null;
  /** Summed across the coalesced sessions: workers still in flight. > 0 means
   *  the colony is doing real work even when no queen loop is executing. */
  active_worker_count: number;
}

/** Runtime-wide upstream network status published by the runtime's
 * agent_loop retry path. ``degraded`` flips on as soon as a
 * connection-class error fires; the connectivity banner consumes this
 * via the connectivity bus. */
export interface RuntimeNetworkSnapshot {
  degraded: boolean;
  reason: string | null;
  since_epoch: number | null;
  last_event_epoch: number | null;
}

// ── Context ─────────────────────────────────────────────────────────────

interface LiveSessionsContextValue {
  rows: LiveSessionRow[];
  byQueen: Map<string, QueenLiveness>;
  byColony: Map<string, QueenLiveness>;
  connected: boolean;
  network: RuntimeNetworkSnapshot;
}

const EMPTY_MAP = new Map<string, QueenLiveness>();
const NETWORK_INIT: RuntimeNetworkSnapshot = {
  degraded: false,
  reason: null,
  since_epoch: null,
  last_event_epoch: null,
};

const LiveSessionsContext = createContext<LiveSessionsContextValue>({
  rows: [],
  byQueen: EMPTY_MAP,
  byColony: EMPTY_MAP,
  connected: false,
  network: NETWORK_INIT,
});

// ── Aggregation helpers ─────────────────────────────────────────────────

function aggregateByKey(
  rows: LiveSessionRow[],
  keyFn: (r: LiveSessionRow) => string | null,
  skipFn?: (r: LiveSessionRow) => boolean,
): Map<string, QueenLiveness> {
  const out = new Map<string, QueenLiveness>();
  for (const r of rows) {
    const key = keyFn(r);
    if (!key) continue;
    if (skipFn?.(r)) continue;
    const cur = out.get(key);
    if (!cur) {
      out.set(key, {
        is_executing: r.is_executing,
        awaiting_input: r.awaiting_input,
        interrupted: r.interrupted,
        interrupt_cause: r.interrupt_cause,
        current_tool_name: r.current_tool_name,
        queen_busy_reason: r.queen_busy_reason,
        park_reason: r.park_reason,
        session_ids: [r.session_id],
        last_event_at: r.last_event_at,
        active_worker_count: r.active_worker_count ?? 0,
      });
    } else {
      cur.active_worker_count += r.active_worker_count ?? 0;
      cur.is_executing = cur.is_executing || r.is_executing;
      cur.awaiting_input = cur.awaiting_input || r.awaiting_input;
      cur.interrupted = cur.interrupted || r.interrupted;
      cur.interrupt_cause = cur.interrupt_cause ?? r.interrupt_cause;
      cur.current_tool_name = cur.current_tool_name ?? r.current_tool_name;
      cur.queen_busy_reason = cur.queen_busy_reason ?? r.queen_busy_reason;
      cur.park_reason = cur.park_reason ?? r.park_reason;
      cur.session_ids.push(r.session_id);
      if (r.last_event_at && (!cur.last_event_at || r.last_event_at > cur.last_event_at)) {
        cur.last_event_at = r.last_event_at;
      }
    }
  }
  return out;
}

// ── Provider ────────────────────────────────────────────────────────────

/**
 * Single SSE subscription shared across the whole app.  Mount once
 * inside ``RuntimeProvider`` (the feed requires the runtime to be up).
 *
 * Rows are cleared on disconnect so consumers never render stale
 * liveness indicators while the SSE is reconnecting.
 */
export function LiveSessionsProvider({ children }: { children: ReactNode }) {
  const [rows, setRows] = useState<LiveSessionRow[]>([]);
  const [network, setNetwork] = useState<RuntimeNetworkSnapshot>(NETWORK_INIT);
  const [connected, setConnected] = useState(false);

  const setRowsRef = useRef(setRows);
  setRowsRef.current = setRows;
  const lastDegradedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let unsub: (() => void) | null = null;

    subscribeSse("/sessions/live", {
      onOpen: () => setConnected(true),
      onEvent: (name, data) => {
        if (name !== "snapshot") return;
        try {
          const parsed = JSON.parse(data) as {
            sessions: LiveSessionRow[];
            network?: RuntimeNetworkSnapshot;
          };
          if (Array.isArray(parsed.sessions)) {
            setRowsRef.current(parsed.sessions);
          }
          if (parsed.network) {
            setNetwork(parsed.network);
            const wasDegraded = lastDegradedRef.current;
            const isDegraded = parsed.network.degraded;
            if (isDegraded && !wasDegraded) {
              publishConnectivity("runtime:network_degraded", {
                reason: parsed.network.reason,
                since_epoch: parsed.network.since_epoch,
              });
            } else if (!isDegraded && wasDegraded) {
              publishConnectivity("runtime:network_healthy", {
                reason: null,
                since_epoch: null,
              });
            }
            lastDegradedRef.current = isDegraded;
          }
        } catch {
          // ignore malformed frames
        }
      },
      onError: () => {
        setConnected(false);
      },
      onReconnecting: () => {
        setConnected(false);
      },
      onClose: () => {
        setConnected(false);
        setRowsRef.current([]);
      },
    }).then((u) => {
      if (cancelled) {
        u();
        return;
      }
      unsub = u;
    });

    return () => {
      cancelled = true;
      unsub?.();
    };
  }, []);

  // Per-queen aggregation — colony-scoped sessions excluded (their
  // state belongs to the colony, not the standalone queen profile).
  const byQueen = useMemo(
    () => aggregateByKey(rows, (r) => r.queen_id, (r) => !!r.colony_id),
    [rows],
  );

  // Per-colony aggregation — keyed by the transformed colony ID
  // (slugToColonyId) so lookups by colony.id match.
  const byColony = useMemo(
    () => aggregateByKey(rows, (r) => r.colony_id ? slugToColonyId(r.colony_id) : null),
    [rows],
  );

  const value = useMemo(
    () => ({ rows, byQueen, byColony, connected, network }),
    [rows, byQueen, byColony, connected, network],
  );

  return React.createElement(LiveSessionsContext.Provider, { value }, children);
}

// ── Consumer hook ───────────────────────────────────────────────────────

/**
 * Read the shared live-session feed.  Must be rendered inside
 * ``LiveSessionsProvider``.
 */
export function useLiveSessions() {
  return useContext(LiveSessionsContext);
}
