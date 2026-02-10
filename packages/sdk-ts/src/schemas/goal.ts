/**
 * Goal Schema - The source of truth for agent behavior.
 *
 * A Goal defines WHAT the agent should achieve, not HOW. The graph structure
 * (nodes and edges) is derived from the goal, not hardcoded.
 *
 * Goals are:
 * - Declarative: Define success criteria, not implementation
 * - Measurable: Success criteria are checkable
 * - Constrained: Boundaries the agent must respect
 * - Versionable: Can evolve based on runtime feedback
 */

import { z } from "zod";

/**
 * Lifecycle status of a goal.
 */
export const GoalStatus = {
  DRAFT: "draft",
  READY: "ready",
  ACTIVE: "active",
  COMPLETED: "completed",
  FAILED: "failed",
  SUSPENDED: "suspended",
} as const;

export type GoalStatus = (typeof GoalStatus)[keyof typeof GoalStatus];

/**
 * A measurable condition that defines success.
 *
 * Each criterion should be:
 * - Specific: Clear what it means
 * - Measurable: Can be evaluated programmatically or by LLM
 * - Achievable: Within the agent's capabilities
 */
export const SuccessCriterionSchema = z.object({
  id: z.string(),
  description: z.string().describe("Human-readable description of what success looks like"),
  metric: z
    .string()
    .describe("How to measure: 'output_contains', 'output_equals', 'llm_judge', 'custom'"),
  target: z.any().describe("The target value or condition"),
  weight: z.number().min(0).max(1).default(1.0).describe("Relative importance (0-1)"),
  met: z.boolean().default(false),
});

export type SuccessCriterion = z.infer<typeof SuccessCriterionSchema>;

/**
 * A boundary the agent must respect.
 *
 * Constraints are either:
 * - Hard: Violation means failure
 * - Soft: Violation is discouraged but allowed
 */
export const ConstraintSchema = z.object({
  id: z.string(),
  description: z.string(),
  constraintType: z
    .enum(["hard", "soft"])
    .describe("Type: 'hard' (must not violate) or 'soft' (prefer not to violate)"),
  category: z
    .enum(["time", "cost", "safety", "scope", "quality", "general"])
    .default("general")
    .describe("Category of constraint"),
  check: z
    .string()
    .default("")
    .describe("How to check: expression, function name, or 'llm_judge'"),
});

export type Constraint = z.infer<typeof ConstraintSchema>;

/**
 * The source of truth for agent behavior.
 *
 * A Goal defines:
 * - WHAT to achieve (success criteria)
 * - WHAT NOT to do (constraints)
 * - CONTEXT for decision-making
 *
 * The agent graph (nodes, edges) is derived from this goal.
 *
 * @example
 * ```typescript
 * const goal: Goal = {
 *   id: "calc-001",
 *   name: "Calculator",
 *   description: "Perform mathematical calculations accurately",
 *   status: "draft",
 *   successCriteria: [
 *     {
 *       id: "accuracy",
 *       description: "Result matches expected mathematical answer",
 *       metric: "output_equals",
 *       target: "expected_result",
 *       weight: 1.0,
 *       met: false,
 *     },
 *   ],
 *   constraints: [
 *     {
 *       id: "no-crash",
 *       description: "Handle invalid inputs gracefully",
 *       constraintType: "hard",
 *       category: "safety",
 *       check: "output != exception",
 *     },
 *   ],
 * };
 * ```
 */
export const GoalSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  status: z.nativeEnum(GoalStatus).default(GoalStatus.DRAFT),

  // What defines success
  successCriteria: z.array(SuccessCriterionSchema).default([]),

  // What the agent must respect
  constraints: z.array(ConstraintSchema).default([]),

  // Context for the agent
  context: z
    .record(z.any())
    .default({})
    .describe("Additional context: domain knowledge, user preferences, etc."),

  // Capabilities required
  requiredCapabilities: z
    .array(z.string())
    .default([])
    .describe("What the agent needs: 'llm', 'web_search', 'code_execution', etc."),

  // Input/output schema
  inputSchema: z.record(z.any()).default({}).describe("Expected input format"),
  outputSchema: z.record(z.any()).default({}).describe("Expected output format"),

  // Versioning for evolution
  version: z.string().default("1.0.0"),
  parentVersion: z.string().nullable().default(null),
  evolutionReason: z.string().nullable().default(null),

  // Timestamps
  createdAt: z.date().default(() => new Date()),
  updatedAt: z.date().default(() => new Date()),
});

export type Goal = z.infer<typeof GoalSchema>;

/**
 * Check if all weighted success criteria are met.
 */
export function isGoalSuccess(goal: Goal): boolean {
  if (goal.successCriteria.length === 0) {
    return false;
  }

  const totalWeight = goal.successCriteria.reduce((sum, c) => sum + c.weight, 0);
  const metWeight = goal.successCriteria
    .filter((c) => c.met)
    .reduce((sum, c) => sum + c.weight, 0);

  return metWeight >= totalWeight * 0.9; // 90% threshold
}

/**
 * Generate context string for LLM prompts.
 */
export function goalToPromptContext(goal: Goal): string {
  const lines: string[] = [
    `# Goal: ${goal.name}`,
    goal.description,
    "",
    "## Success Criteria:",
  ];

  for (const sc of goal.successCriteria) {
    lines.push(`- ${sc.description}`);
  }

  if (goal.constraints.length > 0) {
    lines.push("");
    lines.push("## Constraints:");
    for (const c of goal.constraints) {
      const severity = c.constraintType === "hard" ? "MUST" : "SHOULD";
      lines.push(`- [${severity}] ${c.description}`);
    }
  }

  if (Object.keys(goal.context).length > 0) {
    lines.push("");
    lines.push("## Context:");
    for (const [key, value] of Object.entries(goal.context)) {
      lines.push(`- ${key}: ${value}`);
    }
  }

  return lines.join("\n");
}
