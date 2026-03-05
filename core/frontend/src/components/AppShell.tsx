/**
 * AppShell — persistent layout wrapper for Home and MyAgents pages.
 *
 * Renders: TopBar (full width) + HistorySidebar (left) + page content (right).
 * Workspace has its own full layout and does NOT use this wrapper.
 */

import { useNavigate } from "react-router-dom";
import TopBar from "@/components/TopBar";
import HistorySidebar from "@/components/HistorySidebar";

interface AppShellProps {
  children: React.ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
  const navigate = useNavigate();

  const handleOpenSession = (sessionId: string, agentPath?: string | null) => {
    const params = new URLSearchParams();
    params.set("session", sessionId);
    if (agentPath) params.set("agent", agentPath);
    navigate(`/workspace?${params.toString()}`);
  };

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <TopBar />
      <div className="flex flex-1 min-h-0">
        <HistorySidebar
          onOpen={handleOpenSession}
          onNewChat={() => navigate("/")}
        />
        <div className="flex-1 min-h-0 overflow-y-auto">
          {children}
        </div>
      </div>
    </div>
  );
}
