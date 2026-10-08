import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { AgentEvent } from "@/api/types";

/** Lightweight snapshot of the replay state machine used by the
 * debug panel. Avoids passing the full ReplayState object (which
 * contains mutable Maps/Sets and tool row content that could grow
 * large). */
export interface DebugReplaySnapshot {
  turnCounters: Record<string, number>;
  toolTrackers: number;
  seenSeqsSize: number;
  snapshotSeq: number;
}

export interface DebugState {
  /** Last 30 SSE events (newest first). */
  events: AgentEvent[];
  pushEvent: (event: AgentEvent) => void;
  /** Current replay state snapshot (updated after each event). */
  replay: DebugReplaySnapshot | null;
  setReplay: (r: DebugReplaySnapshot | null) => void;
  /** Panel visibility gate — the DebugPanel flips this on mount/unmount. */
  setActive: (active: boolean) => void;
}

const DebugStateContext = createContext<DebugState>({
  events: [],
  pushEvent: () => {},
  replay: null,
  setReplay: () => {},
  setActive: () => {},
});

export function DebugStateProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const eventsRef = useRef<AgentEvent[]>([]);
  const [replay, setReplayState] = useState<DebugReplaySnapshot | null>(null);
  const replayRef = useRef<DebugReplaySnapshot | null>(null);
  // Context re-renders only while the debug panel is OPEN. Every SSE
  // event used to setState here unconditionally — an app-wide context
  // update per delta, re-rendering every consumer even with the panel
  // closed, and one of the setState streams that starved react-router's
  // low-priority navigation transitions. Closed panel → ring buffers in
  // refs only; opening flushes them so nothing is lost.
  const activeRef = useRef(false);

  const pushEvent = useCallback((event: AgentEvent) => {
    eventsRef.current = [event, ...eventsRef.current].slice(0, 30);
    if (activeRef.current) setEvents(eventsRef.current);
  }, []);

  const setReplay = useCallback((r: DebugReplaySnapshot | null) => {
    replayRef.current = r;
    if (activeRef.current) setReplayState(r);
  }, []);

  const setActive = useCallback((active: boolean) => {
    activeRef.current = active;
    if (active) {
      setEvents(eventsRef.current);
      setReplayState(replayRef.current);
    }
  }, []);

  const value = useMemo(
    () => ({ events, pushEvent, replay, setReplay, setActive }),
    [events, replay, pushEvent, setReplay, setActive],
  );

  return (
    <DebugStateContext.Provider value={value}>
      {children}
    </DebugStateContext.Provider>
  );
}

export function useDebugState() {
  return useContext(DebugStateContext);
}
