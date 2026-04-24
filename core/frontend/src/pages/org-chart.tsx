import { useState, useCallback, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  User, Component, X, Calendar, Target, Activity, ArrowRight, Clock,
  Rocket, Globe, Mail, Search, Shield, TrendingUp, Briefcase, Code,
  Database, FileText, MessageSquare, Zap, BarChart3, Users, Bot,
  type LucideIcon,
} from "lucide-react";
import { useColony } from "@/context/ColonyContext";
import { agentsApi } from "@/api/agents";
import type { QueenProfileSummary, Colony } from "@/types/colony";
import QueenProfilePanel from "@/components/QueenProfilePanel";
import { sortQueenProfiles } from "@/lib/colony-registry";

const COLONY_ICONS: Record<string, LucideIcon> = {
  component: Component, rocket: Rocket, globe: Globe, mail: Mail,
  search: Search, shield: Shield, trending: TrendingUp, briefcase: Briefcase,
  code: Code, database: Database, file: FileText, message: MessageSquare,
  zap: Zap, chart: BarChart3, users: Users, bot: Bot,
};
const COLONY_ICON_KEYS = Object.keys(COLONY_ICONS);

/* ── User avatar (CEO card) ──────────────────────────────────────────── */

function UserAvatar({ initials, avatarVersion }: { initials: string; avatarVersion: number }) {
  const [hasAvatar, setHasAvatar] = useState(true);
  const url = `/api/config/profile/avatar?v=${avatarVersion}`;
  useEffect(() => setHasAvatar(true), [avatarVersion]);
  return (
    <div className="w-12 h-12 rounded-full bg-primary/15 mx-auto mb-3 flex items-center justify-center overflow-hidden">
      {hasAvatar ? (
        <img src={url} alt="" className="w-full h-full object-cover" onError={() => setHasAvatar(false)} />
      ) : initials ? (
        <span className="text-sm font-bold text-primary">{initials}</span>
      ) : (
        <User className="w-5 h-5 text-primary" />
      )}
    </div>
  );
}

/* ── Colony tag ──────────────────────────────────────────────────────── */

function ColonyTag({ colony, onSelect }: { colony: Colony; onSelect: () => void }) {
  const Icon = (colony.icon && COLONY_ICONS[colony.icon]) || Component;
  return (
    <button
      onClick={onSelect}
      className="flex items-center gap-1.5 rounded-lg border border-border/50 bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground hover:border-primary/30 hover:text-foreground transition-colors w-full text-left"
    >
      <Icon className="w-3 h-3 flex-shrink-0 text-primary/60" />
      <span className="truncate">{colony.name}</span>
    </button>
  );
}

/* ── Colony detail drawer ────────────────────────────────────────────── */

