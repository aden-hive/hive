/**
 * Graph Schema - The complete agent graph specification.
 *
 * A GraphSpec defines the complete structure of an agent:
 * - All nodes and their configurations
 * - All edges and their conditions
 * - Entry and exit points
 * - Default settings
 */

import { z } from "zod";
import { EdgeSpecSchema, type EdgeSpec } from "./edge.js";
import { NodeSpecSchema, type NodeSpec } from "./node.js";

/**
 * Complete specification for an agent graph.
 *
 * @example
 * ```typescript
 * const graph: GraphSpec = {
 *   id: "calculator-agent",
 *   name: "Calculator Agent",
 *   version: "1.0.0",
 *   entryNode: "input_parser",
 *   nodes: [
 *     { id: "input_parser", name: "Parse Input", ... },
 *     { id: "calculator", name: "Calculate", ... },
 *     { id: "formatter", name: "Format Output", ... },
 *   ],
 *   edges: [
 *     { id: "e1", source: "input_parser", target: "calculator", ... },
 *     { id: "e2", source: "calculator", target: "formatter", ... },
 *   ],
 * };
 * ```
 */
export const GraphSpecSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().default(""),
  version: z.string().default("1.0.0"),

  // Graph structure
  nodes: z.array(NodeSpecSchema),
  edges: z.array(EdgeSpecSchema),

  // Entry/exit points
  entryNode: z.string().describe("ID of the entry node"),
  exitNodes: z
    .array(z.string())
    .default([])
    .describe("IDs of exit nodes (if empty, any terminal node is an exit)"),

  // Default settings
  defaultModel: z.string().default("gpt-4o").describe("Default LLM model for nodes"),
  defaultMaxRetries: z.number().default(3),

  // Metadata
  goalId: z.string().nullable().default(null).describe("Associated goal ID"),
  createdAt: z.date().default(() => new Date()),
  updatedAt: z.date().default(() => new Date()),
});

export type GraphSpec = z.infer<typeof GraphSpecSchema>;

/**
 * Validate a graph specification.
 * Returns an array of validation errors (empty if valid).
 */
export function validateGraph(graph: GraphSpec): string[] {
  const errors: string[] = [];
  const nodeIds = new Set(graph.nodes.map((n) => n.id));

  // Check entry node exists
  if (!nodeIds.has(graph.entryNode)) {
    errors.push(`Entry node '${graph.entryNode}' not found in nodes`);
  }

  // Check exit nodes exist
  for (const exitNode of graph.exitNodes) {
    if (!nodeIds.has(exitNode)) {
      errors.push(`Exit node '${exitNode}' not found in nodes`);
    }
  }

  // Check edge source/target nodes exist
  for (const edge of graph.edges) {
    if (!nodeIds.has(edge.source)) {
      errors.push(`Edge '${edge.id}' references unknown source node '${edge.source}'`);
    }
    if (!nodeIds.has(edge.target)) {
      errors.push(`Edge '${edge.id}' references unknown target node '${edge.target}'`);
    }
  }

  // Check for duplicate node IDs
  const seenNodeIds = new Set<string>();
  for (const node of graph.nodes) {
    if (seenNodeIds.has(node.id)) {
      errors.push(`Duplicate node ID: '${node.id}'`);
    }
    seenNodeIds.add(node.id);
  }

  // Check for duplicate edge IDs
  const seenEdgeIds = new Set<string>();
  for (const edge of graph.edges) {
    if (seenEdgeIds.has(edge.id)) {
      errors.push(`Duplicate edge ID: '${edge.id}'`);
    }
    seenEdgeIds.add(edge.id);
  }

  return errors;
}

/**
 * Get all nodes that can be reached from a given node.
 */
export function getReachableNodes(graph: GraphSpec, fromNodeId: string): Set<string> {
  const reachable = new Set<string>();
  const queue = [fromNodeId];

  while (queue.length > 0) {
    const current = queue.shift()!;
    if (reachable.has(current)) continue;
    reachable.add(current);

    // Find all outgoing edges
    for (const edge of graph.edges) {
      if (edge.source === current && !reachable.has(edge.target)) {
        queue.push(edge.target);
      }
    }
  }

  return reachable;
}

/**
 * Get outgoing edges from a node.
 */
export function getOutgoingEdges(graph: GraphSpec, nodeId: string): EdgeSpec[] {
  return graph.edges
    .filter((e) => e.source === nodeId)
    .sort((a, b) => b.priority - a.priority);
}

/**
 * Get incoming edges to a node.
 */
export function getIncomingEdges(graph: GraphSpec, nodeId: string): EdgeSpec[] {
  return graph.edges.filter((e) => e.target === nodeId);
}

/**
 * Get a node by ID.
 */
export function getNode(graph: GraphSpec, nodeId: string): NodeSpec | undefined {
  return graph.nodes.find((n) => n.id === nodeId);
}

/**
 * Check if a node is a terminal node (no outgoing edges).
 */
export function isTerminalNode(graph: GraphSpec, nodeId: string): boolean {
  return !graph.edges.some((e) => e.source === nodeId);
}
