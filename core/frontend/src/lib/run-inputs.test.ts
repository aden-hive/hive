import { describe, expect, it } from "vitest";

import type { NodeSpec } from "@/api/types";
import type { GraphNode } from "@/components/graph-types";

import {
  buildStructuredRunQuestions,
  canShowRunButton,
  getStructuredRunInputKeys,
  hasAllStructuredRunInputs,
  trimStructuredRunInputs,
} from "./run-inputs";

function makeNodeSpec(overrides: Partial<NodeSpec>): NodeSpec {
  return {
    id: "node-1",
    name: "Node 1",
    description: "",
    node_type: "event_loop",
    input_keys: [],
    output_keys: [],
    nullable_output_keys: [],
    tools: [],
    routes: {},
    max_retries: 0,
    max_node_visits: 0,
    client_facing: false,
    success_criteria: null,
    system_prompt: "",
    sub_agents: [],
    ...overrides,
  };
}

function makeGraphNode(overrides: Partial<GraphNode>): GraphNode {
  return {
    id: "node-1",
    label: "Node 1",
    status: "pending",
    ...overrides,
  };
}

describe("getStructuredRunInputKeys", () => {
  it("returns structured input keys from the first non-trigger graph node", () => {
    const nodeSpecs = [
      makeNodeSpec({
        id: "receive-runtime-inputs",
        input_keys: ["target_dir", "review_dir", "word_threshold"],
      }),
    ];
    const graphNodes = [
      makeGraphNode({ id: "__trigger_default", nodeType: "trigger" }),
      makeGraphNode({ id: "receive-runtime-inputs", nodeType: "execution" }),
    ];

    expect(getStructuredRunInputKeys(nodeSpecs, graphNodes)).toEqual([
      "target_dir",
      "review_dir",
      "word_threshold",
    ]);
  });

  it("filters out generic task-style entry keys", () => {
    const nodeSpecs = [
      makeNodeSpec({
        id: "entry",
        input_keys: ["user_request", "task", "feedback", "target_dir"],
      }),
    ];

    expect(getStructuredRunInputKeys(nodeSpecs, [])).toEqual(["target_dir"]);
  });
});

describe("hasAllStructuredRunInputs", () => {
  it("requires every structured key to be present and non-blank", () => {
    expect(
      hasAllStructuredRunInputs(["target_dir", "word_threshold"], {
        target_dir: "/tmp/project",
        word_threshold: "800",
      }),
    ).toBe(true);

    expect(
      hasAllStructuredRunInputs(["target_dir", "word_threshold"], {
        target_dir: "   ",
        word_threshold: "800",
      }),
    ).toBe(false);

    expect(
      hasAllStructuredRunInputs(["target_dir", "word_threshold"], {
        target_dir: "/tmp/project",
      }),
    ).toBe(false);
  });
});

describe("buildStructuredRunQuestions", () => {
  it("creates free-text prompts for each required run input", () => {
    expect(buildStructuredRunQuestions(["target_dir", "review_dir"])).toEqual([
      { id: "target_dir", prompt: "Provide target_dir for this run." },
      { id: "review_dir", prompt: "Provide review_dir for this run." },
    ]);
  });
});

describe("canShowRunButton", () => {
  it("only exposes Run when a worker session is ready and staged/running", () => {
    expect(canShowRunButton("sess-1", true, "staging", true)).toBe(true);
    expect(canShowRunButton("sess-1", true, "running", true)).toBe(true);

    expect(canShowRunButton("sess-1", true, "planning", true)).toBe(false);
    expect(canShowRunButton("sess-1", true, "building", true)).toBe(false);
    expect(canShowRunButton("sess-1", false, "staging", true)).toBe(false);
    expect(canShowRunButton("sess-1", true, "staging", false)).toBe(false);
    expect(canShowRunButton(null, true, "staging", true)).toBe(false);
  });
});

describe("trimStructuredRunInputs", () => {
  it("drops stale keys that are no longer part of the current schema", () => {
    expect(
      trimStructuredRunInputs(["target_dir", "word_threshold"], {
        target_dir: "/tmp/project",
        word_threshold: 800,
        stale_key: "old",
      }),
    ).toEqual({
      target_dir: "/tmp/project",
      word_threshold: 800,
    });
  });
});
