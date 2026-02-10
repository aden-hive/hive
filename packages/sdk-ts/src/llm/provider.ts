/**
 * LLM Provider abstraction for pluggable LLM backends.
 *
 * Implementations should handle:
 * - API authentication
 * - Request/response formatting
 * - Token counting
 * - Error handling
 */

import { z } from "zod";

/**
 * Response from an LLM call.
 */
export const LLMResponseSchema = z.object({
  content: z.string(),
  model: z.string(),
  inputTokens: z.number().default(0),
  outputTokens: z.number().default(0),
  stopReason: z.string().default(""),
  rawResponse: z.any().optional(),
});

export type LLMResponse = z.infer<typeof LLMResponseSchema>;

/**
 * A tool the LLM can use.
 */
export const ToolSchema = z.object({
  name: z.string(),
  description: z.string(),
  parameters: z.record(z.any()).default({}),
});

export type Tool = z.infer<typeof ToolSchema>;

/**
 * A tool call requested by the LLM.
 */
export const ToolUseSchema = z.object({
  id: z.string(),
  name: z.string(),
  input: z.record(z.any()),
});

export type ToolUse = z.infer<typeof ToolUseSchema>;

/**
 * Result of executing a tool.
 */
export const ToolResultSchema = z.object({
  toolUseId: z.string(),
  content: z.string(),
  isError: z.boolean().default(false),
});

export type ToolResult = z.infer<typeof ToolResultSchema>;

/**
 * Message in a conversation.
 */
export interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

/**
 * Options for LLM completion.
 */
export interface CompletionOptions {
  messages: Message[];
  system?: string;
  tools?: Tool[];
  maxTokens?: number;
  jsonMode?: boolean;
  responseFormat?: {
    type: "json_object" | "json_schema";
    jsonSchema?: {
      name: string;
      schema: Record<string, unknown>;
    };
  };
}

/**
 * Options for tool-use completion loop.
 */
export interface ToolCompletionOptions extends CompletionOptions {
  tools: Tool[];
  toolExecutor: (toolUse: ToolUse) => Promise<ToolResult>;
  maxIterations?: number;
}

/**
 * Abstract LLM provider - plug in any LLM backend.
 */
export interface LLMProvider {
  /**
   * Generate a completion from the LLM.
   */
  complete(options: CompletionOptions): Promise<LLMResponse>;

  /**
   * Run a tool-use loop until the LLM produces a final response.
   */
  completeWithTools(options: ToolCompletionOptions): Promise<LLMResponse>;

  /**
   * Get the model name.
   */
  getModel(): string;
}

/**
 * Base class for LLM providers with common functionality.
 */
export abstract class BaseLLMProvider implements LLMProvider {
  protected model: string;

  constructor(model: string) {
    this.model = model;
  }

  abstract complete(options: CompletionOptions): Promise<LLMResponse>;

  async completeWithTools(options: ToolCompletionOptions): Promise<LLMResponse> {
    const { toolExecutor, maxIterations = 10, ...completionOptions } = options;
    let messages = [...options.messages];
    let iterations = 0;

    while (iterations < maxIterations) {
      iterations++;

      const response = await this.complete({
        ...completionOptions,
        messages,
      });

      // Check if the response contains tool calls
      const toolCalls = this.extractToolCalls(response);

      if (toolCalls.length === 0) {
        // No tool calls, return the final response
        return response;
      }

      // Execute each tool call
      const toolResults: ToolResult[] = [];
      for (const toolCall of toolCalls) {
        const result = await toolExecutor(toolCall);
        toolResults.push(result);
      }

      // Add assistant message and tool results to conversation
      messages = [
        ...messages,
        { role: "assistant" as const, content: response.content },
        ...toolResults.map((result) => ({
          role: "user" as const,
          content: `Tool result for ${result.toolUseId}: ${result.content}`,
        })),
      ];
    }

    throw new Error(`Tool use loop exceeded maximum iterations (${maxIterations})`);
  }

  getModel(): string {
    return this.model;
  }

  /**
   * Extract tool calls from a response.
   * Override in subclasses for provider-specific parsing.
   */
  protected extractToolCalls(_response: LLMResponse): ToolUse[] {
    // Default implementation returns empty - subclasses should override
    return [];
  }
}

/**
 * Simple mock LLM provider for testing.
 */
export class MockLLMProvider extends BaseLLMProvider {
  private responses: string[];
  private responseIndex = 0;

  constructor(responses: string[] = ["Mock response"]) {
    super("mock-model");
    this.responses = responses;
  }

  async complete(_options: CompletionOptions): Promise<LLMResponse> {
    const content = this.responses[this.responseIndex % this.responses.length];
    this.responseIndex++;

    return {
      content,
      model: this.model,
      inputTokens: 10,
      outputTokens: 20,
      stopReason: "end_turn",
    };
  }
}
