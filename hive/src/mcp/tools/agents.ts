/**
 * Agent Status MCP Tools
 *
 * Tools for monitoring connected SDK agent instances:
 * - hive_agents_list: List all connected SDK instances
 * - hive_agent_health_check: Check health of specific agent
 * - hive_agents_summary: Get fleet health overview
 */
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ApiClient } from "../utils/api-client";
import {
  createSuccessResponse,
  handleToolError,
} from "../utils/response-helpers";

export interface ControlEmitter {
  getConnectedCount: (teamId: string) => number;
  getConnectedInstances: (teamId: string) => Array<{
    instance_id: string;
    agent?: string;
    policy_id?: string | null;
    connected_at: string;
    last_heartbeat: string;
  }>;
}

export function registerAgentTools(
  server: McpServer,
  api: ApiClient,
  getControlEmitter: () => ControlEmitter | undefined
) {
  // ==================== hive_agents_list ====================
  server.tool(
    "hive_agents_list",
    "Get list of all connected SDK agent instances with health status and connection details",
    {
      includeMetrics: z
        .boolean()
        .default(false)
        .describe("Include per-agent metrics (connection duration, heartbeat lag)"),
    },
    async (params) => {
      try {
        const controlEmitter = getControlEmitter();
        const result = api.agents.getList(controlEmitter);

        if (params.includeMetrics && result.instances) {
          const now = Date.now();
          const enrichedInstances = (result.instances as Array<{
            instance_id: string;
            connected_at: string;
            last_heartbeat: string;
          }>).map((instance) => {
            const connectedAt = new Date(instance.connected_at).getTime();
            const lastHeartbeat = new Date(instance.last_heartbeat).getTime();

            return {
              ...instance,
              metrics: {
                connection_duration_ms: now - connectedAt,
                connection_duration_seconds: Math.round((now - connectedAt) / 1000),
                heartbeat_lag_ms: now - lastHeartbeat,
                heartbeat_lag_seconds: Math.round((now - lastHeartbeat) / 1000),
                is_healthy: now - lastHeartbeat < 60000,
              },
            };
          });

          return createSuccessResponse({
            ...result,
            instances: enrichedInstances,
          });
        }

        return createSuccessResponse(result);
      } catch (error: unknown) {
        return handleToolError(error, "hive_agents_list");
      }
    }
  );

  // ==================== hive_agent_health_check ====================
  server.tool(
    "hive_agent_health_check",
    "Check health of a specific agent by instance ID or agent name. Returns health status, last heartbeat, and connection details.",
    {
      instanceId: z
        .string()
        .optional()
        .describe("SDK instance ID to check"),
      agentName: z
        .string()
        .optional()
        .describe("Agent name to filter (returns all instances with this name)"),
    },
    async (params) => {
      try {
        if (!params.instanceId && !params.agentName) {
          return handleToolError(
            new Error("Either instanceId or agentName is required"),
            "hive_agent_health_check"
          );
        }

        const controlEmitter = getControlEmitter();
        const result = api.agents.getList(controlEmitter);

        if (!result.instances || result.instances.length === 0) {
          return createSuccessResponse({
            found: false,
            message: "No agents connected",
            query: params,
          });
        }

        const now = Date.now();
        const STALE_THRESHOLD_MS = 60000; // 60 seconds

        // Filter instances based on query
        const instances = (result.instances as Array<{
          instance_id: string;
          agent?: string;
          connected_at: string;
          last_heartbeat: string;
        }>).filter((instance) => {
          if (params.instanceId && instance.instance_id === params.instanceId) {
            return true;
          }
          if (params.agentName && instance.agent === params.agentName) {
            return true;
          }
          return false;
        });

        if (instances.length === 0) {
          return createSuccessResponse({
            found: false,
            message: params.instanceId
              ? `Instance ${params.instanceId} not found`
              : `No instances found for agent ${params.agentName}`,
            query: params,
            total_connected: result.count,
          });
        }

        // Enrich with health status
        const healthResults = instances.map((instance) => {
          const lastHeartbeat = new Date(instance.last_heartbeat).getTime();
          const heartbeatLag = now - lastHeartbeat;
          const isHealthy = heartbeatLag < STALE_THRESHOLD_MS;

          return {
            instance_id: instance.instance_id,
            agent_name: instance.agent || "unknown",
            status: isHealthy ? "healthy" : "unhealthy",
            last_heartbeat: instance.last_heartbeat,
            last_heartbeat_ago_seconds: Math.round(heartbeatLag / 1000),
            connected_at: instance.connected_at,
            connection_duration_seconds: Math.round(
              (now - new Date(instance.connected_at).getTime()) / 1000
            ),
            health_threshold_seconds: STALE_THRESHOLD_MS / 1000,
          };
        });

        return createSuccessResponse({
          found: true,
          count: healthResults.length,
          instances: healthResults,
          summary: {
            healthy: healthResults.filter((h) => h.status === "healthy").length,
            unhealthy: healthResults.filter((h) => h.status === "unhealthy").length,
          },
        });
      } catch (error: unknown) {
        return handleToolError(error, "hive_agent_health_check");
      }
    }
  );

  // ==================== hive_agents_summary ====================
  server.tool(
    "hive_agents_summary",
    "Get summary of agent fleet health: total active, healthy count, unhealthy count, and breakdown by agent name",
    {},
    async () => {
      try {
        const controlEmitter = getControlEmitter();
        const result = api.agents.getSummary(controlEmitter);
        return createSuccessResponse(result);
      } catch (error: unknown) {
        return handleToolError(error, "hive_agents_summary");
      }
    }
  );
}
