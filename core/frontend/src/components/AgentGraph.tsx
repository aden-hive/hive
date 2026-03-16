import { memo, useMemo, useState, useRef, useEffect, useCallback } from "react";
import { Play, Pause, Loader2, CheckCircle2 } from "lucide-react";

export type NodeStatus = "running" | "complete" | "pending" | "error" | "looping";

export type NodeType = "execution" | "trigger";

export interface GraphNode {
  id: string;
  label: string;
  status: NodeStatus;
  nodeType?: NodeType;
  triggerType?: string;
  triggerConfig?: Record<string, unknown>;
  next?: string[];
  backEdges?: string[];
  iterations?: number;
  maxIterations?: number;
  statusLabel?: string;
  edgeLabels?: Record<string, string>;
}

export type RunState = "idle" | "deploying" | "running";

interface AgentGraphProps {
  nodes: GraphNode[];
  title: string;
  onNodeClick?: (node: GraphNode) => void;
  onRun?: () => void;
  onPause?: () => void;
  version?: string;
  runState?: RunState;
  building?: boolean;
  queenPhase?: "planning" | "building" | "staging" | "running";
}

// --- Extracted RunButton so hover state survives parent re-renders ---
export interface RunButtonProps {
  runState: RunState;
  disabled: boolean;
  onRun: () => void;
  onPause: () => void;
  btnRef: React.Ref<HTMLButtonElement>;
}

