import { NavLink } from "react-router-dom";
import type { QueenBee } from "@/types/colony";

interface SidebarQueenItemProps {
  queen: QueenBee;
}

export default function SidebarQueenItem({ queen }: SidebarQueenItemProps) {
  return (
    <NavLink
      to={`/queen/${queen.id}`}
      className={({ isActive }) =>
        `group flex items-center gap-2.5 px-3 py-1.5 mx-2 rounded-md text-sm transition-colors ${
          isActive
            ? "bg-sidebar-active-bg text-foreground font-medium"
            : "text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground"
        }`
      }
    >
      <span
        className={`flex-shrink-0 w-2 h-2 rounded-full ${
          queen.status === "online" ? "bg-status-online" : "bg-status-offline"
        }`}
      />
      <div className="min-w-0 flex-1 flex items-center gap-2">
        <span className="font-medium truncate">{queen.name}</span>
        <span className="text-xs text-sidebar-muted truncate">{queen.role}</span>
      </div>
    </NavLink>
  );
}
