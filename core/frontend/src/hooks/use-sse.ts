import { useEffect, useRef, useCallback, useState } from "react";
import type { AgentEvent, EventTypeName } from "@/api/types";

interface UseSSEOptions {
  agentId: string;
  eventTypes?: EventTypeName[];
  onEvent?: (event: AgentEvent) => void;
  enabled?: boolean;
}

export function useSSE({
  agentId,
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
    if (!enabled || !agentId) return;

    let url = `/api/agents/${agentId}/events`;
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

    // Listen on generic message for all events
    es.onmessage = handler;

    return () => {
      es.close();
      eventSourceRef.current = null;
      setConnected(false);
    };
  }, [agentId, enabled, typesKey]);

  const close = useCallback(() => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    setConnected(false);
  }, []);

  return { connected, lastEvent, close };
}
