import { useEffect, useState } from "react";
import {
  subscribeConnectivity,
  type ApiErrorDetail,
  type RuntimeNetworkDetail,
  type SseDetail,
} from "@/lib/connectivity-bus";

export type ConnectivityStatus = "online" | "offline" | "degraded";

export interface ConnectivitySnapshot {
  status: ConnectivityStatus;
  /** Short human-readable detail for the banner. ``null`` when online. */
  detail: string | null;
  /** Wall-clock millis since the issue began. ``null`` when online. */
  since: number | null;
}

/**
 * Single-source-of-truth connectivity hook.  Combines:
 *
 *   • ``navigator.onLine`` and the window 'online'/'offline' events
 *     (instant — Chromium polls the OS network state)
 *   • a rolling window of API failures published by api/client.ts
 *     (catches "the LLM proxy is down but the OS still says we're
 *     online")
 *   • SSE state transitions published by subscribeSse
 *     (catches "main↔runtime IPC bridge is dead")
 *
 * Returns the worst of the three signals.  When everything is healthy
 * the hook reports ``online`` with no detail; the banner self-hides.
 */
export function useConnectivityStatus(): ConnectivitySnapshot {
  const [snap, setSnap] = useState<ConnectivitySnapshot>(() => ({
    status: typeof navigator !== "undefined" && !navigator.onLine ? "offline" : "online",
    detail: typeof navigator !== "undefined" && !navigator.onLine ? "Your computer is offline" : null,
    since: typeof navigator !== "undefined" && !navigator.onLine ? Date.now() : null,
  }));

  useEffect(() => {
    // Rolling window of API failures keyed by request path. Any path
    // failing twice in 30 s flips us to "degraded"; the entry expires
    // after 30 s of no further hits, recovering automatically.
    const FAILURE_WINDOW_MS = 30_000;
    const FAILURE_THRESHOLD = 2;
    const recentFailures = new Map<string, number[]>();
    // Active SSE reconnect set — when non-empty we're in degraded.
    const reconnectingPaths = new Set<string>();
    // Runtime upstream-network state — published from the
    // ``/sessions/live`` feed in useLiveSessions. When ``true`` it
    // means the runtime can't reach the LLM proxy (DNS, refused, TLS
    // handshake), even though renderer↔runtime IPC is fine. Without
    // this, dropping wifi looks identical to "everything's quiet".
    let runtimeNetworkDegraded = false;
    let runtimeNetworkReason: string | null = null;
    // First-failure timestamp for "since".
    let degradedSince: number | null = null;

    const recompute = () => {
      const now = Date.now();
      // Prune stale failure entries.
      let totalRecentFailures = 0;
      let pathsOverThreshold = 0;
      for (const [path, ts] of recentFailures) {
        const fresh = ts.filter((t) => now - t < FAILURE_WINDOW_MS);
        if (fresh.length === 0) {
          recentFailures.delete(path);
        } else {
          recentFailures.set(path, fresh);
          totalRecentFailures += fresh.length;
          if (fresh.length >= FAILURE_THRESHOLD) pathsOverThreshold += 1;
        }
      }

      let next: ConnectivitySnapshot;
      if (typeof navigator !== "undefined" && !navigator.onLine) {
        next = {
          status: "offline",
          detail: "Your computer is offline",
          since: degradedSince ?? now,
        };
      } else if (runtimeNetworkDegraded) {
        // Highest-priority degraded signal — the runtime is telling us
        // its outbound LLM calls are failing. Show the reason so a
        // sysadmin user can tell DNS apart from a 5xx.
        next = {
          status: "degraded",
          detail: runtimeNetworkReason
            ? `LLM unreachable — ${runtimeNetworkReason}`
            : "LLM unreachable — runtime can't reach the upstream proxy",
          since: degradedSince ?? now,
        };
      } else if (pathsOverThreshold > 0) {
        next = {
          status: "degraded",
          detail: `Backend requests are failing (${totalRecentFailures} recent errors)`,
          since: degradedSince ?? now,
        };
      } else if (reconnectingPaths.size > 0) {
        next = {
          status: "degraded",
          detail:
            reconnectingPaths.size === 1
              ? "Reconnecting to runtime…"
              : `Reconnecting (${reconnectingPaths.size} streams)…`,
          since: degradedSince ?? now,
        };
      } else {
        next = { status: "online", detail: null, since: null };
        degradedSince = null;
      }

      if (next.status !== "online" && degradedSince === null) {
        degradedSince = now;
        next.since = now;
      }

      setSnap((cur) => {
        if (
          cur.status === next.status &&
          cur.detail === next.detail &&
          cur.since === next.since
        ) {
          return cur;
        }
        return next;
      });
    };

    const onOnline = () => recompute();
    const onOffline = () => recompute();
    if (typeof window !== "undefined") {
      window.addEventListener("online", onOnline);
      window.addEventListener("offline", onOffline);
    }

    const unsubApiErr = subscribeConnectivity("api:error", (detail) => {
      const d = detail as ApiErrorDetail | undefined;
      if (!d) return;
      const arr = recentFailures.get(d.path) ?? [];
      arr.push(Date.now());
      recentFailures.set(d.path, arr);
      recompute();
    });
    const unsubApiOk = subscribeConnectivity("api:ok", () => {
      // A success doesn't immediately wipe failures (a flapping
      // backend should still register as degraded), but the periodic
      // recompute will prune them as their window expires.
      recompute();
    });
    const unsubSseRe = subscribeConnectivity("sse:reconnecting", (detail) => {
      const d = detail as SseDetail | undefined;
      if (!d) return;
      reconnectingPaths.add(d.path);
      recompute();
    });
    const unsubSseOpen = subscribeConnectivity("sse:open", (detail) => {
      const d = detail as SseDetail | undefined;
      if (!d) return;
      reconnectingPaths.delete(d.path);
      recompute();
    });
    const unsubSseClose = subscribeConnectivity("sse:close", (detail) => {
      const d = detail as SseDetail | undefined;
      if (!d) return;
      reconnectingPaths.delete(d.path);
      recompute();
    });
    const unsubRuntimeDegraded = subscribeConnectivity("runtime:network_degraded", (detail) => {
      const d = detail as RuntimeNetworkDetail | undefined;
      runtimeNetworkDegraded = true;
      runtimeNetworkReason = d?.reason ?? null;
      recompute();
    });
    const unsubRuntimeHealthy = subscribeConnectivity("runtime:network_healthy", () => {
      runtimeNetworkDegraded = false;
      runtimeNetworkReason = null;
      recompute();
    });

    // Re-run once a second so the failure window prunes and the
    // banner self-clears even if no new events fire.
    const tick = setInterval(recompute, 1000);

    return () => {
      clearInterval(tick);
      if (typeof window !== "undefined") {
        window.removeEventListener("online", onOnline);
        window.removeEventListener("offline", onOffline);
      }
      unsubApiErr();
      unsubApiOk();
      unsubSseRe();
      unsubSseOpen();
      unsubSseClose();
      unsubRuntimeDegraded();
      unsubRuntimeHealthy();
    };
  }, []);

  return snap;
}
