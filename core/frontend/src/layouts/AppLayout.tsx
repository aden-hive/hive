import { useEffect, useState, useCallback, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import AppHeader from "@/components/AppHeader";
import QueenProfilePanel from "@/components/QueenProfilePanel";
import ColonyWorkersPanel from "@/components/ColonyWorkersPanel";
import TaskListPanel, { TaskListPanelStacked } from "@/components/TaskListPanel";
import { sessionTaskListId, colonyTaskListId } from "@/api/tasks";
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
  const { sessionId, colonyName, dismissed, toggleColonyWorkers } =
    useColonyWorkers();
  // Workers panel is colony-only — queen-DM may publish a sessionId for
  // the tasks panel below, but we don't want the workers panel showing
  // up there (no workers exist).
  const showWorkersPanel = Boolean(sessionId && colonyName && !dismissed);
  const location = useLocation();
  const [taskPanelDismissed, setTaskPanelDismissed] = useState(false);

  // Determine which task panel to show based on the current route.
  // queen-DM (/queen/...)              -> single TaskListPanel for queen session
  // colony chat (/colony/{name})       -> stacked (template + queen session)
  // anywhere else                      -> hidden
  const isColony = location.pathname.startsWith("/colony/");
  const isQueenDm = location.pathname.startsWith("/queen/");
  const showTasksPanel = !taskPanelDismissed && Boolean(sessionId) && (isQueenDm || isColony);

  let tasksPanel: ReactNode = null;
  if (showTasksPanel && sessionId) {
    if (isColony) {
      const colonyId = colonyName ?? location.pathname.replace("/colony/", "");
      tasksPanel = (
        <TaskListPanelStacked
          templateTaskListId={colonyTaskListId(colonyId)}
          queenSessionTaskListId={sessionTaskListId("queen", sessionId)}
          sessionId={sessionId}
          onClose={() => setTaskPanelDismissed(true)}
        />
      );
    } else {
      tasksPanel = (
        <TaskListPanel
          taskListId={sessionTaskListId("queen", sessionId)}
          sessionId={sessionId}
          variant="rail"
          onClose={() => setTaskPanelDismissed(true)}
        />
      );
    }
  }

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
              colonyName={colonyName}
              onClose={toggleColonyWorkers}
            />
          )}
          {tasksPanel}
        </div>
      </div>
    </div>
  );
}

// Re-exported so tsc sees React used (removes import-only warning when
// the file compiles down to JSX-less output).
export type { ReactNode };
