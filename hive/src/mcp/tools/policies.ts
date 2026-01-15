/**
 * Policy Management MCP Tools
 *
 * Tools for managing control policies:
 * - hive_policies_list: List all policies
 * - hive_policy_get: Get specific policy with rules
 * - hive_policy_create: Create new policy
 * - hive_policy_update: Update policy
 * - hive_policy_clear: Clear all rules from policy
 */
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ApiClient } from "../utils/api-client";
import {
  createSuccessResponse,
  handleToolError,
} from "../utils/response-helpers";

export function registerPolicyTools(server: McpServer, api: ApiClient) {
  // ==================== hive_policies_list ====================
  server.tool(
    "hive_policies_list",
    "List all policies for the team. Returns policy IDs, names, and rule counts.",
    {
      limit: z
        .number()
        .min(1)
        .max(100)
        .default(100)
        .describe("Maximum policies to return"),
      offset: z
        .number()
        .min(0)
        .default(0)
        .describe("Number of policies to skip"),
    },
    async (params) => {
      try {
        const policies = await api.policy.list({
          limit: params.limit,
          offset: params.offset,
        });

        // Summarize policies
        const summary = (policies as unknown as Array<{
          _id?: string;
          id?: string;
          name?: string;
          budgets?: unknown[];
          throttles?: unknown[];
          blocks?: unknown[];
          degradations?: unknown[];
        }>).map((p) => ({
          id: p._id || p.id || "unknown",
          name: p.name || "Unnamed Policy",
          rule_counts: {
            budgets: p.budgets?.length || 0,
            throttles: p.throttles?.length || 0,
            blocks: p.blocks?.length || 0,
            degradations: p.degradations?.length || 0,
          },
        }));

        return createSuccessResponse({
          count: policies.length,
          policies: summary,
        });
      } catch (error) {
        return handleToolError(error, "hive_policies_list");
      }
    }
  );

  // ==================== hive_policy_get ====================
  server.tool(
    "hive_policy_get",
    'Get a specific policy with all rules (budgets, throttles, blocks, degradations). Use "default" to get the team\'s default policy.',
    {
      policyId: z
        .string()
        .default("default")
        .describe('Policy ID or "default" for team default'),
    },
    async (params) => {
      try {
        const policy = await api.policy.get(params.policyId);

        if (!policy) {
          return handleToolError(
            new Error(`Policy ${params.policyId} not found`),
            "hive_policy_get"
          );
        }

        return createSuccessResponse(policy);
      } catch (error) {
        return handleToolError(error, "hive_policy_get");
      }
    }
  );

  // ==================== hive_policy_create ====================
  server.tool(
    "hive_policy_create",
    "Create a new policy for the team. New policies start empty (no rules).",
    {
      name: z.string().min(1).describe("Policy name"),
    },
    async (params) => {
      try {
        const policy = await api.policy.create(params.name);

        return createSuccessResponse({
          success: true,
          message: "Policy created",
          policy,
        });
      } catch (error) {
        return handleToolError(error, "hive_policy_create");
      }
    }
  );

  // ==================== hive_policy_update ====================
  server.tool(
    "hive_policy_update",
    "Update a policy's name or replace all rules. For individual rule changes, use budget/throttle/block rule tools.",
    {
      policyId: z
        .string()
        .default("default")
        .describe('Policy ID or "default" for team default'),
      name: z.string().optional().describe("New policy name"),
      budgets: z
        .array(z.any())
        .optional()
        .describe("Complete budgets array (replaces all budgets)"),
      throttles: z
        .array(z.any())
        .optional()
        .describe("Complete throttles array (replaces all throttles)"),
      blocks: z
        .array(z.any())
        .optional()
        .describe("Complete blocks array (replaces all blocks)"),
      degradations: z
        .array(z.any())
        .optional()
        .describe("Complete degradations array (replaces all degradations)"),
    },
    async (params) => {
      try {
        // Only pass defined fields
        const updates: {
          name?: string;
          budgets?: unknown[];
          throttles?: unknown[];
          blocks?: unknown[];
          degradations?: unknown[];
        } = {};

        if (params.name !== undefined) updates.name = params.name;
        if (params.budgets !== undefined) updates.budgets = params.budgets;
        if (params.throttles !== undefined) updates.throttles = params.throttles;
        if (params.blocks !== undefined) updates.blocks = params.blocks;
        if (params.degradations !== undefined)
          updates.degradations = params.degradations;

        if (Object.keys(updates).length === 0) {
          return handleToolError(
            new Error("No updates provided"),
            "hive_policy_update"
          );
        }

        const policy = await api.policy.update(params.policyId, updates);

        return createSuccessResponse({
          success: true,
          updated_fields: Object.keys(updates),
          policy,
        });
      } catch (error) {
        return handleToolError(error, "hive_policy_update");
      }
    }
  );

  // ==================== hive_policy_clear ====================
  server.tool(
    "hive_policy_clear",
    "Clear all rules from a policy (budgets, throttles, blocks, degradations). The policy itself is preserved.",
    {
      policyId: z
        .string()
        .default("default")
        .describe('Policy ID or "default" for team default'),
      confirm: z
        .boolean()
        .describe("Set to true to confirm clearing all rules"),
    },
    async (params) => {
      try {
        if (!params.confirm) {
          return createSuccessResponse({
            warning:
              "This will delete ALL rules from the policy. Set confirm=true to proceed.",
            policy_id: params.policyId,
          });
        }

        const policy = await api.policy.clear(params.policyId);

        return createSuccessResponse({
          success: true,
          message: "All rules cleared from policy",
          policy,
        });
      } catch (error) {
        return handleToolError(error, "hive_policy_clear");
      }
    }
  );
}
