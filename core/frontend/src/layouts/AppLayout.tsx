import {
  useEffect,
  useState,
  useCallback,
  Suspense,
  type ReactNode,
} from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import Sidebar from "@/components/Sidebar";
import AppHeader from "@/components/AppHeader";
import QueenProfilePanel from "@/components/QueenProfilePanel";
import ColonyPanel from "@/components/ColonyPanel";
import RuntimeLogsDrawer from "@/components/RuntimeLogsDrawer";
import ConnectivityBanner from "@/components/ConnectivityBanner";
import DebugPanel from "@/components/DebugPanel";
import { DebugStateProvider } from "@/components/DebugStateContext";
import { ColonyProvider, useColony } from "@/context/ColonyContext";
import { HeaderActionsProvider } from "@/context/HeaderActionsContext";
import { QueenProfileProvider } from "@/context/QueenProfileContext";
import { SessionUsageProvider } from "@/context/SessionUsageContext";
import {
  QueensAuthorizationPromptProvider,
  useQueensAuthorizationPrompt,
} from "@/context/QueensAuthorizationPromptContext";
import {
  QueenDisconnectPromptProvider,
  useQueenDisconnectPrompt,
} from "@/context/QueenDisconnectPromptContext";
import { useGlobalEvents } from "@/hooks/use-sse";
import NewUserOnboarding from "@/components/NewUserOnboarding";
import {
  VISIBLE_CREDENTIAL_IDS,
  autoEnableProviderAcrossQueens,
  credentialIdToProvider,
} from "@/lib/visible-tools";
import { credentialsApi } from "@/api/credentials";
import {
  ColonyWorkersProvider,
  useColonyWorkers,
} from "@/context/ColonyWorkersContext";
import { TutorialProvider } from "@/components/Tutorial/TutorialOverlay";
import { CreateColonyProvider } from "@/context/CreateColonyContext";

export default function AppLayout() {
  return (
    <ColonyProvider>
      <HeaderActionsProvider>
        <ColonyWorkersProvider>
          <DebugStateProvider>
            <SessionUsageProvider>
              <QueensAuthorizationPromptProvider>
                <QueenDisconnectPromptProvider>
                  <CreateColonyProvider>
                    <AppLayoutInner />
                  </CreateColonyProvider>
                </QueenDisconnectPromptProvider>
              </QueensAuthorizationPromptProvider>
            </SessionUsageProvider>
          </DebugStateProvider>
        </ColonyWorkersProvider>
      </HeaderActionsProvider>
    </ColonyProvider>
  );
}

