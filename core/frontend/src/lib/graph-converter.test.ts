import { describe, it, expect } from "vitest";
import { topologyToGraphNodes } from "./graph-converter";
import type { GraphTopology, NodeSpec } from "@/api/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeNode(id: string, overrides: Partial<NodeSpec> = {}): NodeSpec {
  return {
    id,
    name: id,
    description: "",
    node_type: "event_loop",
    input_keys: [],
    output_keys: [],
    nullable_output_keys: [],
    tools: [],
    routes: {},
    max_retries: 3,
    max_node_visits: 0,
    client_facing: false,
    success_criteria: null,
    system_prompt: "",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Edge classification
// ---------------------------------------------------------------------------

describe("edge classification", () => {
  it("linear chain: all edges in next[], no backEdges", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A"), makeNode("B"), makeNode("C")],
      edges: [
        { source: "A", target: "B", condition: "on_success", priority: 0 },
        { source: "B", target: "C", condition: "on_success", priority: 0 },
      ],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result).toHaveLength(3);

    const a = result.find((n) => n.id === "A")!;
    const b = result.find((n) => n.id === "B")!;
    const c = result.find((n) => n.id === "C")!;

    expect(a.next).toEqual(["B"]);
    expect(a.backEdges).toBeUndefined();
    expect(b.next).toEqual(["C"]);
    expect(b.backEdges).toBeUndefined();
    expect(c.next).toBeUndefined();
    expect(c.backEdges).toBeUndefined();
  });

  it("loop edge: classified as backEdge", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A"), makeNode("B"), makeNode("C")],
      edges: [
        { source: "A", target: "B", condition: "on_success", priority: 0 },
        { source: "B", target: "C", condition: "on_success", priority: 0 },
        { source: "C", target: "A", condition: "on_success", priority: 0 },
      ],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    const c = result.find((n) => n.id === "C")!;

    expect(c.next).toBeUndefined();
    expect(c.backEdges).toEqual(["A"]);
  });

  it("diamond/fan-out: multiple next targets", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A"), makeNode("B"), makeNode("C"), makeNode("D")],
      edges: [
        { source: "A", target: "B", condition: "on_success", priority: 0 },
        { source: "A", target: "C", condition: "on_failure", priority: 1 },
        { source: "B", target: "D", condition: "on_success", priority: 0 },
        { source: "C", target: "D", condition: "on_success", priority: 0 },
      ],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    const a = result.find((n) => n.id === "A")!;

    expect(a.next).toEqual(expect.arrayContaining(["B", "C"]));
    expect(a.next).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// Status mapping
// ---------------------------------------------------------------------------

describe("status mapping", () => {
  it("no enrichment: all nodes pending", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A"), makeNode("B")],
      edges: [
        { source: "A", target: "B", condition: "on_success", priority: 0 },
      ],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result.every((n) => n.status === "pending")).toBe(true);
  });

  it("is_current: running", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A", { is_current: true, visit_count: 1, in_path: true })],
      edges: [],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result[0].status).toBe("running");
  });

  it("is_current + visit_count > 1: looping", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A", { is_current: true, visit_count: 3, in_path: true })],
      edges: [],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result[0].status).toBe("looping");
  });

  it("in_path + visited + not current: complete", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A", { in_path: true, visit_count: 1, is_current: false })],
      edges: [],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result[0].status).toBe("complete");
  });

  it("has_failures: error", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A", { has_failures: true, in_path: true, visit_count: 1 })],
      edges: [],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result[0].status).toBe("error");
  });
});

// ---------------------------------------------------------------------------
// Iteration tracking
// ---------------------------------------------------------------------------

describe("iteration tracking", () => {
  it("visit_count maps to iterations", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A", { visit_count: 3, in_path: true })],
      edges: [],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result[0].iterations).toBe(3);
  });

  it("max_node_visits maps to maxIterations", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A", { max_node_visits: 5, visit_count: 1, in_path: true })],
      edges: [],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result[0].maxIterations).toBe(5);
  });

  it("max_node_visits == 0 (unlimited): maxIterations omitted", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A", { max_node_visits: 0, visit_count: 1, in_path: true })],
      edges: [],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result[0].maxIterations).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Edge labels
// ---------------------------------------------------------------------------

