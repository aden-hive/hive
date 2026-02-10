/**
 * Aden TypeScript SDK
 *
 * Build goal-driven, self-improving AI agents with TypeScript.
 *
 * @example
 * ```typescript
 * import { Goal, GraphSpec, Runtime, NodeSpec } from "@aden/sdk";
 *
 * // Define a goal
 * const goal: Goal = {
 *   id: "calc-001",
 *   name: "Calculator",
 *   description: "Perform mathematical calculations",
 *   status: "draft",
 *   successCriteria: [
 *     {
 *       id: "accuracy",
 *       description: "Result matches expected answer",
 *       metric: "output_equals",
 *       target: "expected_result",
 *       weight: 1.0,
 *       met: false,
 *     },
 *   ],
 *   constraints: [],
 * };
 *
 * // Create a runtime
 * const runtime = new Runtime();
 * const runId = runtime.startRun(goal.id, goal.description);
 *
 * // Record decisions
 * const decisionId = runtime.decide({
 *   intent: "Calculate expression",
 *   options: [
 *     { id: "direct", description: "Direct calculation" },
 *     { id: "parse", description: "Parse then calculate" },
 *   ],
 *   chosen: "direct",
 *   reasoning: "Simple expression, direct is faster",
 * });
 *
 * // Record outcome
 * runtime.recordOutcome(decisionId, {
 *   success: true,
 *   result: 42,
 *   summary: "Calculated successfully",
 * });
 *
 * // End run
 * runtime.endRun(true, "Calculation complete");
 * ```
 */

// Schemas
export {
  // Goal
  GoalSchema,
  GoalStatus,
  SuccessCriterionSchema,
  ConstraintSchema,
  isGoalSuccess,
  goalToPromptContext,
  type Goal,
  type SuccessCriterion,
  type Constraint,
} from "./schemas/goal.js";

export {
  // Node
  NodeSpecSchema,
  NodeResultSchema,
  NodeType,
  SharedMemory,
  type NodeSpec,
  type NodeResult,
  type NodeContext,
} from "./schemas/node.js";

export {
  // Edge
  EdgeSpecSchema,
  EdgeCondition,
  shouldTraverse,
  type EdgeSpec,
} from "./schemas/edge.js";

export {
  // Graph
  GraphSpecSchema,
  validateGraph,
  getReachableNodes,
  getOutgoingEdges,
  getIncomingEdges,
  getNode,
  isTerminalNode,
  type GraphSpec,
} from "./schemas/graph.js";

// LLM
export {
  LLMResponseSchema,
  ToolSchema,
  ToolUseSchema,
  ToolResultSchema,
  BaseLLMProvider,
  MockLLMProvider,
  type LLMResponse,
  type Tool,
  type ToolUse,
  type ToolResult,
  type LLMProvider,
  type Message,
  type CompletionOptions,
  type ToolCompletionOptions,
} from "./llm/provider.js";

// Runtime
export {
  Runtime,
  DecisionSchema,
  DecisionType,
  OptionSchema,
  OutcomeSchema,
  RunSchema,
  RunStatus,
  type Decision,
  type Option,
  type Outcome,
  type Run,
} from "./runtime/core.js";
