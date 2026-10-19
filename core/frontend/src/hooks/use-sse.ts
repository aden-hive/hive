import { useEffect, useRef, useCallback, useState } from "react";
import { subscribeSse } from "@/api/client";
import type { AgentEvent, EventTypeName } from "@/api/types";
import { trace as traceLoad } from "@/lib/session-load-trace";

interface UseSSEOptions {
  sessionId: string;
  eventTypes?: EventTypeName[];
  onEvent?: (event: AgentEvent) => void;
  enabled?: boolean;
  /**
   * Opt in to a specific worker's per-turn chatter (text deltas, tool calls).
   *
   * By default the server sends only worker META events (start / progress /
   * finish) — enough to render a worker's bubble, and nothing more. Pass a
   * stream id (`worker:<uuid>`) to also receive that ONE worker's detail, or
   * `"*"` for every worker (debug only).
   *
   * This exists because the runtime may live on another machine: a human can
   * only look at one worker at a time, so we only pay to ship one.
   */
  watch?: string;
}

export function useSSE({
  sessionId,
  eventTypes,
  onEvent,
  enabled = true,
  watch,
}: UseSSEOptions) {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<AgentEvent | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const typesKey = eventTypes?.join(",") ?? "";

  useEffect(() => {
    if (!enabled || !sessionId) return;

    const params = new URLSearchParams();
    if (eventTypes?.length) params.set("types", eventTypes.join(","));
    if (watch) params.set("watch", watch);
    const qs = params.toString();
    const path = `/sessions/${sessionId}/events${qs ? `?${qs}` : ""}`;

    let cancelled = false;
    let localUnsub: (() => void) | null = null;

    subscribeSse(path, {
      onOpen: () => setConnected(true),
      onEvent: (_evt, data) => {
        try {
          const event: AgentEvent = JSON.parse(data);
          setLastEvent(event);
          onEventRef.current?.(event);
        } catch {
          // Ignore parse errors (keepalive comments)
        }
      },
      onError: () => setConnected(false),
      onClose: () => setConnected(false),
    }).then((unsub) => {
      if (cancelled) {
        unsub();
        return;
      }
      localUnsub = unsub;
      unsubscribeRef.current = unsub;
    });

    return () => {
      cancelled = true;
      localUnsub?.();
      unsubscribeRef.current = null;
      setConnected(false);
    };
  }, [sessionId, enabled, typesKey, watch]);

  const close = useCallback(() => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    setConnected(false);
  }, []);

  return { connected, lastEvent, close };
}

// --- Global app-wide SSE hook ---

/** Event types streamed by the global SSE channel (see backend
 * `_GLOBAL_EVENT_TYPES` in routes_events.py). Cross-cutting events
 * that aren't scoped to a particular session — credential
 * connect/disconnect, tool catalog refreshes, tools-config edits in
 * other tabs/windows, CRM writes made by an agent's `hive-crm` CLI. */
const GLOBAL_EVENT_TYPES: ReadonlySet<EventTypeName> = new Set<EventTypeName>([
  "credential_provider_connected",
  "credential_provider_disconnected",
  "tool_catalog_refreshed",
  "tools_config_changed",
  "crm_changed",
]);

interface UseGlobalEventsOptions {
  /** Subset of GLOBAL_EVENT_TYPES to react to. Omit to receive all
   * global events. */
  eventTypes?: readonly EventTypeName[];
  onEvent: (event: AgentEvent) => void;
  enabled?: boolean;
}

// ---------------------------------------------------------------------------
// Shared global stream. Browsers cap same-origin HTTP/1.1 connections at ~6
// and every EventSource holds one for its whole life — with several
// components each opening their own /events/global (AppLayout mounts two,
// SentinelSection, ToolsEditor, DebugPanel), the pool exhausts and every
// <img> / fetch / SSE-reconnect queues forever ("frozen until refresh").
// One refcounted EventSource serves all useGlobalEvents instances instead:
// the first listener opens it, the last listener out closes it.
// (The Electron desktop app never had this problem: its SSE rides IPC to
// the main process and bypasses the renderer's connection pool entirely.)
// ---------------------------------------------------------------------------

