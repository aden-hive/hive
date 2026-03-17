import { useEffect, useLayoutEffect, useMemo, useRef, useState, useCallback } from "react";
import { Loader2 } from "lucide-react";
import type { DraftGraph as DraftGraphData, DraftNode } from "@/api/types";
import { RunButton } from "./RunButton";
import type { GraphNode, RunState } from "./graph-types";

// Read a CSS custom property value (space-separated HSL components)
function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

interface DraftChromeColors {
  edge: string;
  edgeArrow: string;
  edgeLabel: string;
  backEdge: string;
  groupFill: string;
  groupStroke: string;
  chromeText: string;
  chromeTextDim: string;
  nodeText: string;
  nodeTextHover: string;
  statusRunning: string;
  statusComplete: string;
  statusError: string;
}

function buildDraftChromeColors(): DraftChromeColors {
  const edge = cssVar("--draft-edge") || "220 10% 30%";
  const edgeArrow = cssVar("--draft-edge-arrow") || "220 10% 35%";
  const edgeLabel = cssVar("--draft-edge-label") || "220 10% 45%";
  const backEdge = cssVar("--draft-back-edge") || "220 10% 25%";
  const groupFill = cssVar("--draft-group-fill") || "220 15% 18%";
  const groupStroke = cssVar("--draft-group-stroke") || "220 10% 40%";
  const chromeText = cssVar("--draft-chrome-text") || "220 10% 50%";
  const chromeTextDim = cssVar("--draft-chrome-text-dim") || "220 10% 55%";
  const nodeText = cssVar("--draft-node-text") || "0 0% 78%";
  const nodeTextHover = cssVar("--draft-node-text-hover") || "0 0% 92%";
  const running = cssVar("--node-running") || "45 95% 58%";
  const complete = cssVar("--node-complete") || "43 70% 45%";
  const error = cssVar("--node-error") || "0 65% 55%";

  return {
    edge: `hsl(${edge})`,
    edgeArrow: `hsl(${edgeArrow})`,
    edgeLabel: `hsl(${edgeLabel})`,
    backEdge: `hsl(${backEdge})`,
    groupFill: `hsl(${groupFill})`,
    groupStroke: `hsl(${groupStroke})`,
    chromeText: `hsl(${chromeText})`,
    chromeTextDim: `hsl(${chromeTextDim})`,
    nodeText: `hsl(${nodeText})`,
    nodeTextHover: `hsl(${nodeTextHover})`,
    statusRunning: `hsl(${running})`,
    statusComplete: `hsl(${complete})`,
    statusError: `hsl(${error})`,
  };
}

function useDraftChromeColors() {
  const [colors, setColors] = useState<DraftChromeColors>(buildDraftChromeColors);

  useEffect(() => {
    const rebuild = () => setColors(buildDraftChromeColors());
    const obs = new MutationObserver(rebuild);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style"] });
    return () => obs.disconnect();
  }, []);

  return colors;
}

type DraftNodeStatus = "pending" | "running" | "complete" | "error";

interface DraftGraphProps {
  draft: DraftGraphData | null;
  /** The post-build originalDraft — animation fires when this changes to a new non-null value. */
  originalDraft?: DraftGraphData | null;
  onNodeClick?: (node: DraftNode) => void;
  /** Runtime node ID → list of original draft node IDs (post-dissolution mapping). */
  flowchartMap?: Record<string, string[]>;
  /** Current runtime graph nodes with live status (for overlay during execution). */
  runtimeNodes?: GraphNode[];
  /** Called when a draft node is clicked in overlay mode — receives the runtime node ID. */
  onRuntimeNodeClick?: (runtimeNodeId: string) => void;
  /** True while the queen is building the agent from the draft. */
  building?: boolean;
  /** Message to show with a spinner while loading/designing. Null = no spinner. */
  loadingMessage?: string | null;
  /** Called when the user clicks Run. */
  onRun?: () => void;
  /** Called when the user clicks Pause. */
  onPause?: () => void;
  /** Current run state — drives the RunButton appearance. */
  runState?: RunState;
}

// Layout constants — tuned for a ~500px panel (484px after px-2 padding)
const NODE_H = 52;
const GAP_Y = 48;
const TOP_Y = 28;
const MARGIN_X = 16;
const GAP_X = 16;
const GROUP_GAP_COLS = 1; // extra column spacing between different groups

