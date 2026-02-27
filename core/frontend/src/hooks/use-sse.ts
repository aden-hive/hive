import { useEffect, useRef, useCallback, useState } from "react";
import type { AgentEvent, EventTypeName } from "@/api/types";

interface UseSSEOptions {
  sessionId: string;
  eventTypes?: EventTypeName[];
  onEvent?: (event: AgentEvent) => void;
  enabled?: boolean;
}

export function useSSE({
  sessionId,
  eventTypes,
  onEvent,
  enabled = true,
}: UseSSEOptions) {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<AgentEvent | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const typesKey = eventTypes?.join(",") ?? "";

  useEffect(() => {
    if (!enabled || !sessionId) return;

    let url = `/api/sessions/${sessionId}/events`;
    if (eventTypes?.length) {
      url += `?types=${eventTypes.join(",")}`;
    }

    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    const handler = (e: MessageEvent) => {
      try {
        const event: AgentEvent = JSON.parse(e.data);
        setLastEvent(event);
        onEventRef.current?.(event);
      } catch {
        // Ignore parse errors (keepalive comments)
      }
    };

    es.onmessage = handler;

    return () => {
      es.close();
      eventSourceRef.current = null;
      setConnected(false);
    };
  }, [sessionId, enabled, typesKey]);

  const close = useCallback(() => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    setConnected(false);
  }, []);

  return { connected, lastEvent, close };
}

// --- Multi-session SSE hook ---

interface UseMultiSSEOptions {
  /** Map of agentType → backendSessionId. Only non-empty IDs get an EventSource. */
  sessions: Record<string, string>;
  onEvent: (agentType: string, event: AgentEvent) => void;
}

/**
 * Manages one EventSource per loaded session. Diffs `sessions` on each render:
 * opens new connections, closes removed ones, leaves existing ones alone.
 */
export function useMultiSSE({ sessions, onEvent }: UseMultiSSEOptions) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const sourcesRef = useRef(new Map<string, EventSource>());

  // Diff-based open/close — runs on every `sessions` change
  useEffect(() => {
    const current = sourcesRef.current;
    const desired = new Set(Object.keys(sessions));

    // Close connections for sessions no longer in the map
    for (const [agentType, es] of current) {
      if (!desired.has(agentType)) {
        es.close();
        current.delete(agentType);
      }
    }

    // Open connections for newly added sessions
    for (const [agentType, sessionId] of Object.entries(sessions)) {
      if (!sessionId || current.has(agentType)) continue;

      const url = `/api/sessions/${sessionId}/events`;
      const es = new EventSource(url);

      es.onmessage = (e: MessageEvent) => {
        try {
          const event: AgentEvent = JSON.parse(e.data);
          console.log('[SSE] received:', agentType, event.type, event.stream_id, event.node_id);
          onEventRef.current(agentType, event);
        } catch {
          // Ignore parse errors (keepalive comments)
        }
      };

      current.set(agentType, es);
    }
  }, [sessions]);

  // Close all on unmount only
  useEffect(() => {
    return () => {
      for (const es of sourcesRef.current.values()) es.close();
      sourcesRef.current.clear();
    };
  }, []);
}
