import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useColony } from "@/context/ColonyContext";
import { useHeaderActions } from "@/context/HeaderActionsContext";
import { getQueenForAgent } from "@/lib/colony-registry";
import { Crown, KeyRound, Network } from "lucide-react";
import SettingsModal from "@/components/SettingsModal";
import ModelSwitcher from "@/components/ModelSwitcher";

export default function AppHeader() {
  const location = useLocation();
  const { colonies, queens, userProfile } = useColony();
  const { actions } = useHeaderActions();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<"profile" | "byok">("profile");

  // Derive page title + icon from current route
  const colonyMatch = location.pathname.match(/^\/colony\/(.+)/);
  const queenMatch = location.pathname.match(/^\/queen\/(.+)/);

  let title = "OpenHive";
  let icon: React.ReactNode = null;

  if (colonyMatch) {
    const colonyId = colonyMatch[1];
    const colony = colonies.find((c) => c.id === colonyId);
    title = colony?.name ?? colonyId;
  } else if (queenMatch) {
    const queenId = queenMatch[1];
    const queen = queens.find((q) => q.id === queenId);
    const queenInfo = getQueenForAgent(queenId);
    title = queen?.name ?? queenInfo.name;
    icon = <Crown className="w-4 h-4 text-primary" />;
  } else if (location.pathname === "/org-chart") {
    title = "Org Chart";
    icon = <Network className="w-4 h-4 text-muted-foreground/60" />;
  } else if (location.pathname === "/credentials") {
    title = "Credentials";
    icon = <KeyRound className="w-4 h-4 text-muted-foreground/60" />;
  }

  // Profile initials
  const initials = userProfile.displayName
    .trim()
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <>
      <div className="relative z-20 h-12 flex items-center justify-between px-5 border-b border-border/60 bg-card/50 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-2">
          {icon}
          <h1 className="text-sm font-semibold text-foreground">{title}</h1>
        </div>
        <div className="flex items-center gap-2">
          {actions}
          <ModelSwitcher
            onOpenSettings={() => {
              setSettingsSection("byok");
              setSettingsOpen(true);
            }}
          />
          <button
            onClick={() => {
              setSettingsSection("profile");
              setSettingsOpen(true);
            }}
            className="w-7 h-7 rounded-full bg-primary/15 flex items-center justify-center hover:bg-primary/25 transition-colors"
            title="Profile settings"
          >
            <span className="text-[10px] font-bold text-primary">
              {initials || "U"}
            </span>
          </button>
        </div>
      </div>

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        initialSection={settingsSection}
      />
    </>
  );
}
