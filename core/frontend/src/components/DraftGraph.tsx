import { useEffect, useMemo, useRef, useState } from "react";
import type { DraftGraph as DraftGraphData, DraftNode } from "@/api/types";
import type { GraphNode } from "./AgentGraph";

type DraftNodeStatus = "pending" | "running" | "complete" | "error";

interface DraftGraphProps {
  draft: DraftGraphData;
  onNodeClick?: (node: DraftNode) => void;
  /** Runtime node ID → list of original draft node IDs (post-dissolution mapping). */
  flowchartMap?: Record<string, string[]>;
  /** Current runtime graph nodes with live status (for overlay during execution). */
  runtimeNodes?: GraphNode[];
  /** Called when a draft node is clicked in overlay mode — receives the runtime node ID. */
  onRuntimeNodeClick?: (runtimeNodeId: string) => void;
}

// Layout constants — tuned for a ~500px panel (484px after px-2 padding)
const NODE_H = 52;
const GAP_Y = 48;
const TOP_Y = 28;
const MARGIN_X = 16;
const GAP_X = 16;

function truncateLabel(label: string, availablePx: number, fontSize: number): string {
  const avgCharW = fontSize * 0.58;
  const maxChars = Math.floor(availablePx / avgCharW);
  if (label.length <= maxChars) return label;
  return label.slice(0, Math.max(maxChars - 1, 1)) + "\u2026";
}

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

    case "rounded_rect":
      return <rect x={x} y={y} width={w} height={h} rx={12} {...common} />;

    case "diamond": {
      const cx = x + w / 2;
      const cy = y + h / 2;
      // Keep diamond within bounding box
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

    case "multi_document": {
      const off = 3;
      const d = `M ${x} ${y + 4 + off} Q ${x} ${y + off}, ${x + 8} ${y + off} L ${x + w - 8 - off} ${y + off} Q ${x + w - off} ${y + off}, ${x + w - off} ${y + 4 + off} L ${x + w - off} ${y + h - 8} C ${x + (w - off) * 0.75} ${y + h + 2}, ${x + (w - off) * 0.25} ${y + h - 10}, ${x} ${y + h - 4} Z`;
      return (
        <g>
          <rect x={x + off * 2} y={y} width={w - off * 2} height={h - off} rx={4} fill={fill} stroke={stroke} strokeWidth={1.2} opacity={0.4} />
          <rect x={x + off} y={y + off / 2} width={w - off} height={h - off} rx={4} fill={fill} stroke={stroke} strokeWidth={1.2} opacity={0.6} />
          <path d={d} {...common} />
        </g>
      );
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

    case "manual_input":
      return (
        <polygon
          points={`${x},${y + 10} ${x + w},${y} ${x + w},${y + h} ${x},${y + h}`}
          {...common}
        />
      );

    case "trapezoid": {
      const inset = 12;
      return (
        <polygon
          points={`${x},${y} ${x + w},${y} ${x + w - inset},${y + h} ${x + inset},${y + h}`}
          {...common}
        />
      );
    }

    case "delay": {
      const d = `M ${x} ${y + 4} Q ${x} ${y}, ${x + 4} ${y} L ${x + w * 0.65} ${y} A ${w * 0.35} ${h / 2} 0 0 1 ${x + w * 0.65} ${y + h} L ${x + 4} ${y + h} Q ${x} ${y + h}, ${x} ${y + h - 4} Z`;
      return <path d={d} {...common} />;
    }

    case "display": {
      const d = `M ${x + 16} ${y} L ${x + w * 0.65} ${y} A ${w * 0.35} ${h / 2} 0 0 1 ${x + w * 0.65} ${y + h} L ${x + 16} ${y + h} L ${x} ${y + h / 2} Z`;
      return <path d={d} {...common} />;
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

    case "stored_data": {
      const d = `M ${x + 14} ${y} L ${x + w} ${y} A 10 ${h / 2} 0 0 0 ${x + w} ${y + h} L ${x + 14} ${y + h} A 10 ${h / 2} 0 0 1 ${x + 14} ${y} Z`;
      return <path d={d} {...common} />;
    }

    case "internal_storage":
      return (
        <g>
          <rect x={x} y={y} width={w} height={h} rx={4} {...common} />
          <line x1={x + 10} y1={y} x2={x + 10} y2={y + h} stroke={stroke} strokeWidth={0.8} opacity={0.5} />
          <line x1={x} y1={y + 10} x2={x + w} y2={y + 10} stroke={stroke} strokeWidth={0.8} opacity={0.5} />
        </g>
      );

    case "circle": {
      const r = Math.min(w, h) / 2 - 2;
      return <circle cx={x + w / 2} cy={y + h / 2} r={r} {...common} />;
    }

    case "pentagon":
      return (
        <polygon
          points={`${x},${y} ${x + w},${y} ${x + w},${y + h * 0.6} ${x + w / 2},${y + h} ${x},${y + h * 0.6}`}
          {...common}
        />
      );

    case "triangle_inv":
      return (
        <polygon
          points={`${x},${y} ${x + w},${y} ${x + w / 2},${y + h}`}
          {...common}
        />
      );

    case "triangle":
      return (
        <polygon
          points={`${x + w / 2},${y} ${x + w},${y + h} ${x},${y + h}`}
          {...common}
        />
      );

    case "hourglass":
      return (
        <polygon
          points={`${x},${y} ${x + w},${y} ${x + w / 2},${y + h / 2} ${x + w},${y + h} ${x},${y + h} ${x + w / 2},${y + h / 2}`}
          {...common}
        />
      );

    case "circle_cross": {
      const r = Math.min(w, h) / 2 - 2;
      const cx = x + w / 2;
      const cy = y + h / 2;
      return (
        <g>
          <circle cx={cx} cy={cy} r={r} {...common} />
          <line x1={cx - r * 0.7} y1={cy - r * 0.7} x2={cx + r * 0.7} y2={cy + r * 0.7} stroke={stroke} strokeWidth={1} />
          <line x1={cx + r * 0.7} y1={cy - r * 0.7} x2={cx - r * 0.7} y2={cy + r * 0.7} stroke={stroke} strokeWidth={1} />
        </g>
      );
    }

    case "circle_bar": {
      const r = Math.min(w, h) / 2 - 2;
      const cx = x + w / 2;
      const cy = y + h / 2;
      return (
        <g>
          <circle cx={cx} cy={cy} r={r} {...common} />
          <line x1={cx} y1={cy - r} x2={cx} y2={cy + r} stroke={stroke} strokeWidth={1} />
          <line x1={cx - r} y1={cy} x2={cx + r} y2={cy} stroke={stroke} strokeWidth={1} />
        </g>
      );
    }

    case "flag": {
      const d = `M ${x} ${y} L ${x + w} ${y} L ${x + w - 8} ${y + h / 2} L ${x + w} ${y + h} L ${x} ${y + h} Z`;
      return <path d={d} {...common} />;
    }

    default:
      return <rect x={x} y={y} width={w} height={h} rx={8} {...common} />;
  }
}

/** HTML tooltip positioned over the graph container */
function Tooltip({ node, style }: { node: DraftNode; style: React.CSSProperties }) {
  const lines: string[] = [];
  if (node.description) lines.push(node.description);
  if (node.tools.length > 0) lines.push(`Tools: ${node.tools.join(", ")}`);
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

export default function DraftGraph({ draft, onNodeClick, flowchartMap, runtimeNodes, onRuntimeNodeClick }: DraftGraphProps) {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerW, setContainerW] = useState(484);

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

  const { nodes, edges } = draft;

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

    // Compute node width
    const backEdgeMargin = backEdges.length > 0 ? 30 + backEdges.length * 14 : 8;
    const totalMargin = MARGIN_X * 2 + backEdgeMargin;
    const availW = containerW - totalMargin;
    const nodeW = Math.min(360, Math.floor((availW - (maxCols - 1) * GAP_X) / maxCols));

    // Parent-aware column placement using fractional positions.
    // Instead of snapping to a fixed grid, nodes inherit positions from parents
    // and fan-out children spread around the parent's position.
    const colPos = new Array(nodes.length).fill(0); // fractional column positions
    const maxLayer = Math.max(...layers);

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
      const assigned: number[] = [];
      for (const item of ideals) {
        let pos = item.pos;
        // Clamp to valid range
        pos = Math.max(0, Math.min(maxCols - 1, pos));
        // Push right if overlapping previous
        if (assigned.length > 0) {
          const prev = assigned[assigned.length - 1];
          if (pos < prev + 1) pos = prev + 1;
        }
        assigned.push(pos);
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

    // Convert fractional column positions to pixel X positions
    const colSpacing = nodeW + GAP_X;
    const usedMin = Math.min(...colPos);
    const usedMax = Math.max(...colPos);
    const usedSpan = usedMax - usedMin || 1;
    const totalNodesW = usedSpan * colSpacing;
    const firstColX = MARGIN_X + (availW - totalNodesW) / 2;

    const nodeXPositions = colPos.map((c: number) => firstColX + (c - usedMin) * colSpacing);

    return { layers, nodeW, firstColX, nodeXPositions };
  }, [nodes, forwardEdges, backEdges.length, containerW]);

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <div className="px-4 pt-4 pb-2">
          <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">
            Draft
          </p>
        </div>
        <div className="flex-1 flex items-center justify-center px-4">
          <p className="text-xs text-muted-foreground/60 text-center italic">
            No draft graph yet.
            <br />
            Describe your workflow to get started.
          </p>
        </div>
      </div>
    );
  }

  const { layers, nodeW, nodeXPositions } = layout;

  const nodePos = (i: number) => ({
    x: nodeXPositions[i],
    y: TOP_Y + layers[i] * (NODE_H + GAP_Y),
  });

  const maxLayer = Math.max(...layers);
  const svgHeight = TOP_Y + (maxLayer + 1) * NODE_H + maxLayer * GAP_Y + 16;

  // Compute group areas for multi-node runtime groups
  const groupAreas = useMemo(() => {
    if (!flowchartMap || !runtimeNodes?.length) return [];
    const groups: { runtimeId: string; label: string; draftIds: string[] }[] = [];
    for (const [runtimeId, draftIds] of Object.entries(flowchartMap)) {
      if (draftIds.length < 2) continue;
      const rn = runtimeNodes.find(n => n.id === runtimeId);
      groups.push({ runtimeId, label: rn?.label ?? runtimeId, draftIds });
    }
    return groups;
  }, [flowchartMap, runtimeNodes]);

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

  // Find hovered node for tooltip positioning
  const hoveredNodeData = hoveredNode ? nodes.find(n => n.id === hoveredNode) : null;
  const hoveredIdx = hoveredNode ? idxMap[hoveredNode] : -1;
  const hoveredPos = hoveredIdx >= 0 ? nodePos(hoveredIdx) : null;

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
    const d = `M ${startX} ${y1} C ${startX} ${midY}, ${toCenterX} ${midY}, ${toCenterX} ${y2}`;

    return (
      <g key={`fwd-${i}`}>
        <path d={d} fill="none" stroke="hsl(220,10%,30%)" strokeWidth={1.2} />
        <polygon
          points={`${toCenterX - 3},${y2 - 5} ${toCenterX + 3},${y2 - 5} ${toCenterX},${y2 - 1}`}
          fill="hsl(220,10%,35%)"
        />
        {edge.label && (
          <text
            x={(startX + toCenterX) / 2}
            y={midY - 3}
            fill="hsl(220,10%,45%)"
            fontSize={9}
            fontStyle="italic"
            textAnchor="middle"
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

    return (
      <g key={`back-${i}`}>
        <path d={path} fill="none" stroke="hsl(220,10%,25%)" strokeWidth={1.2} strokeDasharray="4 3" />
        <polygon
          points={`${endX + 5},${endY - 2.5} ${endX + 5},${endY + 2.5} ${endX},${endY}`}
          fill="hsl(220,10%,30%)"
        />
      </g>
    );
  };

  const STATUS_COLORS: Record<DraftNodeStatus, string> = {
    running: "#F59E0B",  // amber
    complete: "#22C55E", // green
    error: "#EF4444",    // red
    pending: "",         // no overlay
  };

  const renderNode = (node: DraftNode, i: number) => {
    const pos = nodePos(i);
    const isHovered = hoveredNode === node.id;
    const status = nodeStatuses[node.id] as DraftNodeStatus | undefined;
    const statusColor = status ? STATUS_COLORS[status] : "";
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
        onMouseEnter={() => setHoveredNode(node.id)}
        onMouseLeave={() => setHoveredNode(null)}
        style={{ cursor: "pointer" }}
      >
        <title>{`${node.name}\n${node.flowchart_type}`}</title>

        {/* Status glow ring (runtime overlay) */}
        {hasStatusOverlay && statusColor && (
          <rect
            x={pos.x - 3}
            y={pos.y - 3}
            width={nodeW + 6}
            height={NODE_H + 6}
            rx={8}
            fill="none"
            stroke={statusColor}
            strokeWidth={2}
            opacity={status === "running" ? 0.8 : 0.6}
          >
            {status === "running" && (
              <animate attributeName="opacity" values="0.4;0.9;0.4" dur="1.5s" repeatCount="indefinite" />
            )}
          </rect>
        )}

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
          fill={isHovered ? "hsl(0,0%,92%)" : "hsl(0,0%,78%)"}
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
          fill="hsl(220,10%,50%)"
          fontSize={9.5}
          textAnchor="middle"
          dominantBaseline="middle"
        >
          {descLabel}
        </text>

        {/* Status dot indicator */}
        {hasStatusOverlay && statusColor && (
          <circle
            cx={pos.x + nodeW - 6}
            cy={pos.y + 6}
            r={4}
            fill={statusColor}
          >
            {status === "running" && (
              <animate attributeName="r" values="3;5;3" dur="1s" repeatCount="indefinite" />
            )}
          </circle>
        )}
      </g>
    );
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 pt-3 pb-1.5 flex items-center gap-2">
        <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">
          {hasStatusOverlay ? "Flowchart" : "Draft"}
        </p>
        <span className={`text-[9px] font-mono font-medium rounded px-1 py-0.5 leading-none border ${hasStatusOverlay ? "text-emerald-500/60 border-emerald-500/20" : "text-amber-500/60 border-amber-500/20"}`}>
          {hasStatusOverlay ? "live" : "planning"}
        </span>
      </div>

      {/* Agent name + goal */}
      <div className="px-4 pb-2.5 border-b border-border/20">
        <p className="text-[11px] font-medium text-foreground/80 truncate">
          {draft.agent_name}
        </p>
        {draft.goal && (
          <p className="text-[10px] text-muted-foreground/60 mt-0.5 line-clamp-2 leading-snug">
            {draft.goal}
          </p>
        )}
      </div>

      {/* Graph */}
      <div ref={containerRef} className="flex-1 overflow-y-auto overflow-x-hidden px-2 pb-2 relative">
        <svg
          width="100%"
          viewBox={`0 0 ${containerW} ${totalH}`}
          preserveAspectRatio="xMidYMin meet"
          className="select-none"
          style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
        >
          {/* Group areas — dashed boxes behind multi-node runtime groups */}
          {groupAreas.map((group) => {
            const memberIndices = group.draftIds
              .map(id => idxMap[id])
              .filter((idx): idx is number => idx !== undefined);
            if (memberIndices.length < 2) return null;
            const positions = memberIndices.map(i => nodePos(i));
            const pad = 10;
            const minX = Math.min(...positions.map(p => p.x)) - pad;
            const minY = Math.min(...positions.map(p => p.y)) - pad - 14; // extra space for label
            const maxX = Math.max(...positions.map(p => p.x + nodeW)) + pad;
            const maxY = Math.max(...positions.map(p => p.y + NODE_H)) + pad;
            return (
              <g key={`group-${group.runtimeId}`}>
                <rect
                  x={minX}
                  y={minY}
                  width={maxX - minX}
                  height={maxY - minY}
                  rx={8}
                  fill="hsl(220,15%,18%)"
                  fillOpacity={0.35}
                  stroke="hsl(220,10%,40%)"
                  strokeWidth={1}
                  strokeDasharray="5 3"
                />
                <text
                  x={minX + 8}
                  y={minY + 11}
                  fill="hsl(220,10%,50%)"
                  fontSize={9}
                  fontWeight={500}
                >
                  {truncateLabel(group.label, maxX - minX - 16, 9)}
                </text>
              </g>
            );
          })}

          {forwardEdges.map((e, i) => renderEdge(e, i))}
          {backEdges.map((e, i) => renderBackEdge(e, i))}
          {nodes.map((n, i) => renderNode(n, i))}

          {/* Legend */}
          <g transform={`translate(${MARGIN_X}, ${svgHeight + 4})`}>
            <text fill="hsl(220,10%,40%)" fontSize={9} fontWeight={600} y={4}>
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
                <text x={22} y={9} fill="hsl(220,10%,55%)" fontSize={9.5}>
                  {type.replace(/_/g, " ")}
                </text>
              </g>
            ))}
          </g>
        </svg>

        {/* HTML tooltip — rendered outside SVG so it's not clipped */}
        {hoveredNodeData && hoveredPos && (
          <Tooltip
            node={hoveredNodeData}
            style={{
              left: 8,
              right: 8,
              // Position below the hovered node, scaled to container width
              top: `calc(${((hoveredPos.y + NODE_H + 4) / totalH) * 100}%)`,
            }}
          />
        )}
      </div>
    </div>
  );
}
