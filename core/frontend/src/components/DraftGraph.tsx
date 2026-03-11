import { memo, useMemo, useState } from "react";
import type { DraftGraph as DraftGraphData, DraftNode } from "@/api/types";

interface DraftGraphProps {
  draft: DraftGraphData;
  onNodeClick?: (node: DraftNode) => void;
}

// Layout constants (matching AgentGraph spacing)
const NODE_W = 180;
const NODE_H = 52;
const GAP_Y = 52;
const TOP_Y = 40;
const MARGIN_LEFT = 20;
const MARGIN_RIGHT = 50;
const SVG_BASE_W = 320;
const GAP_X = 16;

function truncateLabel(label: string, availablePx: number, fontSize: number): string {
  const avgCharW = fontSize * 0.58;
  const maxChars = Math.floor(availablePx / avgCharW);
  if (label.length <= maxChars) return label;
  return label.slice(0, Math.max(maxChars - 1, 1)) + "\u2026";
}

/**
 * Render an ISO 5807 flowchart shape as an SVG element.
 * Returns the shape path/element positioned at (x, y) with given dimensions.
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
  const fill = `${color}18`; // ~10% opacity
  const stroke = selected ? color : `${color}80`;
  const strokeWidth = selected ? 2 : 1.2;
  const common = { fill, stroke, strokeWidth };

  switch (shape) {
    // Terminal / start / end — stadium (rounded rect with full radius)
    case "stadium":
      return <rect x={x} y={y} width={w} height={h} rx={h / 2} {...common} />;

    // Process — standard rectangle
    case "rectangle":
      return <rect x={x} y={y} width={w} height={h} rx={4} {...common} />;

    // Alternate process — rounded rectangle (larger radius)
    case "rounded_rect":
      return <rect x={x} y={y} width={w} height={h} rx={12} {...common} />;

    // Decision — diamond
    case "diamond": {
      const cx = x + w / 2;
      const cy = y + h / 2;
      return (
        <polygon
          points={`${cx},${y - 4} ${x + w + 4},${cy} ${cx},${y + h + 4} ${x - 4},${cy}`}
          {...common}
        />
      );
    }

    // I/O — parallelogram
    case "parallelogram": {
      const skew = 14;
      return (
        <polygon
          points={`${x + skew},${y} ${x + w},${y} ${x + w - skew},${y + h} ${x},${y + h}`}
          {...common}
        />
      );
    }

    // Document — rectangle with wavy bottom
    case "document": {
      const d = `M ${x} ${y + 4} Q ${x} ${y}, ${x + 8} ${y} L ${x + w - 8} ${y} Q ${x + w} ${y}, ${x + w} ${y + 4} L ${x + w} ${y + h - 8} C ${x + w * 0.75} ${y + h + 4}, ${x + w * 0.25} ${y + h - 12}, ${x} ${y + h - 4} Z`;
      return <path d={d} {...common} />;
    }

    // Multi-document
    case "multi_document": {
      const off = 4;
      const d = `M ${x} ${y + 4 + off} Q ${x} ${y + off}, ${x + 8} ${y + off} L ${x + w - 8 - off} ${y + off} Q ${x + w - off} ${y + off}, ${x + w - off} ${y + 4 + off} L ${x + w - off} ${y + h - 8} C ${x + (w - off) * 0.75} ${y + h + 4}, ${x + (w - off) * 0.25} ${y + h - 12}, ${x} ${y + h - 4} Z`;
      return (
        <g>
          <rect x={x + off * 2} y={y} width={w - off * 2} height={h - off} rx={4} fill={fill} stroke={stroke} strokeWidth={strokeWidth} opacity={0.4} />
          <rect x={x + off} y={y + off / 2} width={w - off} height={h - off} rx={4} fill={fill} stroke={stroke} strokeWidth={strokeWidth} opacity={0.6} />
          <path d={d} {...common} />
        </g>
      );
    }

    // Subprocess / subroutine — double-bordered rectangle
    case "subroutine": {
      const inset = 8;
      return (
        <g>
          <rect x={x} y={y} width={w} height={h} rx={4} {...common} />
          <line x1={x + inset} y1={y} x2={x + inset} y2={y + h} stroke={stroke} strokeWidth={strokeWidth} />
          <line x1={x + w - inset} y1={y} x2={x + w - inset} y2={y + h} stroke={stroke} strokeWidth={strokeWidth} />
        </g>
      );
    }

    // Preparation — hexagon
    case "hexagon": {
      const inset = 16;
      return (
        <polygon
          points={`${x + inset},${y} ${x + w - inset},${y} ${x + w},${y + h / 2} ${x + w - inset},${y + h} ${x + inset},${y + h} ${x},${y + h / 2}`}
          {...common}
        />
      );
    }

    // Manual input — slanted top
    case "manual_input":
      return (
        <polygon
          points={`${x},${y + 12} ${x + w},${y} ${x + w},${y + h} ${x},${y + h}`}
          {...common}
        />
      );

    // Manual operation — trapezoid (wider top)
    case "trapezoid": {
      const inset = 14;
      return (
        <polygon
          points={`${x},${y} ${x + w},${y} ${x + w - inset},${y + h} ${x + inset},${y + h}`}
          {...common}
        />
      );
    }

    // Delay — D-shape (flat left, rounded right)
    case "delay": {
      const d = `M ${x} ${y + 4} Q ${x} ${y}, ${x + 4} ${y} L ${x + w * 0.65} ${y} A ${w * 0.35} ${h / 2} 0 0 1 ${x + w * 0.65} ${y + h} L ${x + 4} ${y + h} Q ${x} ${y + h}, ${x} ${y + h - 4} Z`;
      return <path d={d} {...common} />;
    }

    // Display — pointed left, curved right
    case "display": {
      const d = `M ${x + 20} ${y} L ${x + w * 0.65} ${y} A ${w * 0.35} ${h / 2} 0 0 1 ${x + w * 0.65} ${y + h} L ${x + 20} ${y + h} L ${x} ${y + h / 2} Z`;
      return <path d={d} {...common} />;
    }

    // Database — cylinder
    case "cylinder": {
      const ry = 8;
      return (
        <g>
          <path
            d={`M ${x} ${y + ry} L ${x} ${y + h - ry} A ${w / 2} ${ry} 0 0 0 ${x + w} ${y + h - ry} L ${x + w} ${y + ry}`}
            {...common}
          />
          <ellipse cx={x + w / 2} cy={y + ry} rx={w / 2} ry={ry} {...common} />
          <ellipse cx={x + w / 2} cy={y + h - ry} rx={w / 2} ry={ry} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </g>
      );
    }

    // Stored data — partial cylinder (open right)
    case "stored_data": {
      const d = `M ${x + 16} ${y} L ${x + w} ${y} A 10 ${h / 2} 0 0 0 ${x + w} ${y + h} L ${x + 16} ${y + h} A 10 ${h / 2} 0 0 1 ${x + 16} ${y} Z`;
      return <path d={d} {...common} />;
    }

    // Internal storage — rectangle with inner lines
    case "internal_storage":
      return (
        <g>
          <rect x={x} y={y} width={w} height={h} rx={4} {...common} />
          <line x1={x + 12} y1={y} x2={x + 12} y2={y + h} stroke={stroke} strokeWidth={0.8} opacity={0.5} />
          <line x1={x} y1={y + 12} x2={x + w} y2={y + 12} stroke={stroke} strokeWidth={0.8} opacity={0.5} />
        </g>
      );

    // Connector — circle
    case "circle": {
      const r = Math.min(w, h) / 2 - 2;
      return <circle cx={x + w / 2} cy={y + h / 2} r={r} {...common} />;
    }

    // Off-page connector — pentagon (arrow pointing down)
    case "pentagon":
      return (
        <polygon
          points={`${x},${y} ${x + w},${y} ${x + w},${y + h * 0.6} ${x + w / 2},${y + h} ${x},${y + h * 0.6}`}
          {...common}
        />
      );

    // Merge — inverted triangle
    case "triangle_inv":
      return (
        <polygon
          points={`${x},${y} ${x + w},${y} ${x + w / 2},${y + h}`}
          {...common}
        />
      );

    // Extract — triangle pointing up
    case "triangle":
      return (
        <polygon
          points={`${x + w / 2},${y} ${x + w},${y + h} ${x},${y + h}`}
          {...common}
        />
      );

    // Sort — hourglass
    case "hourglass":
      return (
        <polygon
          points={`${x},${y} ${x + w},${y} ${x + w / 2},${y + h / 2} ${x + w},${y + h} ${x},${y + h} ${x + w / 2},${y + h / 2}`}
          {...common}
        />
      );

    // Summing junction — circle with X
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

    // Or — circle with vertical/horizontal bars
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

    // Comment / annotation — flag shape
    case "flag": {
      const d = `M ${x} ${y} L ${x + w} ${y} L ${x + w - 10} ${y + h / 2} L ${x + w} ${y + h} L ${x} ${y + h} Z`;
      return <path d={d} {...common} />;
    }

    // Fallback — rounded rect
    default:
      return <rect x={x} y={y} width={w} height={h} rx={8} {...common} />;
  }
}

// Small info panel shown on hover/click
const DraftNodeTooltip = memo(function DraftNodeTooltip({
  node,
  x,
  y,
}: {
  node: DraftNode;
  x: number;
  y: number;
}) {
  const lines: string[] = [];
  if (node.description) lines.push(node.description);
  if (node.tools.length > 0) lines.push(`Tools: ${node.tools.join(", ")}`);
  if (node.success_criteria) lines.push(`Criteria: ${node.success_criteria}`);

  if (lines.length === 0) return null;

  const lineH = 14;
  const padding = 8;
  const tipW = 220;
  // Wrap long lines
  const wrappedLines = lines.flatMap((l) => {
    const maxChars = 38;
    if (l.length <= maxChars) return [l];
    const parts: string[] = [];
    for (let i = 0; i < l.length; i += maxChars) {
      parts.push(l.slice(i, i + maxChars));
    }
    return parts;
  });
  const tipH = wrappedLines.length * lineH + padding * 2;

  return (
    <g>
      <rect
        x={x}
        y={y}
        width={tipW}
        height={tipH}
        rx={6}
        fill="hsl(220,15%,12%)"
        stroke="hsl(220,10%,25%)"
        strokeWidth={1}
      />
      {wrappedLines.map((line, i) => (
        <text
          key={i}
          x={x + padding}
          y={y + padding + (i + 0.75) * lineH}
          fill="hsl(220,10%,70%)"
          fontSize={10.5}
        >
          {line}
        </text>
      ))}
    </g>
  );
});

export default function DraftGraph({ draft, onNodeClick }: DraftGraphProps) {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const { nodes, edges } = draft;

  // Build adjacency for layout
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
      if (toIdx <= fromIdx) continue; // skip back edges
      const list = grouped.get(fromIdx) || [];
      list.push({ toIdx, label: e.condition !== "on_success" && e.condition !== "always" ? e.condition : e.description || undefined });
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

  // Layer-based layout
  const layout = useMemo(() => {
    if (nodes.length === 0) {
      return { layers: [] as number[], cols: [] as number[], maxCols: 1, nodeW: NODE_W, firstColX: MARGIN_LEFT };
    }

    const parents = new Map<number, number[]>();
    nodes.forEach((_, i) => parents.set(i, []));
    forwardEdges.forEach((e) => parents.get(e.toIdx)!.push(e.fromIdx));

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

    const usableW = SVG_BASE_W - MARGIN_LEFT - MARGIN_RIGHT;
    const nodeW = Math.min(NODE_W, Math.floor((usableW - (maxCols - 1) * GAP_X) / maxCols));
    const colSpacing = nodeW + GAP_X;
    const totalNodesW = maxCols * nodeW + (maxCols - 1) * GAP_X;
    const firstColX = MARGIN_LEFT + (usableW - totalNodesW) / 2;

    const cols = new Array(nodes.length).fill(0);
    layerGroups.forEach((group) => {
      if (group.length === 1) {
        cols[group[0]] = (maxCols - 1) / 2;
      } else {
        const sorted = [...group].sort((a, b) => {
          const aP = parents.get(a) || [];
          const bP = parents.get(b) || [];
          const aAvg = aP.length > 0 ? aP.reduce((s, p) => s + cols[p], 0) / aP.length : 0;
          const bAvg = bP.length > 0 ? bP.reduce((s, p) => s + cols[p], 0) / bP.length : 0;
          return aAvg - bAvg;
        });
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
        <div className="px-5 pt-4 pb-2">
          <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">
            Draft
          </p>
        </div>
        <div className="flex-1 flex items-center justify-center px-5">
          <p className="text-xs text-muted-foreground/60 text-center italic">
            No draft graph yet.
            <br />
            Describe your workflow to get started.
          </p>
        </div>
      </div>
    );
  }

  const { layers, cols, nodeW, colSpacing, firstColX } = layout;

  const nodePos = (i: number) => ({
    x: firstColX + cols[i] * (colSpacing ?? nodeW + GAP_X),
    y: TOP_Y + layers[i] * (NODE_H + GAP_Y),
  });

  const maxLayer = Math.max(...layers);
  const svgHeight = TOP_Y * 2 + (maxLayer + 1) * NODE_H + maxLayer * GAP_Y + 30;
  const backEdgeSpace = backEdges.length > 0 ? MARGIN_RIGHT + backEdges.length * 18 : 20;
  const svgWidth = Math.max(
    SVG_BASE_W,
    firstColX + layout.maxCols * nodeW + (layout.maxCols - 1) * GAP_X + backEdgeSpace,
  );

  const renderEdge = (edge: typeof forwardEdges[number], i: number) => {
    const from = nodePos(edge.fromIdx);
    const to = nodePos(edge.toIdx);
    const fromCenterX = from.x + nodeW / 2;
    const toCenterX = to.x + nodeW / 2;
    const y1 = from.y + NODE_H;
    const y2 = to.y;

    let startX = fromCenterX;
    if (edge.fanCount > 1) {
      const spread = nodeW * 0.5;
      const step = edge.fanCount > 1 ? spread / (edge.fanCount - 1) : 0;
      startX = fromCenterX - spread / 2 + edge.fanIndex * step;
    }

    const midY = (y1 + y2) / 2;
    const d = `M ${startX} ${y1} C ${startX} ${midY}, ${toCenterX} ${midY}, ${toCenterX} ${y2}`;

    return (
      <g key={`fwd-${i}`}>
        <path d={d} fill="none" stroke="hsl(220,10%,30%)" strokeWidth={1.2} />
        <polygon
          points={`${toCenterX - 3.5},${y2 - 5} ${toCenterX + 3.5},${y2 - 5} ${toCenterX},${y2 - 1}`}
          fill="hsl(220,10%,35%)"
        />
        {edge.label && (
          <text
            x={(startX + toCenterX) / 2 + 8}
            y={midY - 2}
            fill="hsl(220,10%,45%)"
            fontSize={9}
            fontStyle="italic"
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
    const rightOffset = 28 + i * 18;
    const startX = from.x + nodeW;
    const startY = from.y + NODE_H / 2;
    const endX = to.x + nodeW;
    const endY = to.y + NODE_H / 2;
    const curveX = rightX + rightOffset;
    const r = 12;

    const path = `M ${startX} ${startY} C ${startX + r} ${startY}, ${curveX} ${startY}, ${curveX} ${startY - r} L ${curveX} ${endY + r} C ${curveX} ${endY}, ${endX + r} ${endY}, ${endX + 6} ${endY}`;

    return (
      <g key={`back-${i}`}>
        <path d={path} fill="none" stroke="hsl(220,10%,25%)" strokeWidth={1.2} strokeDasharray="4 3" />
        <polygon
          points={`${endX + 6},${endY - 3} ${endX + 6},${endY + 3} ${endX},${endY}`}
          fill="hsl(220,10%,30%)"
        />
      </g>
    );
  };

  const renderNode = (node: DraftNode, i: number) => {
    const pos = nodePos(i);
    const isHovered = hoveredNode === node.id;
    const fontSize = 11.5;
    const labelAvailW = nodeW - 20;
    const displayLabel = truncateLabel(node.name, labelAvailW, fontSize);

    // Text placement: centered in the bounding box
    const textX = pos.x + nodeW / 2;
    const textY = pos.y + NODE_H / 2;

    return (
      <g
        key={node.id}
        onClick={() => onNodeClick?.(node)}
        onMouseEnter={() => setHoveredNode(node.id)}
        onMouseLeave={() => setHoveredNode(null)}
        style={{ cursor: onNodeClick ? "pointer" : "default" }}
      >
        <title>{`${node.name}\n${node.flowchart_type}`}</title>

        {/* Shape */}
        <FlowchartShape
          shape={node.flowchart_shape}
          x={pos.x}
          y={pos.y}
          w={nodeW}
          h={NODE_H}
          color={node.flowchart_color}
          selected={isHovered}
        />

        {/* Label */}
        <text
          x={textX}
          y={textY - 4}
          fill={isHovered ? "hsl(0,0%,92%)" : "hsl(0,0%,78%)"}
          fontSize={fontSize}
          fontWeight={500}
          textAnchor="middle"
          dominantBaseline="middle"
        >
          {displayLabel}
        </text>

        {/* Flowchart type sub-label */}
        <text
          x={textX}
          y={textY + 12}
          fill="hsl(220,10%,45%)"
          fontSize={9}
          textAnchor="middle"
          dominantBaseline="middle"
          fontStyle="italic"
        >
          {node.flowchart_type.replace(/_/g, " ")}
        </text>

        {/* Tooltip on hover */}
        {isHovered && (
          <DraftNodeTooltip
            node={node}
            x={pos.x + nodeW + 12}
            y={pos.y}
          />
        )}
      </g>
    );
  };

  // Build legend from unique types used in this draft
  const usedTypes = useMemo(() => {
    const seen = new Map<string, { shape: string; color: string }>();
    for (const n of nodes) {
      if (!seen.has(n.flowchart_type)) {
        seen.set(n.flowchart_type, {
          shape: n.flowchart_shape,
          color: n.flowchart_color,
        });
      }
    }
    return [...seen.entries()];
  }, [nodes]);

  const legendH = usedTypes.length * 20 + 16;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-4 pb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">
            Draft
          </p>
          <span className="text-[10px] font-mono font-medium text-amber-500/60 border border-amber-500/20 rounded px-1 py-0.5 leading-none">
            planning
          </span>
        </div>
      </div>

      {/* Agent name + goal */}
      <div className="px-5 pb-3 border-b border-border/20">
        <p className="text-xs font-medium text-foreground/80 truncate">
          {draft.agent_name}
        </p>
        {draft.goal && (
          <p className="text-[10.5px] text-muted-foreground/60 mt-0.5 line-clamp-2">
            {draft.goal}
          </p>
        )}
      </div>

      {/* Graph */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 pb-3 relative">
        <svg
          width={svgWidth}
          height={svgHeight + legendH}
          viewBox={`0 0 ${svgWidth} ${svgHeight + legendH}`}
          className="select-none"
          style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
        >
          {/* Edges */}
          {forwardEdges.map((e, i) => renderEdge(e, i))}
          {backEdges.map((e, i) => renderBackEdge(e, i))}
          {/* Nodes */}
          {nodes.map((n, i) => renderNode(n, i))}

          {/* Legend */}
          <g transform={`translate(${MARGIN_LEFT}, ${svgHeight + 4})`}>
            <text fill="hsl(220,10%,40%)" fontSize={9} fontWeight={600} y={6}>
              LEGEND
            </text>
            {usedTypes.map(([type, meta], i) => (
              <g key={type} transform={`translate(0, ${16 + i * 20})`}>
                <FlowchartShape
                  shape={meta.shape}
                  x={0}
                  y={0}
                  w={20}
                  h={14}
                  color={meta.color}
                  selected={false}
                />
                <text
                  x={28}
                  y={10}
                  fill="hsl(220,10%,55%)"
                  fontSize={9.5}
                >
                  {type.replace(/_/g, " ")}
                </text>
              </g>
            ))}
          </g>
        </svg>
      </div>
    </div>
  );
}
