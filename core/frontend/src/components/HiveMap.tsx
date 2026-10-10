import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import HiveLogo from "./HiveLogo";
import QueenAvatar from "./QueenAvatar";
import { ScrambleText } from "./fx/ScrambleText";
import { useCreateColony } from "@/context/CreateColonyContext";
import { useLiveSessions } from "@/hooks/use-live-sessions";
import { deriveColonyStatus, describeColonyStatus, type ColonyStatus } from "@/lib/colony-status";
import { isFullMotion } from "@/lib/motion";
import type { Colony, QueenProfileSummary } from "@/types/colony";

const SQRT3 = Math.sqrt(3);
/** Each cell is drawn at this fraction of its lattice slot: the gap between
 *  neighbours is the comb's "wax". */
const CELL_FILL = 0.93;
const MAX_RADIUS = 56;
// Below this a ten-letter word no longer fits a cell's line.
const MIN_RADIUS = 42;
const MAX_HEIGHT = 600;
const HIVES_PER_BAND = 6;
const MAX_COLONY_PETALS = 6;
/** One pass of the scan beam across the comb. */
const BEAM_MS = 9000;

/** Axial neighbour offsets, clockwise from the right (pointy-top cells). */
const PETALS: [number, number][] = [
  [1, 0],
  [0, 1],
  [-1, 1],
  [-1, 0],
  [0, -1],
  [1, -1],
];

/** Hive centres for one band, in axial coordinates. Seven-cell hives tile the
 *  plane on the lattice u=(2,1), v=(-1,3); stepping u, then u−v, zig-zags them
 *  into a wide row that repeats every (7,0). Each further band shifts by v. */
const BAND_STEPS: [number, number][] = [
  [0, 0],
  [2, 1],
  [5, -1],
];

function hiveCentre(index: number): [number, number] {
  const band = Math.floor(index / HIVES_PER_BAND);
  const k = index % HIVES_PER_BAND;
  const [q, r] = BAND_STEPS[k % 3];
  return [q + 7 * Math.floor(k / 3) - band, r + 3 * band];
}

/** Centre of axial cell (q, r) in units of the cell's circumradius. */
function toPoint(q: number, r: number): { x: number; y: number } {
  return { x: SQRT3 * (q + r / 2), y: 1.5 * r };
}

type CellKind = "queen" | "unassigned" | "colony" | "more" | "empty";

interface Cell {
  key: string;
  kind: CellKind;
  x: number;
  y: number;
  /** The hive (flower) this cell belongs to, and its slot: 0 = centre. */
  hive: number;
  slot: number;
  /** Entrance order: hives in turn, each centre first, then its petals. */
  delayMs: number;
  queen?: QueenProfileSummary;
  colony?: Colony;
  /** For "more": how many colonies did not fit. */
  hidden?: number;
}

interface Hive {
  queen: QueenProfileSummary | null;
  colonies: Colony[];
}

function layout(hives: Hive[]): Cell[] {
  const cells: Cell[] = [];
  hives.forEach((hive, h) => {
    const [cq, cr] = hiveCentre(h);
    const id = hive.queen?.id ?? "unassigned";
    cells.push({
      key: `${id}:centre`,
      kind: hive.queen ? "queen" : "unassigned",
      ...toPoint(cq, cr),
      hive: h,
      slot: 0,
      delayMs: h * 90,
      queen: hive.queen ?? undefined,
    });
    const overflow = hive.colonies.length > MAX_COLONY_PETALS;
    const shown = overflow ? hive.colonies.slice(0, MAX_COLONY_PETALS - 1) : hive.colonies;
    PETALS.forEach(([dq, dr], p) => {
      const base = {
        ...toPoint(cq + dq, cr + dr),
        hive: h,
        slot: p + 1,
        delayMs: h * 90 + 160 + p * 45,
        queen: hive.queen ?? undefined,
      };
      if (p < shown.length) {
        cells.push({ key: `${id}:${shown[p].id}`, kind: "colony", colony: shown[p], ...base });
      } else if (overflow && p === MAX_COLONY_PETALS - 1) {
        cells.push({ key: `${id}:more`, kind: "more", hidden: hive.colonies.length - shown.length, ...base });
      } else {
        cells.push({ key: `${id}:empty${p}`, kind: "empty", ...base });
      }
    });
  });
  return cells;
}