describe("edge labels", () => {
  it("conditional edges produce edgeLabels, on_success/always do not", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A"), makeNode("B"), makeNode("C"), makeNode("D")],
      edges: [
        { source: "A", target: "B", condition: "conditional", priority: 0 },
        { source: "A", target: "C", condition: "on_failure", priority: 1 },
        { source: "B", target: "D", condition: "on_success", priority: 0 },
        { source: "C", target: "D", condition: "always", priority: 0 },
      ],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    const a = result.find((n) => n.id === "A")!;
    const b = result.find((n) => n.id === "B")!;
    const c = result.find((n) => n.id === "C")!;

    // A has conditional + on_failure edges → both get labels
    expect(a.edgeLabels).toEqual({ B: "conditional", C: "on_failure" });
    // B has on_success → no label
    expect(b.edgeLabels).toBeUndefined();
    // C has always → no label
    expect(c.edgeLabels).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Node ordering
// ---------------------------------------------------------------------------

describe("node ordering", () => {
  it("nodes returned in BFS walk order from entry_node, not input order", () => {
    const topology: GraphTopology = {
      // Input order: C, A, B — but BFS from A should yield A, B, C
      nodes: [makeNode("C"), makeNode("A"), makeNode("B")],
      edges: [
        { source: "A", target: "B", condition: "on_success", priority: 0 },
        { source: "B", target: "C", condition: "on_success", priority: 0 },
      ],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result.map((n) => n.id)).toEqual(["A", "B", "C"]);
  });

  it("empty topology returns empty array", () => {
    const topology: GraphTopology = {
      nodes: [],
      edges: [],
      entry_node: "",
    };

    const result = topologyToGraphNodes(topology);
    expect(result).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Trigger node synthesis from entry_points
// ---------------------------------------------------------------------------

describe("trigger node synthesis", () => {
  it("single non-manual entry point: trigger node prepended before entry_node", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A"), makeNode("B")],
      edges: [
        { source: "A", target: "B", condition: "on_success", priority: 0 },
      ],
      entry_node: "A",
      entry_points: [
        { id: "webhook", name: "Webhook Handler", entry_node: "A", trigger_type: "webhook", trigger_config: { url: "/hook" } },
      ],
    };

    const result = topologyToGraphNodes(topology);
    expect(result).toHaveLength(3);

    const trigger = result[0];
    expect(trigger.id).toBe("__trigger_webhook");
    expect(trigger.nodeType).toBe("trigger");
    expect(trigger.triggerType).toBe("webhook");
    expect(trigger.triggerConfig).toEqual({ url: "/hook" });
    expect(trigger.label).toBe("Webhook Handler");
    expect(trigger.status).toBe("pending");
    expect(trigger.next).toEqual(["A"]);
  });

  it("trigger_config is threaded through for timer triggers", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A")],
      edges: [],
      entry_node: "A",
      entry_points: [
        { id: "timer", name: "Daily Check", entry_node: "A", trigger_type: "timer", trigger_config: { cron: "0 9 * * *" } },
      ],
    };

    const result = topologyToGraphNodes(topology);
    const trigger = result[0];
    expect(trigger.triggerConfig).toEqual({ cron: "0 9 * * *" });
  });

  it("no entry_points: no trigger nodes added", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A")],
      edges: [],
      entry_node: "A",
    };

    const result = topologyToGraphNodes(topology);
    expect(result).toHaveLength(1);
    expect(result[0].nodeType).toBeUndefined();
  });

  it("only manual entry points: no trigger nodes added", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A")],
      edges: [],
      entry_node: "A",
      entry_points: [
        { id: "main", name: "Main", entry_node: "A", trigger_type: "manual" },
      ],
    };

    const result = topologyToGraphNodes(topology);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("A");
  });

  it("multiple non-manual entry points: multiple trigger nodes", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A"), makeNode("B"), makeNode("C")],
      edges: [
        { source: "A", target: "C", condition: "on_success", priority: 0 },
        { source: "B", target: "C", condition: "on_success", priority: 0 },
      ],
      entry_node: "A",
      entry_points: [
        { id: "webhook", name: "Webhook", entry_node: "A", trigger_type: "webhook" },
        { id: "timer", name: "Daily Timer", entry_node: "B", trigger_type: "timer" },
      ],
    };

    const result = topologyToGraphNodes(topology);
    expect(result).toHaveLength(5); // 2 triggers + 3 nodes
    const triggers = result.filter((n) => n.nodeType === "trigger");
    expect(triggers).toHaveLength(2);
    expect(triggers[0].next).toEqual(["A"]);
    expect(triggers[1].next).toEqual(["B"]);
  });

  it("mix of manual and non-manual: only non-manual become trigger nodes", () => {
    const topology: GraphTopology = {
      nodes: [makeNode("A"), makeNode("B")],
      edges: [
        { source: "A", target: "B", condition: "on_success", priority: 0 },
      ],
      entry_node: "A",
      entry_points: [
        { id: "main", name: "Main", entry_node: "A", trigger_type: "manual" },
        { id: "webhook", name: "Webhook", entry_node: "A", trigger_type: "webhook" },
      ],
    };

    const result = topologyToGraphNodes(topology);
    expect(result).toHaveLength(3); // 1 trigger + 2 nodes
    const triggers = result.filter((n) => n.nodeType === "trigger");
    expect(triggers).toHaveLength(1);
    expect(triggers[0].triggerType).toBe("webhook");
  });
});
