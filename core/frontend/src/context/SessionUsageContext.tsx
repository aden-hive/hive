import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export interface SessionUsage {
  input: number;
  output: number;
  cached: number;
  cacheCreated: number;
  costUsd: number;
  /** Hive credit cost summed across turns. ``null`` when no turn since
   *  launch reported credits — distinguished from zero on purpose. */
  credits: number | null;
  /** Number of live `llm_turn_complete` events merged into this total. */
  requests: number;
}

interface Ctx {
  /**
   * Usage accumulated across ALL chat surfaces (queen DMs, colonies) since
   * app launch, or null when no live turn has completed yet. Monotone —
   * switching pages or colonies never loses spend that already happened.
   */
  usage: SessionUsage | null;
  /**
   * Merge one live turn's usage into the running total. Pages call this
   * per `llm_turn_complete` event, live turns only — historical replays
   * would double-count on every revisit.
   */
  addUsage: (turn: SessionUsage) => void;
}

const SessionUsageCtx = createContext<Ctx | null>(null);

export function SessionUsageProvider({ children }: { children: ReactNode }) {
  const [usage, setUsage] = useState<SessionUsage | null>(null);
  const addUsage = useCallback((turn: SessionUsage) => {
    setUsage((prev) => ({
      input: (prev?.input ?? 0) + turn.input,
      output: (prev?.output ?? 0) + turn.output,
      cached: (prev?.cached ?? 0) + turn.cached,
      cacheCreated: (prev?.cacheCreated ?? 0) + turn.cacheCreated,
      costUsd: (prev?.costUsd ?? 0) + turn.costUsd,
      credits:
        turn.credits === null
          ? (prev?.credits ?? null)
          : (prev?.credits ?? 0) + turn.credits,
      requests: (prev?.requests ?? 0) + turn.requests,
    }));
  }, []);
  const value = useMemo(() => ({ usage, addUsage }), [usage, addUsage]);
  return (
    <SessionUsageCtx.Provider value={value}>{children}</SessionUsageCtx.Provider>
  );
}

export function useSessionUsage(): Ctx {
  const ctx = useContext(SessionUsageCtx);
  if (!ctx) {
    throw new Error("useSessionUsage must be used within SessionUsageProvider");
  }
  return ctx;
}
