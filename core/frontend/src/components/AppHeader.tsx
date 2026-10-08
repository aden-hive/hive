import { useState, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { apiUrl } from "@/api/client";
import { useColony } from "@/context/ColonyContext";
import { useHeaderActions } from "@/context/HeaderActionsContext";
import { useModel } from "@/context/ModelContext";
import { getQueenForAgent } from "@/lib/colony-registry";
import {
  Crown,
  Component,
  Settings,
  GraduationCap,
} from "lucide-react";
import SettingsModal from "@/components/SettingsModal";
import ColonySettingsModal from "@/components/ColonySettingsModal";

/** OpenHive video tutorials — opens in the user's browser. */
const TUTORIAL_PLAYLIST_URL = "https://www.youtube.com/@adenhive";

/**
 * Avatar + account menu with profile settings and the tutorial link.
 */
function UserMenu({
  initials,
  onOpenSettings,
  avatarVersion,
  userHasAvatar,
}: {
  initials: string;
  onOpenSettings: () => void;
  avatarVersion: number;
  userHasAvatar: boolean;
}) {
  const [hasAvatar, setHasAvatar] = useState(userHasAvatar);
  const [menuOpen, setMenuOpen] = useState(false);
  const url = apiUrl(`/config/profile/avatar?v=${avatarVersion}`);
  // Re-evaluate when the version changes (new upload) or when the runtime
  // confirms presence on initial load.
  useEffect(() => setHasAvatar(userHasAvatar), [avatarVersion, userHasAvatar]);

  return (
    <div className="relative">
      <button
        onClick={() => setMenuOpen((o) => !o)}
        className="relative w-7 h-7 rounded-full bg-primary/15 flex items-center justify-center hover:bg-primary/25 transition-colors overflow-hidden"
        title="Account"
      >
        {hasAvatar ? (
          <img src={url} alt="" className="w-full h-full object-cover" onError={() => setHasAvatar(false)} />
        ) : (
          <span className="text-[10px] font-bold text-primary">{initials || "U"}</span>
        )}
      </button>

      {menuOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
          <div className="absolute right-0 top-9 z-50 w-48 bg-card border border-border/60 rounded-lg shadow-lg overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <button
              onClick={() => {
                setMenuOpen(false);
                onOpenSettings();
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs text-foreground hover:bg-muted/60 transition-colors"
            >
              <Settings className="w-3.5 h-3.5 text-muted-foreground" />
              <span className="flex-1 text-left">Profile &amp; settings</span>
            </button>
            <button
              onClick={() => {
                setMenuOpen(false);
                window.open(TUTORIAL_PLAYLIST_URL, "_blank", "noopener");
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs text-foreground hover:bg-muted/60 transition-colors"
            >
              <GraduationCap className="w-3.5 h-3.5 text-muted-foreground" />
              <span className="flex-1 text-left">Tutorial</span>
              <span className="rounded-full bg-primary/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">
                New
              </span>
            </button>
          </div>
        </>
      )}
    </div>
  );
}

interface AppHeaderProps {
  onOpenQueenProfile?: (queenId: string) => void;
}

export default function AppHeader({ onOpenQueenProfile }: AppHeaderProps) {
  const location = useLocation();
  const { colonies, queens, queenProfiles, userProfile, userAvatarVersion, userHasAvatar } = useColony();
  const { actions, leftActions } = useHeaderActions();
  const { currentModel, currentProvider, availableModels, activeSubscription, subscriptions } = useModel();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<"profile" | "byok">("profile");
  const [colonySettingsOpen, setColonySettingsOpen] = useState(false);

  // Derive active model display label
  const activeSubInfo = activeSubscription
    ? subscriptions.find((s) => s.id === activeSubscription)
    : null;
  const modelsProvider = activeSubInfo?.provider || currentProvider;
  const models = availableModels[modelsProvider] || [];
  const currentModelInfo = models.find((m) => m.id === currentModel);
  const modelLabel = currentModelInfo
    ? currentModelInfo.label.split(" - ")[0]
    : currentModel || "No model";

  // Derive page title + icon from current route
  const colonyMatch = location.pathname.match(/^\/colony\/(.+)/);
  const queenMatch = location.pathname.match(/^\/queen\/(.+)/);

  let title = "OpenHive";
  let icon: React.ReactNode = null;
  let queenTitle: string | null = null;
  let queenIdForProfile: string | null = null;
  let activeColony: (typeof colonies)[number] | null = null;

  if (colonyMatch) {
    const colonyId = colonyMatch[1];
    const colony = colonies.find((c) => c.id === colonyId);
    activeColony = colony ?? null;
    title = colony?.name ?? colonyId;
    if (colony?.queenProfileId) {
      const profile = queenProfiles.find((q) => q.id === colony.queenProfileId);
      if (profile) {
        queenTitle = profile.title ?? null;
      }
    }
    icon = <Component className="w-4 h-4 text-primary" />;
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
      <div className="relative z-30 h-12 flex items-center justify-between px-5 border-b border-border/60 bg-card/50 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          {icon ? (
            queenIdForProfile ? (
              <button
                onClick={() => onOpenQueenProfile?.(queenIdForProfile!)}
                className="flex items-center gap-2 rounded-md px-1.5 -mx-1.5 py-0.5 hover:bg-muted/60 transition-colors"
                title={`View ${title}'s profile`}
              >
                {queenHeaderContent}
              </button>
            ) : activeColony ? (
              <button
                onClick={() => setColonySettingsOpen(true)}
                className="flex items-center gap-2 rounded-md px-1.5 -mx-1.5 py-0.5 hover:bg-muted/60 transition-colors"
                title="View colony settings"
              >
                {queenHeaderContent}
              </button>
            ) : (
              <div className="flex items-center gap-2">{queenHeaderContent}</div>
            )
          ) : null}
          {leftActions}
        </div>
        <div className="flex items-center gap-2">
          {actions}
          {actions && <span className="w-px h-5 bg-border/60 mx-0.5" aria-hidden />}
          <UserMenu
            initials={initials}
            avatarVersion={userAvatarVersion}
            userHasAvatar={userHasAvatar}
            onOpenSettings={() => {
              setSettingsSection("profile");
              setSettingsOpen(true);
            }}
          />
        </div>
      </div>

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        initialSection={settingsSection}
      />

      {colonySettingsOpen && activeColony && (
        <ColonySettingsModal
          colony={activeColony}
          onClose={() => setColonySettingsOpen(false)}
        />
      )}
    </>
  );
}
