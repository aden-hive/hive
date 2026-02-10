/**
 * Runtime Core - The interface agents use to record their behavior.
 *
 * This is designed to make it EASY for agents to record decisions in a way
 * that can be analyzed. The agent calls simple methods, and the runtime
 * handles all the structured logging.
 */

import { z } from "zod";

/**
 * Types of decisions an agent can make.
 */
export const DecisionType = {
  TOOL_SELECTION: "tool_selection",
  PARAMETER_CHOICE: "parameter_choice",
  PATH_CHOICE: "path_choice",
  OUTPUT_FORMAT: "output_format",
  RETRY_STRATEGY: "retry_strategy",
} as const;

export type DecisionType = (typeof DecisionType)[keyof typeof DecisionType];

/**
 * An option the agent considered.
 */
export const OptionSchema = z.object({
  id: z.string(),
  description: z.string(),
  metadata: z.record(z.any()).default({}),
});

export type Option = z.infer<typeof OptionSchema>;

/**
 * The outcome of a decision.
 */
export const OutcomeSchema = z.object({
  success: z.boolean(),
  result: z.any(),
  summary: z.string().default(""),
  errorType: z.string().nullable().default(null),
  errorMessage: z.string().nullable().default(null),
  durationMs: z.number().default(0),
});

export type Outcome = z.infer<typeof OutcomeSchema>;

/**
 * A decision made by the agent.
 */
export const DecisionSchema = z.object({
  id: z.string(),
  nodeId: z.string(),
  decisionType: z.nativeEnum(DecisionType),
  intent: z.string().describe("What the agent was trying to do"),
  options: z.array(OptionSchema).describe("Options considered"),
  chosen: z.string().describe("ID of the chosen option"),
  reasoning: z.string().describe("Why this option was chosen"),
  outcome: OutcomeSchema.nullable().default(null),
  timestamp: z.date().default(() => new Date()),
});

export type Decision = z.infer<typeof DecisionSchema>;

/**
 * Status of a run.
 */
export const RunStatus = {
  RUNNING: "running",
  COMPLETED: "completed",
  FAILED: "failed",
  PAUSED: "paused",
} as const;

export type RunStatus = (typeof RunStatus)[keyof typeof RunStatus];

/**
 * A single execution run of an agent.
 */
export const RunSchema = z.object({
  id: z.string(),
  goalId: z.string(),
  goalDescription: z.string().default(""),
  status: z.nativeEnum(RunStatus).default(RunStatus.RUNNING),
  inputData: z.record(z.any()).default({}),
  outputData: z.record(z.any()).default({}),
  decisions: z.array(DecisionSchema).default([]),
  startedAt: z.date().default(() => new Date()),
  endedAt: z.date().nullable().default(null),
  narrative: z.string().default(""),
});

export type Run = z.infer<typeof RunSchema>;

/**
 * Generate a unique ID.
 */
function generateId(prefix: string): string {
  const timestamp = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}_${timestamp}_${random}`;
}

/**
 * The runtime environment that agents execute within.
 *
 * @example
 * ```typescript
 * const runtime = new Runtime();
 *
 * // Start a run
 * const runId = runtime.startRun("goal_123", "Qualify sales leads");
 *
 * // Record a decision
 * const decisionId = runtime.decide({
 *   nodeId: "lead-qualifier",
 *   intent: "Determine if lead has budget",
 *   options: [
 *     { id: "ask", description: "Ask the lead directly" },
 *     { id: "infer", description: "Infer from company size" },
 *   ],
 *   chosen: "infer",
 *   reasoning: "Company data is available, asking would be slower",
 * });
 *
 * // Record the outcome
 * runtime.recordOutcome(decisionId, {
 *   success: true,
 *   result: { hasBudget: true, estimated: "$50k" },
 *   summary: "Inferred budget of $50k from company revenue",
 * });
 *
 * // End the run
 * runtime.endRun(true, "Qualified 10 leads successfully");
 * ```
 */
export class Runtime {
  private runs: Map<string, Run> = new Map();
  private currentRun: Run | null = null;
  private currentNodeId = "unknown";

  /**
   * Start a new run.
   */
  startRun(goalId: string, goalDescription = "", inputData: Record<string, unknown> = {}): string {
    const runId = generateId("run");

    const run: Run = {
      id: runId,
      goalId,
      goalDescription,
      status: RunStatus.RUNNING,
      inputData,
      outputData: {},
      decisions: [],
      startedAt: new Date(),
      endedAt: null,
      narrative: "",
    };

    this.runs.set(runId, run);
    this.currentRun = run;

    return runId;
  }

  /**
   * End the current run.
   */
  endRun(success: boolean, narrative = "", outputData: Record<string, unknown> = {}): void {
    if (!this.currentRun) {
      throw new Error("No active run to end");
    }

    this.currentRun.status = success ? RunStatus.COMPLETED : RunStatus.FAILED;
    this.currentRun.endedAt = new Date();
    this.currentRun.narrative = narrative;
    this.currentRun.outputData = outputData;

    this.currentRun = null;
  }

  /**
   * Set the current node context.
   */
  setCurrentNode(nodeId: string): void {
    this.currentNodeId = nodeId;
  }

  /**
   * Record a decision.
   */
  decide(params: {
    nodeId?: string;
    decisionType?: DecisionType;
    intent: string;
    options: Option[];
    chosen: string;
    reasoning: string;
  }): string {
    if (!this.currentRun) {
      throw new Error("No active run - call startRun first");
    }

    const decisionId = generateId("dec");

    const decision: Decision = {
      id: decisionId,
      nodeId: params.nodeId ?? this.currentNodeId,
      decisionType: params.decisionType ?? DecisionType.PATH_CHOICE,
      intent: params.intent,
      options: params.options,
      chosen: params.chosen,
      reasoning: params.reasoning,
      outcome: null,
      timestamp: new Date(),
    };

    this.currentRun.decisions.push(decision);

    return decisionId;
  }

  /**
   * Record the outcome of a decision.
   */
  recordOutcome(
    decisionId: string,
    outcome: {
      success: boolean;
      result?: unknown;
      summary?: string;
      errorType?: string;
      errorMessage?: string;
      durationMs?: number;
    }
  ): void {
    if (!this.currentRun) {
      throw new Error("No active run");
    }

    const decision = this.currentRun.decisions.find((d) => d.id === decisionId);
    if (!decision) {
      throw new Error(`Decision not found: ${decisionId}`);
    }

    decision.outcome = {
      success: outcome.success,
      result: outcome.result ?? null,
      summary: outcome.summary ?? "",
      errorType: outcome.errorType ?? null,
      errorMessage: outcome.errorMessage ?? null,
      durationMs: outcome.durationMs ?? 0,
    };
  }

  /**
   * Get the current run.
   */
  getCurrentRun(): Run | null {
    return this.currentRun;
  }

  /**
   * Get a run by ID.
   */
  getRun(runId: string): Run | undefined {
    return this.runs.get(runId);
  }

  /**
   * Get all runs.
   */
  getAllRuns(): Run[] {
    return Array.from(this.runs.values());
  }

  /**
   * Export runs to JSON.
   */
  toJSON(): string {
    return JSON.stringify(Array.from(this.runs.values()), null, 2);
  }
}
