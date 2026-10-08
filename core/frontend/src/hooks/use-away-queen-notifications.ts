import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { QueenLiveness } from "./use-live-sessions";

/**
 * Fire an OS notification once whenever an *away* queen transitions
 * into ``awaiting_input``.  Solves the inverse of the "stale modal"
 * bug: when the user is on queen B and queen A starts waiting on
 * input, they have no signal until they happen to navigate back.
 *
 * Rules:
 *   • Only fire when the user is NOT currently viewing that queen
 *     (otherwise the in-page modal is the better UX).
 *   • Only fire on the rising edge — re-arming when awaiting_input
 *     flips back to false. Avoids spamming if the queen oscillates.
 *   • Suppress if the user already saw the notification for this
 *     awaiting cycle (per queen). Reset when awaiting_input clears.
 *   • Best-effort: the OS may deny notification permission; we never
 *     throw. Browser notifications (DOM ``Notification``) ride on
 *     Electron's permission UI without extra wiring.
 */
export function useAwayQueenNotifications(byQueen: Map<string, QueenLiveness>) {
  const location = useLocation();
  const navigate = useNavigate();
  // Track the last awaiting state we observed per queen so we can
  // detect rising edges without re-firing on every snapshot.
  const lastAwaitingRef = useRef<Map<string, boolean>>(new Map());
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  useEffect(() => {
    if (typeof Notification === "undefined") return; // SSR / unsupported
    // Lazy permission: ask once when we have something to notify.
    let anyAwaiting = false;
    for (const [, l] of byQueen) {
      if (l.awaiting_input) {
        anyAwaiting = true;
        break;
      }
    }
    if (anyAwaiting && Notification.permission === "default") {
      // Fire-and-forget — the prompt is async, doesn't block us.
      void Notification.requestPermission();
    }

    // Determine which queen the user is currently viewing.
    const viewing = location.pathname.match(/^\/queen\/([^/]+)/)?.[1] ?? null;

    const last = lastAwaitingRef.current;
    for (const [queenId, liveness] of byQueen) {
      const wasAwaiting = last.get(queenId) === true;
      const isAwaiting = liveness.awaiting_input;
      last.set(queenId, isAwaiting);

      // Rising edge for an away queen → notify.
      if (isAwaiting && !wasAwaiting && queenId !== viewing) {
        if (Notification.permission === "granted") {
          try {
            const n = new Notification("A queen needs your input", {
              body: liveness.current_tool_name
                ? `Was running ${liveness.current_tool_name}, now waiting on you.`
                : "Click to answer.",
              tag: `queen-await-${queenId}`,
            });
            n.onclick = () => {
              window.focus();
              navigateRef.current(`/queen/${queenId}`);
              n.close();
            };
          } catch {
            // ignore — notification failures are not fatal
          }
        }
      }
    }
    // Drop trackers for queens that vanished from the live feed.
    for (const id of Array.from(last.keys())) {
      if (!byQueen.has(id)) last.delete(id);
    }
  }, [byQueen, location.pathname]);
}
