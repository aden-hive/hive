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

// --- Multi-agent SSE hook ---

interface UseMultiSSEOptions {
  /** Map of agentType → backendAgentId. Only non-empty IDs get an EventSource. */
  agents: Record<string, string>;
  onEvent: (agentType: string, event: AgentEvent) => void;
}

/**
 * Manages one EventSource per loaded agent. Diffs `agents` on each render:
 * opens new connections, closes removed ones, leaves existing ones alone.
 */
export function useMultiSSE({ agents, onEvent }: UseMultiSSEOptions) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const sourcesRef = useRef(new Map<string, EventSource>());

  // Diff-based open/close — runs on every `agents` change
  useEffect(() => {
    const current = sourcesRef.current;
    const desired = new Set(Object.keys(agents));

    // Close connections for agents no longer in the map
    for (const [agentType, es] of current) {
      if (!desired.has(agentType)) {
        es.close();
        current.delete(agentType);
      }
    }

    // Open connections for newly added agents
    for (const [agentType, agentId] of Object.entries(agents)) {
      if (!agentId || current.has(agentType)) continue;

      const url = `/api/agents/${agentId}/events`;
      const es = new EventSource(url);

      es.onmessage = (e: MessageEvent) => {
        try {
          const event: AgentEvent = JSON.parse(e.data);
          onEventRef.current(agentType, event);
        } catch {
          // Ignore parse errors (keepalive comments)
        }
      };

      current.set(agentType, es);
    }
    // No cleanup here — diff logic handles open/close incrementally
  }, [agents]);

  // Close all on unmount only
  useEffect(() => {
    return () => {
      for (const es of sourcesRef.current.values()) es.close();
      sourcesRef.current.clear();
    };
  }, []);
}
