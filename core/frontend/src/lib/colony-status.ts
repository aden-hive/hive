import type { Colony } from "@/types/colony";
import type { QueenLiveness } from "@/hooks/use-live-sessions";

export type ColonyStatus = Colony["status"];

/**
 * A colony is "active" whenever *anything* in it is working — the overseer's
 * own loop OR the workers it dispatched.
 *
 * `is_executing` alone is not enough: the overseer parks its loop the moment it
 * fans work out to workers and waits for their reports, so a colony with N
 * workers churning away would render as "Parked" for the entire run. Counting
 * in-flight workers (queued/pending/running, from the /sessions/live feed) is
 * what makes the dot match reality.
 */
export function deriveColonyStatus(
  hasSession: boolean,
  liveness?: QueenLiveness,
): ColonyStatus {
  if (!hasSession) return "idle";
  if (liveness?.is_executing) return "active";
  if ((liveness?.active_worker_count ?? 0) > 0) return "active";
  if (liveness?.awaiting_input || liveness?.interrupted) return "parked";
  return "idle";
}

/**
 * The amber dot is a CALL TO ACTION: the colony has stopped and it needs the
 * user to do something. Every string here therefore tells them what to DO — it
 * never just narrates state ("finished its turn" leaves the user with nothing
 * to act on).
 *
 * Keys are the runtime's raw `park_reason` values (the last three are its
 * "broken" parks — see `ParkReason.is_broken`), but none of that vocabulary
 * reaches the user.
 */
const NEEDS_YOU_TEXT: Record<string, string> = {
  ask_user: "Needs your answer — reply to continue",
  turn_done: "Your turn — send a message to continue",
  llm_error: "Needs a retry — the AI hit an error. Send your message again.",
  empty_responses: "Needs a retry — no response came back. Send your message again.",
  doom_loop: "Needs your help — it was going in circles and stopped.",
};

/**
 * Plain-English explanation of a colony's status dot, for the hover tooltip.
 *
 * Shared by every surface that shows the dot, so the words can never drift from
 * the colour, and so all of them stay worker-aware — a colony whose overseer has
 * parked while its workers churn is *working*, and this says so.
 *
 * Deliberately jargon-free: no "queen", "parked", "session", "LLM", or raw
 * tool/park identifiers. Users are not developers; the Ctrl+Shift+D panel is
 * where the raw fields live.
 */
export function describeColonyStatus(
  status: ColonyStatus,
  liveness?: QueenLiveness,
): string {
  if (status === "idle") return "Idle — nothing is running";

  const workers = liveness?.active_worker_count ?? 0;

  if (status === "active") {
    // Workers are the headline when there are any — that's the work the user
    // can actually see happening on the Workers tab.
    if (workers > 0) {
      return `Working — ${workers} ${workers === 1 ? "task" : "tasks"} running`;
    }
    const tool = liveness?.current_tool_name;
    return tool
      ? `Working — using ${tool.replace(/_/g, " ")}`
      : "Working on your request";
  }

  // Amber dot — the colony has stopped and needs the user. Always a next step.
  if (liveness?.interrupted) return "Stopped — send a message to continue";
  const reason = liveness?.park_reason;
  if (reason) {
    return NEEDS_YOU_TEXT[reason] ?? "Your turn — send a message to continue";
  }
  return "Your turn — send a message to continue";
}

export const STATUS_DOT_CLASS: Record<ColonyStatus, string> = {
  active: "bg-status-online",
  idle: "bg-status-offline",
  parked: "bg-amber-500",
};

/** User-facing labels. "Parked" was internal jargon *and* passive — the amber
 *  state exists precisely because the colony needs the user, so it says so. */
export const STATUS_LABEL: Record<ColonyStatus, string> = {
  active: "Working",
  idle: "Idle",
  parked: "Your turn",
};

export const STATUS_TEXT_CLASS: Record<ColonyStatus, string> = {
  active: "text-emerald-500",
  idle: "text-muted-foreground",
  parked: "text-amber-500",
};
