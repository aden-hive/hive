import {
  MessageSquare,
  LayoutDashboard,
  Settings,
  Layers,
  History,
  Plus,
  Zap,
  PanelLeftClose,
  LogOut,
  Circle,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { RECENT_SESSIONS } from "@/data/mock-data";
import type { SessionItem } from "@/hooks/useSessions";
import type { AgentTemplate } from "@/data/mock-data";

type View = "chat" | "dashboard" | "settings" | "templates" | "logs";

interface AppSidebarProps {
  activeView: View;
  onViewChange: (view: View) => void;
  isOpen: boolean;
  onToggle: () => void;
  sessions: SessionItem[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onSignOut?: () => void;
  activeTemplate?: AgentTemplate | null;
}

const NAV_ITEMS: { icon: typeof MessageSquare; label: string; view: View }[] = [
  { icon: MessageSquare, label: "Chat", view: "chat" },
  { icon: LayoutDashboard, label: "Dashboard", view: "dashboard" },
  { icon: Layers, label: "Templates", view: "templates" },
  { icon: History, label: "Logs", view: "logs" },
  { icon: Settings, label: "Settings", view: "settings" },
];

const STATUS_DOT: Record<string, string> = {
  running: "text-primary",
  completed: "text-success",
  failed: "text-destructive",
};

export function AppSidebar({
  activeView,
  onViewChange,
  isOpen,
  onToggle,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  activeTemplate,
}: AppSidebarProps) {
  const { signOut, user } = useAuth();

  const hasSessions = sessions.length > 0;
  const displaySessions = hasSessions
    ? sessions.slice(0, 10)
    : RECENT_SESSIONS.slice(0, 7);

  return (
    <>
      {isOpen && (
        <div className="fixed inset-0 bg-foreground/20 backdrop-blur-[2px] z-40 lg:hidden" onClick={onToggle} />
      )}

      <aside
        className={`fixed lg:relative z-50 h-full w-[240px] border-r border-border bg-card flex flex-col shrink-0 transition-transform duration-200 ease-out ${
          isOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        {/* Logo */}
        <div className="h-12 px-4 flex items-center justify-between border-b border-border">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-primary rounded-md flex items-center justify-center text-primary-foreground">
              <Zap size={13} strokeWidth={2.5} />
            </div>
            <span className="font-display font-bold text-[14px] tracking-tight text-foreground">Nexus</span>
          </div>
          <button
            onClick={onToggle}
            className="p-1 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors lg:hidden"
          >
            <PanelLeftClose size={14} />
          </button>
        </div>

        {/* New Session */}
        <div className="px-3 pt-3">
          <button
            onClick={onNewSession}
            className="w-full flex items-center justify-center gap-1.5 bg-primary text-primary-foreground py-2 rounded-lg text-[12px] font-semibold hover:opacity-90 transition-all"
          >
            <Plus size={13} strokeWidth={2.5} /> New Session
          </button>
        </div>

        {/* Active template indicator */}
        {activeTemplate && (
          <div className="mx-3 mt-2.5 px-2.5 py-2 bg-primary/5 border border-primary/15 rounded-lg">
            <p className="text-[10px] font-bold text-primary truncate">{activeTemplate.title}</p>
            <p className="text-[9px] text-muted-foreground/50 mt-0.5">Active template</p>
          </div>
        )}

        {/* Nav */}
        <nav className="px-3 pt-3 space-y-px">
          {NAV_ITEMS.map(({ icon: Icon, label, view }) => (
            <button
              key={view}
              onClick={() => { onViewChange(view); if (window.innerWidth < 1024) onToggle(); }}
              className={`w-full flex items-center gap-2.5 px-2.5 py-[7px] rounded-lg transition-all duration-100 group text-[12px] font-medium ${
                activeView === view
                  ? "bg-primary/8 text-foreground"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              }`}
            >
              <Icon size={14} strokeWidth={activeView === view ? 2.25 : 1.75} className={activeView === view ? "text-primary" : "group-hover:text-foreground"} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        {/* Sessions */}
        <div className="flex-1 overflow-y-auto no-scrollbar px-3 pt-4 pb-2">
          <div className="px-2.5 mb-1.5">
            <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-muted-foreground/50">
              History
            </span>
          </div>
          <div className="space-y-px">
            {displaySessions.map((session) => {
              const isActive = hasSessions && session.id === activeSessionId;
              const mockSession = !hasSessions ? RECENT_SESSIONS.find(s => s.id === session.id) : null;
              return (
                <button
                  key={session.id}
                  onClick={() => hasSessions ? onSelectSession(session.id) : onViewChange("chat")}
                  className={`w-full text-left px-2.5 py-[6px] rounded-md transition-colors ${
                    isActive
                      ? "text-foreground bg-muted font-medium"
                      : "text-muted-foreground/70 hover:text-foreground hover:bg-muted/40"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    {mockSession && (
                      <Circle size={5} className={`shrink-0 fill-current ${STATUS_DOT[mockSession.status] || "text-muted-foreground/30"}`} />
                    )}
                    <span className="text-[11px] truncate block">{session.title}</span>
                  </div>
                  {mockSession && (
                    <p className="text-[9px] text-muted-foreground/35 mt-px truncate pl-[14px]">{mockSession.date}</p>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Bottom */}
        <div className="px-3 py-2.5 border-t border-border">
          {user && (
            <div className="flex items-center justify-between px-1.5">
              <p className="text-[10px] text-muted-foreground/40 truncate flex-1">{user.email}</p>
              <button
                onClick={signOut}
                className="p-1 text-muted-foreground/30 hover:text-foreground hover:bg-muted rounded-md transition-colors ml-1"
                title="Sign out"
              >
                <LogOut size={12} />
              </button>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
