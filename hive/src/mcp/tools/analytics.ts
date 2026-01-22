/**
 * Analytics MCP Tools
 *
 * Tools for querying analytics and insights:
 * - hive_analytics_wide: Dashboard analytics with daily resolution
 * - hive_analytics_narrow: Hourly analytics for today
 * - hive_insights: Actionable insights and anomalies
 * - hive_metrics: Summary metrics with period-over-period change
 * - hive_logs: Raw or aggregated event logs
 */
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ApiClient } from "../utils/api-client";
import {
  createSuccessResponse,
  handleToolError,
} from "../utils/response-helpers";
import { analyticsWindowSchema, dateTimeSchema } from "../utils/schema-helpers";

export function registerAnalyticsTools(server: McpServer, api: ApiClient) {
  // ==================== hive_analytics_wide ====================
  server.tool(
    "hive_analytics_wide",
    "Get dashboard analytics with daily resolution. Use for trend analysis over days/weeks/months. Returns volume, cost, tokens, and performance data points by day.",
    {
      window: analyticsWindowSchema.describe(
        "Time window: all_time, this_month, this_week, last_2_weeks, or today"
      ),
    },
    async (params) => {
      try {
        const result = await api.analytics.getWide(params.window);
        return createSuccessResponse(result);
      } catch (error: unknown) {
        return handleToolError(error, "hive_analytics_wide");
      }
    }
  );

  // ==================== hive_analytics_narrow ====================
  server.tool(
    "hive_analytics_narrow",
    "Get hourly analytics for today. Use for intraday monitoring, detecting recent spikes, and real-time cost tracking.",
    {},
    async () => {
      try {
        const result = await api.analytics.getNarrow();
        return createSuccessResponse(result);
      } catch (error: unknown) {
        return handleToolError(error, "hive_analytics_narrow");
      }
    }
  );

  // ==================== hive_insights ====================
  server.tool(
    "hive_insights",
    "Get actionable insights: cost spikes, anomalies, trends, cache efficiency, and recommendations. Critical for autonomous monitoring and cost control.",
    {
      days: z
        .number()
        .min(1)
        .max(90)
        .default(30)
        .describe("Analysis period in days (1-90)"),
    },
    async (params) => {
      try {
        const result = await api.analytics.getInsights(params.days);
        return createSuccessResponse(result);
      } catch (error: unknown) {
        return handleToolError(error, "hive_insights");
      }
    }
  );

  // ==================== hive_metrics ====================
  server.tool(
    "hive_metrics",
    "Get summary metrics with period-over-period percentage change. Good for quick health checks and comparing current vs previous period.",
    {
      days: z
        .number()
        .min(1)
        .max(365)
        .default(30)
        .describe("Period in days for current window and comparison"),
    },
    async (params) => {
      try {
        const result = await api.analytics.getMetrics(params.days);
        return createSuccessResponse(result);
      } catch (error: unknown) {
        return handleToolError(error, "hive_metrics");
      }
    }
  );

  // ==================== hive_logs ====================
  server.tool(
    "hive_logs",
    "Query raw or aggregated event logs. Use for investigation, drill-down, and detailed analysis. Supports grouping by model, agent, or provider.",
    {
      start: dateTimeSchema.describe("Start time (ISO 8601 format)"),
      end: dateTimeSchema.describe("End time (ISO 8601 format)"),
      groupBy: z
        .enum(["model", "agent", "provider", "model,agent", "model,provider"])
        .optional()
        .describe(
          "Aggregate by field(s). If not specified, returns raw log rows."
        ),
      limit: z
        .number()
        .min(1)
        .max(5000)
        .default(500)
        .describe("Maximum rows/aggregations to return"),
      offset: z
        .number()
        .min(0)
        .default(0)
        .describe("Number of rows to skip (for pagination)"),
    },
    async (params) => {
      try {
        // Validate date range
        const startDate = new Date(params.start);
        const endDate = new Date(params.end);

        if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) {
          return handleToolError(
            new Error("Invalid date format. Use ISO 8601 format."),
            "hive_logs"
          );
        }

        if (endDate < startDate) {
          return handleToolError(
            new Error("End date must be after start date"),
            "hive_logs"
          );
        }

        // Warn if range is too large
        const rangeDays =
          (endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24);
        if (rangeDays > 90 && !params.groupBy) {
          console.warn(
            `[MCP] hive_logs: Large date range (${rangeDays.toFixed(
              0
            )} days) without aggregation may be slow`
          );
        }

        const result = await api.analytics.getLogs({
          start: params.start,
          end: params.end,
          groupBy: params.groupBy,
          limit: params.limit,
          offset: params.offset,
        });

        return createSuccessResponse(result);
      } catch (error: unknown) {
        return handleToolError(error, "hive_logs");
      }
    }
  );
}