function formatNodeId(id: string): string {
  return id.split("-").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function truncateLabel(label: string, availablePx: number, fontSize: number): string {
  const avgCharW = fontSize * 0.58;
  const maxChars = Math.floor(availablePx / avgCharW);
  if (label.length <= maxChars) return label;
  return label.slice(0, Math.max(maxChars - 1, 1)) + "\u2026";
}

/** Return the bounding-rect corner radius for a given flowchart shape. */
/**
 * Render an ISO 5807 flowchart shape as an SVG element.
 */
function FlowchartShape({
  shape,
  x,
  y,
  w,
  h,
  color,
  selected,
}: {
  shape: string;
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
  selected: boolean;
}) {
  const fill = selected ? `${color}28` : `${color}18`;
  const stroke = selected ? color : `${color}80`;
  const common = { fill, stroke, strokeWidth: 1.2 };

  switch (shape) {
    case "stadium":
      return <rect x={x} y={y} width={w} height={h} rx={h / 2} {...common} />;

    case "rectangle":
      return <rect x={x} y={y} width={w} height={h} rx={4} {...common} />;

    case "diamond": {
      const cx = x + w / 2;
      const cy = y + h / 2;
      return (
        <polygon
          points={`${cx},${y} ${x + w},${cy} ${cx},${y + h} ${x},${cy}`}
          {...common}
        />
      );
    }

    case "parallelogram": {
      const skew = 12;
      return (
        <polygon
          points={`${x + skew},${y} ${x + w},${y} ${x + w - skew},${y + h} ${x},${y + h}`}
          {...common}
        />
      );
    }

    case "document": {
      const d = `M ${x} ${y + 4} Q ${x} ${y}, ${x + 8} ${y} L ${x + w - 8} ${y} Q ${x + w} ${y}, ${x + w} ${y + 4} L ${x + w} ${y + h - 8} C ${x + w * 0.75} ${y + h + 2}, ${x + w * 0.25} ${y + h - 10}, ${x} ${y + h - 4} Z`;
      return <path d={d} {...common} />;
    }

    case "subroutine": {
      const inset = 7;
      return (
        <g>
          <rect x={x} y={y} width={w} height={h} rx={4} {...common} />
          <line x1={x + inset} y1={y} x2={x + inset} y2={y + h} stroke={stroke} strokeWidth={1.2} />
          <line x1={x + w - inset} y1={y} x2={x + w - inset} y2={y + h} stroke={stroke} strokeWidth={1.2} />
        </g>
      );
    }

    case "hexagon": {
      const inset = 14;
      return (
        <polygon
          points={`${x + inset},${y} ${x + w - inset},${y} ${x + w},${y + h / 2} ${x + w - inset},${y + h} ${x + inset},${y + h} ${x},${y + h / 2}`}
          {...common}
        />
      );
    }

    case "cylinder": {
      const ry = 7;
      return (
        <g>
          <path
            d={`M ${x} ${y + ry} L ${x} ${y + h - ry} A ${w / 2} ${ry} 0 0 0 ${x + w} ${y + h - ry} L ${x + w} ${y + ry}`}
            {...common}
          />
          <ellipse cx={x + w / 2} cy={y + ry} rx={w / 2} ry={ry} {...common} />
          <ellipse cx={x + w / 2} cy={y + h - ry} rx={w / 2} ry={ry} fill={fill} stroke={stroke} strokeWidth={1.2} />
        </g>
      );
    }

    default:
      return <rect x={x} y={y} width={w} height={h} rx={8} {...common} />;
  }
}

/** HTML tooltip positioned over the graph container */
function Tooltip({ node, style }: { node: DraftNode; style: React.CSSProperties }) {
  const lines: string[] = [];
  if (node.description) lines.push(node.description);
  if (node.success_criteria) lines.push(`Criteria: ${node.success_criteria}`);
  if (lines.length === 0) return null;

  return (
    <div
      className="absolute z-20 pointer-events-none px-2.5 py-2 rounded-md border border-border/40 bg-popover/95 backdrop-blur-sm shadow-lg max-w-[260px]"
      style={style}
    >
      {lines.map((line, i) => (
        <p key={i} className="text-[10px] text-muted-foreground leading-[1.4] mb-0.5 last:mb-0">
          {line}
        </p>
      ))}
    </div>
  );
}

export default function DraftGraph({ draft, originalDraft, onNodeClick, flowchartMap, runtimeNodes, onRuntimeNodeClick, building, loadingMessage, onRun, onPause, runState = "idle" }: DraftGraphProps) {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const runBtnRef = useRef<HTMLButtonElement>(null);
  const [containerW, setContainerW] = useState(484);
  const chrome = useDraftChromeColors();

  // ── Entrance animation — fires when originalDraft becomes a new non-null value ──
  // This covers: agent loaded, build finished, queen modifies flowchart.
  // Tab switches remount via React key={activeWorker}, resetting all refs.
  const prevOriginalDraft = useRef<DraftGraphData | null>(null);
  const pendingAnimation = useRef(false);
  const [entrancePhase, setEntrancePhase] = useState<"idle" | "hidden" | "visible">("idle");

  const nodes = draft?.nodes ?? [];

  useLayoutEffect(() => {
    const prev = prevOriginalDraft.current;
    prevOriginalDraft.current = originalDraft ?? null;

    // Detect a new non-null originalDraft (object identity — each API/SSE response is a fresh object)
    if (originalDraft && originalDraft !== prev) {
      pendingAnimation.current = true;
    }

    // Fire when we have a pending animation, nodes are ready, and not mid-build
    if (pendingAnimation.current && nodes.length > 0 && !building) {
      pendingAnimation.current = false;
      setEntrancePhase("hidden");
      let raf1 = 0, raf2 = 0;
      raf1 = requestAnimationFrame(() => {
        raf2 = requestAnimationFrame(() => setEntrancePhase("visible"));
      });
      const t = setTimeout(() => setEntrancePhase("idle"), nodes.length * 120 + 1000);
      return () => { clearTimeout(t); cancelAnimationFrame(raf1); cancelAnimationFrame(raf2); };
    }
  }, [originalDraft, nodes.length, building]);

  // Shift-to-pin tooltip
  const shiftHeld = useRef(false);
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === "Shift") shiftHeld.current = true; };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === "Shift") {
        shiftHeld.current = false;
        setHoveredNode(null);
        setMousePos(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => { window.removeEventListener("keydown", onKeyDown); window.removeEventListener("keyup", onKeyUp); };
  }, []);

  // Pan & Zoom state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const MIN_ZOOM = 0.4;
  const MAX_ZOOM = 3;

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setZoom(z => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z * delta)));
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
  }, [pan]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging) return;
    setPan({
      x: dragStart.current.panX + (e.clientX - dragStart.current.x),
      y: dragStart.current.panY + (e.clientY - dragStart.current.y),
    });
  }, [dragging]);

  const handleMouseUp = useCallback(() => setDragging(false), []);

  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  // Measure actual container width so layout fills it exactly
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setContainerW(w);
    });
    ro.observe(el);
    // Capture initial width
    setContainerW(el.clientWidth || 484);
    return () => ro.disconnect();
  }, []);

  // Invert flowchartMap: draftNodeId → runtimeNodeId
  const draftToRuntime = useMemo<Record<string, string>>(() => {
    if (!flowchartMap) return {};
    const map: Record<string, string> = {};
    for (const [runtimeId, draftIds] of Object.entries(flowchartMap)) {
      for (const did of draftIds) {
        map[did] = runtimeId;
      }
    }
    return map;
  }, [flowchartMap]);

  // Compute draft node statuses from runtime overlay
  const nodeStatuses = useMemo<Record<string, DraftNodeStatus>>(() => {
    if (!runtimeNodes?.length || !Object.keys(draftToRuntime).length) return {};
    // Build runtime status lookup
    const runtimeStatus: Record<string, DraftNodeStatus> = {};
    for (const rn of runtimeNodes) {
      const s = rn.status;
      runtimeStatus[rn.id] =
        s === "running" || s === "looping" ? "running"
        : s === "complete" ? "complete"
        : s === "error" ? "error"
        : "pending";
    }
    // Map to draft nodes
    const result: Record<string, DraftNodeStatus> = {};
    for (const [draftId, runtimeId] of Object.entries(draftToRuntime)) {
      result[draftId] = runtimeStatus[runtimeId] ?? "pending";
    }
    return result;
  }, [draftToRuntime, runtimeNodes]);

  const hasStatusOverlay = Object.keys(nodeStatuses).length > 0;

  const edges = draft?.edges ?? [];

  const idxMap = useMemo(
    () => Object.fromEntries(nodes.map((n, i) => [n.id, i])),
    [nodes],
  );

  const forwardEdges = useMemo(() => {
    const fwd: { fromIdx: number; toIdx: number; fanCount: number; fanIndex: number; label?: string }[] = [];
    const grouped = new Map<number, { toIdx: number; label?: string }[]>();
    for (const e of edges) {
      const fromIdx = idxMap[e.source];
      const toIdx = idxMap[e.target];
      if (fromIdx === undefined || toIdx === undefined) continue;
      if (toIdx <= fromIdx) continue;
      const list = grouped.get(fromIdx) || [];
      list.push({ toIdx, label: e.label || (e.condition !== "on_success" && e.condition !== "always" ? e.condition : e.description || undefined) });
      grouped.set(fromIdx, list);
    }
    for (const [fromIdx, targets] of grouped) {
      targets.forEach((t, fi) => {
        fwd.push({ fromIdx, toIdx: t.toIdx, fanCount: targets.length, fanIndex: fi, label: t.label });
      });
    }
    return fwd;
  }, [edges, idxMap]);

  const backEdges = useMemo(() => {
    const back: { fromIdx: number; toIdx: number }[] = [];
    for (const e of edges) {
      const fromIdx = idxMap[e.source];
      const toIdx = idxMap[e.target];
      if (fromIdx === undefined || toIdx === undefined) continue;
      if (toIdx <= fromIdx) back.push({ fromIdx, toIdx });
    }
    return back;
  }, [edges, idxMap]);

  // Layer-based layout with parent-aware column placement
  const layout = useMemo(() => {
    if (nodes.length === 0) {
      return { layers: [] as number[], nodeW: 200, firstColX: MARGIN_X, nodeXPositions: [] as number[] };
    }

    // Build parent and children maps
    const parents = new Map<number, number[]>();
    const children = new Map<number, number[]>();
    nodes.forEach((_, i) => { parents.set(i, []); children.set(i, []); });
    forwardEdges.forEach((e) => {
      parents.get(e.toIdx)!.push(e.fromIdx);
      children.get(e.fromIdx)!.push(e.toIdx);
    });

    // Assign layers (longest path from root)
    const layers = new Array(nodes.length).fill(0);
    for (let i = 0; i < nodes.length; i++) {
      const pars = parents.get(i) || [];
      if (pars.length > 0) {
        layers[i] = Math.max(...pars.map((p) => layers[p])) + 1;
      }
    }

    const layerGroups = new Map<number, number[]>();
    layers.forEach((l, i) => {
      const group = layerGroups.get(l) || [];
      group.push(i);
      layerGroups.set(l, group);
    });

    let maxCols = 1;
    layerGroups.forEach((group) => {
      maxCols = Math.max(maxCols, group.length);
    });
    // Ensure maxCols accommodates any parent's children fan-out
    // (prevents fan-out scaling from collapsing to zero)
    children.forEach((kids) => {
      maxCols = Math.max(maxCols, kids.length);
    });

    // Compute node width — keep back-edge overflow out of node sizing so nodes
    // get full width.  The viewBox is expanded later to fit back-edge curves.
    const totalMargin = MARGIN_X * 2 + 8;
    const availW = containerW - totalMargin;
    const nodeW = Math.min(360, Math.floor((availW - (maxCols - 1) * GAP_X) / maxCols));
    const backEdgeOverflow = backEdges.length > 0 ? 20 + (backEdges.length - 1) * 14 + 14 : 0;

    // Parent-aware column placement using fractional positions.
    // Instead of snapping to a fixed grid, nodes inherit positions from parents
    // and fan-out children spread around the parent's position.
    const colPos = new Array(nodes.length).fill(0); // fractional column positions
    const maxLayer = Math.max(...layers);

    // Map each draft node index to its runtime group ID for group-aware spacing
    const nodeGroup = new Map<number, string>();
    if (flowchartMap) {
      for (const [runtimeId, draftIds] of Object.entries(flowchartMap)) {
        for (const did of draftIds) {
          const idx = idxMap[did];
          if (idx !== undefined) nodeGroup.set(idx, runtimeId);
        }
      }
    }

    // Process layers top-down
    for (let layer = 0; layer <= maxLayer; layer++) {
      const group = layerGroups.get(layer) || [];
      if (layer === 0) {
        // Root layer: spread evenly across available columns
        if (group.length === 1) {
          colPos[group[0]] = (maxCols - 1) / 2;
        } else {
          const offset = (maxCols - group.length) / 2;
          group.forEach((nodeIdx, i) => { colPos[nodeIdx] = offset + i; });
        }
        continue;
      }

      // For each node, compute ideal position from parents
      const ideals: { idx: number; pos: number }[] = [];
      for (const nodeIdx of group) {
        const pars = parents.get(nodeIdx) || [];
        if (pars.length === 0) {
          ideals.push({ idx: nodeIdx, pos: (maxCols - 1) / 2 });
          continue;
        }
        // Average parent column — weighted center
        const avgCol = pars.reduce((s, p) => s + colPos[p], 0) / pars.length;

        // If this node is one of multiple children of a parent, offset from center
        // Find the parent with the most children to determine fan-out
        let bestOffset = 0;
        for (const p of pars) {
          const siblings = (children.get(p) || []).filter(c => layers[c] === layer);
          if (siblings.length > 1) {
            const sibIdx = siblings.indexOf(nodeIdx);
            if (sibIdx >= 0) {
              bestOffset = sibIdx - (siblings.length - 1) / 2;
              // Scale so siblings don't exceed available columns
              bestOffset *= Math.min(1, (maxCols - 1) / Math.max(siblings.length - 1, 1));
            }
          }
        }
        ideals.push({ idx: nodeIdx, pos: avgCol + bestOffset });
      }

      // Sort by ideal position, then assign while preventing overlaps
      ideals.sort((a, b) => a.pos - b.pos);

      // Ensure minimum spacing of 1 column between nodes in the same layer
      // (wider gap between nodes from different groups to prevent box overlap)
      const assigned: number[] = [];
      const assignedIdxs: number[] = [];
      for (const item of ideals) {
        let pos = item.pos;
        // Clamp to valid range
        pos = Math.max(0, Math.min(maxCols - 1, pos));
        // Push right if overlapping previous
        if (assigned.length > 0) {
          const prev = assigned[assigned.length - 1];
          const prevIdx = assignedIdxs[assignedIdxs.length - 1];
          let minGap = 1;
          const curGroup = nodeGroup.get(item.idx);
          const prevGroup = nodeGroup.get(prevIdx);
          if (curGroup !== prevGroup && (curGroup || prevGroup)) {
            minGap = 1 + GROUP_GAP_COLS;
          }
          if (pos < prev + minGap) pos = prev + minGap;
        }
        assigned.push(pos);
        assignedIdxs.push(item.idx);
        colPos[item.idx] = pos;
      }

      // If we pushed nodes too far right, shift the whole group left
      const maxPos = assigned[assigned.length - 1];
      if (maxPos > maxCols - 1) {
        const shift = maxPos - (maxCols - 1);
        for (const item of ideals) {
          colPos[item.idx] = Math.max(0, colPos[item.idx] - shift);
        }
      }
    }

    // Post-process: enforce minimum spacing within each layer
    for (const [, group] of layerGroups) {
      if (group.length <= 1) continue;
      const sorted = [...group].sort((a, b) => colPos[a] - colPos[b]);
      for (let j = 1; j < sorted.length; j++) {
        if (colPos[sorted[j]] < colPos[sorted[j - 1]] + 1) {
          colPos[sorted[j]] = colPos[sorted[j - 1]] + 1;
        }
      }
    }

    // Convert fractional column positions to pixel X positions
    const colSpacing = nodeW + GAP_X;
    const usedMin = Math.min(...colPos);
    const usedMax = Math.max(...colPos);
    const usedSpan = usedMax - usedMin || 1;
    const totalNodesW = usedSpan * colSpacing;
    const firstColX = MARGIN_X + (availW - totalNodesW) / 2;

    const nodeXPositions = colPos.map((c: number) => firstColX + (c - usedMin) * colSpacing);

    const maxContentRight = Math.max(containerW, ...nodeXPositions.map(x => x + nodeW));

    return { layers, nodeW, firstColX, nodeXPositions, backEdgeOverflow, maxContentRight };
  }, [nodes, forwardEdges, backEdges.length, containerW, flowchartMap, idxMap]);

  const { layers, nodeW, nodeXPositions, backEdgeOverflow, maxContentRight } = layout;

  const maxLayer = nodes.length > 0 ? Math.max(...layers) : 0;

  // Group-box collision resolution: compute per-node Y offsets so that group
  // bounding boxes (dashed rectangles) never overlap.  Handles both same-layer
  // groups (sub-row splitting) and adjacent-layer groups (inter-box gap).
  const { nodeYOffset, totalExtraY, groupBoxMaxX } = useMemo(() => {
    const offsets = new Array(nodes.length).fill(0);
    if (!flowchartMap || !Object.keys(flowchartMap).length) {
      return { nodeYOffset: offsets, totalExtraY: 0, groupBoxMaxX: 0 };
    }

    const PAD = 7;
    const LABEL_H = 14;
    const MIN_GROUP_GAP = 16;
    const SUB_ROW_GAP = NODE_H + 24; // spacing for same-layer sub-rows

    // Build node index → group ID
    const nodeToGroup = new Map<number, string>();
    for (const [runtimeId, draftIds] of Object.entries(flowchartMap)) {
      for (const did of draftIds) {
        const idx = idxMap[did];
        if (idx !== undefined) nodeToGroup.set(idx, runtimeId);
      }
    }

    // Step 1: Same-layer sub-row splitting — when multiple groups share a layer,
    // assign per-node offsets to separate them into sub-rows.
    const layerGroupMap = new Map<number, Map<string, number[]>>();
    nodes.forEach((_, i) => {
      const group = nodeToGroup.get(i);
      if (!group) return;
      const layer = layers[i];
      if (!layerGroupMap.has(layer)) layerGroupMap.set(layer, new Map());
      const lg = layerGroupMap.get(layer)!;
      if (!lg.has(group)) lg.set(group, []);
      lg.get(group)!.push(i);
    });

    // Per-node sub-row offset and per-layer extra height from sub-rows
    const layerSubRowExtra = new Array(maxLayer + 1).fill(0);
    for (let L = 0; L <= maxLayer; L++) {
      const groups = layerGroupMap.get(L);
      if (!groups || groups.size <= 1) continue;
      let subIdx = 0;
      for (const [, nodeIndices] of groups) {
        for (const idx of nodeIndices) {
          offsets[idx] = subIdx * SUB_ROW_GAP;
        }
        subIdx++;
      }
      layerSubRowExtra[L] = (groups.size - 1) * SUB_ROW_GAP;
    }

    // Cumulative sub-row shift: layers after a split layer are pushed down
    const subRowCumShift = new Array(maxLayer + 1).fill(0);
    let subCum = 0;
    for (let L = 0; L <= maxLayer; L++) {
      subRowCumShift[L] = subCum;
      subCum += layerSubRowExtra[L];
    }

    // Add cumulative sub-row shift to each node's offset
    for (let i = 0; i < nodes.length; i++) {
      offsets[i] += subRowCumShift[layers[i]];
    }

    // Step 2: Compute group bounding boxes using sub-row-adjusted positions
    type GroupBox = { runtimeId: string; minLayer: number; maxLayer: number; minY: number; maxY: number; maxX: number };
    const boxes: GroupBox[] = [];
    for (const [runtimeId, draftIds] of Object.entries(flowchartMap)) {
      const indices = draftIds.map(id => idxMap[id]).filter((idx): idx is number => idx !== undefined);
      if (indices.length === 0) continue;
      const memberLayers = indices.map(i => layers[i]);
      const ys = indices.map(i => TOP_Y + layers[i] * (NODE_H + GAP_Y) + offsets[i]);
      const xs = indices.map(i => nodeXPositions[i]);
      boxes.push({
        runtimeId,
        minLayer: Math.min(...memberLayers),
        maxLayer: Math.max(...memberLayers),
        minY: Math.min(...ys) - PAD - LABEL_H,
        maxY: Math.max(...ys) + NODE_H + PAD,
        maxX: Math.max(...xs.map(x => x + nodeW)) + PAD,
      });
    }

    boxes.sort((a, b) => a.minY - b.minY || a.minLayer - b.minLayer);

    // Step 3: Resolve remaining overlaps between adjacent group boxes
    // by pushing lower boxes down.  Track shifts per-group so they apply
    // only to that group's nodes.
    const groupShift = new Map<string, number>();
    for (let i = 1; i < boxes.length; i++) {
      const prev = boxes[i - 1];
      const curr = boxes[i];

      const prevShift = groupShift.get(prev.runtimeId) ?? 0;
      const currShift = groupShift.get(curr.runtimeId) ?? 0;
      const prevBottom = prev.maxY + prevShift;
      const currTop = curr.minY + currShift;

      const overlap = prevBottom + MIN_GROUP_GAP - currTop;
      if (overlap > 0) {
        groupShift.set(curr.runtimeId, currShift + overlap);
      }
    }

    // Apply group shifts to node offsets
    let maxShift = 0;
    for (let i = 0; i < nodes.length; i++) {
      const group = nodeToGroup.get(i);
      if (group) {
        const shift = groupShift.get(group) ?? 0;
        offsets[i] += shift;
        maxShift = Math.max(maxShift, offsets[i]);
      }
    }

    // Also shift ungrouped nodes by their layer's cumulative sub-row shift
    // (they already have it from the subRowCumShift step above)

    const totalExtra = subCum + Math.max(0, ...Array.from(groupShift.values()));
    const maxGroupX = boxes.length > 0 ? Math.max(...boxes.map(b => b.maxX)) : 0;

    return { nodeYOffset: offsets, totalExtraY: totalExtra, groupBoxMaxX: maxGroupX };
  }, [nodes, maxLayer, flowchartMap, idxMap, layers, nodeXPositions, nodeW]);

  const nodePos = (i: number) => ({
    x: nodeXPositions[i],
    y: TOP_Y + layers[i] * (NODE_H + GAP_Y) + nodeYOffset[i],
  });

  const svgHeight = TOP_Y + (maxLayer + 1) * NODE_H + maxLayer * GAP_Y + totalExtraY + 16;

  // Compute group areas for runtime node boundaries on the draft
  const groupAreas = useMemo(() => {
    if (!flowchartMap) return [];
    const groups: { runtimeId: string; label: string; draftIds: string[] }[] = [];
    for (const [runtimeId, draftIds] of Object.entries(flowchartMap)) {
      groups.push({ runtimeId, label: formatNodeId(runtimeId), draftIds });
    }
    return groups;
  }, [flowchartMap]);

  // Legend
  const usedTypes = (() => {
    const seen = new Map<string, { shape: string; color: string }>();
    for (const n of nodes) {
      if (!seen.has(n.flowchart_type)) {
        seen.set(n.flowchart_type, { shape: n.flowchart_shape, color: n.flowchart_color });
      }
    }
    return [...seen.entries()];
  })();
  const legendH = usedTypes.length * 18 + 20;
  const totalH = svgHeight + legendH;

  const hoveredNodeData = hoveredNode ? nodes.find(n => n.id === hoveredNode) : null;

  const renderEdge = (edge: typeof forwardEdges[number], i: number) => {
    const from = nodePos(edge.fromIdx);
    const to = nodePos(edge.toIdx);
    const fromCenterX = from.x + nodeW / 2;
    const toCenterX = to.x + nodeW / 2;
    const y1 = from.y + NODE_H;
    const y2 = to.y;

    let startX = fromCenterX;
    if (edge.fanCount > 1) {
      const spread = nodeW * 0.4;
      const step = edge.fanCount > 1 ? spread / (edge.fanCount - 1) : 0;
      startX = fromCenterX - spread / 2 + edge.fanIndex * step;
    }

    const midY = (y1 + y2) / 2;
    // Orthogonal routing: straight when aligned, L-shape when offset
    const d = Math.abs(startX - toCenterX) < 2
      ? `M ${startX} ${y1} L ${toCenterX} ${y2}`
      : `M ${startX} ${y1} L ${startX} ${midY} L ${toCenterX} ${midY} L ${toCenterX} ${y2}`;

    // Edge draw-in animation (stroke-dashoffset)
    const isAnimating = entrancePhase !== "idle";
    const pathLength = Math.abs(y2 - y1) + Math.abs(startX - toCenterX) + 1;
    const edgeDelay = 200 + i * 80;
    const edgeStyle: React.CSSProperties | undefined = isAnimating ? {
      strokeDasharray: pathLength,
      strokeDashoffset: entrancePhase === "hidden" ? pathLength : 0,
      transition: `stroke-dashoffset 400ms ease-in-out ${edgeDelay}ms`,
    } : undefined;
    const edgeEndStyle: React.CSSProperties | undefined = isAnimating ? {
      opacity: entrancePhase === "hidden" ? 0 : 1,
      transition: `opacity 100ms ease-out ${edgeDelay + 350}ms`,
    } : undefined;

    return (
      <g key={`fwd-${i}`}>
        <path d={d} fill="none" stroke={chrome.edge} strokeWidth={1.2} style={edgeStyle} />
        <polygon
          points={`${toCenterX - 3},${y2 - 5} ${toCenterX + 3},${y2 - 5} ${toCenterX},${y2 - 1}`}
          fill={chrome.edgeArrow}
          style={edgeEndStyle}
        />
        {edge.label && (
          <text
            x={(startX + toCenterX) / 2}
            y={midY - 3}
            fill={chrome.edgeLabel}
            fontSize={9}
            fontStyle="italic"
            textAnchor="middle"
            style={edgeEndStyle}
          >
            {truncateLabel(edge.label, 80, 9)}
          </text>
        )}
      </g>
    );
  };

  const renderBackEdge = (edge: typeof backEdges[number], i: number) => {
    const from = nodePos(edge.fromIdx);
    const to = nodePos(edge.toIdx);
    const rightX = Math.max(from.x, to.x) + nodeW;
    const rightOffset = 20 + i * 14;
    const startX = from.x + nodeW;
    const startY = from.y + NODE_H / 2;
    const endX = to.x + nodeW;
    const endY = to.y + NODE_H / 2;
    const curveX = rightX + rightOffset;
    const r = 10;

    const path = `M ${startX} ${startY} C ${startX + r} ${startY}, ${curveX} ${startY}, ${curveX} ${startY - r} L ${curveX} ${endY + r} C ${curveX} ${endY}, ${endX + r} ${endY}, ${endX + 5} ${endY}`;

    // Back-edge draw-in animation (starts after forward edges)
    const isAnimating = entrancePhase !== "idle";
    const backPathLength = Math.abs(curveX - startX) + Math.abs(startY - endY) + Math.abs(curveX - endX) + 20;
    const backDelay = nodes.length * 120 + 300 + i * 80;
    const backEdgeStyle: React.CSSProperties | undefined = isAnimating ? {
      strokeDashoffset: entrancePhase === "hidden" ? backPathLength : 0,
      transition: `stroke-dashoffset 400ms ease-in-out ${backDelay}ms`,
    } : undefined;
    const backEndStyle: React.CSSProperties | undefined = isAnimating ? {
      opacity: entrancePhase === "hidden" ? 0 : 1,
      transition: `opacity 100ms ease-out ${backDelay + 350}ms`,
    } : undefined;

    return (
      <g key={`back-${i}`}>
        <path d={path} fill="none" stroke={chrome.backEdge} strokeWidth={1.2} strokeDasharray={isAnimating ? backPathLength : "4 3"} style={backEdgeStyle} />
        <polygon
          points={`${endX + 5},${endY - 2.5} ${endX + 5},${endY + 2.5} ${endX},${endY}`}
          fill={chrome.edge}
          style={backEndStyle}
        />
      </g>
    );
  };

  const STATUS_COLORS: Record<DraftNodeStatus, string> = {
    running: chrome.statusRunning,
    complete: chrome.statusComplete,
    error: chrome.statusError,
    pending: "",
  };

  const renderNode = (node: DraftNode, i: number) => {
    const pos = nodePos(i);
    const isHovered = hoveredNode === node.id;
    const fontSize = 13;
    const labelAvailW = nodeW - 28;
    const displayLabel = truncateLabel(node.name, labelAvailW, fontSize);
    const descAvailW = nodeW - 24;
    const descLabel = node.description
      ? truncateLabel(node.description, descAvailW, 9.5)
      : node.flowchart_type.replace(/_/g, " ");
    const textX = pos.x + nodeW / 2;
    const textY = pos.y + NODE_H / 2;

    return (
      <g
        key={node.id}
        onClick={() => {
          if (hasStatusOverlay && onRuntimeNodeClick) {
            const runtimeId = draftToRuntime[node.id];
            if (runtimeId) onRuntimeNodeClick(runtimeId);
          } else {
            onNodeClick?.(node);
          }
        }}
        onMouseEnter={(e) => {
          if (shiftHeld.current && hoveredNode) return;
          setHoveredNode(node.id);
          const rect = containerRef.current?.getBoundingClientRect();
          if (rect) setMousePos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
        }}
        onMouseLeave={() => { if (!shiftHeld.current) { setHoveredNode(null); setMousePos(null); } }}
        style={{
          cursor: "pointer",
          ...(entrancePhase !== "idle" ? {
            opacity: entrancePhase === "hidden" ? 0 : 1,
            transition: `opacity 300ms ease-out ${i * 120}ms`,
          } : {}),
        }}
      >

        <FlowchartShape
          shape={node.flowchart_shape}
          x={pos.x}
          y={pos.y}
          w={nodeW}
          h={NODE_H}
          color={node.flowchart_color}
          selected={isHovered}
        />

        <text
          x={textX}
          y={textY - 5}
          fill={isHovered ? chrome.nodeTextHover : chrome.nodeText}
          fontSize={fontSize}
          fontWeight={500}
          textAnchor="middle"
          dominantBaseline="middle"
        >
          {displayLabel}
        </text>

        <text
          x={textX}
          y={textY + 11}
          fill={chrome.chromeText}
          fontSize={9.5}
          textAnchor="middle"
          dominantBaseline="middle"
        >
          {descLabel}
        </text>

      </g>
    );
  };

  if (!draft || nodes.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <div className="px-4 pt-3 pb-1.5 flex items-center gap-2">
          <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">Draft</p>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center gap-3">
          {loadingMessage ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground/40" />
              <p className="text-xs text-muted-foreground/50">{loadingMessage}</p>
            </>
          ) : (
            <p className="text-xs text-muted-foreground/60 text-center italic">
              No draft graph yet.
              <br />
              Describe your workflow to get started.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 pt-3 pb-1.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">
            {hasStatusOverlay ? "Flowchart" : "Draft"}
          </p>
          {building ? (
            <span className="text-[9px] font-mono font-medium rounded px-1 py-0.5 leading-none border text-primary/60 border-primary/20 flex items-center gap-1">
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
              building
            </span>
          ) : loadingMessage ? (
            <span className="text-[9px] font-mono font-medium rounded px-1 py-0.5 leading-none border text-amber-500/60 border-amber-500/20 flex items-center gap-1">
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
              updating
            </span>
          ) : (
            <span className={`text-[9px] font-mono font-medium rounded px-1 py-0.5 leading-none border ${hasStatusOverlay ? "text-emerald-500/60 border-emerald-500/20" : "text-amber-500/60 border-amber-500/20"}`}>
              {hasStatusOverlay ? "live" : "planning"}
            </span>
          )}
        </div>
        {onRun && (
          <RunButton runState={runState} disabled={draft.nodes.length === 0} onRun={onRun} onPause={onPause ?? (() => {})} btnRef={runBtnRef} />
        )}
      </div>

      {/* Graph */}
      <div ref={containerRef} className="flex-1 overflow-hidden px-2 pb-2 relative">
        <div
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          className="w-full h-full"
          style={{
            opacity: building || loadingMessage ? 0.3 : 1,
            transition: building || loadingMessage ? "none" : "opacity 300ms ease-out",
            cursor: dragging ? "grabbing" : "grab",
          }}
        >
        <svg
          width="100%"
          viewBox={`0 0 ${Math.max((maxContentRight ?? 0), groupBoxMaxX) + (backEdgeOverflow ?? 0)} ${totalH}`}
          preserveAspectRatio="xMidYMin meet"
          className="select-none"
          style={{
            fontFamily: "'Inter', system-ui, sans-serif",
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "center top",
          }}
        >
          {/* Group areas — dashed boxes behind multi-node runtime groups */}
          {groupAreas.map((group) => {
            const memberIndices = group.draftIds
              .map(id => idxMap[id])
              .filter((idx): idx is number => idx !== undefined);
            if (memberIndices.length === 0) return null;
            const positions = memberIndices.map(i => nodePos(i));
            const pad = 7;
            const minX = Math.min(...positions.map(p => p.x)) - pad;
            const minY = Math.min(...positions.map(p => p.y)) - pad - 14; // extra space for label
            const maxX = Math.max(...positions.map(p => p.x + nodeW)) + pad;
            const maxY = Math.max(...positions.map(p => p.y + NODE_H)) + pad;

            // Runtime status for this group
            const runtimeNode = runtimeNodes?.find(rn => rn.id === group.runtimeId);
            const groupStatus: DraftNodeStatus | undefined = runtimeNode
              ? (runtimeNode.status === "running" || runtimeNode.status === "looping" ? "running"
                : runtimeNode.status === "complete" ? "complete"
                : runtimeNode.status === "error" ? "error" : "pending")
              : undefined;
            const groupStatusColor = groupStatus ? STATUS_COLORS[groupStatus] : "";

            return (
              <g key={`group-${group.runtimeId}`}>
                {/* Status glow around group boundary */}
                {(groupStatus === "running" || groupStatus === "error") && groupStatusColor && (
                  <rect
                    x={minX - 3}
                    y={minY - 3}
                    width={maxX - minX + 6}
                    height={maxY - minY + 6}
                    rx={10}
                    fill="none"
                    stroke={groupStatusColor}
                    strokeWidth={2}
                    opacity={groupStatus === "running" ? 0.8 : 0.6}
                  >
                    {groupStatus === "running" && (
                      <animate attributeName="opacity" values="0.4;0.9;0.4" dur="1.5s" repeatCount="indefinite" />
                    )}
                  </rect>
                )}
                <rect
                  x={minX}
                  y={minY}
                  width={maxX - minX}
                  height={maxY - minY}
                  rx={8}
                  fill={chrome.groupFill}
                  fillOpacity={0.35}
                  stroke={chrome.groupStroke}
                  strokeWidth={1}
                  strokeDasharray="5 3"
                />
                <text
                  x={minX + 8}
                  y={minY + 11}
                  fill={chrome.chromeText}
                  fontSize={9}
                  fontWeight={500}
                >
                  {truncateLabel(group.label, maxX - minX - 16, 9)}
                </text>
                {/* Status dot on group boundary */}
                {hasStatusOverlay && (groupStatus === "running" || groupStatus === "error") && groupStatusColor && (
                  <circle cx={maxX - 6} cy={minY + 6} r={4} fill={groupStatusColor}>
                    {groupStatus === "running" && (
                      <animate attributeName="r" values="3;5;3" dur="1s" repeatCount="indefinite" />
                    )}
                  </circle>
                )}
              </g>
            );
          })}

          {forwardEdges.map((e, i) => renderEdge(e, i))}
          {backEdges.map((e, i) => renderBackEdge(e, i))}
          {nodes.map((n, i) => renderNode(n, i))}

          {/* Legend */}
          <g transform={`translate(${MARGIN_X}, ${svgHeight + 4})`}>
            <text fill={chrome.groupStroke} fontSize={9} fontWeight={600} y={4}>
              LEGEND
            </text>
            {usedTypes.map(([type, meta], i) => (
              <g key={type} transform={`translate(0, ${14 + i * 18})`}>
                <FlowchartShape
                  shape={meta.shape}
                  x={0}
                  y={0}
                  w={16}
                  h={12}
                  color={meta.color}
                  selected={false}
                />
                <text x={22} y={9} fill={chrome.chromeTextDim} fontSize={9.5}>
                  {type.replace(/_/g, " ")}
                </text>
              </g>
            ))}
          </g>
        </svg>
        </div>

        {building && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-primary/60" />
              <p className="text-xs text-muted-foreground/80">Building agent...</p>
            </div>
          </div>
        )}

        {!building && loadingMessage && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground/40" />
              <p className="text-xs text-muted-foreground/50">{loadingMessage}</p>
            </div>
          </div>
        )}

        {/* Zoom controls */}
        <div className="absolute bottom-3 right-3 flex items-center gap-1 bg-card/80 backdrop-blur-sm border border-border/40 rounded-lg p-0.5 shadow-sm">
          <button
            onClick={() => setZoom(z => Math.min(MAX_ZOOM, z * 1.2))}
            className="w-6 h-6 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors text-xs font-bold"
            aria-label="Zoom in"
          >+</button>
          <button
            onClick={resetView}
            className="px-1.5 h-6 flex items-center justify-center rounded text-[10px] font-mono text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            aria-label="Reset zoom"
          >{Math.round(zoom * 100)}%</button>
          <button
            onClick={() => setZoom(z => Math.max(MIN_ZOOM, z * 0.8))}
            className="w-6 h-6 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors text-xs font-bold"
            aria-label="Zoom out"
          >{"\u2212"}</button>
        </div>

        {/* HTML tooltip — rendered outside SVG so it's not clipped */}
        {hoveredNodeData && mousePos && (() => {
          const TOOLTIP_W = 260;
          const OFFSET = 12;
          const rect = containerRef.current?.getBoundingClientRect();
          const cw = rect?.width ?? 0;
          const ch = rect?.height ?? 0;
          const flipX = mousePos.x + OFFSET + TOOLTIP_W > cw;
          const flipY = mousePos.y + 16 + 60 > ch;
          return (
            <Tooltip
              node={hoveredNodeData}
              style={{
                left: flipX ? undefined : mousePos.x + OFFSET,
                right: flipX ? (cw - mousePos.x + OFFSET) : undefined,
                top: flipY ? undefined : mousePos.y + 16,
                bottom: flipY ? (ch - mousePos.y + 16) : undefined,
              }}
            />
          );
        })()}
      </div>
    </div>
  );
}
