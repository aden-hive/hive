import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import type { GraphNode } from "@/components/graph-types";

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

  /** Current session's triggers, pushed from whichever page is active
   *  (colony-chat today). ``ColonyWorkersPanel`` reads these to render
   *  its Triggers tab without having to re-subscribe to SSE itself. */
  triggers: GraphNode[];
  setTriggers: (triggers: GraphNode[]) => void;
}

const ColonyWorkersContext = createContext<ColonyWorkersContextValue | null>(null);

export function ColonyWorkersProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionIdState] = useState<string | null>(null);
  const [colonyName, setColonyName] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [triggers, setTriggers] = useState<GraphNode[]>([]);

  const setSessionId = useCallback((next: string | null) => {
    setSessionIdState((prev) => {
      // Reset dismissal whenever the active session changes so entering
      // a new colony opens the panel again even if the user closed it
      // in the previous room.
      if (prev !== next) setDismissed(false);
      return next;
    });
  }, []);

  const toggleColonyWorkers = useCallback(() => {
    setDismissed((d) => !d);
  }, []);

  return (
    <ColonyWorkersContext.Provider
      value={{
        sessionId,
        setSessionId,
        colonyName,
        setColonyName,
        dismissed,
        toggleColonyWorkers,
        triggers,
        setTriggers,
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
