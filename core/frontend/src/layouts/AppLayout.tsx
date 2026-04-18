import { useEffect, useState, useCallback, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import AppHeader from "@/components/AppHeader";
import QueenProfilePanel from "@/components/QueenProfilePanel";
import ColonyWorkersPanel from "@/components/ColonyWorkersPanel";
import { ColonyProvider, useColony } from "@/context/ColonyContext";
import { HeaderActionsProvider } from "@/context/HeaderActionsContext";
import { QueenProfileProvider } from "@/context/QueenProfileContext";
import {
  ColonyWorkersProvider,
  useColonyWorkers,
} from "@/context/ColonyWorkersContext";

export default function AppLayout() {
  return (
    <ColonyProvider>
      <HeaderActionsProvider>
        <ColonyWorkersProvider>
          <AppLayoutInner />
        </ColonyWorkersProvider>
      </HeaderActionsProvider>
    </ColonyProvider>
  );
}

function AppLayoutInner() {
  const { colonies } = useColony();
  const location = useLocation();
  const [openQueenId, setOpenQueenId] = useState<string | null>(null);

  // Queen profile closes on route change (it's a per-queen view).
  useEffect(() => {
    setOpenQueenId(null);
  }, [location.pathname]);

  const handleOpenQueenProfile = useCallback(
    (queenId: string) => setOpenQueenId((prev) => (prev === queenId ? null : queenId)),
    [],
  );

  return (
    <QueenProfileProvider onOpen={handleOpenQueenProfile}>
      <LayoutShell
        openQueenId={openQueenId}
        onCloseQueenProfile={() => setOpenQueenId(null)}
        onOpenQueenProfile={handleOpenQueenProfile}
        colonies={colonies}
      />
    </QueenProfileProvider>
  );
}

function LayoutShell({
  openQueenId,
  onCloseQueenProfile,
  onOpenQueenProfile,
  colonies,
}: {
  openQueenId: string | null;
  onCloseQueenProfile: () => void;
  onOpenQueenProfile: (queenId: string) => void;
  colonies: ReturnType<typeof useColony>["colonies"];
}) {
  const { sessionId, dismissed, toggleColonyWorkers } = useColonyWorkers();
  const showWorkersPanel = Boolean(sessionId && !dismissed);

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <AppHeader onOpenQueenProfile={onOpenQueenProfile} />
        <div className="flex-1 min-h-0 flex">
          <main className="flex-1 min-w-0 flex flex-col">
            <Outlet />
          </main>
          {openQueenId && (
            <QueenProfilePanel
              queenId={openQueenId}
              colonies={colonies.filter((c) => c.queenProfileId === openQueenId)}
              onClose={onCloseQueenProfile}
            />
          )}
          {showWorkersPanel && sessionId && (
            <ColonyWorkersPanel
              sessionId={sessionId}
              onClose={toggleColonyWorkers}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// Re-exported so tsc sees React used (removes import-only warning when
// the file compiles down to JSX-less output).
export type { ReactNode };
