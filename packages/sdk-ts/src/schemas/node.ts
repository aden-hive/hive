/**
 * Node Protocol - The building block of agent graphs.
 *
 * A Node is a unit of work that:
 * 1. Receives context (goal, shared memory, input)
 * 2. Makes decisions (using LLM, tools, or logic)
 * 3. Produces results (output, state changes)
 * 4. Records everything to the Runtime
 *
 * Nodes are composable and reusable. The same node can appear
 * in different graphs for different goals.
 */

import { z } from "zod";

/**
 * Node behavior types.
 */
export const NodeType = {
  LLM_TOOL_USE: "llm_tool_use",
  LLM_GENERATE: "llm_generate",
  FUNCTION: "function",
  ROUTER: "router",
  HUMAN_INPUT: "human_input",
} as const;

export type NodeType = (typeof NodeType)[keyof typeof NodeType];

/**
 * Specification for a node in the graph.
 *
 * This is the declarative definition of a node - what it does,
 * what it needs, and what it produces.
 *
 * @example
 * ```typescript
 * const node: NodeSpec = {
 *   id: "calculator",
 *   name: "Calculator Node",
 *   description: "Performs mathematical calculations",
 *   nodeType: "llm_tool_use",
 *   inputKeys: ["expression"],
 *   outputKeys: ["result"],
 *   tools: ["calculate", "math_function"],
 *   systemPrompt: "You are a calculator...",
 * };
 * ```
 */
export const NodeSpecSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),

  // Node behavior type
  nodeType: z
    .enum(["llm_tool_use", "llm_generate", "function", "router", "human_input"])
    .default("llm_tool_use")
    .describe("Type of node behavior"),

  // Data flow
  inputKeys: z
    .array(z.string())
    .default([])
    .describe("Keys this node reads from shared memory or input"),
  outputKeys: z
    .array(z.string())
    .default([])
    .describe("Keys this node writes to shared memory or output"),
  nullableOutputKeys: z
    .array(z.string())
    .default([])
    .describe("Output keys that can be null without triggering validation errors"),

  // Optional schemas for validation
  inputSchema: z.record(z.any()).default({}).describe("Optional schema for input validation"),
  outputSchema: z.record(z.any()).default({}).describe("Optional schema for output validation"),

  // For LLM nodes
  systemPrompt: z.string().nullable().default(null).describe("System prompt for LLM nodes"),
  tools: z.array(z.string()).default([]).describe("Tool names this node can use"),
  model: z
    .string()
    .nullable()
    .default(null)
    .describe("Specific model to use (defaults to graph default)"),

  // For function nodes
  function: z.string().nullable().default(null).describe("Function name or path for function nodes"),

  // For router nodes
  routes: z
    .record(z.string())
    .default({})
    .describe("Condition -> target_node_id mapping for routers"),

  // Retry behavior
  maxRetries: z.number().default(3),
  retryOn: z.array(z.string()).default([]).describe("Error types to retry on"),

  // Pydantic/Zod model for output validation
  maxValidationRetries: z
    .number()
    .default(2)
    .describe("Maximum retries when validation fails (with feedback to LLM)"),
});

export type NodeSpec = z.infer<typeof NodeSpecSchema>;

/**
 * Result from executing a node.
 */
export const NodeResultSchema = z.object({
  success: z.boolean(),
  output: z.record(z.any()).default({}),
  error: z.string().nullable().default(null),
  tokensUsed: z.number().default(0),
  latencyMs: z.number().default(0),
  retryCount: z.number().default(0),
});

export type NodeResult = z.infer<typeof NodeResultSchema>;

/**
 * Context provided to a node during execution.
 */
export interface NodeContext {
  /** The node specification */
  nodeSpec: NodeSpec;
  /** Shared memory for reading/writing state */
  memory: SharedMemory;
  /** Input data for this node */
  input: Record<string, unknown>;
  /** The goal being pursued */
  goal: unknown; // Goal type from goal.ts
  /** Runtime for decision logging */
  runtime: unknown; // Runtime type
}

/**
 * Shared state between nodes in a graph execution.
 *
 * Nodes read and write to shared memory using typed keys.
 * The memory is scoped to a single run.
 */
export class SharedMemory {
  private data: Map<string, unknown> = new Map();
  private allowedRead: Set<string> = new Set();
  private allowedWrite: Set<string> = new Set();

  constructor(
    initialData?: Record<string, unknown>,
    allowedRead?: string[],
    allowedWrite?: string[]
  ) {
    if (initialData) {
      for (const [key, value] of Object.entries(initialData)) {
        this.data.set(key, value);
      }
    }
    if (allowedRead) {
      this.allowedRead = new Set(allowedRead);
    }
    if (allowedWrite) {
      this.allowedWrite = new Set(allowedWrite);
    }
  }

  /**
   * Read a value from shared memory.
   */
  read<T = unknown>(key: string): T | undefined {
    if (this.allowedRead.size > 0 && !this.allowedRead.has(key)) {
      throw new Error(`Node not allowed to read key: ${key}`);
    }
    return this.data.get(key) as T | undefined;
  }

  /**
   * Write a value to shared memory.
   */
  write(key: string, value: unknown): void {
    if (this.allowedWrite.size > 0 && !this.allowedWrite.has(key)) {
      throw new Error(`Node not allowed to write key: ${key}`);
    }
    this.data.set(key, value);
  }

  /**
   * Get all data as a plain object.
   */
  toObject(): Record<string, unknown> {
    const obj: Record<string, unknown> = {};
    for (const [key, value] of this.data) {
      obj[key] = value;
    }
    return obj;
  }

  /**
   * Check if a key exists.
   */
  has(key: string): boolean {
    return this.data.has(key);
  }

  /**
   * Get all keys.
   */
  keys(): string[] {
    return Array.from(this.data.keys());
  }
}
