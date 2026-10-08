import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useLocation, useMatch, useNavigate } from "react-router-dom";

declare const __APP_VERSION__: string;
import {
  ChevronLeft,
  ChevronRight,
  MessageSquarePlus,
  Network,
  KeyRound,
  Send,
  ChevronDown,
  Plus,
  X,
  Crown,
  Loader2,
  Settings,
  Library,
  Brain,
  Download,
  Contact,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import HiveLogo from "./HiveLogo";
import { apiUrl } from "@/api/client";
import SidebarColonyItem from "./SidebarColonyItem";
import SidebarQueenItem from "./SidebarQueenItem";
import QueenPortraitGlyph from "./QueenPortraitGlyph";
import { useColony } from "@/context/ColonyContext";
import { useMe, isQueenDecommissioned } from "@/lib/me";
import { useCreateColony } from "@/context/CreateColonyContext";
import { sessionsApi } from "@/api/sessions";
import { slugToColonyId, orderQueens } from "@/lib/colony-registry";
import type { QueenProfileSummary } from "@/types/colony";
import { useLiveSessions } from "@/hooks/use-live-sessions";
import { useLatestVersion } from "@/hooks/use-latest-version";
import type { Colony } from "@/types/colony";
import { deriveColonyStatus, describeColonyStatus, STATUS_DOT_CLASS } from "@/lib/colony-status";
import { useTutorial } from "./Tutorial/TutorialOverlay";
import { DEMO_COLONY_TITLE } from "./Tutorial/demoColony";

function CollapsedColonyAvatar({
  colony,
  liveness,
}: {
  colony: Colony;
  liveness?: ReturnType<typeof useLiveSessions>["byColony"] extends Map<string, infer T> ? T : never;
}) {
  const s = deriveColonyStatus(colony.sessionId !== null, liveness);
  let title = colony.name;
  if (s !== "idle") title = `${colony.name} · ${describeColonyStatus(s, liveness)}`;

  return (
    <NavLink
      to={`/colony/${colony.id}`}
      title={title}
      className={({ isActive: isRouteActive }) =>
        `relative w-7 h-7 rounded-lg flex-shrink-0 flex items-center justify-center transition-colors ${
          isRouteActive
            ? "bg-primary/20 text-primary"
            : "bg-muted/40 text-foreground/50 hover:bg-muted/70 hover:text-foreground"
        }`
      }
    >
      <Network className="w-3.5 h-3.5" />
      {s !== "idle" && (
        <span className={`absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full ring-2 ring-sidebar-bg ${STATUS_DOT_CLASS[s]}`} />
      )}
    </NavLink>
  );
}

function CollapsedQueenAvatar({
  queen,
  isActive,
  liveness,
}: {
  queen: QueenProfileSummary;
  isActive: boolean;
  liveness?: ReturnType<typeof useLiveSessions>["byQueen"] extends Map<string, infer T> ? T : never;
}) {
  const { queenAvatarVersion, queenHasAvatar } = useColony();
  const version = queenAvatarVersion(queen.id);
  const [hasAvatar, setHasAvatar] = useState(() => queenHasAvatar(queen.id));
  const url = apiUrl(`/queen/${queen.id}/avatar?v=${version}`);
  useEffect(() => setHasAvatar(queenHasAvatar(queen.id)), [version, queen.id, queenHasAvatar]);

  let dotColor: string | null = null;
  let dotPulse = false;
  let title = `${queen.name} — ${queen.title}`;
  if (liveness?.interrupted) {
    // Not moving and not a deliberate end-of-turn — amber, steady.
    dotColor = "bg-amber-500";
    title = liveness.interrupt_cause
      ? `${queen.name} — interrupted (${liveness.interrupt_cause})`
      : `${queen.name} — interrupted`;
  } else if (liveness?.is_executing) {
    dotColor = "bg-emerald-500";
    dotPulse = true;
    title = liveness.current_tool_name
      ? `${queen.name} — running ${liveness.current_tool_name}`
      : `${queen.name} — working`;
  } else if (isActive) {
    dotColor = "bg-emerald-500";
  }

  return (
    <NavLink
      to={`/queen/${queen.id}`}
      title={title}
      className={({ isActive: isRouteActive }) =>
        `relative w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center ring-2 transition-colors ${
          isRouteActive
            ? "ring-primary"
            : "ring-transparent hover:ring-primary/40"
        }`
      }
    >
      <span className="w-full h-full rounded-full overflow-hidden flex items-center justify-center">
        {hasAvatar ? (
          <img src={url} alt={queen.name} className="w-full h-full object-cover" onError={() => setHasAvatar(false)} />
        ) : queen.portrait ? (
          <QueenPortraitGlyph p={queen.portrait} className="w-full h-full" />
        ) : (
          <span className="w-full h-full bg-primary/15 flex items-center justify-center text-[10px] font-bold text-primary">
            {queen.name.charAt(0)}
          </span>
        )}
      </span>
      {dotColor && (
        <span className="absolute -bottom-0.5 -right-0.5 flex h-2 w-2">
          {dotPulse && (
            <span
              className={`absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping ${dotColor}`}
            />
          )}
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ring-2 ring-sidebar-bg ${dotColor}`}
          />
        </span>
      )}
    </NavLink>
  );
}

export default function Sidebar() {
  const navigate = useNavigate();
  const { colonies, queens, queenProfiles, sidebarCollapsed, setSidebarCollapsed, refresh } = useColony();
  const { me } = useMe();
  // Decommissioned queens vanish from the sidebar entirely; users
  // re-hire them from the org chart, not from here.
  const visibleQueenProfiles = useMemo(
    () => queenProfiles.filter((q) => !isQueenDecommissioned(me, q.id)),
    [queenProfiles, me],
  );
  // Canonical order: the queens the user configured during onboarding first
  // (in their configured order), then any other active queens by the default
  // GTM order. Stable — recency does NOT reorder the list (see orderQueens).
  const sortedQueenProfiles = useMemo(
    () =>
      orderQueens(
        visibleQueenProfiles,
        Object.keys(me?.preferences?.queens ?? {}),
      ),
    [visibleQueenProfiles, me?.preferences?.queens],
  );
  const activeQueenIds = new Set(
    queens.filter((q) => q.status === "online").map((q) => q.id),
  );
  // Live multi-queen feed → drives status dots and the away-queen
  // attention badge. One IPC subscription, fanned out via this hook.
  const { byQueen: liveByQueen, byColony: liveByColony } = useLiveSessions();
  // Fire OS notifications when an away queen starts waiting on input.
  // No-op when the focused queen is the one waiting (they'll see the
  // modal directly).
  // Non-null only when a newer desktop build is published.
  const update = useLatestVersion();
  const [coloniesExpanded, setColoniesExpanded] = useState(true);
  const [queensExpanded, setQueensExpanded] = useState(true);
  const [libraryExpanded, setLibraryExpanded] = useState(false);

  // Keep the Configuration dropdown collapsed while the tour runs so the
  // sidebar stays deterministic. We key off the route too so the state
  // re-asserts after any sidebar interaction that toggled it mid-tour.
  // Only managed while the tour is active — otherwise the user controls it.
  const tutorial = useTutorial();
  const sidebarLocation = useLocation();
  const tourStepId = tutorial.active
    ? (tutorial.steps[tutorial.index]?.id ?? null)
    : null;
  useEffect(() => {
    if (!tutorial.active) return;
    setLibraryExpanded(false);
  }, [tutorial.active, tourStepId, sidebarLocation.pathname]);

  // The colony demo steps render a scripted colony in the content pane. Mirror
  // that in the sidebar: force the Colonies section open and show the scripted
  // colony as the selected row (real colonies are hidden for these steps so the
  // tutorial stays deterministic — see the render below).
  const showDemoColonyInSidebar =
    tourStepId === "colony-chat" || tourStepId === "colony-data";
  useEffect(() => {
    if (!tutorial.active || !showDemoColonyInSidebar) return;
    setColoniesExpanded(true);
  }, [tutorial.active, showDemoColonyInSidebar, sidebarLocation.pathname]);

  // Colony creation
  const [createColonyOpen, setCreateColonyOpen] = useState(false);
  const [newColonyQueen, setNewColonyQueen] = useState("");
  const [newColonyName, setNewColonyName] = useState("");
  const [newColonyGoal, setNewColonyGoal] = useState("");
  const [creatingColony, setCreatingColony] = useState(false);

  // Cross-page hook: other pages (e.g. the prompt library "Deploy"
  // button) push a {name, goal} request through CreateColonyContext.
  // When one arrives, open the modal and seed the form, then clear the
  // request so the prefill only applies once.
  const { pendingRequest, clearRequest } = useCreateColony();
  useEffect(() => {
    if (!pendingRequest) return;
    const slugged = (pendingRequest.name ?? "").toLowerCase().replace(/[^a-z0-9_]+/g, "_");
    setNewColonyName(slugged);
    setNewColonyGoal(pendingRequest.goal ?? "");
    // Pre-select the queen the prompt maps to, but only if the user actually
    // has that queen active — otherwise leave it unselected so the form still
    // makes them pick a valid one.
    const wantedQueen = pendingRequest.queenId;
    const queenIsAvailable = !!wantedQueen && visibleQueenProfiles.some((q) => q.id === wantedQueen);
    setNewColonyQueen(queenIsAvailable ? wantedQueen! : "");
    setCreateColonyOpen(true);
    clearRequest();
  }, [pendingRequest, clearRequest, visibleQueenProfiles]);

  const handleCreateColony = async () => {
    const cname = newColonyName.trim();
    if (!cname || !newColonyQueen || creatingColony) return;
    setCreatingColony(true);
    const goal = newColonyGoal.trim();
    try {
      const created = await sessionsApi.create({
        colonyId: cname,
        colonyGoal: goal || undefined,
        queenName: newColonyQueen,
        initialPhase: "colony",
      });
      setCreateColonyOpen(false);
      setNewColonyQueen("");
      setNewColonyName("");
      setNewColonyGoal("");
      refresh();
      const actualColonyId = created.colony_id ?? cname;
      navigate(`/colony/${slugToColonyId(actualColonyId)}`, {
        state: goal ? { initialGoal: goal } : undefined,
      });
    } catch (err) {
      console.error("Failed to create colony:", err);
    } finally {
      setCreatingColony(false);
    }
  };

  // ── Resizable width ──────────────────────────────────────────────────
  const MIN_WIDTH = 180;
  const MAX_WIDTH = 400;
  const [width, setWidth] = useState(240);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    startX.current = e.clientX;
    startWidth.current = width;

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const delta = ev.clientX - startX.current;
      setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth.current + delta)));
    };
    const onUp = () => {
      dragging.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [width]);

  if (sidebarCollapsed) {
    return (
      <aside className="w-[52px] flex-shrink-0 flex flex-col bg-sidebar-bg border-r border-sidebar-border h-full">
        {/* Header — logo + expand toggle on the border line */}
        <div className="relative h-12 flex items-center px-3 border-b border-border/60">
          <button
            onClick={() => navigate("/")}
            title={`OpenHive v${__APP_VERSION__}`}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-sidebar-item-hover transition-colors"
          >
            <HiveLogo size={21} className="text-primary" />
          </button>
          <button
            onClick={() => setSidebarCollapsed(false)}
            title="Expand sidebar"
            className="absolute -right-2.5 top-1/2 -translate-y-1/2 z-40 w-5 h-5 rounded-full bg-background border border-border shadow-sm flex items-center justify-center text-sidebar-muted hover:text-foreground hover:bg-sidebar-item-hover transition-colors"
          >
            <ChevronRight className="w-3 h-3" />
          </button>
        </div>

        {/* Nav icons */}
        <div className="flex flex-col items-center py-3 gap-1 border-b border-border/60">
          <button onClick={() => navigate("/")} title="New Chat"
            className="w-8 h-8 rounded-md flex items-center justify-center text-foreground/60 hover:text-foreground hover:bg-sidebar-item-hover transition-colors">
            <MessageSquarePlus className="w-4 h-4" />
          </button>
          <button onClick={() => navigate("/org-chart")} title="Org Chart"
            className="w-8 h-8 rounded-md flex items-center justify-center text-foreground/60 hover:text-foreground hover:bg-sidebar-item-hover transition-colors">
            <Network className="w-4 h-4" />
          </button>
          <button onClick={() => setLibraryExpanded((v) => !v)} title="Configuration"
            className="w-8 h-8 rounded-md flex items-center justify-center text-foreground/60 hover:text-foreground hover:bg-sidebar-item-hover transition-colors">
            <Settings className="w-4 h-4" />
          </button>
          {libraryExpanded && (
            <>
              <button onClick={() => navigate("/credentials")} title="Credentials"
                className="w-6 h-6 rounded-md flex items-center justify-center text-foreground/50 hover:text-foreground hover:bg-sidebar-item-hover transition-colors">
                <KeyRound className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => navigate("/skills-library")} title="Skills"
                className="w-6 h-6 rounded-md flex items-center justify-center text-foreground/50 hover:text-foreground hover:bg-sidebar-item-hover transition-colors">
                <Library className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => navigate("/memory-library")} title="Memory"
                className="w-6 h-6 rounded-md flex items-center justify-center text-foreground/50 hover:text-foreground hover:bg-sidebar-item-hover transition-colors">
                <Brain className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>

        {/* Colonies + Queen avatars */}
        <div className="flex-1 overflow-y-auto flex flex-col items-center py-3 gap-1.5">
          {colonies.length > 0 && (
            <>
              {colonies.map((colony) => (
                <CollapsedColonyAvatar
                  key={colony.id}
                  colony={colony}
                  liveness={liveByColony.get(colony.id)}
                />
              ))}
              <div className="w-5 border-t border-border/40 my-1" />
            </>
          )}
          {visibleQueenProfiles.map((queen) => (
            <CollapsedQueenAvatar key={queen.id} queen={queen} isActive={activeQueenIds.has(queen.id)} liveness={liveByQueen.get(queen.id)} />
          ))}
        </div>

      </aside>
    );
  }

  return (
    <>
    <aside
      className="flex-shrink-0 flex flex-col bg-sidebar-bg border-r border-sidebar-border h-full relative"
      style={{ width }}
    >
      {/* Drag handle on right edge */}
      <div
        onMouseDown={onDragStart}
        className="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
      />
      {/* Header */}
      <div className="h-12 flex items-center justify-between px-4 border-b border-border/60">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
        >
          <div className="w-7 h-7 rounded-lg flex items-center justify-center">
            <HiveLogo size={19} className="text-primary" />
          </div>
          <div className="flex items-baseline gap-0.5 -ml-[10px]">
            <span className="text-[13px] font-semibold tracking-[-0.02em] text-foreground">Open</span>
            <span className="text-[13px] font-semibold tracking-[-0.02em] text-primary">Hive</span>
          </div>
        </button>
        <button
          onClick={() => setSidebarCollapsed(true)}
          className="p-1 rounded-md text-sidebar-muted hover:text-foreground hover:bg-sidebar-item-hover transition-colors"
          title="Collapse sidebar"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
      </div>

      {/* Nav links */}
      <div className="px-2 py-3 flex flex-col gap-px border-b border-border/60">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2 px-3 py-[5px] rounded-md text-[12.5px] text-foreground/65 hover:bg-sidebar-item-hover hover:text-foreground transition-all duration-150"
        >
          <MessageSquarePlus className="w-[15px] h-[15px] opacity-70" />
          <span>New Chat</span>
        </button>
        <button
          onClick={() => navigate("/org-chart")}
          className="flex items-center gap-2 px-3 py-[5px] rounded-md text-[12.5px] text-foreground/65 hover:bg-sidebar-item-hover hover:text-foreground transition-all duration-150"
        >
          <Network className="w-[15px] h-[15px] opacity-70" />
          <span>Org Chart</span>
        </button>
        <button
          onClick={() => setLibraryExpanded((v) => !v)}
          className="flex items-center gap-2 px-3 py-[5px] rounded-md text-[12.5px] text-foreground/65 hover:bg-sidebar-item-hover hover:text-foreground transition-all duration-150"
        >
          <Settings className="w-[15px] h-[15px] opacity-70" />
          <span className="flex-1 text-left">Configuration</span>
          <ChevronDown
            className={`w-3 h-3 opacity-50 transition-transform duration-200 ${
              libraryExpanded ? "" : "-rotate-90"
            }`}
          />
        </button>
        {libraryExpanded && (
          <div className="ml-[22px] pl-2.5 border-l border-border/40 flex flex-col gap-px mt-px mb-0.5">
            <button
              onClick={() => navigate("/credentials")}
              className="flex items-center gap-2 px-2.5 py-[4px] rounded-md text-[12px] text-foreground/55 hover:bg-sidebar-item-hover hover:text-foreground transition-all duration-150"
            >
              <KeyRound className="w-3.5 h-3.5 opacity-60" />
              <span>Credentials</span>
            </button>
            <button
              onClick={() => navigate("/skills-library")}
              className="flex items-center gap-2 px-2.5 py-[4px] rounded-md text-[12px] text-foreground/55 hover:bg-sidebar-item-hover hover:text-foreground transition-all duration-150"
            >
              <Library className="w-3.5 h-3.5 opacity-60" />
              <span>Skills</span>
            </button>
            <button
              onClick={() => navigate("/memory-library")}
              className="flex items-center gap-2 px-2.5 py-[4px] rounded-md text-[12px] text-foreground/55 hover:bg-sidebar-item-hover hover:text-foreground transition-all duration-150"
            >
              <Brain className="w-3.5 h-3.5 opacity-60" />
              <span>Memory</span>
            </button>
          </div>
        )}
      </div>

      {/* COLONIES section */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="py-2">
          <div className="flex items-center px-4 py-1.5">
            <button
              onClick={() => setColoniesExpanded((v) => !v)}
              className="flex items-center gap-1.5 flex-1 text-[10.5px] font-semibold text-sidebar-section-text uppercase tracking-wider hover:text-foreground transition-colors"
            >
              <ChevronDown
                className={`w-3 h-3 transition-transform ${coloniesExpanded ? "" : "-rotate-90"}`}
              />
              <span>Colonies</span>
              {colonies.length > 0 && (
                <span className="text-[10px] bg-sidebar-item-hover rounded-full px-1.5 py-0.5 font-medium">
                  {colonies.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setCreateColonyOpen(true)}
              className="p-0.5 rounded text-sidebar-section-text hover:text-foreground hover:bg-sidebar-item-hover transition-colors"
              title="Create colony"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
          {coloniesExpanded && (
            <div className="flex flex-col gap-0.5 mt-0.5">
              {showDemoColonyInSidebar ? (
                // Scripted colony row for the tutorial demo steps — rendered as
                // if selected, matching the mock filling the content pane. Not a
                // NavLink: it's a static, non-navigating stand-in.
                <div className="group relative flex items-center mx-2">
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-md text-[12.5px] flex-1 min-w-0 bg-sidebar-active-bg text-foreground font-medium">
                    <span className="flex-shrink-0 w-2 h-2 rounded-full bg-status-online" />
                    <span className="truncate flex-1">{DEMO_COLONY_TITLE}</span>
                  </div>
                </div>
              ) : (
                <>
                  {colonies.map((colony) => (
                    <SidebarColonyItem
                      key={colony.id}
                      colony={colony}
                      liveness={liveByColony.get(colony.id)}
                    />
                  ))}
                  {colonies.length === 0 && (
                    <p className="px-5 py-2 text-xs text-sidebar-muted">
                      No colonies yet
                    </p>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* QUEEN BEES section */}
        <div className="py-2">
          <button
            onClick={() => setQueensExpanded((v) => !v)}
            className="flex items-center gap-1.5 px-4 py-1.5 w-full text-[10.5px] font-semibold text-sidebar-section-text uppercase tracking-wider hover:text-foreground transition-colors"
          >
            <ChevronDown
              className={`w-3 h-3 transition-transform ${queensExpanded ? "" : "-rotate-90"}`}
            />
            <span>Queen Bees</span>
          </button>
          {queensExpanded && (
            <div className="flex flex-col gap-0.5 mt-0.5">
              {sortedQueenProfiles.map((queen) => (
                <SidebarQueenItem
                  key={queen.id}
                  queen={queen}
                  isActive={activeQueenIds.has(queen.id)}
                  liveness={liveByQueen.get(queen.id)}
                />
              ))}
              {sortedQueenProfiles.length === 0 && (
                <p className="px-5 py-2 text-xs text-sidebar-muted">
                  Loading queens...
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="px-4 py-2 border-t border-border/60 text-[10.5px] font-mono tracking-tight">
        {update ? (
          <button
            type="button"
            onClick={() => window.open(update.downloadUrl, "_blank", "noopener")}
            title={`Update available — download OpenHive v${update.latest}`}
            className="flex items-center gap-1 text-primary hover:underline"
          >
            <Download className="w-3 h-3 shrink-0" />
            <span>v{update.latest.split("-")[0]} is now available</span>
          </button>
        ) : (
          <span className="text-sidebar-muted/70">v{__APP_VERSION__}</span>
        )}
      </div>
    </aside>

    {/* Create Colony modal */}
    {createColonyOpen && (
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="absolute inset-0 bg-black/40" onClick={() => !creatingColony && setCreateColonyOpen(false)} />
        <div className="relative bg-card border border-border/60 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground">Create Colony</h2>
            <button onClick={() => setCreateColonyOpen(false)} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="space-y-3">
            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">Queen Bee <span className="text-primary">*</span></label>
              <div className="grid grid-cols-2 gap-1.5 max-h-[156px] overflow-y-auto pr-1">
                {orderQueens(visibleQueenProfiles, Object.keys(me?.preferences?.queens ?? {})).map((q) => (
                  <button key={q.id} onClick={() => setNewColonyQueen(q.id)}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                      newColonyQueen === q.id
                        ? "border-primary/40 bg-primary/[0.06] text-primary"
                        : "border-border/50 text-foreground hover:border-primary/30"
                    }`}>
                    <Crown className="w-3 h-3 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="font-medium truncate">{q.name}</p>
                      <p className="text-[10px] text-muted-foreground truncate">{q.title}</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">Colony Name <span className="text-primary">*</span></label>
              <input type="text" value={newColonyName}
                onChange={(e) => setNewColonyName(e.target.value.toLowerCase().replace(/[^a-z0-9_]+/g, "_"))}
                placeholder="e.g. research team" autoFocus
                className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">Goal <span className="text-muted-foreground/40">(optional)</span></label>
              <textarea value={newColonyGoal} onChange={(e) => setNewColonyGoal(e.target.value)}
                placeholder="Describe what this colony should work on" rows={3}
                className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary resize-none" />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => { setCreateColonyOpen(false); setNewColonyQueen(""); setNewColonyName(""); setNewColonyGoal(""); }}
              disabled={creatingColony}
              className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50">
              Cancel
            </button>
            <button onClick={handleCreateColony} disabled={creatingColony || !newColonyName.trim() || !newColonyQueen}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
              {creatingColony ? <><Loader2 className="w-3 h-3 animate-spin" /> Creating...</> : "Create"}
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}