type GlobalEventListener = (event: AgentEvent) => void;
const globalEventListeners = new Set<GlobalEventListener>();
let globalStreamUnsub: (() => void) | null = null;
let globalStreamOpening = false;

function ensureGlobalStream(): void {
  if (globalStreamUnsub || globalStreamOpening) return;
  globalStreamOpening = true;
  void subscribeSse("/events/global", {
    onEvent: (_evt, data) => {
      try {
        const event: AgentEvent = JSON.parse(data);
        if (!GLOBAL_EVENT_TYPES.has(event.type)) return;
        // Snapshot: a listener may unsubscribe (or another mount) mid-loop.
        for (const listener of [...globalEventListeners]) listener(event);
      } catch {
        // Ignore parse errors (keepalive comments)
      }
    },
  }).then((unsub) => {
    globalStreamOpening = false;
    if (globalEventListeners.size === 0) {
      // Everyone left while the subscription was being established.
      unsub();
      return;
    }
    globalStreamUnsub = unsub;
  });
}

function releaseGlobalStream(): void {
  if (globalEventListeners.size === 0 && globalStreamUnsub) {
    globalStreamUnsub();
    globalStreamUnsub = null;
  }
}

/**
 * Subscribe to the process-wide global SSE channel
 * (`/events/global`). Used by the Tool Library and Integrations
 * pages to refetch silently when credentials connect/disconnect or
 * a sibling tab edits a queen's allowlist. All instances share ONE
 * underlying EventSource (see above).
 */
export function useGlobalEvents({
  eventTypes,
  onEvent,
  enabled = true,
}: UseGlobalEventsOptions) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const filterRef = useRef<ReadonlySet<EventTypeName> | null>(null);
  filterRef.current = eventTypes && eventTypes.length > 0 ? new Set(eventTypes) : null;

  useEffect(() => {
    if (!enabled) return;

    const listener: GlobalEventListener = (event) => {
      const filter = filterRef.current;
      if (filter && !filter.has(event.type)) return;
      onEventRef.current(event);
    };
    globalEventListeners.add(listener);
    ensureGlobalStream();

    return () => {
      globalEventListeners.delete(listener);
      releaseGlobalStream();
    };
  }, [enabled]);
}


// --- Multi-session SSE hook ---

/** Connection state for one session's SSE subscription, surfaced to
 * callers so the UI can show "Reconnecting…" instead of going silent
 * while the main-side bridge is sleeping between attempts. */
export type SseConnectionState = "live" | "reconnecting" | "closed";

interface UseMultiSSEOptions {
  /** Map of agentType → backendSessionId. Only non-empty IDs get a subscription. */
  sessions: Record<string, string>;
  onEvent: (agentType: string, event: AgentEvent) => void;
  /** Optional: receives state changes per agentType. Lets the queen
   * page render a "Reconnecting…" pill, the sidebar mark a queen as
   * offline, etc. Same callback identity is fine across renders. */
  onConnectionState?: (agentType: string, state: SseConnectionState) => void;
  /** Fires when the runtime confirms the session id is gone (HTTP 404
   * on SSE pre-open). Happens after a hive-serve restart drops the
   * in-memory session_manager entry while the on-disk queen_dir
   * survives. Consumers should call sessionsApi.create with
   * queenResumeFrom = sessionId to have the runtime re-load the same
   * session id from disk, then bump ``resumeNonce`` below to force a
   * fresh SSE mount. */
  onSessionGone?: (agentType: string, sessionId: string) => void;
  /** Consumer-controlled nonce. Bumping this forces every subscription
   * to re-mount, which is how a caller signals "I've fixed the
   * underlying condition (e.g. resumed a session that had gone 404),
   * please retry now." Unchanged sessions map alone won't re-trigger. */
  resumeNonce?: number;
}

/**
 * Manages one SSE subscription per loaded session. Diffs `sessions` on each
 * render: opens new subscriptions, closes removed ones, leaves existing alone.
 */
