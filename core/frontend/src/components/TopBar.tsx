import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Crown, X } from "lucide-react";
import {
  loadPersistedTabs,
  savePersistedTabs,
  TAB_STORAGE_KEY,
  type PersistedTabState,
} from "@/lib/tab-persistence";
import { sessionsApi } from "@/api/sessions";
import ThemeToggle from "./ThemeToggle";

export interface TopBarTab {
  agentType: string;
  label: string;
  isActive: boolean;
  hasRunning: boolean;
}

interface TopBarProps {
  tabs?: TopBarTab[];
  onTabClick?: (agentType: string) => void;
  onCloseTab?: (agentType: string) => void;
  canCloseTabs?: boolean;
  afterTabs?: React.ReactNode;
  children?: React.ReactNode;
}

export default function TopBar({
  tabs: tabsProp,
  onTabClick,
  onCloseTab,
  canCloseTabs,
  afterTabs,
  children,
}: TopBarProps) {
  const navigate = useNavigate();

  /* ---------------- EXISTING CODE ---------------- */

  const [persisted, setPersisted] = useState<PersistedTabState | null>(() =>
    tabsProp ? null : loadPersistedTabs(),
  );

  const tabs: TopBarTab[] = tabsProp ?? deriveTabs(persisted);
  const showClose = canCloseTabs ?? true;

  const handleTabClick = useCallback(
    (agentType: string) => {
      if (onTabClick) {
        onTabClick(agentType);
      } else {
        navigate(`/workspace?agent=${encodeURIComponent(agentType)}`);
      }
    },
    [onTabClick, navigate],
  );

  const handleCloseTab = useCallback(
    (agentType: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (onCloseTab) {
        onCloseTab(agentType);
        return;
      }

      sessionsApi
        .list()
        .then(({ sessions }) => {
          const match = sessions.find((s) => s.agent_path === agentType);
          if (match) return sessionsApi.stop(match.session_id);
        })
        .catch(() => {});

      setPersisted((prev) => {
        if (!prev) return null;
        const nextTabs = prev.tabs.filter((t) => t.agentType !== agentType);

        if (nextTabs.length === 0) {
          localStorage.removeItem(TAB_STORAGE_KEY);
          return null;
        }

        const removedIds = new Set(
          prev.tabs.filter((t) => t.agentType === agentType).map((t) => t.id),
        );
        const nextSessions = { ...prev.sessions };
        for (const id of removedIds) delete nextSessions[id];

        const nextActiveSession = { ...prev.activeSessionByAgent };
        delete nextActiveSession[agentType];

        const nextActiveWorker =
          prev.activeWorker === agentType
            ? nextTabs[0].agentType
            : prev.activeWorker;

        const nextState: PersistedTabState = {
          tabs: nextTabs,
          activeSessionByAgent: nextActiveSession,
          activeWorker: nextActiveWorker,
          sessions: nextSessions,
        };

        savePersistedTabs(nextState);
        return nextState;
      });
    },
    [onCloseTab],
  );

  return (
    <div className="relative h-12 flex items-center justify-between px-5 border-b border-border/60 bg-card/50 backdrop-blur-sm">
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
        >
          <Crown className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold text-primary">Open Hive</span>
        </button>

        {tabs.length > 0 && (
          <>
            <span className="text-border text-xs">|</span>
            <div className="flex items-center gap-0.5 min-w-0 overflow-x-auto scrollbar-hide">
              {tabs.map((tab) => (
                <button
                  key={tab.agentType}
                  onClick={() => handleTabClick(tab.agentType)}
                  className={`group flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
                    tab.isActive
                      ? "bg-primary/15 text-primary"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
                >
                  {tab.hasRunning && (
                    <span className="relative flex h-1.5 w-1.5 ">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-60" />
                      <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-primary" />
                    </span>
                  )}

                  <span>{tab.label}</span>

                  {showClose && (
                    <X
                      className="w-3 h-3 opacity-0 group-hover:opacity-60 transition-opacity"
                      onClick={(e) => handleCloseTab(tab.agentType, e)}
                    />
                  )}
                </button>
              ))}
            </div>

            {afterTabs}
          </>
        )}
      </div>

      <div className="flex items-center gap-2">
        {/* THEME BUTTON */}
        <ThemeToggle />

        {children}
      </div>
    </div>
  );
}

function deriveTabs(persisted: PersistedTabState | null): TopBarTab[] {
  if (!persisted) return [];

  const seen = new Set<string>();
  const tabs: TopBarTab[] = [];

  for (const tab of persisted.tabs) {
    if (seen.has(tab.agentType)) continue;

    seen.add(tab.agentType);

    const sessionData = persisted.sessions?.[tab.id];

    const hasRunning =
      sessionData?.graphNodes?.some(
        (n) => n.status === "running" || n.status === "looping",
      ) ?? false;

    tabs.push({
      agentType: tab.agentType,
      label: tab.label,
      isActive: false,
      hasRunning,
    });
  }

  return tabs;
}
