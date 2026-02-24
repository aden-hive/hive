/**
 * ExecutionSubGraph — renders a DAG of workflow steps extracted from a node's
 * system prompt. Replaces the hardcoded SubGraph SVG for real (loaded) agents.
 *
 * Layout algorithm: longest-path layer assignment (same approach as AgentGraph).
 * Rendering: shared SVG primitives from sgPrimitives.ts, matching SubGraph's
 * visual style for consistency.
 */

import { useMemo } from "react";
import type { SubgraphStep } from "../api/types";
import type { NodeStatus } from "./AgentGraph";
import { sgPort, computeEdgePath, computeArrowhead } from "./sgPrimitives";
import type { PortSide, Rect } from "./sgPrimitives";

// Layout constants — smaller than AgentGraph (this is an intra-node detail view)
const NODE_W = 130;
const NODE_H = 34;
const TOOL_W = 118;
const TOOL_H = 28;
const GAP_X = 16;
const GAP_Y = 60;
const TOP_Y = 10;
const SVG_W = 440;
const MARGIN_X = 16;

const statusColors: Record<NodeStatus, string> = {
  running: "hsl(45,95%,58%)",
  looping: "hsl(38,90%,55%)",
  complete: "hsl(43,70%,45%)",
  pending: "hsl(220,15%,45%)",
  error: "hsl(0,65%,55%)",
};

type StepType = SubgraphStep["type"];

interface LayoutNode {
  step: SubgraphStep;
  layer: number;
  col: number;
  pos: Rect;
}

interface LayoutEdge {
  fromId: string;
  toId: string;
  fromPort: PortSide;
  toPort: PortSide;
}

function computeLayout(steps: SubgraphStep[]): {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  svgH: number;
} {
  if (steps.length === 0) return { nodes: [], edges: [], svgH: 0 };

  const idxMap = new Map<string, number>();
  steps.forEach((s, i) => idxMap.set(s.id, i));

  // Build parent adjacency from depends_on
  const parents = new Map<number, number[]>();
  steps.forEach((_, i) => parents.set(i, []));
  steps.forEach((s, i) => {
    for (const dep of s.depends_on) {
      const pi = idxMap.get(dep);
      if (pi !== undefined) {
        parents.get(i)!.push(pi);
      }
    }
  });

  // Longest-path layer assignment
  const layers = new Array(steps.length).fill(0);
  for (let i = 0; i < steps.length; i++) {
    const pars = parents.get(i) || [];
    if (pars.length > 0) {
      layers[i] = Math.max(...pars.map((p) => layers[p])) + 1;
    }
  }

  // Group by layer
  const layerGroups = new Map<number, number[]>();
  layers.forEach((l, i) => {
    const group = layerGroups.get(l) || [];
    group.push(i);
    layerGroups.set(l, group);
  });

  // Column assignment (centered, ordered by average parent column)
  let maxCols = 1;
  layerGroups.forEach((group) => {
    maxCols = Math.max(maxCols, group.length);
  });

  const cols = new Array(steps.length).fill(0);
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
      sorted.forEach((nodeIdx, j) => {
        cols[nodeIdx] = offset + j;
      });
    }
  });

  // Compute positions
  const usableW = SVG_W - MARGIN_X * 2;
  const colSpacing = maxCols > 1 ? Math.min(NODE_W + GAP_X, usableW / maxCols) : 0;
  const totalW = maxCols > 1 ? (maxCols - 1) * colSpacing + NODE_W : NODE_W;
  const firstColX = MARGIN_X + (usableW - totalW) / 2;

  const layoutNodes: LayoutNode[] = steps.map((step, i) => {
    const isTool = step.type === "action" && step.tool !== null;
    const w = isTool ? TOOL_W : NODE_W;
    const h = isTool ? TOOL_H : NODE_H;
    const x = firstColX + cols[i] * colSpacing + (NODE_W - w) / 2;
    const y = TOP_Y + layers[i] * (NODE_H + GAP_Y) + (NODE_H - h) / 2;
    return { step, layer: layers[i], col: cols[i], pos: { x, y, w, h } };
  });

  // Build edges from depends_on
  const layoutEdges: LayoutEdge[] = [];
  steps.forEach((step, i) => {
    for (const dep of step.depends_on) {
      const pi = idxMap.get(dep);
      if (pi === undefined) continue;
      const fromLayer = layers[pi];
      const toLayer = layers[i];
      const fromCol = cols[pi];
      const toCol = cols[i];

      let fromPort: PortSide = "bottom";
      let toPort: PortSide = "top";

      // Same layer = horizontal edge
      if (fromLayer === toLayer) {
        fromPort = fromCol < toCol ? "right" : "left";
        toPort = fromCol < toCol ? "left" : "right";
      }
      // Back edge (loop)
      if (toLayer <= fromLayer) {
        fromPort = "left";
        toPort = "left";
      }

      layoutEdges.push({ fromId: dep, toId: step.id, fromPort, toPort });
    }
  });

  const maxLayer = Math.max(...layers);
  const svgH = TOP_Y + (maxLayer + 1) * (NODE_H + GAP_Y) + 10;

  return { nodes: layoutNodes, edges: layoutEdges, svgH };
}