const STATUS_LABEL: Record<ColonyStatus, string> = {
  active: "Working",
  parked: "Needs you",
  idle: "Idle",
};

/** The home page's live map of the user's hive: one seven-cell honeycomb per
 *  queen — the queen at the centre, her colonies in the petals, empty petals
 *  to found new ones. Projected like a HUD: the comb tilts toward the
 *  pointer, a scan beam sweeps it, hovering locks a reticle onto a cell and
 *  lights its hive, and busy cells pulse. */
export default function HiveMap({
  queens,
  colonies,
}: {
  queens: QueenProfileSummary[];
  colonies: Colony[];
}) {
  const navigate = useNavigate();
  const { openCreateColony } = useCreateColony();
  const { byQueen, byColony } = useLiveSessions();

  const hives = useMemo<Hive[]>(() => {
    const byRecent = (a: Colony, b: Colony) => (b.lastActive ?? "").localeCompare(a.lastActive ?? "");
    const known = new Set(queens.map((q) => q.id));
    const result: Hive[] = queens.map((queen) => ({
      queen,
      colonies: colonies.filter((c) => c.queenProfileId === queen.id).sort(byRecent),
    }));
    const unassigned = colonies.filter((c) => !c.queenProfileId || !known.has(c.queenProfileId));
    if (unassigned.length) result.push({ queen: null, colonies: unassigned.sort(byRecent) });
    return result;
  }, [queens, colonies]);

  const cells = useMemo(() => layout(hives), [hives]);
  const bounds = useMemo(() => {
    const xs = cells.map((c) => c.x);
    const ys = cells.map((c) => c.y);
    const minX = Math.min(...xs) - SQRT3 / 2;
    const minY = Math.min(...ys) - 1;
    return { minX, minY, width: Math.max(...xs) + SQRT3 / 2 - minX, height: Math.max(...ys) + 1 - minY };
  }, [cells]);

  // The radius follows the container: as large as fits, within limits.
  const hostRef = useRef<HTMLDivElement>(null);
  const planeRef = useRef<HTMLDivElement>(null);
  const [hostWidth, setHostWidth] = useState(0);
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    setHostWidth(host.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setHostWidth(host.clientWidth));
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  const radius = Math.max(
    MIN_RADIUS,
    Math.min(MAX_RADIUS, hostWidth / bounds.width, MAX_HEIGHT / bounds.height),
  );
  const mapWidth = bounds.width * radius;
  const mapHeight = bounds.height * radius;
  const cellW = SQRT3 * radius * CELL_FILL;
  const cellH = 2 * radius * CELL_FILL;
  const centre = (c: Cell) => ({ cx: (c.x - bounds.minX) * radius, cy: (c.y - bounds.minY) * radius });

  const [focused, setFocused] = useState<Cell | null>(null);

  const colonyStatus = (c: Colony) => deriveColonyStatus(c.sessionId !== null, byColony.get(c.id));
  const queenWorking = (q: QueenProfileSummary) => Boolean(byQueen.get(q.id)?.is_executing);

  const readout = (cell: Cell | null): string => {
    if (!cell) return "Hover a cell to inspect · click to open";
    if (cell.kind === "queen" && cell.queen) {
      const live = byQueen.get(cell.queen.id);
      const count = colonies.filter((c) => c.queenProfileId === cell.queen!.id).length;
      const state = live?.current_tool_name
        ? `running ${live.current_tool_name}`
        : live?.is_executing
          ? "thinking"
          : "standing by";
      return `${cell.queen.name} · ${cell.queen.title} · ${count} ${count === 1 ? "colony" : "colonies"} · ${state}`;
    }
    if (cell.kind === "colony" && cell.colony) {
      const s = colonyStatus(cell.colony);
      const owner = cell.queen ? ` · led by ${cell.queen.name}` : "";
      return `${cell.colony.name}${owner} · ${describeColonyStatus(s, byColony.get(cell.colony.id))}`;
    }
    if (cell.kind === "more") return `${cell.hidden} more ${cell.hidden === 1 ? "colony" : "colonies"} · open ${cell.queen?.name ?? "the queen"} to see them all`;
    if (cell.kind === "unassigned") return "Colonies whose queen is no longer active";
    return `Empty cell · found a new colony under ${cell.queen?.name ?? "a queen"}`;
  };

  const open = (cell: Cell) => {
    if (cell.kind === "colony" && cell.colony) navigate(`/colony/${cell.colony.id}`);
    else if ((cell.kind === "queen" || cell.kind === "more") && cell.queen) navigate(`/queen/${cell.queen.id}`);
    else if (cell.kind === "empty") openCreateColony({ queenId: cell.queen?.id });
  };

  // HUD projection: the comb plane leans toward the pointer. Written straight
  // to CSS variables so tracking never re-renders the cells.
  const tilt = (e: React.PointerEvent<HTMLDivElement>) => {
    const plane = planeRef.current;
    if (!plane || !isFullMotion()) return;
    const r = e.currentTarget.getBoundingClientRect();
    plane.style.setProperty("--tilt-x", ((e.clientX - r.left) / r.width - 0.5).toFixed(3));
    plane.style.setProperty("--tilt-y", ((e.clientY - r.top) / r.height - 0.5).toFixed(3));
  };
  const leave = () => {
    setFocused(null);
    planeRef.current?.style.setProperty("--tilt-x", "0");
    planeRef.current?.style.setProperty("--tilt-y", "0");
  };

  const working =
    [...byQueen.values()].filter((l) => l.is_executing).length +
    colonies.filter((c) => colonyStatus(c) === "active").length;
  const needsYou = colonies.filter((c) => colonyStatus(c) === "parked").length;
  const lock = focused ? centre(focused) : null;

  return (
    <section className="hive-map" aria-label="Hive map">
      <header className="hive-map-head">
        <span className="hive-map-title">
          <HiveLogo size={12} className="text-primary" />
          Hive map
        </span>
        <span aria-hidden className="fx-ruler flex-1" />
        <span className="hive-map-legend">
          <span data-state="working">{working} working</span>
          <span data-state="parked">{needsYou} need you</span>
          <span data-state="idle">{hives.length} {hives.length === 1 ? "hive" : "hives"}</span>
        </span>
      </header>

      <div ref={hostRef} className="hive-map-stage" onPointerMove={tilt} onMouseLeave={leave}>
        <div
          ref={planeRef}
          className="hive-map-plane"
          data-focus={focused ? "" : undefined}
          style={{
            width: mapWidth,
            height: mapHeight,
            "--beam-ms": `${BEAM_MS}ms`,
            // Type scales with the cells so a line always fits its band.
            "--cell-name": `${Math.min(12.5, Math.max(10.5, radius * 0.24)).toFixed(1)}px`,
            "--cell-text": `${Math.min(11, Math.max(9.5, radius * 0.215)).toFixed(1)}px`,
          } as CSSProperties}
        >
          <span aria-hidden className="hive-map-beam" />
          {lock && focused && (
            <>
              <span aria-hidden className="hive-map-cross" data-axis="x" style={{ top: lock.cy }} />
              <span aria-hidden className="hive-map-cross" data-axis="y" style={{ left: lock.cx }} />
            </>
          )}
          {cells.map((cell) => {
            const { cx, cy } = centre(cell);
            const state =
              cell.kind === "colony" && cell.colony
                ? colonyStatus(cell.colony)
                : cell.kind === "queen" && cell.queen && queenWorking(cell.queen)
                  ? "active"
                  : undefined;
            const style = {
              left: cx - cellW / 2,
              top: cy - cellH / 2,
              width: cellW,
              height: cellH,
              "--fx-d": `${cell.delayMs}ms`,
              // The beam lights each cell as it crosses the cell's centre.
              "--hit-d": `${Math.round((cx / mapWidth) * BEAM_MS)}ms`,
            } as CSSProperties;
            return (
              <button
                key={cell.key}
                type="button"
                className="hive-cell"
                data-kind={cell.kind}
                data-state={state}
                data-lit={focused && focused.hive === cell.hive ? "" : undefined}
                style={style}
                aria-label={readout(cell)}
                title={cell.kind === "queen" && cell.queen ? `${cell.queen.name} — ${cell.queen.title}` : undefined}
                onMouseEnter={() => setFocused(cell)}
                onFocus={() => setFocused(cell)}
                onBlur={() => setFocused(null)}
                onClick={() => open(cell)}
                disabled={cell.kind === "unassigned"}
              >
                <span aria-hidden className="hive-cell-edge" />
                <span className="hive-cell-face">
                  <CellFace cell={cell} radius={radius} state={state} />
                </span>
              </button>
            );
          })}
          {/* Busy cells send hexagonal ripples out past their edges. */}
          {cells
            .filter((c) =>
              c.kind === "colony" && c.colony
                ? colonyStatus(c.colony) === "active"
                : c.kind === "queen" && c.queen
                  ? queenWorking(c.queen)
                  : false,
            )
            .map((c) => {
              const { cx, cy } = centre(c);
              return (
                <svg
                  key={`${c.key}:pulse`}
                  aria-hidden
                  className="hive-map-pulse"
                  viewBox="-1 -1 2 2"
                  style={{ left: cx - radius, top: cy - radius, width: radius * 2, height: radius * 2 }}
                >
                  <polygon points="0,-1 0.866,-0.5 0.866,0.5 0,1 -0.866,0.5 -0.866,-0.5" />
                </svg>
              );
            })}
          {lock && focused && (
            <span
              aria-hidden
              key={focused.key}
              className="hive-map-reticle"
              style={{
                left: lock.cx - cellW / 2 - 7,
                top: lock.cy - cellH / 2 - 7,
                width: cellW + 14,
                height: cellH + 14,
              }}
            >
              <span className="hive-map-reticle-tag">
                Hive {String(focused.hive + 1).padStart(2, "0")} · {focused.slot === 0 ? "Core" : `Cell ${focused.slot}`}
              </span>
            </span>
          )}
        </div>
      </div>

      <div className="hive-map-readout" aria-live="polite">
        <span className="text-primary">&gt;</span>
        <ScrambleText text={readout(focused)} durationMs={320} className="min-w-0 truncate" />
        <span aria-hidden className="fx-caret" />
      </div>
    </section>
  );
}

