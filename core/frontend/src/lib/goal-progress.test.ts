import { describe, expect, it } from "vitest";
import { goalProgressSummary, normalizeGoalProgress } from "./goal-progress";

describe("normalizeGoalProgress", () => {
  it("normalizes the rich backend payload", () => {
    const result = normalizeGoalProgress({
      overall_progress: 0.65,
      criteria_status: {
        c1: {
          description: "Find relevant sources",
          met: false,
          progress: 0.65,
          evidence: ["2 sources found"],
        },
      },
      metrics: { total_decisions: 4 },
      recommendation: "continue",
      updated_at: "2026-03-15T00:00:00Z",
    });

    expect(result.progress).toBe(0.65);
    expect(result.criteria).toHaveLength(1);
    expect(result.criteria[0].criterion_id).toBe("c1");
    expect(result.criteria_status.c1.evidence).toEqual(["2 sources found"]);
    expect(result.metrics.total_decisions).toBe(4);
  });

  it("supports the legacy compact payload", () => {
    const result = normalizeGoalProgress({
      progress: 0.5,
      criteria: [
        {
          criterion_id: "c1",
          description: "Half done",
          met: false,
          progress: 0.5,
          evidence: [],
        },
      ],
    });

    expect(result.overall_progress).toBe(0.5);
    expect(result.criteria_status.c1.description).toBe("Half done");
  });
});

describe("goalProgressSummary", () => {
  it("describes satisfied criteria when available", () => {
    const summary = goalProgressSummary(normalizeGoalProgress({
      progress: 0.75,
      criteria: [
        { criterion_id: "a", description: "A", met: true, progress: 1, evidence: [] },
        { criterion_id: "b", description: "B", met: false, progress: 0.5, evidence: [] },
      ],
    }));

    expect(summary).toBe("1/2 success criteria satisfied");
  });
});
