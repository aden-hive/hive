import { useEffect, useRef, useCallback, useState } from "react";
import type { AgentEvent, EventTypeName } from "@/api/types";
import { agentTypesToClose, connectionsToOpen } from "./multi-sse-diff";

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
 * Manages one EventSource per loaded session. Diffs `sessions` on each change:
 * opens new connections, closes removed agents, and reconnects when the session
 * ID changes for an existing agent type.
 */
export function useMultiSSE({ sessions, onEvent }: UseMultiSSEOptions) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const sourcesRef = useRef(new Map<string, { es: EventSource; sessionId: string }>());

  useEffect(() => {
    const current = sourcesRef.current;

    for (const agentType of agentTypesToClose(current, sessions)) {
      current.get(agentType)?.es.close();
      current.delete(agentType);
    }

    for (const { agentType, sessionId } of connectionsToOpen(current, sessions)) {
      const url = `/api/sessions/${sessionId}/events`;
      const es = new EventSource(url);

      es.onmessage = (e: MessageEvent) => {
        try {
          const event: AgentEvent = JSON.parse(e.data);
          onEventRef.current(agentType, event);
        } catch {
          // Ignore parse errors (keepalive comments)
        }
      };

      current.set(agentType, { es, sessionId });
    }
  }, [sessions]);

  useEffect(() => {
    return () => {
      for (const entry of sourcesRef.current.values()) entry.es.close();
      sourcesRef.current.clear();
    };
  }, []);
}