function AppLayoutInner() {
  const { colonies } = useColony();
  const location = useLocation();
  const { openPrompt } = useQueensAuthorizationPrompt();
  const { openPrompt: openDisconnectPrompt } = useQueenDisconnectPrompt();
  const [openQueenId, setOpenQueenId] = useState<string | null>(null);

  // Whenever any tab/window finishes connecting an OAuth provider, pop
  // the queens-authorization dialog so the user can untick queens that
  // shouldn't receive the new provider's tools. Ticked (default) queens
  // get the tools via the backend's role-default augmentation or via the
  // startup catch-up below. Dedup inside the prompt context handles the
  // in-app Connect flow firing both polling-success AND a paired SSE.
  useGlobalEvents({
    eventTypes: ["credential_provider_connected"],
    onEvent: (event) => {
      const credentialId =
        typeof event.data?.provider === "string"
          ? (event.data.provider as string)
          : typeof event.data?.credential_id === "string"
            ? (event.data.credential_id as string)
            : null;
      if (!credentialId) return;
      const toolProvider = credentialIdToProvider(credentialId);
      if (!toolProvider) return;
      const account =
        typeof event.data === "object" && event.data !== null
          ? (event.data as {
              alias?: string;
              identity?: { email?: string | null } | null;
            })
          : null;
      openPrompt(toolProvider, account);
    },
  });

  // Mirror of the connect listener — when a provider is disconnected
  // (from another tab/window, or Aden's side), pop the disconnect
  // dialog so the user can clean up affected queens' sidecars. The
  // in-app Remove flow opens this dialog directly *before* deleting
  // the credential, and the prompt context's dedup window absorbs the
  // SSE that fires microseconds after the delete completes.
  useGlobalEvents({
    eventTypes: ["credential_provider_disconnected"],
    onEvent: (event) => {
      const credentialId =
        typeof event.data?.provider === "string"
          ? (event.data.provider as string)
          : typeof event.data?.credential_id === "string"
            ? (event.data.credential_id as string)
            : null;
      if (!credentialId) return;
      const toolProvider = credentialIdToProvider(credentialId);
      if (!toolProvider) return;
      const account =
        typeof event.data === "object" && event.data !== null
          ? (event.data as {
              alias?: string;
              identity?: { email?: string | null } | null;
            })
          : null;
      openDisconnectPrompt(toolProvider, account);
    },
  });

  // Startup catch-up: app may have been closed when a SSE connect event
  // fired, or queens may have been created with explicit allowlists
  // before this auto-enable code shipped. Walk currently-authorised
  // providers once on mount so existing queens pick up tools they're
  // missing. Idempotent — autoEnableProviderAcrossQueens skips queens
  // where the tools are already enabled or the queen is on allow-all.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const { specs } = await credentialsApi.listSpecs();
        if (cancelled) return;
        const connectedProviders = specs
          .filter(
            (s) => s.available && VISIBLE_CREDENTIAL_IDS.has(s.credential_id),
          )
          .map((s) => credentialIdToProvider(s.credential_id))
          .filter((p): p is string => p !== null);
        for (const provider of connectedProviders) {
          if (cancelled) return;
          await autoEnableProviderAcrossQueens(provider);
        }
      } catch (err) {
        console.warn("[startup auto-enable] failed:", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Queen profile closes on route change (it's a per-queen view).
  useEffect(() => {
    setOpenQueenId(null);
  }, [location.pathname]);

  const handleOpenQueenProfile = useCallback(
    (queenId: string) =>
      setOpenQueenId((prev) => (prev === queenId ? null : queenId)),
    [],
  );

  return (
    <QueenProfileProvider onOpen={handleOpenQueenProfile}>
      <TutorialProvider>
        {/* Single first-run orchestrator: seeds the demo colony + auto-plays
            the tour. Inside TutorialProvider so it can drive the tour. */}
        <NewUserOnboarding />
        <LayoutShell
          openQueenId={openQueenId}
          onCloseQueenProfile={() => setOpenQueenId(null)}
          onOpenQueenProfile={handleOpenQueenProfile}
          colonies={colonies}
        />
      </TutorialProvider>
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
  const { sessionId, colonyName, dismissed } = useColonyWorkers();
  // Workers panel is colony-only — queen-DM publishes a sessionId for
  // its own Action Plan drawer, but the workers panel must stay hidden
  // there (no workers exist).
  const showWorkersPanel = Boolean(sessionId && colonyName && !dismissed);

  const [showDebug, setShowDebug] = useState(false);

  // Ctrl+Shift+D toggles the real-time debug overlay
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === "D") {
        e.preventDefault();
        setShowDebug((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      <ConnectivityBanner />
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <AppHeader onOpenQueenProfile={onOpenQueenProfile} />
        {/* data-tour anchor: the onboarding tour measures this content region
            to render its scripted colony demo edge-to-edge, keeping the real
            sidebar + header visible around it. */}
        <div className="flex-1 min-h-0 flex" data-tour="tour-colony-canvas">
          <main className="flex-1 min-w-0 flex flex-col">
            {/* Routes are code-split (see App.tsx) — each page is its own
                lazy chunk. The fallback only covers the content area so
                the sidebar/header stay put while a page chunk loads. */}
            <Suspense
              fallback={
                <div className="flex-1 flex items-center justify-center">
                  <Loader2 className="w-5 h-5 animate-spin text-muted-foreground/60" />
                </div>
              }
            >
              <Outlet />
            </Suspense>
          </main>
          {openQueenId && (
            <QueenProfilePanel
              queenId={openQueenId}
              colonies={colonies.filter(
                (c) => c.queenProfileId === openQueenId,
              )}
              onClose={onCloseQueenProfile}
            />
          )}
          {showWorkersPanel && sessionId && (
            <ColonyPanel
              sessionId={sessionId}
              colonyName={colonyName}
            />
          )}
        </div>
      </div>
      <RuntimeLogsDrawer />
      {showDebug && <DebugPanel />}
    </div>
  );
}

// Re-exported so tsc sees React used (removes import-only warning when
// the file compiles down to JSX-less output).
export type { ReactNode };
