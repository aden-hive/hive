import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  MessageSquarePlus,
  Network,
  Sparkles,
  KeyRound,
  ChevronDown,
} from "lucide-react";
import SidebarColonyItem from "./SidebarColonyItem";
import SidebarQueenItem from "./SidebarQueenItem";
import { useColony } from "@/context/ColonyContext";

export default function Sidebar() {
  const navigate = useNavigate();
  const { colonies, queenProfiles, sidebarCollapsed, setSidebarCollapsed } = useColony();
  const [coloniesExpanded, setColoniesExpanded] = useState(true);
  const [queensExpanded, setQueensExpanded] = useState(true);

  if (sidebarCollapsed) {
    return (
      <aside className="w-[52px] flex-shrink-0 flex flex-col bg-sidebar-bg border-r border-sidebar-border h-full">
        {/* Logo */}
        <div className="h-12 flex items-center justify-center border-b border-border/60">
          <button
            onClick={() => navigate("/")}
            className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center hover:bg-primary/20 transition-colors"
          >
            <span className="text-primary text-sm font-bold">H</span>
          </button>
        </div>

        {/* Expand button */}
        <div className="flex-1 flex flex-col items-center py-3 gap-1">
          <button
            onClick={() => setSidebarCollapsed(false)}
            className="w-8 h-8 rounded-md flex items-center justify-center text-sidebar-muted hover:text-foreground hover:bg-sidebar-item-hover transition-colors"
            title="Expand sidebar"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="w-[240px] flex-shrink-0 flex flex-col bg-sidebar-bg border-r border-sidebar-border h-full">
      {/* Header */}
      <div className="h-12 flex items-center justify-between px-4 border-b border-border/60">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
        >
          <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
            <span className="text-primary text-xs font-bold">H</span>
          </div>
          <div className="flex items-baseline gap-0.5">
            <span className="text-sm font-bold text-primary">Open</span>
            <span className="text-sm font-bold text-foreground">Hive</span>
          </div>
        </button>
        <button
          onClick={() => setSidebarCollapsed(true)}
          className="p-1 rounded-md text-sidebar-muted hover:text-foreground hover:bg-sidebar-item-hover transition-colors"
          title="Collapse sidebar"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
      </div>

      {/* Nav links */}
      <div className="px-2 py-3 flex flex-col gap-0.5 border-b border-border/60">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground transition-colors"
        >
          <MessageSquarePlus className="w-4 h-4" />
          <span>New Chat</span>
        </button>
        <button
          onClick={() => navigate("/org-chart")}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground transition-colors"
        >
          <Network className="w-4 h-4" />
          <span>Org Chart</span>
        </button>
        <button
          onClick={() => navigate("/prompt-library")}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground transition-colors"
        >
          <Sparkles className="w-4 h-4" />
          <span>Prompt Library</span>
        </button>
        <button
          onClick={() => navigate("/credentials")}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground transition-colors"
        >
          <KeyRound className="w-4 h-4" />
          <span>Credentials</span>
        </button>
      </div>

      {/* COLONIES section */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="py-2">
          <button
            onClick={() => setColoniesExpanded((v) => !v)}
            className="flex items-center gap-1.5 px-4 py-1.5 w-full text-[11px] font-semibold text-sidebar-section-text uppercase tracking-wider hover:text-foreground transition-colors"
          >
            <ChevronDown
              className={`w-3 h-3 transition-transform ${coloniesExpanded ? "" : "-rotate-90"}`}
            />
            <span>Colonies</span>
            {colonies.length > 0 && (
              <span className="ml-auto text-[10px] bg-sidebar-item-hover rounded-full px-1.5 py-0.5 font-medium">
                {colonies.length}
              </span>
            )}
          </button>
          {coloniesExpanded && (
            <div className="flex flex-col gap-0.5 mt-0.5">
              {colonies.map((colony) => (
                <SidebarColonyItem key={colony.id} colony={colony} />
              ))}
              {colonies.length === 0 && (
                <p className="px-5 py-2 text-xs text-sidebar-muted">
                  No colonies yet
                </p>
              )}
            </div>
          )}
        </div>

        {/* QUEEN BEES section */}
        <div className="py-2">
          <button
            onClick={() => setQueensExpanded((v) => !v)}
            className="flex items-center gap-1.5 px-4 py-1.5 w-full text-[11px] font-semibold text-sidebar-section-text uppercase tracking-wider hover:text-foreground transition-colors"
          >
            <ChevronDown
              className={`w-3 h-3 transition-transform ${queensExpanded ? "" : "-rotate-90"}`}
            />
            <span>Queen Bees</span>
          </button>
          {queensExpanded && (
            <div className="flex flex-col gap-0.5 mt-0.5">
              {queenProfiles.map((queen) => (
                <SidebarQueenItem key={queen.id} queen={queen} />
              ))}
              {queenProfiles.length === 0 && (
                <p className="px-5 py-2 text-xs text-sidebar-muted">
                  Loading queens...
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
