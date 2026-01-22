/**
 * Budget MCP Tools
 *
 * Tools for cost control and budget management:
 * - hive_budget_get: Get budget status
 * - hive_budget_reset: Reset budget spend
 * - hive_budget_validate: Validate request against budgets
 * - hive_budget_rule_create: Create budget rule
 * - hive_budget_rule_update: Update budget rule
 * - hive_budget_rule_delete: Delete budget rule
 */
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ApiClient } from "../utils/api-client";
import {
  createSuccessResponse,
  handleToolError,
} from "../utils/response-helpers";
import {
  idSchema,
  budgetTypeSchema,
  limitActionSchema,
  validationContextSchema,
  budgetAlertSchema,
  budgetNotificationsSchema,
} from "../utils/schema-helpers";

export function registerBudgetTools(server: McpServer, api: ApiClient) {
  // ==================== hive_budget_get ====================
  server.tool(
    "hive_budget_get",
    "Get budget status including spend, limit, burn rate, and projected spend for a specific budget ID",
    {
      budgetId: idSchema.describe("Budget ID to query"),
    },
    async (params) => {
      try {
        const result = await api.budget.getStatus(params.budgetId);
        return createSuccessResponse(result);
      } catch (error: unknown) {
        return handleToolError(error, "hive_budget_get");
      }
    }
  );

  // ==================== hive_budget_reset ====================
  server.tool(
    "hive_budget_reset",
    "Reset a budget spend counter to zero. Use when starting new billing cycle or after resolving overage.",
    {
      budgetId: idSchema.describe("Budget ID to reset"),
      reason: z
        .string()
        .optional()
        .describe("Reason for reset (for audit trail)"),
    },
    async (params) => {
      try {
        const result = await api.budget.reset(params.budgetId);
        return createSuccessResponse({
          ...result,
          reason: params.reason,
          reset_at: new Date().toISOString(),
        });
      } catch (error: unknown) {
        return handleToolError(error, "hive_budget_reset");
      }
    }
  );

  // ==================== hive_budget_validate ====================
  server.tool(
    "hive_budget_validate",
    "Validate if a request should be allowed based on budget constraints. Returns allow/throttle/degrade/block decision with authoritative spend data.",
    {
      budgetId: z
        .string()
        .optional()
        .describe("Specific budget ID to validate against"),
      estimatedCost: z
        .number()
        .min(0)
        .describe("Estimated cost of the request in USD"),
      context: validationContextSchema
        .optional()
        .describe(
          "Context for multi-budget matching (agent, tenant_id, customer_id, feature, tags)"
        ),
      localSpend: z
        .number()
        .optional()
        .describe("Local spend tracked by SDK (for drift detection)"),
    },
    async (params) => {
      try {
        const result = await api.budget.validate({
          budgetId: params.budgetId,
          estimatedCost: params.estimatedCost,
          context: params.context,
          localSpend: params.localSpend,
        });
        return createSuccessResponse(result);
      } catch (error: unknown) {
        return handleToolError(error, "hive_budget_validate");
      }
    }
  );

  // ==================== hive_budget_rule_create ====================
  server.tool(
    "hive_budget_rule_create",
    "Create a new budget rule within a policy. Budget rules define spending limits and actions when exceeded.",
    {
      policyId: z
        .string()
        .default("default")
        .describe('Policy ID (use "default" for default policy)'),
      id: idSchema.describe("Unique budget rule ID"),
      name: z.string().min(1).describe("Human-readable budget name"),
      type: budgetTypeSchema.describe("Budget scope type"),
      limit: z.number().min(0).describe("Budget limit in USD"),
      limitAction: limitActionSchema
        .default("kill")
        .describe("Action when limit exceeded"),
      degradeToModel: z
        .string()
        .optional()
        .describe('Target model for degradation (required when limitAction is "degrade")'),
      degradeToProvider: z
        .string()
        .optional()
        .describe('Target provider for degradation (required when limitAction is "degrade")'),
      tags: z
        .array(z.string())
        .optional()
        .describe('Tags for tag-type budgets (required when type is "tag")'),
      alerts: z
        .array(budgetAlertSchema)
        .default([
          { threshold: 80, enabled: true },
          { threshold: 95, enabled: true },
        ])
        .describe("Alert thresholds as percentage of limit"),
      notifications: budgetNotificationsSchema
        .default({
          inApp: true,
          email: false,
          emailRecipients: [],
          webhook: false,
        })
        .describe("Notification settings"),
    },
    async (params) => {
      try {
        // Validate degradation requirements
        if (params.limitAction === "degrade") {
          if (!params.degradeToModel || !params.degradeToProvider) {
            return handleToolError(
              new Error(
                "degradeToModel and degradeToProvider are required when limitAction is 'degrade'"
              ),
              "hive_budget_rule_create"
            );
          }
        }

        // Validate tag requirements
        if (params.type === "tag") {
          if (!params.tags || params.tags.length === 0) {
            return handleToolError(
              new Error("tags array is required when type is 'tag'"),
              "hive_budget_rule_create"
            );
          }
        }

        const result = await api.policy.addBudgetRule(params.policyId, {
          id: params.id,
          name: params.name,
          type: params.type,
          limit: params.limit,
          spent: 0,
          limitAction: params.limitAction,
          degradeToModel: params.degradeToModel,
          degradeToProvider: params.degradeToProvider,
          tags: params.tags,
          alerts: params.alerts,
          notifications: params.notifications,
        });

        return createSuccessResponse({
          success: true,
          budget_id: params.id,
          policy: result,
        });
      } catch (error: unknown) {
        return handleToolError(error, "hive_budget_rule_create");
      }
    }
  );

  // ==================== hive_budget_rule_update ====================
  server.tool(
    "hive_budget_rule_update",
    "Update an existing budget rule. Only provided fields will be updated.",
    {
      policyId: z
        .string()
        .default("default")
        .describe('Policy ID (use "default" for default policy)'),
      budgetId: idSchema.describe("Budget rule ID to update"),
      name: z.string().optional().describe("New budget name"),
      limit: z.number().min(0).optional().describe("New budget limit in USD"),
      limitAction: limitActionSchema.optional().describe("New action when limit exceeded"),
      degradeToModel: z
        .string()
        .optional()
        .describe("New target model for degradation"),
      degradeToProvider: z
        .string()
        .optional()
        .describe("New target provider for degradation"),
      alerts: z
        .array(budgetAlertSchema)
        .optional()
        .describe("New alert thresholds"),
    },
    async (params) => {
      try {
        // Get current policy to find and update the budget
        const policy = await api.policy.get(params.policyId);

        if (!policy) {
          return handleToolError(
            new Error("Policy not found"),
            "hive_budget_rule_update"
          );
        }

        const budgets = policy.budgets || [];
        const budgetIndex = budgets.findIndex(
          (b: { id: string }) => b.id === params.budgetId
        );

        if (budgetIndex === -1) {
          return handleToolError(
            new Error(`Budget ${params.budgetId} not found in policy`),
            "hive_budget_rule_update"
          );
        }

        // Update the budget with new values
        const updatedBudget = {
          ...budgets[budgetIndex],
          ...(params.name && { name: params.name }),
          ...(params.limit !== undefined && { limit: params.limit }),
          ...(params.limitAction && { limitAction: params.limitAction }),
          ...(params.degradeToModel && { degradeToModel: params.degradeToModel }),
          ...(params.degradeToProvider && { degradeToProvider: params.degradeToProvider }),
          ...(params.alerts && { alerts: params.alerts }),
        };

        budgets[budgetIndex] = updatedBudget;

        const result = await api.policy.update(params.policyId, { budgets });

        return createSuccessResponse({
          success: true,
          budget_id: params.budgetId,
          updated_fields: Object.keys(params).filter(
            (k) =>
              k !== "policyId" &&
              k !== "budgetId" &&
              params[k as keyof typeof params] !== undefined
          ),
          policy: result,
        });
      } catch (error: unknown) {
        return handleToolError(error, "hive_budget_rule_update");
      }
    }
  );

  // ==================== hive_budget_rule_delete ====================
  server.tool(
    "hive_budget_rule_delete",
    "Delete a budget rule from a policy",
    {
      policyId: z
        .string()
        .default("default")
        .describe('Policy ID (use "default" for default policy)'),
      budgetId: idSchema.describe("Budget rule ID to delete"),
    },
    async (params) => {
      try {
        // Get current policy to remove the budget
        const policy = await api.policy.get(params.policyId);

        if (!policy) {
          return handleToolError(
            new Error("Policy not found"),
            "hive_budget_rule_delete"
          );
        }

        const budgets = policy.budgets || [];
        const budgetIndex = budgets.findIndex(
          (b: { id: string }) => b.id === params.budgetId
        );

        if (budgetIndex === -1) {
          return handleToolError(
            new Error(`Budget ${params.budgetId} not found in policy`),
            "hive_budget_rule_delete"
          );
        }

        // Remove the budget
        budgets.splice(budgetIndex, 1);

        const result = await api.policy.update(params.policyId, { budgets });

        return createSuccessResponse({
          success: true,
          deleted_budget_id: params.budgetId,
          remaining_budgets: budgets.length,
          policy: result,
        });
      } catch (error: unknown) {
        return handleToolError(error, "hive_budget_rule_delete");
      }
    }
  );
}
