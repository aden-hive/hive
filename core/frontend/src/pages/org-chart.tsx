import { useState, useCallback, useRef } from "react";
import { NavLink } from "react-router-dom";
import { User } from "lucide-react";
import { useColony } from "@/context/ColonyContext";
import type { QueenProfileSummary, Colony } from "@/types/colony";
import { getColonyIcon } from "@/lib/colony-registry";
import QueenProfilePanel from "@/components/QueenProfilePanel";

/* ── Colony tag (clickable link to colony chat) ───────────────────────── */

function ColonyTag({ colony }: { colony: Colony }) {
  const Icon = getColonyIcon(colony.queenId);
  return (
    <NavLink
      to={`/colony/${colony.id}`}
      className="flex items-center gap-1.5 rounded-lg border border-border/50 bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground hover:border-primary/30 hover:text-foreground transition-colors"
    >
      <Icon className="w-3 h-3 flex-shrink-0" />
      <span className="truncate">{colony.name}</span>
    </NavLink>
  );
}

/* ── Queen card in the org grid ───────────────────────────────────────── */

function QueenCard({
  queen,
  colonies,
  selected,
  onSelect,
}: {
  queen: QueenProfileSummary;
  colonies: Colony[];
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div className="flex flex-col items-center w-[140px] flex-shrink-0">
      {/* Vertical stub from horizontal bar */}
      <div className="w-px h-6 bg-border" />

      {/* Queen card */}
      <button
        onClick={onSelect}
        className={`group flex flex-col items-center rounded-xl border bg-card p-4 w-full transition-all duration-200 text-center ${
          selected
            ? "border-primary/40 bg-primary/[0.04] ring-1 ring-primary/20"
            : "border-border/60 hover:border-primary/30 hover:bg-primary/[0.03]"
        }`}
      >
        <div className="w-11 h-11 rounded-full bg-primary/15 flex items-center justify-center mb-2.5">
          <span className="text-sm font-bold text-primary">
            {queen.name.charAt(0)}
          </span>
        </div>
        <span className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors">
          {queen.name}
        </span>
        <span className="text-xs text-muted-foreground mt-0.5">
          {queen.title}
        </span>
      </button>

      {/* Colony connections */}
      {colonies.length > 0 && (
        <>
          <div className="w-px h-4 bg-border" />
          <div className="flex flex-col gap-1.5 w-full">
            {colonies.map((colony) => (
              <ColonyTag key={colony.id} colony={colony} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Main org chart page ──────────────────────────────────────────────── */

export default function OrgChart() {
  const { queenProfiles, colonies, userProfile } = useColony();
  const [selectedQueenId, setSelectedQueenId] = useState<string | null>(null);

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
              <div className="w-12 h-12 rounded-full bg-primary/15 mx-auto mb-3 flex items-center justify-center">
                {initials ? (
                  <span className="text-sm font-bold text-primary">
                    {initials}
                  </span>
                ) : (
                  <User className="w-5 h-5 text-primary" />
                )}
              </div>
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
                    onSelect={() =>
                      setSelectedQueenId(
                        selectedQueenId === queen.id ? null : queen.id,
                      )
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Profile side panel */}
      {selectedQueenId && (
        <QueenProfilePanel
          queenId={selectedQueenId}
          colonies={coloniesByQueen.get(selectedQueenId) ?? []}
          onClose={() => setSelectedQueenId(null)}
        />
      )}
    </div>
  );
}
