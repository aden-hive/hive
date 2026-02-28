import type { GraphTopology, NodeSpec } from "@/api/types";
import type { GraphNode, NodeStatus } from "@/components/AgentGraph";

/**
 * Convert a backend GraphTopology (nodes + edges + entry_node) into
 * the GraphNode[] shape that AgentGraph renders.
 *
 * Four jobs:
 *  1. Synthesize trigger nodes from non-manual entry_points
 *  2. Order nodes via BFS from trigger/entry_node
 *  3. Classify edges as forward (next) or backward (backEdges)
 *  4. Map session enrichment fields to NodeStatus
 */
export function topologyToGraphNodes(topology: GraphTopology): GraphNode[] {
  const { nodes, edges, entry_node, entry_points } = topology;
  if (nodes.length === 0) return [];

  // --- Synthesize trigger nodes for non-manual entry points ---
  const schedulerEntryPoints = (entry_points || []).filter(
    (ep) => ep.trigger_type !== "manual",
  );
  const triggerMap = new Map<string, GraphNode>();

  for (const ep of schedulerEntryPoints) {
    const triggerId = `__trigger_${ep.id}`;
    triggerMap.set(triggerId, {
      id: triggerId,
      label: ep.name,
      status: "pending",
      nodeType: "trigger",
      triggerType: ep.trigger_type,
      triggerConfig: ep.trigger_config,
      next: [ep.entry_node],
    });
  }

  // Build adjacency list: source → [target, ...] (includes trigger edges)
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    const list = adj.get(e.source) || [];
    list.push(e.target);
    adj.set(e.source, list);
  }
  for (const [triggerId, triggerNode] of triggerMap) {
    adj.set(triggerId, triggerNode.next!);
  }

  // BFS — start from trigger nodes (if any), then entry_node.
  // Always include entry_node so the DAG ordering stays correct
  // even when triggers target a node other than entry.
  const order: string[] = [];
  const position = new Map<string, number>();
  const visited = new Set<string>();

  const entryStart = entry_node || nodes[0].id;
  const starts =
    triggerMap.size > 0
      ? [...triggerMap.keys(), entryStart]
      : [entryStart];
  const queue = [...starts];
  for (const s of starts) visited.add(s);

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
    // Synthetic trigger nodes are returned directly
    const trigger = triggerMap.get(id);
    if (trigger) return trigger;

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
