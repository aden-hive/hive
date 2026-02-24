/**
 * Shared SVG geometry primitives for SubGraph and ExecutionSubGraph.
 *
 * Extracted from NodeDetailPanel's inline SubGraph renderer so both
 * demo-mode (hardcoded sgDefs) and real-mode (ExecutionSubGraph) can
 * share the same port, edge path, and arrowhead math.
 */

export type PortSide = "top" | "bottom" | "left" | "right";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Return the [x, y] connection point for a given side of a rect. */
export function sgPort(pos: Rect, port: PortSide): [number, number] {
  if (port === "top") return [pos.x + pos.w / 2, pos.y];
  if (port === "bottom") return [pos.x + pos.w / 2, pos.y + pos.h];
  if (port === "left") return [pos.x, pos.y + pos.h / 2];
  return [pos.x + pos.w, pos.y + pos.h / 2]; // right
}

/**
 * Compute an SVG path `d` attribute for an edge between two ports.
 * Uses cubic Bézier curves with smart midpoint handling for 6 port
 * combinations (right→left, bottom→top, bottom→left, bottom→right,
 * right→top, fallback).
 */
export function computeEdgePath(
  fromPort: PortSide,
  toPort: PortSide,
  fx: number,
  fy: number,
  tx: number,
  ty: number,
): string {
  if (fromPort === "right" && toPort === "left") {
    const midX = (fx + tx) / 2;
    return `M ${fx} ${fy} C ${midX} ${fy}, ${midX} ${ty}, ${tx} ${ty}`;
  }
  if (fromPort === "bottom" && toPort === "top") {
    if (Math.abs(tx - fx) < 10) {
      return `M ${fx} ${fy} L ${tx} ${ty}`;
    }
    const cY = fy + (ty - fy) * 0.5;
    return `M ${fx} ${fy} C ${fx} ${cY}, ${tx} ${cY}, ${tx} ${ty}`;
  }
  if (fromPort === "bottom" && toPort === "left") {
    return `M ${fx} ${fy} C ${fx} ${fy + 20}, ${tx - 20} ${ty}, ${tx} ${ty}`;
  }
  if (fromPort === "bottom" && toPort === "right") {
    return `M ${fx} ${fy} C ${fx} ${fy + 20}, ${tx + 20} ${ty}, ${tx} ${ty}`;
  }
  if (fromPort === "right" && toPort === "top") {
    return `M ${fx} ${fy} C ${fx + 20} ${fy}, ${tx} ${ty - 20}, ${tx} ${ty}`;
  }
  // Fallback
  const cX = (fx + tx) / 2;
  return `M ${fx} ${fy} C ${cX} ${fy}, ${cX} ${ty}, ${tx} ${ty}`;
}

/**
 * Compute an SVG polygon `points` attribute for an arrowhead at the
 * target port. Arrow size is configurable (default 4.5).
 */
export function computeArrowhead(
  toPort: PortSide,
  tx: number,
  ty: number,
  arrowSize = 4.5,
): string {
  const A = arrowSize;
  if (toPort === "top")
    return `${tx - A},${ty + A * 1.4} ${tx + A},${ty + A * 1.4} ${tx},${ty + 1}`;
  if (toPort === "left")
    return `${tx + A * 1.4},${ty - A} ${tx + A * 1.4},${ty + A} ${tx + 1},${ty}`;
  if (toPort === "right")
    return `${tx - A * 1.4},${ty - A} ${tx - A * 1.4},${ty + A} ${tx - 1},${ty}`;
  // bottom
  return `${tx - A},${ty - A * 1.4} ${tx + A},${ty - A * 1.4} ${tx},${ty - 1}`;
}
