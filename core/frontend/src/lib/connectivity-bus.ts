/**
 * Tiny in-process event bus for connectivity signals.
 *
 * Publishers:
 *   • api/client.ts           — emits on every request: success or failure
 *   • api/client.ts subscribeSse — emits on SSE open / reconnecting / error / close
 *   • window 'online' / 'offline' (consumed directly by the hook, not here)
 *
 * Subscriber:
 *   • useConnectivityStatus() in hooks/use-connectivity-status.ts
 *
 * Kept deliberately small — one EventTarget shared across the renderer
 * process, no React, no Redux. Importing modules can publish without
 * reaching for the React tree.
 */

export type ConnectivityEventName =
  | "api:ok"
  | "api:error"
  | "sse:open"
  | "sse:reconnecting"
  | "sse:error"
  | "sse:close"
  | "runtime:network_degraded"
  | "runtime:network_healthy";

/** Detail payload for runtime network events. ``reason`` describes
 * what failed upstream (e.g. "ConnectionError: Cannot connect to host
 * llm.open-hive.com"); ``since_epoch`` is when the degradation began. */
export interface RuntimeNetworkDetail {
  reason: string | null;
  since_epoch: number | null;
}

export interface ApiErrorDetail {
  /** HTTP status if available, else 0 (network/IPC failure). */
  status: number;
  /** Path of the failing request — short label for diagnostics. */
  path: string;
}

export interface SseDetail {
  /** Path of the SSE subscription. */
  path: string;
  /** Optional retry delay in ms (for reconnecting). */
  delayMs?: number;
  /** Optional HTTP status (for error). */
  status?: number;
}

const target = new EventTarget();

type ConnectivityDetail = ApiErrorDetail | SseDetail | RuntimeNetworkDetail;

export function publishConnectivity(
  name: ConnectivityEventName,
  detail?: ConnectivityDetail,
): void {
  target.dispatchEvent(new CustomEvent(name, { detail }));
}

export function subscribeConnectivity(
  name: ConnectivityEventName,
  handler: (detail: ConnectivityDetail | undefined) => void,
): () => void {
  const listener = (e: Event) => {
    handler((e as CustomEvent).detail);
  };
  target.addEventListener(name, listener);
  return () => target.removeEventListener(name, listener);
}
