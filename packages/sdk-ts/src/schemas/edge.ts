/**
 * Edge Protocol - How nodes connect in a graph.
 *
 * Edges define:
 * 1. Source and target nodes
 * 2. Conditions for traversal
 * 3. Data mapping between nodes
 *
 * Unlike traditional graph frameworks where edges are programmatic,
 * our edges can be created dynamically by a Builder agent based on the goal.
 */

import { z } from "zod";

/**
 * When an edge should be traversed.
 */
export const EdgeCondition = {
  ALWAYS: "always",
  ON_SUCCESS: "on_success",
  ON_FAILURE: "on_failure",
  CONDITIONAL: "conditional",
  LLM_DECIDE: "llm_decide",
} as const;

export type EdgeCondition = (typeof EdgeCondition)[keyof typeof EdgeCondition];

/**
 * Specification for an edge between nodes.
 *
 * @example
 * ```typescript
 * // Simple success-based routing
 * const edge: EdgeSpec = {
 *   id: "calc-to-format",
 *   source: "calculator",
 *   target: "formatter",
 *   condition: "on_success",
 *   inputMapping: { result: "value_to_format" },
 * };
 *
 * // Conditional routing based on output
 * const conditionalEdge: EdgeSpec = {
 *   id: "validate-to-retry",
 *   source: "validator",
 *   target: "retry_handler",
 *   condition: "conditional",
 *   conditionExpr: "output.confidence < 0.8",
 * };
 *
 * // LLM-powered routing (goal-aware)
 * const llmEdge: EdgeSpec = {
 *   id: "search-to-filter",
 *   source: "search_results",
 *   target: "filter_results",
 *   condition: "llm_decide",
 *   description: "Only filter if results need refinement",
 * };
 * ```
 */
export const EdgeSpecSchema = z.object({
  id: z.string(),
  source: z.string().describe("Source node ID"),
  target: z.string().describe("Target node ID"),

  // When to traverse
  condition: z.nativeEnum(EdgeCondition).default(EdgeCondition.ALWAYS),
  conditionExpr: z
    .string()
    .nullable()
    .default(null)
    .describe("Expression for CONDITIONAL edges, e.g., 'output.confidence > 0.8'"),

  // Data flow
  inputMapping: z
    .record(z.string())
    .default({})
    .describe("Map source outputs to target inputs: {target_key: source_key}"),

  // Priority for multiple outgoing edges
  priority: z.number().default(0).describe("Higher priority edges are evaluated first"),

  // Metadata
  description: z.string().default(""),
});

export type EdgeSpec = z.infer<typeof EdgeSpecSchema>;

/**
 * Evaluate if an edge should be traversed based on its condition.
 */
export function shouldTraverse(
  edge: EdgeSpec,
  sourceSuccess: boolean,
  sourceOutput: Record<string, unknown>,
  memory: Record<string, unknown>
): boolean {
  switch (edge.condition) {
    case EdgeCondition.ALWAYS:
      return true;

    case EdgeCondition.ON_SUCCESS:
      return sourceSuccess;

    case EdgeCondition.ON_FAILURE:
      return !sourceSuccess;

    case EdgeCondition.CONDITIONAL:
      return evaluateCondition(edge.conditionExpr, sourceOutput, memory);

    case EdgeCondition.LLM_DECIDE:
      // Fallback to ON_SUCCESS if no LLM provided
      // Full implementation would call LLM to decide
      return sourceSuccess;

    default:
      return false;
  }
}

/**
 * Safely evaluate a condition expression.
 * Only allows basic comparisons on output and memory values.
 */
function evaluateCondition(
  expr: string | null,
  output: Record<string, unknown>,
  memory: Record<string, unknown>
): boolean {
  if (!expr) return true;

  // Create a safe evaluation context
  const context = { output, memory };

  try {
    // Simple expression parser for safety
    // Supports: output.key, memory.key, comparisons (<, >, <=, >=, ==, !=)
    const parsed = parseSimpleExpression(expr, context);
    return Boolean(parsed);
  } catch {
    console.warn(`Failed to evaluate condition: ${expr}`);
    return false;
  }
}

/**
 * Parse a simple expression safely without eval().
 * Supports: dot access, comparisons, boolean logic.
 */
function parseSimpleExpression(
  expr: string,
  context: { output: Record<string, unknown>; memory: Record<string, unknown> }
): boolean {
  // Match patterns like "output.key > value" or "memory.key == 'string'"
  const comparisonMatch = expr.match(
    /^(output|memory)\.(\w+)\s*(==|!=|>=|<=|>|<)\s*(.+)$/
  );

  if (comparisonMatch) {
    const [, source, key, operator, rawValue] = comparisonMatch;
    const sourceObj = source === "output" ? context.output : context.memory;
    const actualValue = sourceObj[key];

    // Parse the comparison value
    let expectedValue: unknown;
    const trimmedValue = rawValue.trim();

    if (trimmedValue === "true") {
      expectedValue = true;
    } else if (trimmedValue === "false") {
      expectedValue = false;
    } else if (trimmedValue === "null") {
      expectedValue = null;
    } else if (/^['"].*['"]$/.test(trimmedValue)) {
      expectedValue = trimmedValue.slice(1, -1);
    } else if (!isNaN(Number(trimmedValue))) {
      expectedValue = Number(trimmedValue);
    } else {
      expectedValue = trimmedValue;
    }

    switch (operator) {
      case "==":
        return actualValue === expectedValue;
      case "!=":
        return actualValue !== expectedValue;
      case ">":
        return Number(actualValue) > Number(expectedValue);
      case "<":
        return Number(actualValue) < Number(expectedValue);
      case ">=":
        return Number(actualValue) >= Number(expectedValue);
      case "<=":
        return Number(actualValue) <= Number(expectedValue);
      default:
        return false;
    }
  }

  // Boolean check: "output.key" or "!output.key"
  const boolMatch = expr.match(/^(!?)(output|memory)\.(\w+)$/);
  if (boolMatch) {
    const [, negation, source, key] = boolMatch;
    const sourceObj = source === "output" ? context.output : context.memory;
    const value = Boolean(sourceObj[key]);
    return negation === "!" ? !value : value;
  }

  throw new Error(`Unsupported expression format: ${expr}`);
}
