import type { GraphTopology, NodeSpec } from "@/api/types";
import type { GraphNode, NodeStatus } from "@/components/AgentGraph";

/**
 * Convert a backend GraphTopology (nodes + edges + entry_node) into
 * the GraphNode[] shape that AgentGraph renders.
 *
 * Three jobs:
 *  1. Order nodes via BFS from entry_node
 *  2. Classify edges as forward (next) or backward (backEdges)
 *  3. Map session enrichment fields to NodeStatus
 */
export function topologyToGraphNodes(topology: GraphTopology): GraphNode[] {
  const { nodes, edges, entry_node } = topology;
  if (nodes.length === 0) return [];

  // Build adjacency list: source → [target, ...]
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    const list = adj.get(e.source) || [];
    list.push(e.target);
    adj.set(e.source, list);
  }

  // BFS from entry_node to determine walk order + position map
  const order: string[] = [];
  const position = new Map<string, number>();
  const visited = new Set<string>();

  const start = entry_node || nodes[0].id;
  const queue = [start];
  visited.add(start);

  while (queue.length > 0) {
    const id = queue.shift()!;
    position.set(id, order.length);
    order.push(id);

    for (const target of adj.get(id) || []) {
      if (!visited.has(target)) {
        visited.add(target);
        queue.push(target);
      }
    }
  }

  // Add any nodes not reachable from entry (shouldn't happen in valid graphs)
  for (const n of nodes) {
    if (!visited.has(n.id)) {
      position.set(n.id, order.length);
      order.push(n.id);
    }
  }

  // Build a node lookup
  const nodeMap = new Map<string, NodeSpec>();
  for (const n of nodes) {
    nodeMap.set(n.id, n);
  }

  // Classify edges per source node
  const nextMap = new Map<string, string[]>();
  const backMap = new Map<string, string[]>();

  for (const e of edges) {
    const srcPos = position.get(e.source) ?? 0;
    const tgtPos = position.get(e.target) ?? 0;

    if (tgtPos <= srcPos) {
      // Back edge (target is at same or earlier position in BFS)
      const list = backMap.get(e.source) || [];
      list.push(e.target);
      backMap.set(e.source, list);
    } else {
      // Forward edge
      const list = nextMap.get(e.source) || [];
      list.push(e.target);
      nextMap.set(e.source, list);
    }
  }

  // Build edge condition labels (only for non-trivial conditions)
  const edgeLabelMap = new Map<string, Record<string, string>>();
  for (const e of edges) {
    if (e.condition !== "always" && e.condition !== "on_success") {
      const labels = edgeLabelMap.get(e.source) || {};
      labels[e.target] = e.condition;
      edgeLabelMap.set(e.source, labels);
    }
  }

  // Build GraphNode[] in BFS order
  return order.map((id) => {
    const spec = nodeMap.get(id);
    const next = nextMap.get(id);
    const back = backMap.get(id);
    const labels = edgeLabelMap.get(id);

    const result: GraphNode = {
      id,
      label: spec?.name || id,
      status: mapStatus(spec),
      ...(next && next.length > 0 ? { next } : {}),
      ...(back && back.length > 0 ? { backEdges: back } : {}),
      ...(labels ? { edgeLabels: labels } : {}),
    };

    // Iteration tracking from session enrichment
    if (spec?.visit_count !== undefined && spec.visit_count > 0) {
      result.iterations = spec.visit_count;
    }
    if (spec?.max_node_visits !== undefined && spec.max_node_visits > 0) {
      result.maxIterations = spec.max_node_visits;
    }

    return result;
  });
}

function mapStatus(spec: NodeSpec | undefined): NodeStatus {
  if (!spec) return "pending";

  if (spec.has_failures) return "error";
  if (spec.is_current) {
    return (spec.visit_count ?? 0) > 1 ? "looping" : "running";
  }
  if (spec.in_path && (spec.visit_count ?? 0) > 0) return "complete";

  return "pending";
}