function ColonyDetailPanel({ colony, queenName, onClose, onIconChange }: {
  colony: Colony; queenName: string; onClose: () => void;
  onIconChange: (colonyId: string, icon: string) => void;
}) {
  const navigate = useNavigate();
  const [iconPickerOpen, setIconPickerOpen] = useState(false);

  const formatDate = (iso: string | null) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
        + " at " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    } catch { return "—"; }
  };

  const formatRelative = (iso: string | null) => {
    if (!iso) return null;
    try {
      const diff = Date.now() - new Date(iso).getTime();
      const mins = Math.floor(diff / 60000);
      if (mins < 1) return "just now";
      if (mins < 60) return `${mins}m ago`;
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return `${hrs}h ago`;
      const days = Math.floor(hrs / 24);
      return `${days}d ago`;
    } catch { return null; }
  };

  const currentIconKey = colony.icon || "component";
  const CurrentIcon = COLONY_ICONS[currentIconKey] || Component;

  const handlePickIcon = async (key: string) => {
    setIconPickerOpen(false);
    onIconChange(colony.id, key);
    await agentsApi.updateMetadata(colony.agentPath, { icon: key }).catch(() => {});
  };

  return (
    <aside className="w-[320px] min-w-[320px] max-w-[320px] flex-shrink-0 border-l border-border/60 bg-card overflow-y-auto overflow-x-hidden overscroll-contain">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/60">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Component className="w-4 h-4 text-primary" />
          Colony Details
        </div>
        <button onClick={onClose} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="px-5 py-6">
        {/* Icon + Name */}
        <div className="mb-6 text-center">
          <div className="relative inline-block">
            <button
              onClick={() => setIconPickerOpen(!iconPickerOpen)}
              className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center mx-auto mb-3 hover:bg-primary/20 transition-colors"
              title="Change icon"
            >
              <CurrentIcon className="w-6 h-6 text-primary" />
            </button>
            {iconPickerOpen && (
              <div className="absolute top-14 left-1/2 -translate-x-1/2 bg-card border border-border/60 rounded-lg shadow-xl z-20 p-2 w-[200px]">
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-1">Choose icon</p>
                <div className="grid grid-cols-4 gap-1">
                  {COLONY_ICON_KEYS.map((key) => {
                    const Icon = COLONY_ICONS[key];
                    return (
                      <button key={key} onClick={() => handlePickIcon(key)}
                        className={`w-10 h-10 rounded-lg flex items-center justify-center ${key === currentIconKey ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"}`}>
                        <Icon className="w-4.5 h-4.5" />
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
          <h3 className="text-base font-semibold text-foreground">{colony.name}</h3>
          {queenName && <p className="text-xs text-muted-foreground mt-0.5">Managed by {queenName}</p>}
        </div>

        {/* Go to colony */}
        <button
          onClick={() => navigate(`/colony/${colony.id}`)}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary text-primary-foreground py-2.5 text-sm font-medium hover:bg-primary/90 mb-6"
        >
          Open Colony
          <ArrowRight className="w-4 h-4" />
        </button>

        {/* Metadata */}
        <div className="space-y-4">
          <div>
            <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Start Date</h4>
            <div className="flex items-center gap-2 text-sm text-foreground">
              <Calendar className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
              {formatDate(colony.createdAt)}
            </div>
          </div>

          <div>
            <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Project Goal</h4>
            <div className="flex items-start gap-2 text-sm text-foreground/80 min-w-0">
              <Target className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0 mt-0.5" />
              <p className="leading-relaxed break-words min-w-0">{colony.task || colony.description || "No goal specified"}</p>
            </div>
          </div>

          <div>
            <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Current Status</h4>
            <div className="flex items-center gap-2 text-sm">
              <Activity className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
              <span className={`inline-flex items-center gap-1.5 ${colony.status === "running" ? "text-emerald-500" : "text-muted-foreground"}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${colony.status === "running" ? "bg-emerald-500" : "bg-muted-foreground/40"}`} />
                {colony.status === "running" ? "Running" : "Idle"}
              </span>
            </div>
          </div>

          {colony.lastActive && (
            <div>
              <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Last Active</h4>
              <div className="flex items-center gap-2 text-sm text-foreground">
                <Clock className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                {formatRelative(colony.lastActive) || formatDate(colony.lastActive)}
              </div>
            </div>
          )}

          <div>
            <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Stats</h4>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg bg-muted/30 px-3 py-2 text-center">
                <p className="text-lg font-semibold text-foreground">{colony.sessionCount}</p>
                <p className="text-[10px] text-muted-foreground">Sessions</p>
              </div>
              <div className="rounded-lg bg-muted/30 px-3 py-2 text-center">
                <p className="text-lg font-semibold text-foreground">{colony.runCount}</p>
                <p className="text-[10px] text-muted-foreground">Runs</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

/* ── Queen avatar ────────────────────────────────────────────────────── */

function QueenAvatar({ queenId, name, size = "w-11 h-11" }: { queenId: string; name: string; size?: string }) {
  const [hasAvatar, setHasAvatar] = useState(true);
  const url = `/api/queen/${queenId}/avatar`;
  return (
    <div className={`${size} rounded-full bg-primary/15 flex items-center justify-center overflow-hidden`}>
      {hasAvatar ? (
        <img src={url} alt={name} className="w-full h-full object-cover" onError={() => setHasAvatar(false)} />
      ) : (
        <span className="text-sm font-bold text-primary">{name.charAt(0)}</span>
      )}
    </div>
  );
}

/* ── Queen card in the org grid ───────────────────────────────────────── */

function QueenCard({
  queen,
  colonies,
  selected,
  onSelect,
  onSelectColony,
}: {
  queen: QueenProfileSummary;
  colonies: Colony[];
  selected: boolean;
  onSelect: () => void;
  onSelectColony: (colony: Colony) => void;
}) {
  return (
    <div className="flex flex-col items-center w-[140px] flex-shrink-0">
      {/* Vertical stub from horizontal bar */}
      <div className="w-px h-6 bg-border" />

      {/* Queen card — fixed height so all cards align */}
      <button
        onClick={onSelect}
        className={`group flex flex-col items-center justify-center rounded-xl border bg-card p-4 w-full h-[130px] transition-all duration-200 text-center ${
          selected
            ? "border-primary/40 bg-primary/[0.04] ring-1 ring-primary/20"
            : "border-border/60 hover:border-primary/30 hover:bg-primary/[0.03]"
        }`}
      >
        <div className="mb-2.5">
          <QueenAvatar queenId={queen.id} name={queen.name} />
        </div>
        <span className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors line-clamp-1">
          {queen.name}
        </span>
        <span className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
          {queen.title}
        </span>
      </button>

      {/* Colony connections */}
      {colonies.length > 0 && (
        <>
          <div className="w-px h-4 bg-border" />
          <div className="flex flex-col gap-1.5 w-full">
            {colonies.map((colony) => (
              <ColonyTag key={colony.id} colony={colony} onSelect={() => onSelectColony(colony)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Main org chart page ──────────────────────────────────────────────── */

// Fixed left-to-right order for queen cards
export default function OrgChart() {
  const { queenProfiles: unsortedQueenProfiles, colonies, userProfile, userAvatarVersion } = useColony();
  const queenProfiles = sortQueenProfiles(unsortedQueenProfiles);
  const [selectedQueenId, setSelectedQueenId] = useState<string | null>(null);
  const [selectedColony, setSelectedColony] = useState<Colony | null>(null);

  // Pan & zoom state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const MIN_ZOOM = 0.3;
  const MAX_ZOOM = 2;

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.93 : 1.07;
    setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z * delta)));
  }, []);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      setDragging(true);
      dragStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
    },
    [pan],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!dragging) return;
      setPan({
        x: dragStart.current.panX + (e.clientX - dragStart.current.x),
        y: dragStart.current.panY + (e.clientY - dragStart.current.y),
      });
    },
    [dragging],
  );

  const handleMouseUp = useCallback(() => setDragging(false), []);

  // Group colonies by their queen profile ID
  const coloniesByQueen = new Map<string, Colony[]>();
  for (const colony of colonies) {
    if (colony.queenProfileId) {
      const list = coloniesByQueen.get(colony.queenProfileId) ?? [];
      list.push(colony);
      coloniesByQueen.set(colony.queenProfileId, list);
    }
  }

  const initials = userProfile.displayName
    .trim()
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  const handleSelectColony = (colony: Colony) => {
    setSelectedQueenId(null);
    setSelectedColony(selectedColony?.id === colony.id ? null : colony);
  };

  const handleSelectQueen = (queenId: string) => {
    setSelectedColony(null);
    setSelectedQueenId(selectedQueenId === queenId ? null : queenId);
  };

  // Resolve queen name for colony panel
  const colonyQueenName = selectedColony?.queenProfileId
    ? (queenProfiles.find((q) => q.id === selectedColony.queenProfileId)?.name ?? "")
    : "";

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Main chart area — pannable canvas */}
      <div
        className="flex-1 overflow-hidden relative"
        style={{ cursor: dragging ? "grabbing" : "grab", userSelect: "none" }}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {/* Header — fixed above the canvas */}
        <div className="absolute top-0 left-0 right-0 px-6 py-4 z-10 pointer-events-none">
          <div className="flex items-baseline gap-3">
            <h2 className="text-lg font-semibold text-foreground">
              Org Chart
            </h2>
            <span className="text-xs text-muted-foreground">
              {queenProfiles.length} queen bees &middot; {colonies.length}{" "}
              {colonies.length === 1 ? "colony" : "colonies"}
            </span>
          </div>
        </div>

        {/* Pannable + zoomable content */}
        <div
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "center top",
            transition: dragging ? "none" : "transform 100ms ease-out",
          }}
        >
          <div className="min-w-max px-6 pt-16 pb-10 mx-auto flex flex-col items-center">
            {/* CEO card */}
            <div className="rounded-xl border border-border/60 bg-card px-8 py-5 text-center">
              <UserAvatar initials={initials} avatarVersion={userAvatarVersion} />
              <div className="font-semibold text-sm text-foreground">
                {userProfile.displayName || "You"}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                CEO / Founder
              </div>
            </div>

            {/* Vertical stem from CEO to queens row */}
            {queenProfiles.length > 0 && (
              <div className="w-px h-8 bg-border" />
            )}

            {/* Queens — all on the same level with horizontal connector */}
            {queenProfiles.length > 0 && (
              <div className="flex gap-4 justify-center relative">
                {/* Horizontal bar connecting first to last queen */}
                <div
                  className="absolute top-0 h-px bg-border"
                  style={{
                    left: `calc(140px / 2)`,
                    right: `calc(140px / 2)`,
                  }}
                />
                {queenProfiles.map((queen) => (
                  <QueenCard
                    key={queen.id}
                    queen={queen}
                    colonies={coloniesByQueen.get(queen.id) ?? []}
                    selected={selectedQueenId === queen.id}
                    onSelect={() => handleSelectQueen(queen.id)}
                    onSelectColony={handleSelectColony}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Queen profile side panel */}
      {selectedQueenId && (
        <QueenProfilePanel
          queenId={selectedQueenId}
          colonies={coloniesByQueen.get(selectedQueenId) ?? []}
          onClose={() => setSelectedQueenId(null)}
        />
      )}

      {/* Colony detail side panel */}
      {selectedColony && (
        <ColonyDetailPanel
          colony={selectedColony}
          queenName={colonyQueenName}
          onClose={() => setSelectedColony(null)}
          onIconChange={(colonyId, icon) => {
            setSelectedColony((prev) => prev && prev.id === colonyId ? { ...prev, icon } : prev);
          }}
        />
      )}
    </div>
  );
}