/**
 * A cell's contents. Pointy-top hexagons are full width only through their
 * middle half, so every line sits inside that band: a queen shows her avatar
 * and name (her role is in the tooltip and the readout), a colony its name
 * and a one-line status.
 */
function CellFace({ cell, radius, state }: { cell: Cell; radius: number; state?: ColonyStatus }) {
  if (cell.kind === "queen" && cell.queen) {
    const avatar = Math.round(radius * 0.52);
    return (
      <>
        <span className="hive-cell-avatar" style={{ width: avatar, height: avatar }}>
          <QueenAvatar queen={cell.queen} className="w-full h-full" />
        </span>
        <ScrambleText
          text={cell.queen.name.split(" ")[0]}
          className="hive-cell-name"
          delayMs={cell.delayMs + 220}
          durationMs={420}
        />
      </>
    );
  }
  if (cell.kind === "unassigned") {
    return (
      <>
        <HiveLogo size={Math.round(radius * 0.46)} className="text-muted-foreground" />
        <span className="hive-cell-status">Unassigned</span>
      </>
    );
  }
  if (cell.kind === "colony" && cell.colony) {
    return (
      <>
        <span className="hive-cell-colony">{cell.colony.name}</span>
        <span className="hive-cell-status" data-state={state}>
          {state ? STATUS_LABEL[state] : ""}
        </span>
      </>
    );
  }
  if (cell.kind === "more") {
    return (
      <>
        <span className="hive-cell-name">+{cell.hidden}</span>
        <span className="hive-cell-status">more</span>
      </>
    );
  }
  return (
    <span className="hive-cell-new">
      <Plus className="w-3.5 h-3.5" />
      <span>New colony</span>
    </span>
  );
}