interface ExecutionSubGraphProps {
  steps: SubgraphStep[];
  status: NodeStatus;
}

export default function ExecutionSubGraph({ steps, status }: ExecutionSubGraphProps) {
  const color = statusColors[status];
  const { nodes, edges, svgH } = useMemo(() => computeLayout(steps), [steps]);

  const posMap = useMemo(() => {
    const m: Record<string, Rect> = {};
    nodes.forEach((n) => { m[n.step.id] = n.pos; });
    return m;
  }, [nodes]);

  if (nodes.length === 0) {
    return (
      <div className="flex items-center justify-center py-8">
        <p className="text-xs text-muted-foreground/60 italic">No workflow steps available</p>
      </div>
    );
  }

  const renderEdge = (edge: LayoutEdge, i: number) => {
    const fp = posMap[edge.fromId];
    const tp = posMap[edge.toId];
    if (!fp || !tp) return null;

    const [fx, fy] = sgPort(fp, edge.fromPort);
    const [tx, ty] = sgPort(tp, edge.toPort);

    const isBackEdge = edge.fromPort === "left" && edge.toPort === "left";
    const stroke = isBackEdge ? "hsl(35,15%,25%)" : "hsl(35,10%,22%)";

    const d = computeEdgePath(edge.fromPort, edge.toPort, fx, fy, tx, ty);
    const arrowPoints = computeArrowhead(edge.toPort, tx, ty);

    return (
      <g key={`e-${i}`}>
        <path
          d={d}
          fill="none"
          stroke={stroke}
          strokeWidth={1.5}
          strokeDasharray={isBackEdge ? "4 3" : "none"}
        />
        <polygon points={arrowPoints} fill="hsl(35,10%,26%)" />
      </g>
    );
  };

  const renderNode = (ln: LayoutNode) => {
    const { step, pos } = ln;
    const isDecision = step.type === "decision" || step.type === "loop";
    const isOutput = step.type === "output";
    const hasTool = step.tool !== null;

    // Visual styling matching SubGraph conventions
    const bgFill = hasTool
      ? "hsl(220,15%,10%)"
      : isOutput
        ? "hsl(35,15%,12%)"
        : "hsl(35,10%,11%)";
    const borderStroke = hasTool
      ? "hsl(220,25%,28%)"
      : isDecision
        ? "hsl(35,15%,26%)"
        : isOutput
          ? `${color}30`
          : "hsl(35,10%,19%)";
    const textFill = hasTool
      ? "hsl(220,25%,60%)"
      : "hsl(35,10%,42%)";

    const rx = hasTool ? 5 : isDecision ? 8 : 7;

    // Icon prefix
    const icon = hasTool ? "\u2699" : isDecision ? "\u25C7" : isOutput ? "\u25B8" : "\u25CB";
    const iconColor = hasTool ? "hsl(220,25%,55%)" : isDecision ? "hsl(35,30%,30%)" : isOutput ? `${color}80` : "hsl(35,10%,28%)";

    return (
      <g key={step.id}>
        <rect
          x={pos.x} y={pos.y} width={pos.w} height={pos.h}
          rx={rx}
          fill={bgFill}
          stroke={borderStroke}
          strokeWidth={hasTool ? 1 : 1.2}
          strokeDasharray={isDecision ? "3 2" : "none"}
        />
        <text
          x={pos.x + 10} y={pos.y + pos.h / 2}
          fontSize={hasTool ? 8 : 9}
          dominantBaseline="middle"
          fill={iconColor}
        >
          {icon}
        </text>
        <text
          x={pos.x + (hasTool ? 20 : 23)} y={pos.y + pos.h / 2}
          fill={textFill}
          fontSize={hasTool ? 9.5 : 10.5}
          fontWeight={400}
          dominantBaseline="middle"
          style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
        >
          {step.label}
        </text>
      </g>
    );
  };

  return (
    <div className="w-full">
      <svg
        width="100%" height={svgH}
        viewBox={`0 0 ${SVG_W} ${svgH}`}
        preserveAspectRatio="xMidYMid meet"
        className="select-none"
        style={{ display: "block" }}
      >
        {edges.map((e, i) => renderEdge(e, i))}
        {nodes.map((n) => renderNode(n))}
      </svg>
    </div>
  );
}
