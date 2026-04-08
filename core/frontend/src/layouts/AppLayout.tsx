import { Outlet } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import AppHeader from "@/components/AppHeader";
import { ColonyProvider } from "@/context/ColonyContext";
import { HeaderActionsProvider } from "@/context/HeaderActionsContext";

export default function AppLayout() {
  return (
    <ColonyProvider>
      <HeaderActionsProvider>
        <div className="flex h-screen bg-background overflow-hidden">
          <Sidebar />
          <div className="flex-1 min-w-0 flex flex-col">
            <AppHeader />
            <main className="flex-1 min-h-0 flex flex-col">
              <Outlet />
            </main>
          </div>
        </div>
      </HeaderActionsProvider>
    </ColonyProvider>
  );
}
