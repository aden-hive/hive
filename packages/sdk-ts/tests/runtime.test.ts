import { describe, it, expect, beforeEach } from "vitest";
import { Runtime, RunStatus, DecisionType } from "../src/runtime/core.js";

describe("Runtime", () => {
  let runtime: Runtime;

  beforeEach(() => {
    runtime = new Runtime();
  });

  it("should start a run", () => {
    const runId = runtime.startRun("goal-1", "Test goal");
    expect(runId).toMatch(/^run_/);

    const run = runtime.getCurrentRun();
    expect(run).not.toBeNull();
    expect(run?.goalId).toBe("goal-1");
    expect(run?.status).toBe(RunStatus.RUNNING);
  });

  it("should record decisions", () => {
    runtime.startRun("goal-1", "Test goal");

    const decisionId = runtime.decide({
      nodeId: "test-node",
      intent: "Make a choice",
      options: [
        { id: "option-a", description: "Option A" },
        { id: "option-b", description: "Option B" },
      ],
      chosen: "option-a",
      reasoning: "Option A is better",
    });

    expect(decisionId).toMatch(/^dec_/);

    const run = runtime.getCurrentRun();
    expect(run?.decisions).toHaveLength(1);
    expect(run?.decisions[0].chosen).toBe("option-a");
  });

  it("should record outcomes", () => {
    runtime.startRun("goal-1", "Test goal");

    const decisionId = runtime.decide({
      intent: "Test decision",
      options: [{ id: "opt", description: "Only option" }],
      chosen: "opt",
      reasoning: "Only choice",
    });

    runtime.recordOutcome(decisionId, {
      success: true,
      result: { value: 42 },
      summary: "It worked!",
    });

    const run = runtime.getCurrentRun();
    const decision = run?.decisions[0];
    expect(decision?.outcome?.success).toBe(true);
    expect(decision?.outcome?.result).toEqual({ value: 42 });
  });

  it("should end a run successfully", () => {
    const runId = runtime.startRun("goal-1", "Test goal");

    runtime.endRun(true, "Completed successfully", { result: "done" });

    const run = runtime.getRun(runId);
    expect(run?.status).toBe(RunStatus.COMPLETED);
    expect(run?.narrative).toBe("Completed successfully");
    expect(run?.outputData).toEqual({ result: "done" });
    expect(run?.endedAt).not.toBeNull();
  });

  it("should end a run with failure", () => {
    const runId = runtime.startRun("goal-1", "Test goal");

    runtime.endRun(false, "Something went wrong");

    const run = runtime.getRun(runId);
    expect(run?.status).toBe(RunStatus.FAILED);
  });

  it("should throw when no active run", () => {
    expect(() => runtime.decide({
      intent: "Test",
      options: [],
      chosen: "",
      reasoning: "",
    })).toThrow("No active run");
  });

  it("should export runs to JSON", () => {
    runtime.startRun("goal-1", "Test");
    runtime.endRun(true, "Done");

    const json = runtime.toJSON();
    const parsed = JSON.parse(json);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].goalId).toBe("goal-1");
  });
});
