import { useState } from "react";
import { NavLink } from "react-router-dom";
import type { QueenProfileSummary } from "@/types/colony";

interface SidebarQueenItemProps {
  queen: QueenProfileSummary;
  isActive?: boolean;
}

export default function SidebarQueenItem({ queen, isActive }: SidebarQueenItemProps) {
  const [hasAvatar, setHasAvatar] = useState(true);
  const avatarUrl = `/api/queen/${queen.id}/avatar`;

  return (
    <NavLink
      to={`/queen/${queen.id}`}
      className={({ isActive: isRouteActive }) =>
        `group flex items-center gap-2.5 px-3 py-1.5 mx-2 rounded-md text-sm transition-colors ${
          isRouteActive
            ? "bg-sidebar-active-bg text-foreground font-medium"
            : "text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground"
        }`
      }
    >
      <span className="relative flex-shrink-0 w-6 h-6 rounded-full bg-primary/15 flex items-center justify-center">
        <span className="w-full h-full rounded-full overflow-hidden flex items-center justify-center">
          {hasAvatar ? (
            <img src={avatarUrl} alt={queen.name} className="w-full h-full object-cover" onError={() => setHasAvatar(false)} />
          ) : (
            <span className="text-[10px] font-bold text-primary">{queen.name.charAt(0)}</span>
          )}
        </span>
        {isActive && (
          <span
            className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-500 ring-2 ring-sidebar-bg"
            title="Session running"
          />
        )}
      </span>
      <div className="min-w-0 flex-1 flex items-center gap-2">
        <span className="font-medium truncate">{queen.name}</span>
        <span className="text-xs text-sidebar-muted truncate">
          {queen.title.replace(/^Head of\s+/i, "")}
        </span>
      </div>
    </NavLink>
  );
}
