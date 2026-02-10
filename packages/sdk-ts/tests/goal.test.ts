import { describe, it, expect } from "vitest";
import {
  GoalSchema,
  GoalStatus,
  isGoalSuccess,
  goalToPromptContext,
  type Goal,
} from "../src/schemas/goal.js";

describe("Goal", () => {
  const sampleGoal: Goal = {
    id: "test-goal",
    name: "Test Goal",
    description: "A test goal for unit testing",
    status: GoalStatus.DRAFT,
    successCriteria: [
      {
        id: "criterion-1",
        description: "First criterion",
        metric: "output_equals",
        target: "expected",
        weight: 0.5,
        met: false,
      },
      {
        id: "criterion-2",
        description: "Second criterion",
        metric: "output_contains",
        target: "value",
        weight: 0.5,
        met: true,
      },
    ],
    constraints: [
      {
        id: "constraint-1",
        description: "Must not fail",
        constraintType: "hard",
        category: "safety",
        check: "",
      },
    ],
    context: { domain: "testing" },
    requiredCapabilities: ["llm"],
    inputSchema: {},
    outputSchema: {},
    version: "1.0.0",
    parentVersion: null,
    evolutionReason: null,
    createdAt: new Date(),
    updatedAt: new Date(),
  };

  it("should validate a goal with GoalSchema", () => {
    const result = GoalSchema.safeParse(sampleGoal);
    expect(result.success).toBe(true);
  });

  it("should parse a minimal goal with defaults", () => {
    const minimalGoal = {
      id: "minimal",
      name: "Minimal Goal",
      description: "A minimal goal",
    };
    const result = GoalSchema.safeParse(minimalGoal);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.status).toBe(GoalStatus.DRAFT);
      expect(result.data.successCriteria).toEqual([]);
      expect(result.data.constraints).toEqual([]);
    }
  });

  it("should correctly check goal success (not met)", () => {
    expect(isGoalSuccess(sampleGoal)).toBe(false);
  });

  it("should correctly check goal success (met)", () => {
    const metGoal: Goal = {
      ...sampleGoal,
      successCriteria: sampleGoal.successCriteria.map((c) => ({ ...c, met: true })),
    };
    expect(isGoalSuccess(metGoal)).toBe(true);
  });

  it("should generate prompt context", () => {
    const context = goalToPromptContext(sampleGoal);
    expect(context).toContain("# Goal: Test Goal");
    expect(context).toContain("A test goal for unit testing");
    expect(context).toContain("## Success Criteria:");
    expect(context).toContain("First criterion");
    expect(context).toContain("## Constraints:");
    expect(context).toContain("[MUST] Must not fail");
    expect(context).toContain("## Context:");
    expect(context).toContain("domain: testing");
  });
});
