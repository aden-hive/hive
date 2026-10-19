import { useCallback, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ChatMessage, ImageContent } from "@/components/ChatPanel";

interface QueuedPayload {
  text: string;
  images?: ImageContent[];
  /** Display echo (file chips / typed text shown in the bubble). Carried
   *  through the queue so the flushed send matches the optimistic bubble —
   *  without it the backend echoes the full extracted file content and the
   *  content-based reconciler can't match, duplicating the bubble. */
  displayMessage?: string;
}

interface UsePendingQueueArgs {
  /** Sends a message to the backend. Must handle its own errors.
   * Return `false` when the message was NOT accepted (gate closed —
   * e.g. session not ready): the queue keeps the entry and retries on
   * the next flush. `void`/`true` counts as accepted. */
  sendToBackend: (
    text: string,
    images?: ImageContent[],
    displayMessage?: string,
  ) => boolean | void;
  /** Setter for the chat message list — used to flip/strip the `queued` flag. */
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  /** Fires once per flush, before any message is sent. Typically sets
   *  active/queenIsTyping so the UI reflects that the queen is busy again. */
  onFlushStart?: () => void;
}

/**
 * Client-side queue for user messages typed while the queen is mid-turn.
 *
 * - `enqueue` stores a message locally keyed by its optimistic UI id.
 * - `steer` pulls one message out and sends it now — backend injects at the
 *   next iteration boundary.
 * - `cancelQueued` drops a queued message entirely (no backend call).
 * - `flushNext` pops and sends one; wire this to `llm_turn_complete` (the
 *   real per-turn boundary — execution_completed only fires at session
 *   shutdown because the queen's loop parks in _await_user_input between
 *   turns). Do NOT call on pause / cancel / fail.
 *
 * `flushRef` exposes the latest `flush` for capture-once SSE handlers.
 */
export function usePendingQueue({
  sendToBackend,
  setMessages,
  onFlushStart,
}: UsePendingQueueArgs) {
  const queueRef = useRef<Map<string, QueuedPayload>>(new Map());

  const enqueue = useCallback(
    (messageId: string, payload: QueuedPayload) => {
      queueRef.current.set(messageId, payload);
    },
    [],
  );

  const steer = useCallback(
    (messageId: string) => {
      const pending = queueRef.current.get(messageId);
      if (!pending) return;
      // Send FIRST, dequeue only on acceptance. The old delete-then-send
      // order destroyed the message whenever sendToBackend's gate was
      // closed (colony `ready === false`): the queue entry was gone, the
      // bubble's queued ring stripped, and nothing had been posted.
      if (sendToBackend(pending.text, pending.images, pending.displayMessage) === false) {
        return; // still queued — a later flush retries
      }
      queueRef.current.delete(messageId);
      // Re-stamp createdAt to the actual send moment. A queued bubble was
      // stamped at *typing* time; the backend injects it at the next
      // iteration boundary (≈ now), so its real conversation position is
      // here, not back where it was typed. Without this the transcript
      // sorts it above the agent output produced while it sat queued, and
      // a >15s-queued message also falls outside the echo-reconcile window
      // and duplicates. Send time keeps the window valid and the position
      // right; the server echo then supplies the authoritative createdAt.
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId ? { ...m, queued: false, createdAt: Date.now() } : m,
        ),
      );
      onFlushStart?.();
    },
    [sendToBackend, setMessages, onFlushStart],
  );

  const cancelQueued = useCallback(
    (messageId: string) => {
      if (!queueRef.current.has(messageId)) return;
      queueRef.current.delete(messageId);
      setMessages((prev) => prev.filter((m) => m.id !== messageId));
    },
    [setMessages],
  );

  // Drop every queued payload without sending. Call on route-level resets
  // (queen switch, colony switch) — the hook outlives those transitions,
  // so without this, stale queue entries flush into the new session.
  const clear = useCallback(() => {
    queueRef.current.clear();
  }, []);

  // Pop and send the oldest queued message (Map iteration is insertion
  // order in JS). One-at-a-time semantics: used for both the Stop-button
  // path (cancel current turn, send next) and the natural-turn-end path
  // (on `execution_completed`, pick up the next queued message).
  const flushNext = useCallback(() => {
    const first = queueRef.current.entries().next();
    if (first.done) return;
    const [firstId, payload] = first.value;
    // Send FIRST, dequeue only on acceptance — see steer() for why the
    // old delete-then-send order destroyed messages.
    if (sendToBackend(payload.text, payload.images, payload.displayMessage) === false) {
      return; // still queued — the next flush trigger retries
    }
    queueRef.current.delete(firstId);
    // Re-stamp to send time — same reasoning as steer(): the message
    // enters the conversation now (at this turn boundary), not when typed.
    setMessages((prev) =>
      prev.map((m) =>
        m.id === firstId ? { ...m, queued: false, createdAt: Date.now() } : m,
      ),
    );
    onFlushStart?.();
  }, [sendToBackend, setMessages, onFlushStart]);

  // Ref to the latest flushNext so SSE handlers captured with narrow deps
  // can still invoke the up-to-date closure.
  const flushNextRef = useRef(flushNext);
  flushNextRef.current = flushNext;

  return { enqueue, steer, cancelQueued, flushNext, flushNextRef, clear };
}