export function useMultiSSE({
  sessions,
  onEvent,
  onConnectionState,
  onSessionGone,
  resumeNonce = 0,
}: UseMultiSSEOptions) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onStateRef = useRef(onConnectionState);
  onStateRef.current = onConnectionState;
  const onGoneRef = useRef(onSessionGone);
  onGoneRef.current = onSessionGone;

  // agentType → { unsub, sessionId, pending }
  // `unsub` is null while the IPC round-trip is in flight.
  const sourcesRef = useRef(
    new Map<
      string,
      { unsub: (() => void) | null; sessionId: string; aborted: boolean }
    >(),
  );

  useEffect(() => {
    const current = sourcesRef.current;
    const desired = new Set(Object.keys(sessions));

    // Close removed agents OR changed session IDs
    for (const [agentType, entry] of current) {
      if (!desired.has(agentType) || sessions[agentType] !== entry.sessionId) {
        console.log(
          "[SSE] closing:",
          agentType,
          entry.sessionId,
          desired.has(agentType) ? "(session changed)" : "(removed)",
        );
        traceLoad("sse-conn", "close", {
          agentType,
          sessionId: entry.sessionId,
          reason: desired.has(agentType) ? "session-changed" : "removed",
          unsubReady: entry.unsub !== null,
        });
        entry.aborted = true;
        entry.unsub?.();
        current.delete(agentType);
      }
    }

    // Open subscriptions for new/changed sessions
    for (const [agentType, sessionId] of Object.entries(sessions)) {
      if (!sessionId || current.has(agentType)) continue;

      const path = `/sessions/${sessionId}/events`;
      console.log("[SSE] opening:", agentType, sessionId);
      traceLoad("sse-conn", "open", { agentType, sessionId });

      const entry: {
        unsub: (() => void) | null;
        sessionId: string;
        aborted: boolean;
      } = { unsub: null, sessionId, aborted: false };
      current.set(agentType, entry);

      subscribeSse(path, {
        onOpen: () => {
          console.log("[SSE] connected:", agentType, sessionId);
          traceLoad("sse-conn", "connected", { agentType, sessionId });
          onStateRef.current?.(agentType, "live");
        },
        onEvent: (_name, data) => {
          try {
            const event: AgentEvent = JSON.parse(data);
            onEventRef.current(agentType, event);
          } catch {
            // Ignore parse errors (keepalive comments)
          }
        },
        onError: (msg, status) => {
          console.error("[SSE] error:", agentType, sessionId, msg, "status", status);
          // status === 404 on a session-scoped SSE URL is definitive:
          // the runtime's session_manager doesn't know this id. Almost
          // always this is a post-crash recovery scenario — hive-serve
          // restarted, in-memory _sessions is empty, but the on-disk
          // queen_dir is intact. Tell the caller so it can resume the
          // session from disk (sessionsApi.create + queen_resume_from).
          if (status === 404) {
            onGoneRef.current?.(agentType, sessionId);
          }
        },
        onReconnecting: () => {
          onStateRef.current?.(agentType, "reconnecting");
        },
        onClose: () => {
          onStateRef.current?.(agentType, "closed");
          // Drop the entry from the internal registry so a bumped
          // ``resumeNonce`` (or any other effect re-run) will treat this
          // agentType as un-subscribed and mount a fresh SSE. Without
          // this the entry lingers as "closed", the effect skips it via
          // ``current.has(agentType) → continue``, and the auto-resume
          // never reopens the stream.
          current.delete(agentType);
        },
      }).then((unsub) => {
        if (entry.aborted) {
          unsub();
          return;
        }
        entry.unsub = unsub;
      });
    }
    // resumeNonce is a caller-controlled dependency: bumping it re-runs
    // the effect, which finds any missing entries (deleted in onClose
    // above) and re-mounts them. This is how "auto-resume a session
    // that went 404" plumbs end-to-end.
  }, [sessions, resumeNonce]);

  // Close all on unmount
  useEffect(() => {
    return () => {
      for (const entry of sourcesRef.current.values()) {
        entry.aborted = true;
        entry.unsub?.();
      }
      sourcesRef.current.clear();
    };
  }, []);
}
