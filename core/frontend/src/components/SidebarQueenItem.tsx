import { NavLink } from "react-router-dom";
import type { QueenProfileSummary } from "@/types/colony";
import type { QueenLiveness } from "@/hooks/use-live-sessions";
import QueenAvatar from "./QueenAvatar";

interface SidebarQueenItemProps {
  queen: QueenProfileSummary;
  /** True when this queen is the queen-of-interest in the current
   * session listing (legacy "online" status). Kept for backwards
   * compatibility with the green dot on the route-active queen. */
  isActive?: boolean;
  /** Live snapshot for this queen, aggregated across any of its
   * active sessions. Set by the sidebar from useLiveSessions. */
  liveness?: QueenLiveness;
}

export default function SidebarQueenItem({ queen, isActive, liveness }: SidebarQueenItemProps) {
  // Bottom-right presence dot: executing/active gets a pulsing green
  // dot; interrupted gets a steady amber dot. The "parked" state is
  // communicated by the colony status dot colour — no separate badge.
  let dotColor: string | null = null;
  let dotPulse = false;
  let title = "";
  if (liveness?.interrupted) {
    // Not moving and not a deliberate end-of-turn — a broken park,
    // stream stall, or crash. Amber, steady (a problem, not presence).
    dotColor = "bg-amber-500";
    title = liveness.interrupt_cause
      ? `Interrupted: ${liveness.interrupt_cause}`
      : "Interrupted";
  } else if (liveness?.is_executing) {
    dotColor = "bg-emerald-500";
    dotPulse = true;
    title = liveness.current_tool_name
      ? `Running: ${liveness.current_tool_name}`
      : liveness.queen_busy_reason === "llm"
        ? "Thinking…"
        : "Working";
  } else if (isActive) {
    dotColor = "bg-emerald-500";
    title = "Working";
  }

  return (
    <NavLink
      to={`/queen/${queen.id}`}
      className={({ isActive: isRouteActive }) =>
        `group flex items-center gap-2.5 px-3 py-1.5 mx-2 rounded-md text-[12.5px] transition-colors ${
          isRouteActive
            ? "bg-sidebar-active-bg text-foreground font-medium"
            : "text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground"
        }`
      }
    >
      <span className="relative flex-shrink-0">
        <QueenAvatar queen={queen} className="w-6 h-6" />
        {dotColor && (
          <span
            className="absolute -bottom-0.5 -right-0.5 flex h-2 w-2"
            title={title}
          >
            {dotPulse && (
              <span
                className={`absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping ${dotColor}`}
              />
            )}
            <span
              className={`relative inline-flex h-2 w-2 rounded-full ring-2 ring-sidebar-bg ${dotColor}`}
            />
          </span>
        )}
      </span>
      <div className="min-w-0 flex-1 flex items-center gap-2">
        <span
          className="truncate font-medium"
        >
          {queen.name}
        </span>
        <span className="text-[11.5px] text-sidebar-muted truncate">
          {queen.title.replace(/^Head of\s+/i, "")}
        </span>
      </div>
    </NavLink>
  );
}
