import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useColony } from "@/context/ColonyContext";
import { useHeaderActions } from "@/context/HeaderActionsContext";
import { getQueenForAgent } from "@/lib/colony-registry";
import { Crown, KeyRound, Network } from "lucide-react";
import SettingsModal from "@/components/SettingsModal";
import ModelSwitcher from "@/components/ModelSwitcher";

interface AppHeaderProps {
  onOpenQueenProfile?: (queenId: string) => void;
}

export default function AppHeader({ onOpenQueenProfile }: AppHeaderProps) {
  const location = useLocation();
  const { colonies, queens, queenProfiles, userProfile } = useColony();
  const { actions } = useHeaderActions();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<"profile" | "byok">("profile");

  // Derive page title + icon from current route
  const colonyMatch = location.pathname.match(/^\/colony\/(.+)/);
  const queenMatch = location.pathname.match(/^\/queen\/(.+)/);

  let title = "OpenHive";
  let icon: React.ReactNode = null;
  let queenTitle: string | null = null;
  let queenIdForProfile: string | null = null;

  if (colonyMatch) {
    const colonyId = colonyMatch[1];
    const colony = colonies.find((c) => c.id === colonyId);
    title = colony?.name ?? colonyId;
  } else if (queenMatch) {
    const queenId = queenMatch[1];
    const profile = queenProfiles.find((q) => q.id === queenId);
    const queen = queens.find((q) => q.id === queenId);
    const queenInfo = getQueenForAgent(queenId);
    title = profile?.name ?? queen?.name ?? queenInfo.name;
    queenTitle = profile?.title ?? queen?.role ?? queenInfo.role;
    icon = <Crown className="w-4 h-4 text-primary" />;
    // Only enable the profile popup when we have a real profile to show.
    if (profile) queenIdForProfile = profile.id;
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

  const queenHeaderContent = (
    <>
      {icon}
      <h1 className="text-sm font-semibold text-foreground">{title}</h1>
      {queenTitle && (
        <span className="inline-flex items-center rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary shadow-sm">
          {queenTitle}
        </span>
      )}
    </>
  );

  return (
    <>
      <div className="relative z-20 h-12 flex items-center justify-between px-5 border-b border-border/60 bg-card/50 backdrop-blur-sm flex-shrink-0">
        {queenIdForProfile ? (
          <button
            onClick={() => onOpenQueenProfile?.(queenIdForProfile!)}
            className="flex items-center gap-2 rounded-md px-1.5 -mx-1.5 py-0.5 hover:bg-muted/60 transition-colors"
            title={`View ${title}'s profile`}
          >
            {queenHeaderContent}
          </button>
        ) : (
          <div className="flex items-center gap-2">{queenHeaderContent}</div>
        )}
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