export const RunButton = memo(function RunButton({ runState, disabled, onRun, onPause, btnRef }: RunButtonProps) {
  const [hovered, setHovered] = useState(false);
  const showPause = runState === "running" && hovered;

  return (
    <button
      ref={btnRef}
      onClick={runState === "running" ? onPause : onRun}
      disabled={runState === "deploying" || disabled}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all duration-200 ${
        showPause
          ? "bg-amber-500/15 text-amber-400 border border-amber-500/40 hover:bg-amber-500/25 active:scale-95 cursor-pointer"
          : runState === "running"
          ? "bg-green-500/15 text-green-400 border border-green-500/30 cursor-pointer"
          : runState === "deploying"
          ? "bg-primary/10 text-primary border border-primary/20 cursor-default"
          : disabled
          ? "bg-muted/30 text-muted-foreground/40 border border-border/20 cursor-not-allowed"
          : "bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 hover:border-primary/40 active:scale-95"
      }`}
    >
      {runState === "deploying" ? (
        <Loader2 className="w-3 h-3 animate-spin" />
      ) : showPause ? (
        <Pause className="w-3 h-3 fill-current" />
      ) : runState === "running" ? (
        <CheckCircle2 className="w-3 h-3" />
      ) : (
        <Play className="w-3 h-3 fill-current" />
      )}
      {runState === "deploying" ? "Deploying\u2026" : showPause ? "Pause" : runState === "running" ? "Running" : "Run"}
    </button>
  );
});

const NODE_W_MAX = 180;
const NODE_H = 44;
const GAP_Y = 48;
const TOP_Y = 30;
const MARGIN_LEFT = 20;
const MARGIN_RIGHT = 50; // space for back-edge arcs
const SVG_BASE_W = 320;
const GAP_X = 12;

// Read a CSS custom property value (space-separated HSL components)
function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

type StatusColorSet = Record<NodeStatus, { dot: string; bg: string; border: string; glow: string }>;
type TriggerColorSet = { bg: string; border: string; text: string; icon: string };

function buildStatusColors(): StatusColorSet {
  const running = cssVar("--node-running") || "45 95% 58%";
  const looping = cssVar("--node-looping") || "38 90% 55%";
  const complete = cssVar("--node-complete") || "43 70% 45%";
  const pending = cssVar("--node-pending") || "35 15% 28%";
  const pendingBg = cssVar("--node-pending-bg") || "35 10% 12%";
  const pendingBorder = cssVar("--node-pending-border") || "35 10% 20%";
  const error = cssVar("--node-error") || "0 65% 55%";

  return {
    running: {
      dot: `hsl(${running})`,
      bg: `hsl(${running} / 0.08)`,
      border: `hsl(${running} / 0.5)`,
      glow: `hsl(${running} / 0.15)`,
    },
    looping: {
      dot: `hsl(${looping})`,
      bg: `hsl(${looping} / 0.08)`,
      border: `hsl(${looping} / 0.5)`,
      glow: `hsl(${looping} / 0.15)`,
    },
    complete: {
      dot: `hsl(${complete})`,
      bg: `hsl(${complete} / 0.05)`,
      border: `hsl(${complete} / 0.25)`,
      glow: "none",
    },
    pending: {
      dot: `hsl(${pending})`,
      bg: `hsl(${pendingBg})`,
      border: `hsl(${pendingBorder})`,
      glow: "none",
    },
    error: {
      dot: `hsl(${error})`,
      bg: `hsl(${error} / 0.06)`,
      border: `hsl(${error} / 0.3)`,
      glow: `hsl(${error} / 0.1)`,
    },
  };
}

function buildTriggerColors(): TriggerColorSet {
  const bg = cssVar("--trigger-bg") || "210 25% 14%";
  const border = cssVar("--trigger-border") || "210 30% 30%";
  const text = cssVar("--trigger-text") || "210 30% 65%";
  const icon = cssVar("--trigger-icon") || "210 40% 55%";
  return {
    bg: `hsl(${bg})`,
    border: `hsl(${border})`,
    text: `hsl(${text})`,
    icon: `hsl(${icon})`,
  };
}

/** Hook that reads node/trigger colors from CSS vars and updates on theme changes. */
function useThemeColors() {
  const [statusColors, setStatusColors] = useState<StatusColorSet>(buildStatusColors);
  const [triggerColors, setTriggerColors] = useState<TriggerColorSet>(buildTriggerColors);

  useEffect(() => {
    const rebuild = () => {
      setStatusColors(buildStatusColors());
      setTriggerColors(buildTriggerColors());
    };
    const obs = new MutationObserver(rebuild);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style"] });
    return () => obs.disconnect();
  }, []);

  return { statusColors, triggerColors };
}

// Active trigger — brighter, more saturated blue
const activeTriggerColors = {
  bg: "hsl(210,30%,18%)",
  border: "hsl(210,50%,50%)",
  text: "hsl(210,40%,75%)",
  icon: "hsl(210,60%,65%)",
};

const triggerIcons: Record<string, string> = {
  webhook: "\u26A1",  // lightning bolt
  timer: "\u23F1",    // stopwatch
  api: "\u2192",      // right arrow
  event: "\u223F",    // sine wave
};

/** Truncate label to fit within `availablePx` at the given fontSize. */
function truncateLabel(label: string, availablePx: number, fontSize: number): string {
  const avgCharW = fontSize * 0.58;
  const maxChars = Math.floor(availablePx / avgCharW);
  if (label.length <= maxChars) return label;
  return label.slice(0, Math.max(maxChars - 1, 1)) + "\u2026";
}

// ─── Pan & Zoom wrapper ───
function PanZoomSvg({ svgW, svgH, className, children }: { svgW: number; svgH: number; className?: string; children: React.ReactNode }) {
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

  return (
    <div className="flex-1 relative overflow-hidden px-1 pb-5">
      <div
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        className="w-full h-full"
        style={{ cursor: dragging ? "grabbing" : "grab" }}
      >
        <svg
          width="100%"
          viewBox={`0 0 ${svgW} ${svgH}`}
          preserveAspectRatio="xMidYMin meet"
          className={`select-none ${className || ""}`}
          style={{
            fontFamily: "'Inter', system-ui, sans-serif",
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "center top",
          }}
        >
          {children}
        </svg>
      </div>

      {/* Zoom controls */}
      <div className="absolute bottom-7 right-3 flex items-center gap-1 bg-card/80 backdrop-blur-sm border border-border/40 rounded-lg p-0.5 shadow-sm">
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
    </div>
  );
}

export default function AgentGraph({ nodes, title: _title, onNodeClick, onRun, onPause, version, runState: externalRunState, building, queenPhase }: AgentGraphProps) {
  const [localRunState, setLocalRunState] = useState<RunState>("idle");
  const runState = externalRunState ?? localRunState;
  const runBtnRef = useRef<HTMLButtonElement>(null);
  const { statusColors, triggerColors } = useThemeColors();

  const handleRun = () => {
    if (runState !== "idle") return;
    if (onRun) {
      onRun();
    } else {
      setLocalRunState("deploying");
      setTimeout(() => setLocalRunState("running"), 1800);
      setTimeout(() => setLocalRunState("idle"), 5000);
    }
  };

  const idxMap = useMemo(() => Object.fromEntries(nodes.map((n, i) => [n.id, i])), [nodes]);

  const backEdges = useMemo(() => {
    const edges: { fromIdx: number; toIdx: number }[] = [];
    nodes.forEach((n, i) => {
      (n.next || []).forEach((toId) => {
        const toIdx = idxMap[toId];
        if (toIdx !== undefined && toIdx <= i) edges.push({ fromIdx: i, toIdx });
      });
      (n.backEdges || []).forEach((toId) => {
        const toIdx = idxMap[toId];
        if (toIdx !== undefined) edges.push({ fromIdx: i, toIdx });
      });
    });
    return edges;
  }, [nodes, idxMap]);

  const forwardEdges = useMemo(() => {
    const edges: { fromIdx: number; toIdx: number; fanCount: number; fanIndex: number; label?: string }[] = [];
    nodes.forEach((n, i) => {
      const targets = (n.next || [])
        .map((toId) => ({ toId, toIdx: idxMap[toId] }))
        .filter((t): t is { toId: string; toIdx: number } => t.toIdx !== undefined && t.toIdx > i);
      targets.forEach(({ toId, toIdx }, fi) => {
        edges.push({
          fromIdx: i,
          toIdx,
          fanCount: targets.length,
          fanIndex: fi,
          label: n.edgeLabels?.[toId],
        });
      });
    });
    return edges;
  }, [nodes, idxMap]);

  // --- Layer-based layout computation ---
  const layout = useMemo(() => {
    if (nodes.length === 0) {
      return { layers: [] as number[], cols: [] as number[], maxCols: 1, nodeW: NODE_W_MAX, colSpacing: 0, firstColX: MARGIN_LEFT };
    }

    // 1. Build reverse adjacency from forward edges (who are the parents of each node)
    const parents = new Map<number, number[]>();
    nodes.forEach((_, i) => parents.set(i, []));
    forwardEdges.forEach((e) => {
      parents.get(e.toIdx)!.push(e.fromIdx);
    });

    // 2. Assign layers via longest-path from entry
    const layers = new Array(nodes.length).fill(0);
    for (let i = 0; i < nodes.length; i++) {
      const pars = parents.get(i) || [];
      if (pars.length > 0) {
        layers[i] = Math.max(...pars.map((p) => layers[p])) + 1;
      }
    }

    // 3. Group nodes by layer
    const layerGroups = new Map<number, number[]>();
    layers.forEach((l, i) => {
      const group = layerGroups.get(l) || [];
      group.push(i);
      layerGroups.set(l, group);
    });

    // 4. Compute max columns and dynamic node width
    let maxCols = 1;
    layerGroups.forEach((group) => {
      maxCols = Math.max(maxCols, group.length);
    });

    const usableW = SVG_BASE_W - MARGIN_LEFT - MARGIN_RIGHT;
    const nodeW = Math.min(NODE_W_MAX, Math.floor((usableW - (maxCols - 1) * GAP_X) / maxCols));
    const colSpacing = nodeW + GAP_X;
    const totalNodesW = maxCols * nodeW + (maxCols - 1) * GAP_X;
    const firstColX = MARGIN_LEFT + (usableW - totalNodesW) / 2;

    // 5. Assign columns within each layer (centered, ordered by parent column)
    const cols = new Array(nodes.length).fill(0);
    layerGroups.forEach((group) => {
      if (group.length === 1) {
        // Center single node: place at middle column
        cols[group[0]] = (maxCols - 1) / 2;
      } else {
        // Sort group by average parent column to reduce crossings
        const sorted = [...group].sort((a, b) => {
          const aParents = parents.get(a) || [];
          const bParents = parents.get(b) || [];
          const aAvg = aParents.length > 0 ? aParents.reduce((s, p) => s + cols[p], 0) / aParents.length : 0;
          const bAvg = bParents.length > 0 ? bParents.reduce((s, p) => s + cols[p], 0) / bParents.length : 0;
          return aAvg - bAvg;
        });
        // Spread evenly, centered within maxCols
        const offset = (maxCols - group.length) / 2;
        sorted.forEach((nodeIdx, i) => {
          cols[nodeIdx] = offset + i;
        });
      }
    });

    return { layers, cols, maxCols, nodeW, colSpacing, firstColX };
  }, [nodes, forwardEdges]);

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <div className="px-5 pt-4 pb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">Pipeline</p>
            {version && (
              <span className="text-[10px] font-mono font-medium text-muted-foreground/60 border border-border/30 rounded px-1 py-0.5 leading-none">
                {version}
              </span>
            )}
          </div>
          <RunButton runState={runState} disabled={nodes.length === 0 || queenPhase === "building" || queenPhase === "planning"} onRun={handleRun} onPause={onPause ?? (() => {})} btnRef={runBtnRef} />
        </div>
        <div className="flex-1 flex items-center justify-center px-5">
          {building ? (
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-primary/60" />
              <p className="text-xs text-muted-foreground/80 text-center">Building agent...</p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground/60 text-center italic">No pipeline configured yet.<br/>Chat with the Queen to get started.</p>
          )}
        </div>
      </div>
    );
  }

  const { layers, cols, nodeW, colSpacing, firstColX } = layout;

  const nodePos = (i: number) => ({
    x: firstColX + cols[i] * colSpacing,
    y: TOP_Y + layers[i] * (NODE_H + GAP_Y),
  });

  const maxLayer = nodes.length > 0 ? Math.max(...layers) : 0;
  const svgHeight = TOP_Y * 2 + (maxLayer + 1) * NODE_H + maxLayer * GAP_Y + 10;
  const backEdgeSpace = backEdges.length > 0 ? MARGIN_RIGHT + backEdges.length * 18 : 20;
  const svgWidth = Math.max(SVG_BASE_W, firstColX + layout.maxCols * nodeW + (layout.maxCols - 1) * GAP_X + backEdgeSpace);

  // Check if a skip-level forward edge would collide with intermediate nodes
  const hasCollision = (fromLayer: number, toLayer: number, fromX: number, toX: number): boolean => {
    const minX = Math.min(fromX, toX);
    const maxX = Math.max(fromX, toX) + nodeW;
    for (let i = 0; i < nodes.length; i++) {
      const l = layers[i];
      if (l > fromLayer && l < toLayer) {
        const nx = firstColX + cols[i] * colSpacing;
        // Check horizontal overlap
        if (nx < maxX && nx + nodeW > minX) return true;
      }
    }
    return false;
  };

  const renderForwardEdge = (edge: { fromIdx: number; toIdx: number; fanCount: number; fanIndex: number; label?: string }, i: number) => {
    const from = nodePos(edge.fromIdx);
    const to = nodePos(edge.toIdx);
    const fromCenterX = from.x + nodeW / 2;
    const toCenterX = to.x + nodeW / 2;
    const y1 = from.y + NODE_H;
    const y2 = to.y;

    // Fan-out: spread exit points across the source node's bottom
    let startX = fromCenterX;
    if (edge.fanCount > 1) {
      const spread = nodeW * 0.5;
      const step = edge.fanCount > 1 ? spread / (edge.fanCount - 1) : 0;
      startX = fromCenterX - spread / 2 + edge.fanIndex * step;
    }

    const midY = (y1 + y2) / 2;
    const fromLayer = layers[edge.fromIdx];
    const toLayer = layers[edge.toIdx];
    const skipsLayers = toLayer - fromLayer > 1;

    let d: string;
    if (skipsLayers && hasCollision(fromLayer, toLayer, from.x, to.x)) {
      // Route around intermediate nodes: orthogonal detour to the left
      const detourX = Math.min(from.x, to.x) - nodeW * 0.4;
      d = `M ${startX} ${y1} L ${startX} ${midY} L ${detourX} ${midY} L ${detourX} ${y2 - 10} L ${toCenterX} ${y2 - 10} L ${toCenterX} ${y2}`;
    } else if (Math.abs(startX - toCenterX) < 2) {
      // Straight vertical line when aligned
      d = `M ${startX} ${y1} L ${toCenterX} ${y2}`;
    } else {
      // Orthogonal: down, across, down
      d = `M ${startX} ${y1} L ${startX} ${midY} L ${toCenterX} ${midY} L ${toCenterX} ${y2}`;
    }

    const fromNode = nodes[edge.fromIdx];
    const isActive = fromNode.status === "complete" || fromNode.status === "running" || fromNode.status === "looping";
    const strokeColor = isActive ? statusColors.complete.border : statusColors.pending.border;
    const arrowColor = isActive ? statusColors.complete.dot : statusColors.pending.border;

    return (
      <g key={`fwd-${i}`}>
        <path d={d} fill="none" stroke={strokeColor} strokeWidth={1.5} />
        <polygon
          points={`${toCenterX - 4},${y2 - 6} ${toCenterX + 4},${y2 - 6} ${toCenterX},${y2 - 1}`}
          fill={arrowColor}
        />
        {edge.label && (
          <text
            x={(startX + toCenterX) / 2 + 8}
            y={midY - 2}
            fill={statusColors.pending.dot}
            fontSize={9}
            fontStyle="italic"
          >
            {edge.label}
          </text>
        )}
      </g>
    );
  };

  const renderBackEdge = (edge: { fromIdx: number; toIdx: number }, i: number) => {
    const from = nodePos(edge.fromIdx);
    const to = nodePos(edge.toIdx);

    const rightX = Math.max(from.x, to.x) + nodeW;
    const rightOffset = 28 + i * 18;
    const startX = from.x + nodeW;
    const startY = from.y + NODE_H / 2;
    const endX = to.x + nodeW;
    const endY = to.y + NODE_H / 2;
    const curveX = rightX + rightOffset;
    const r = 12;

    const fromNode = nodes[edge.fromIdx];
    const isActive = fromNode.status === "complete" || fromNode.status === "running" || fromNode.status === "looping";
    const color = isActive ? statusColors.looping.border : statusColors.pending.border;

    // Bezier curve with rounded corners (kept as curves for back edges)
    const path = `M ${startX} ${startY} C ${startX + r} ${startY}, ${curveX} ${startY}, ${curveX} ${startY - r} L ${curveX} ${endY + r} C ${curveX} ${endY}, ${endX + r} ${endY}, ${endX + 6} ${endY}`;

    return (
      <g key={`back-${i}`}>
        <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray="4 3" />
        <polygon
          points={`${endX + 6},${endY - 3} ${endX + 6},${endY + 3} ${endX},${endY}`}
          fill={isActive ? statusColors.looping.dot : statusColors.pending.border}
        />
      </g>
    );
  };

  const renderTriggerNode = (node: GraphNode, i: number) => {
    const pos = nodePos(i);
    const icon = triggerIcons[node.triggerType || ""] || "\u26A1";
    const triggerFontSize = nodeW < 140 ? 10.5 : 11.5;
    const triggerAvailW = nodeW - 38;
    const triggerDisplayLabel = truncateLabel(node.label, triggerAvailW, triggerFontSize);
    const nextFireIn = node.triggerConfig?.next_fire_in as number | undefined;
    const isActive = node.status === "running" || node.status === "complete";
    const colors = isActive ? activeTriggerColors : triggerColors;

    // Format countdown for display below node
    let countdownLabel: string | null = null;
    if (isActive && nextFireIn != null && nextFireIn > 0) {
      const h = Math.floor(nextFireIn / 3600);
      const m = Math.floor((nextFireIn % 3600) / 60);
      const s = Math.floor(nextFireIn % 60);
      countdownLabel = h > 0
        ? `next in ${h}h ${String(m).padStart(2, "0")}m`
        : `next in ${m}m ${String(s).padStart(2, "0")}s`;
    }

    // Status label below countdown
    const statusLabel = isActive ? "active" : "inactive";
    const statusColor = isActive ? "hsl(140,40%,50%)" : "hsl(210,20%,40%)";

    return (
      <g key={node.id} onClick={() => onNodeClick?.(node)} style={{ cursor: onNodeClick ? "pointer" : "default" }}>
        <title>{node.label}</title>
        {/* Pill-shaped background — solid border when active, dashed when inactive */}
        <rect
          x={pos.x} y={pos.y}
          width={nodeW} height={NODE_H}
          rx={NODE_H / 2}
          fill={colors.bg}
          stroke={colors.border}
          strokeWidth={isActive ? 1.5 : 1}
          strokeDasharray={isActive ? undefined : "4 2"}
        />

        {/* Trigger type icon */}
        <text
          x={pos.x + 18} y={pos.y + NODE_H / 2}
          fill={colors.icon} fontSize={13}
          textAnchor="middle" dominantBaseline="middle"
        >
          {icon}
        </text>

        {/* Label */}
        <text
          x={pos.x + 32} y={pos.y + NODE_H / 2}
          fill={colors.text}
          fontSize={triggerFontSize}
          fontWeight={500}
          dominantBaseline="middle"
          letterSpacing="0.01em"
        >
          {triggerDisplayLabel}
        </text>

        {/* Countdown label below node */}
        {countdownLabel && (
          <text
            x={pos.x + nodeW / 2} y={pos.y + NODE_H + 13}
            fill={triggerColors.text} fontSize={9.5}
            textAnchor="middle" fontStyle="italic" opacity={0.7}
          >
            {countdownLabel}
          </text>
        )}

        {/* Status label */}
        <text
          x={pos.x + nodeW / 2} y={pos.y + NODE_H + (countdownLabel ? 25 : 13)}
          fill={statusColor} fontSize={9}
          textAnchor="middle" opacity={0.8}
        >
          {statusLabel}
        </text>
      </g>
    );
  };

  const renderNode = (node: GraphNode, i: number) => {
    if (node.nodeType === "trigger") return renderTriggerNode(node, i);

    const pos = nodePos(i);
    const isActive = node.status === "running" || node.status === "looping";
    const isDone = node.status === "complete";
    const colors = statusColors[node.status];

    const fontSize = nodeW < 140 ? 10.5 : 12.5;
    const labelAvailW = nodeW - 38;
    const displayLabel = truncateLabel(node.label, labelAvailW, fontSize);

    return (
      <g key={node.id} onClick={() => onNodeClick?.(node)} style={{ cursor: onNodeClick ? "pointer" : "default" }}>
        <title>{node.label}</title>
        {/* Ambient glow for active nodes */}
        {isActive && (
          <>
            <rect
              x={pos.x - 4} y={pos.y - 4}
              width={nodeW + 8} height={NODE_H + 8}
              rx={16} fill={colors.glow}
            />
            <rect
              x={pos.x - 2} y={pos.y - 2}
              width={nodeW + 4} height={NODE_H + 4}
              rx={14} fill="none" stroke={colors.dot} strokeWidth={1} opacity={0.25}
              style={{ animation: "pulse-ring 2.5s ease-out infinite" }}
            />
          </>
        )}

        {/* Node background */}
        <rect
          x={pos.x} y={pos.y}
          width={nodeW} height={NODE_H}
          rx={12}
          fill={colors.bg}
          stroke={colors.border}
          strokeWidth={isActive ? 1.5 : 1}
        />

        {/* Status dot */}
        <circle cx={pos.x + 18} cy={pos.y + NODE_H / 2} r={4.5} fill={colors.dot} />
        {isActive && (
          <circle cx={pos.x + 18} cy={pos.y + NODE_H / 2} r={7} fill="none" stroke={colors.dot} strokeWidth={1} opacity={0.3}>
            <animate attributeName="r" values="7;11;7" dur="2s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.3;0;0.3" dur="2s" repeatCount="indefinite" />
          </circle>
        )}

        {/* Check mark for complete */}
        {isDone && (
          <text
            x={pos.x + 18} y={pos.y + NODE_H / 2 + 1}
            fill={colors.dot} fontSize={8} fontWeight={700}
            textAnchor="middle" dominantBaseline="middle"
          >
            &#x2713;
          </text>
        )}

        {/* Label -- truncated with ellipsis for narrow nodes */}
        <text
          x={pos.x + 32} y={pos.y + NODE_H / 2}
          fill={isActive ? statusColors.running.dot : isDone ? statusColors.complete.dot : statusColors.pending.dot}
          fontSize={fontSize}
          fontWeight={isActive ? 600 : isDone ? 500 : 400}
          dominantBaseline="middle"
          letterSpacing="0.01em"
        >
          {displayLabel}
        </text>

        {/* Status label for active nodes */}
        {node.statusLabel && isActive && (
          <text
            x={pos.x + nodeW + 10} y={pos.y + NODE_H / 2}
            fill={statusColors.running.dot} fontSize={10.5} fontStyle="italic"
            dominantBaseline="middle" opacity={0.8}
          >
            {node.statusLabel}
          </text>
        )}

        {/* Iteration badge */}
        {node.iterations !== undefined && node.iterations > 0 && (
          <g>
            <rect
              x={pos.x + nodeW - 36} y={pos.y + NODE_H / 2 - 8}
              width={26} height={16} rx={8}
              fill={colors.dot} opacity={0.15}
            />
            <text
              x={pos.x + nodeW - 23} y={pos.y + NODE_H / 2}
              fill={colors.dot} fontSize={9} fontWeight={600}
              textAnchor="middle" dominantBaseline="middle" opacity={0.8}
            >
              {node.iterations}{node.maxIterations ? `/${node.maxIterations}` : "\u00d7"}
            </text>
          </g>
        )}
      </g>
    );
  };

  return (
    <div className="flex flex-col h-full">
      {/* Compact sub-label */}
      <div className="px-5 pt-4 pb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">Pipeline</p>
          {version && (
            <span className="text-[10px] font-mono font-medium text-muted-foreground/60 border border-border/30 rounded px-1 py-0.5 leading-none">
              {version}
            </span>
          )}
        </div>
        <RunButton runState={runState} disabled={nodes.length === 0} onRun={handleRun} onPause={onPause ?? (() => {})} btnRef={runBtnRef} />
      </div>

      {/* Graph */}
      <PanZoomSvg svgW={svgWidth} svgH={svgHeight} className={building ? "opacity-30" : ""}>
        {forwardEdges.map((e, i) => renderForwardEdge(e, i))}
        {backEdges.map((e, i) => renderBackEdge(e, i))}
        {nodes.map((n, i) => renderNode(n, i))}
      </PanZoomSvg>
      {building && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="w-6 h-6 animate-spin text-primary/60" />
            <p className="text-xs text-muted-foreground/80">Rebuilding agent...</p>
          </div>
        </div>
      )}
    </div>
  );
}
