import { useEffect, useState, useCallback } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import AppHeader from "@/components/AppHeader";
import QueenProfilePanel from "@/components/QueenProfilePanel";
import ColonyWorkersPanel from "@/components/ColonyWorkersPanel";
import { ColonyProvider, useColony } from "@/context/ColonyContext";
import { HeaderActionsProvider } from "@/context/HeaderActionsContext";
import { QueenProfileProvider } from "@/context/QueenProfileContext";
import { ColonyWorkersProvider } from "@/context/ColonyWorkersContext";

export default function AppLayout() {
  return (
    <ColonyProvider>
      <HeaderActionsProvider>
        <AppLayoutInner />
      </HeaderActionsProvider>
    </ColonyProvider>
  );
}

function AppLayoutInner() {
  const { colonies } = useColony();
  const location = useLocation();
  const [openQueenId, setOpenQueenId] = useState<string | null>(null);
  const [openWorkersSessionId, setOpenWorkersSessionId] = useState<string | null>(
    null,
  );

  // Close side panels whenever the route changes so they don't bleed
  // across pages (panel state lives at the layout level).
  useEffect(() => {
    setOpenQueenId(null);
    setOpenWorkersSessionId(null);
  }, [location.pathname]);

  const handleOpenQueenProfile = useCallback(
    (queenId: string) => setOpenQueenId((prev) => (prev === queenId ? null : queenId)),
    [],
  );

  const handleOpenColonyWorkers = useCallback(
    (sessionId: string) =>
      setOpenWorkersSessionId((prev) => (prev === sessionId ? null : sessionId)),
    [],
  );

  return (
    <QueenProfileProvider onOpen={handleOpenQueenProfile}>
      <ColonyWorkersProvider onOpen={handleOpenColonyWorkers}>
        <div className="flex h-screen bg-background overflow-hidden">
          <Sidebar />
          <div className="flex-1 min-w-0 flex flex-col">
            <AppHeader onOpenQueenProfile={handleOpenQueenProfile} />
            <div className="flex-1 min-h-0 flex">
              <main className="flex-1 min-w-0 flex flex-col">
                <Outlet />
              </main>
              {openQueenId && (
                <QueenProfilePanel
                  queenId={openQueenId}
                  colonies={colonies.filter(
                    (c) => c.queenProfileId === openQueenId,
                  )}
                  onClose={() => setOpenQueenId(null)}
                />
              )}
              {openWorkersSessionId && (
                <ColonyWorkersPanel
                  sessionId={openWorkersSessionId}
                  onClose={() => setOpenWorkersSessionId(null)}
                />
              )}
            </div>
          </div>
        </div>
      </ColonyWorkersProvider>
    </QueenProfileProvider>
  );
}
