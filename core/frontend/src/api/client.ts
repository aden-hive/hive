/**
 * All API traffic flows over HTTP to the runtime's `/api` surface:
 *   - JSON/upload requests  → fetch(`/api/<path>`)
 *   - Event streams         → EventSource(`/api/<path>`)
 *   - <img src> / URL-only  → apiUrl() returns a same-origin `/api/<path>`
 *
 * Served same-origin by the runtime in production; proxied to the runtime by
 * Vite's `/api` proxy in dev (see vite.config.ts). Override the base with
 * `VITE_API_BASE` to point a detached dev frontend at a remote runtime.
 */

import { publishConnectivity } from "@/lib/connectivity-bus";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

/**
 * Build a same-origin URL usable in DOM attributes like <img src> or for
 * `window.open` / `<a download>`.
 */
export function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalized}`;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: { error: string; type?: string; [key: string]: unknown },
  ) {
    super(body.error);
    this.name = "ApiError";
  }
}

/** HTTP statuses that don't represent a connectivity issue, even
 * though they're 4xx/5xx. 401/403 mean the user is logged out;
 * 404/422 are application-level problems. We only treat genuinely-
 * connectivity failures (status 0 = network unreachable, 5xx server
 * errors) as connectivity signals so the global banner stays meaningful. */
function _isConnectivityFailure(status: number): boolean {
  return status === 0 || status >= 500;
}

async function parseError(res: Response): Promise<{ error: string; type?: string }> {
  return res.json().catch(() => ({ error: `HTTP ${res.status}` }));
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    // Network-level failure (runtime unreachable). Surface as a
    // connectivity error, mirroring the old IPC-dead branch.
    publishConnectivity("api:error", { status: 0, path });
    throw new ApiError(0, { error: "Runtime unreachable" });
  }
  if (!res.ok) {
    const errBody = await parseError(res);
    if (_isConnectivityFailure(res.status)) {
      publishConnectivity("api:error", { status: res.status, path });
    } else {
      // Any non-connectivity response (auth, app errors) still proves
      // the runtime is reachable — clears stale "degraded" state.
      publishConnectivity("api:ok", { status: res.status, path });
    }
    throw new ApiError(res.status, errBody);
  }
  publishConnectivity("api:ok", { status: res.status, path });
  return res.json() as Promise<T>;
}

async function upload<T>(path: string, formData: FormData): Promise<T> {
  let res: Response;
  try {
    // Let the browser set the multipart Content-Type boundary.
    res = await fetch(apiUrl(path), { method: "POST", body: formData });
  } catch {
    publishConnectivity("api:error", { status: 0, path });
    throw new ApiError(0, { error: "Runtime unreachable" });
  }
  if (!res.ok) {
    const errBody = await parseError(res);
    throw new ApiError(res.status, errBody);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string, body?: unknown) => request<T>("DELETE", path, body),
  upload: <T>(path: string, formData: FormData) => upload<T>(path, formData),
};

// --- SSE ---

export interface SseHandlers {
  onOpen?: () => void;
  onEvent?: (event: string, data: string) => void;
  onError?: (message: string, status?: number) => void;
  /** Fired when the stream dropped and the browser is retrying. Lets the UI
   * show "Reconnecting…" instead of going silent. */
  onReconnecting?: (delayMs: number) => void;
  onClose?: () => void;
}

export interface SubscribeSseOptions {
  /**
   * Set true for feature-specific streams whose UX is already covered by a
   * dedicated component (e.g. ``BrowserStatusBadge`` for
   * ``/browser/status/stream``). Their open/error events are NOT published to
   * the connectivity bus, so a routine keep-alive drop on a feature stream
   * doesn't flip the global "Reconnecting to runtime…" banner. Defaults to
   * false — every stream is runtime-critical unless its owner declares otherwise.
   */
  silentConnectivity?: boolean;
}

// Reconnect backoff bounds for the fetch-based SSE reader below.
const SSE_RETRY_MIN_MS = 1_000;
const SSE_RETRY_MAX_MS = 15_000;

/**
 * Subscribe to a runtime SSE stream. Returns a promise (kept for API
 * compatibility with the desktop IPC-based client) that resolves to an
 * unsubscribe function. Named SSE events are delivered to `onEvent(name, data)`;
 * default events arrive as `onEvent("message", data)`.
 *
 * Implementation: a fetch()-streaming SSE reader, NOT native EventSource.
 * This restores the lifecycle contract the desktop client has and the
 * EventSource port silently dropped:
 *   - `onError(message, status)` carries the real HTTP status, so the
 *     404 → session-gone auto-resume path actually fires;
 *   - `onClose()` fires TERMINALLY (the subscription is over — today only
 *     the 404 session-gone case), so `sseState: "closed"` and the
 *     resumeNonce re-mount machinery are reachable again; routine stream
 *     rotations are absorbed by the internal retry loop instead;
 *   - reconnects are our own bounded-backoff loop with honest
 *     `onReconnecting(delayMs)` signals (a 404 stops the loop — the
 *     session is gone; retrying the same id is pointless and the caller
 *     resumes from disk instead).
 */
export async function subscribeSse(
  path: string,
  handlers: SseHandlers,
  options?: SubscribeSseOptions,
): Promise<() => void> {
  const silent = options?.silentConnectivity === true;
  let aborted = false;
  let controller: AbortController | null = null;
  let retryDelay = SSE_RETRY_MIN_MS;

  const readStream = async (body: ReadableStream<Uint8Array>) => {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let eventName = "message";
    let dataLines: string[] = [];
    const dispatch = () => {
      if (dataLines.length > 0) {
        handlers.onEvent?.(eventName, dataLines.join("\n"));
      }
      eventName = "message";
      dataLines = [];
    };
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        let line = buf.slice(0, nl);
        buf = buf.slice(nl + 1);
        if (line.endsWith("\r")) line = line.slice(0, -1);
        if (line === "") {
          dispatch();
          continue;
        }
        if (line.startsWith(":")) continue; // comment / keepalive
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim() || "message";
          continue;
        }
        if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).replace(/^ /, ""));
          continue;
        }
        // id:/retry: fields — not used by this backend; ignore.
      }
    }
    dispatch();
  };

  const loop = async () => {
    while (!aborted) {
      controller = new AbortController();
      try {
        const resp = await fetch(apiUrl(path), {
          headers: { Accept: "text/event-stream" },
          cache: "no-store",
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) {
          if (!silent) publishConnectivity("sse:error", { path, status: resp.status });
          handlers.onError?.(`sse_http_${resp.status}`, resp.status);
          if (resp.status === 404) {
            // Session gone — stop retrying this id; the caller's
            // session-gone handler resumes from disk with a fresh id.
            handlers.onClose?.();
            return;
          }
        } else {
          if (!silent) publishConnectivity("sse:open", { path });
          handlers.onOpen?.();
          retryDelay = SSE_RETRY_MIN_MS;
          await readStream(resp.body);
          if (aborted) return;
          // Server ended the stream (restart / keepalive rotation).
          // NOT onClose: that is a TERMINAL signal (consumers tear down
          // their registry entry on it — use-sse deletes the agentType so
          // a resumeNonce can re-mount). A routine rotation is handled by
          // our own retry loop below with an honest onReconnecting.
          if (!silent) publishConnectivity("sse:close", { path });
        }
      } catch (err) {
        if (aborted) return;
        if (!silent) publishConnectivity("sse:error", { path });
        handlers.onError?.(err instanceof Error ? err.message : "sse_error");
      }
      if (aborted) return;
      if (!silent) publishConnectivity("sse:reconnecting", { path, delayMs: retryDelay });
      handlers.onReconnecting?.(retryDelay);
      await new Promise((r) => setTimeout(r, retryDelay));
      retryDelay = Math.min(retryDelay * 2, SSE_RETRY_MAX_MS);
    }
  };
  void loop();

  return () => {
    aborted = true;
    controller?.abort();
    if (!silent) publishConnectivity("sse:close", { path });
  };
}
