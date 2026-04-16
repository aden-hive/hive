import { useEffect, useState, useCallback } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import AppHeader from "@/components/AppHeader";
import QueenProfilePanel from "@/components/QueenProfilePanel";
import { ColonyProvider, useColony } from "@/context/ColonyContext";
import { HeaderActionsProvider } from "@/context/HeaderActionsContext";
import { QueenProfileProvider } from "@/context/QueenProfileContext";

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

  // Close the profile panel whenever the route changes so it doesn't
  // bleed across pages (the panel state lives at the layout level).
  useEffect(() => {
    setOpenQueenId(null);
  }, [location.pathname]);

  const handleOpenQueenProfile = useCallback(
    (queenId: string) => setOpenQueenId((prev) => (prev === queenId ? null : queenId)),
    [],
  );

  return (
    <QueenProfileProvider onOpen={handleOpenQueenProfile}>
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
          </div>
        </div>
      </div>
    </QueenProfileProvider>
  );
}
