/**
 * Session-load tracer (renderer side).
 *
 * Captures every step of the session resume flow — bootstrap-effect runs,
 * `restoreMessages`, the live SSE handoff, and every change to the
 * `messages` array — and ships it to the main process, which writes one
 * log file per load flow to <userData>/session-load-logs/.
 *
 * Why per-file: a single session-loss reproduction is "switch to another
 * session, switch back". Each switch is one bootstrap-effect run = one
 * `beginLoad()` = one file. Three files for an A→B→A reproduction, each
 * self-contained and easy to diff.
 *
 * The tracer is a module singleton so it survives component remounts and
 * keeps recording across a session switch.
 */

/**
 * Master switch. When false the tracer is fully inert — `beginLoad` and
 * `trace` return immediately, nothing is queued, no files are written.
 * The instrumentation call sites throughout the resume flow stay in place
 * as cheap no-ops; flip this to `true` to capture resume-flow logs again.
 */
const ENABLED = false;
/** Callers that build EXPENSIVE trace arguments (full-transcript
 * summaries) must gate on this — trace() no-ops when disabled, but
 * argument evaluation still runs eagerly at the call site. */
export const TRACE_ENABLED = ENABLED;

interface TraceRecord {
  iso: string;
  scope: string;
  event: string;
  data?: unknown;
}

// Pending records, tagged with the load flow they belong to. Flushed to
// main in batches so disk writes don't sit on the hot path.
const queue: Array<{ loadId: string; record: TraceRecord }> = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let loadSeq = 0;

/** The most recent load flow. SSE / message-change traces with no explicit
 *  loadId attach here — after a resume, that activity belongs to it. */
let activeLoadId: string | null = null;

function scheduleFlush(): void {
  if (flushTimer !== null) return;
  flushTimer = setTimeout(flush, 150);
}

function flush(): void {
  flushTimer = null;
  if (queue.length === 0) return;
  const batch = queue.splice(0, queue.length);
  if (!ENABLED) return;
  // In the desktop shell these batched records were persisted to disk via the
  // native bridge (`traceLog`). The web SPA has no such sink, so — when
  // tracing is enabled — emit to the console for debugging instead.
  const byId = new Map<string, TraceRecord[]>();
  for (const { loadId, record } of batch) {
    const list = byId.get(loadId);
    if (list) list.push(record);
    else byId.set(loadId, [record]);
  }
  for (const [loadId, records] of byId) {
    console.debug("[session-load-trace]", loadId, records);
  }
}

/** Keep trace payloads small — a stray huge object can't bloat the log. */
function sanitize(data: unknown): unknown {
  if (data === undefined || data === null) return data;
  try {
    const str = JSON.stringify(data);
    if (str.length <= 4000) return data;
    return { _truncated: true, preview: str.slice(0, 4000) };
  } catch {
    return { _unserializable: String(data) };
  }
}

/**
 * Open a new load flow. Returns its loadId — pass it to `trace(...)` for
 * every record that belongs to this flow (especially async work that may
 * outlive a superseding run). Also becomes the `activeLoadId`.
 */
export function beginLoad(reason: string, meta?: Record<string, unknown>): string {
  if (!ENABLED) return "";
  loadSeq += 1;
  const now = new Date();
  const stamp = now
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d+Z$/, "");
  const safeReason = reason.replace(/[^a-zA-Z0-9_.-]/g, "-");
  const loadId = `${stamp}-${String(loadSeq).padStart(3, "0")}-${safeReason}`;
  activeLoadId = loadId;
  trace("load", "BEGIN", { reason, ...meta }, loadId);
  return loadId;
}

/** The current active load flow, or null before the first `beginLoad`. */
export function currentLoadId(): string | null {
  return activeLoadId;
}

/**
 * Record one trace line. `loadId` defaults to the active load flow; pass
 * it explicitly from async code so a record can't leak into a later flow's
 * file.
 */
export function trace(
  scope: string,
  event: string,
  data?: unknown,
  loadId?: string,
): void {
  if (!ENABLED) return;
  const id = loadId ?? activeLoadId;
  if (!id) return;
  queue.push({
    loadId: id,
    record: {
      iso: new Date().toISOString(),
      scope,
      event,
      data: sanitize(data),
    },
  });
  if (queue.length >= 80) flush();
  else scheduleFlush();
}

/**
 * Compact summary of a message array — count, id/createdAt of the first
 * and last entries, and the distinct calendar days covered. This is the
 * line that makes a message-loss obvious ("days":["2026-05-18"] when the
 * full transcript should span 2026-05-13..18).
 */
export function msgSummary(
  messages: ReadonlyArray<{ id: string; createdAt?: number }>,
): Record<string, unknown> {
  const count = messages.length;
  if (count === 0) return { count: 0 };
  const first = messages[0];
  const last = messages[count - 1];
  const days = new Set<string>();
  for (const m of messages) {
    if (typeof m.createdAt === "number" && m.createdAt > 0) {
      days.add(new Date(m.createdAt).toISOString().slice(0, 10));
    }
  }
  const toIso = (t?: number) =>
    typeof t === "number" && t > 0 ? new Date(t).toISOString() : null;
  return {
    count,
    firstId: first.id,
    firstAt: toIso(first.createdAt),
    lastId: last.id,
    lastAt: toIso(last.createdAt),
    days: [...days].sort(),
  };
}

/** No-op in web mode — there is no on-disk trace log directory to open. */
export function openTraceLogDir(): void {
  /* no-op: web SPA has no native file manager / on-disk trace logs */
}

if (ENABLED) {
  // Best-effort flush on teardown so the tail of the last flow isn't lost.
  if (typeof window !== "undefined") {
    window.addEventListener("beforeunload", flush);
  }
}
