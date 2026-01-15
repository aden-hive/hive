/**
 * Aden Control Service
 *
 * Manages control policies and events for the Aden SDK.
 * Provides policy management, event storage, and budget tracking.
 */

import { randomUUID } from "crypto";
import * as tsdbService from "../tsdb/tsdb_service";
import pricingService from "../tsdb/pricing_service";
import { getTeamPool, buildSchemaName } from "../tsdb/team_context";
// TODO: Integrate mail service from @aden/administration
// import mailService from "../mail_service/mail_service";
import llmEventBatcher from "./llm_event_batcher";
import { registerHttpAgent } from "./control_sockets";

// In-memory budget tracking (could be moved to Redis for distributed tracking)
// Map: budget_id -> { spent: number, lastReset: Date }
const budgetTracker = new Map<string, { spent: number; lastReset: Date }>();

// Notification cooldown tracking to prevent spam
// Map: "budget_id:alert_type:threshold" -> timestamp
const notificationCooldowns = new Map<string, number>();
const NOTIFICATION_COOLDOWN_MS = 15 * 60 * 1000; // 15 minutes

interface MongoCollection {
  find: (query: Record<string, unknown>) => { toArray: () => Promise<unknown[]>; sort: (sort: Record<string, number>) => { skip: (n: number) => { limit: (n: number) => { toArray: () => Promise<unknown[]> } } } };
  findOne: (query: Record<string, unknown>) => Promise<unknown>;
  insertOne: (doc: Record<string, unknown>) => Promise<unknown>;
  updateOne: (query: Record<string, unknown>, update: Record<string, unknown>, options?: Record<string, unknown>) => Promise<unknown>;
  deleteOne: (query: Record<string, unknown>) => Promise<{ deletedCount: number }>;
}

declare const _ACHO_MG_DB: { db: (name: string) => { collection: (name: string) => MongoCollection } };
declare const _ACHO_MDB_CONFIG: { ERP_DBNAME: string };
declare const _ACHO_MDB_COLLECTIONS: { ADEN_CONTROL_POLICIES: string; ADEN_CONTROL_CONTENT: string };
declare const _GLOBAL_CONST: { ARP_URL: string };

interface UserContext {
  user_id?: string;
  team_id?: string | number;
}

interface Budget {
  id: string;
  name: string;
  type: string;
  limit: number;
  spent?: number;
  limitAction?: string;
  degradeToModel?: string;
  degradeToProvider?: string;
  tagCategory?: string;
  tags?: string[];
  alerts?: Array<{ threshold: number; enabled: boolean }>;
  notifications?: {
    email?: boolean;
    emailRecipients?: string[];
    webhook?: boolean;
    webhookUrl?: string;
  };
  analytics?: {
    burnRate: number;
    projectedSpend: number;
    daysUntilLimit: number | null;
    usagePercent: number;
    projectedPercent: number;
    status: string;
    period: {
      daysInMonth: number;
      daysElapsed: number;
      daysRemaining: number;
      startOfMonth: string;
      endOfMonth: string;
    };
  };
}

interface Policy {
  id: string;
  team_id: string | number;
  name: string;
  version: string;
  budgets: Budget[];
  throttles: unknown[];
  blocks: unknown[];
  degradations: unknown[];
  alerts: unknown[];
  created_at: string;
  updated_at: string;
  created_by?: string;
  updated_by?: string;
}

interface ContentCapture {
  system_prompt?: string;
  messages?: unknown[];
  tools?: unknown[];
  params?: Record<string, unknown>;
  response_content?: string;
  finish_reason?: string;
  choice_count?: number;
  has_images?: boolean;
  image_urls?: string[];
}

interface MetricData {
  provider?: string;
  model?: string;
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  cached_tokens?: number;
  reasoning_tokens?: number;
  agent?: string;
  metadata?: Record<string, unknown>;
  trace_id?: string;
  span_id?: string;
  request_id?: string;
  call_sequence?: number;
  stream?: boolean;
  agent_stack?: string[];
  latency_ms?: number;
  content_capture?: ContentCapture;
}

interface Event {
  event_type: string;
  timestamp?: string;
  trace_id?: string;
  data?: MetricData;
  action?: string;
  original_model?: string;
  provider?: string;
  reason?: string;
  budget_id?: string;
  policy_id?: string;
  agent?: string;
  agent_name?: string;
  sdk_instance_id?: string;
  status?: string;
  requests_since_last?: number;
  message?: string;
  stack?: string;
}

/**
 * Get the MongoDB collection for control policies
 * @returns MongoDB collection
 */
function getPolicyCollection(): MongoCollection {
  return _ACHO_MG_DB
    .db(_ACHO_MDB_CONFIG.ERP_DBNAME)
    .collection(_ACHO_MDB_COLLECTIONS.ADEN_CONTROL_POLICIES);
}

/**
 * Calculate actual spend and burn rate analytics for a budget from TSDB data
 * Uses hybrid CA + base table approach for lowest latency
 */
async function calculateBudgetAnalyticsFromTsdb(teamId: string | number, budget: Budget): Promise<{
  spent: number;
  burnRate: number;
  projectedSpend: number;
  daysUntilLimit: number | null;
  usagePercent: number;
  projectedPercent: number;
  status: string;
  source: string;
  period: {
    daysInMonth: number;
    daysElapsed: number;
    daysRemaining: number;
    startOfMonth: string;
    endOfMonth: string;
  };
}> {
  const now = new Date();
  const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  const endOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const daysInMonth = endOfMonth.getDate();
  const daysElapsed = Math.max(
    1,
    Math.floor((now.getTime() - startOfMonth.getTime()) / (1000 * 60 * 60 * 24)) + 1
  );
  const daysRemaining = daysInMonth - daysElapsed + 1;

  // Today's midnight for CA vs base table split
  const todayMidnight = new Date();
  todayMidnight.setUTCHours(0, 0, 0, 0);

  try {
    const pool = await getTeamPool(teamId);
    const schema = buildSchemaName(teamId);
    const client = await pool.connect();

    try {
      // Explicitly set search_path to team schema before querying
      await client.query(`SET search_path TO ${schema}, public`);
      await tsdbService.ensureSchema(client);

      let spent = 0;
      const usedCA = false;

      // Determine which CA to use based on budget type
      // Note: CA (continuous aggregates) are disabled for now because:
      // 1. Team-specific schemas don't have CA tables populated
      // 2. CA tables need to be refreshed periodically
      // TODO: Enable CA once aggregation is set up per-team
      const canUseGlobalCA = false; // Disabled: CA not populated in team schemas
      const canUseAgentCA = false; // Disabled: agent may be in metadata->>'agent'

      // --- Query CA for historical data (before today) ---
      if (startOfMonth < todayMidnight) {
        if (canUseGlobalCA) {
          // Use daily CA for global budgets
          try {
            const caSql = `
              SELECT COALESCE(SUM(cost_total), 0) as total_cost
              FROM llm_events_daily_ca
              WHERE bucket >= $1 AND bucket < $2
            `;
            const caResult = await client.query(caSql, [
              startOfMonth.toISOString(),
              todayMidnight.toISOString(),
            ]);
            spent += parseFloat(caResult.rows[0]?.total_cost) || 0;
          } catch (caErr) {
            // CA not available, will fall back to base table
          }
        } else if (canUseAgentCA) {
          // Use agent CA for agent budgets
          try {
            const caSql = `
              SELECT COALESCE(SUM(cost_total), 0) as total_cost
              FROM llm_events_daily_by_agent_ca
              WHERE bucket >= $1 AND bucket < $2 AND agent = $3
            `;
            const caResult = await client.query(caSql, [
              startOfMonth.toISOString(),
              todayMidnight.toISOString(),
              budget.name,
            ]);
            spent += parseFloat(caResult.rows[0]?.total_cost) || 0;
          } catch (caErr) {
            // CA not available, will fall back to base table
          }
        }
      }

      // --- Query base table for today's data (always) + historical if CA failed ---
      const baseTableStart = usedCA ? todayMidnight : startOfMonth;

      const conditions = [`team_id = $1`, `"timestamp" >= $2`, `"timestamp" <= $3`];
      const values: unknown[] = [String(teamId), baseTableStart, now];
      const paramIndex = 4;

      // Apply budget-specific filter based on budget type
      const budgetFilter = getBudgetFilter(budget, paramIndex);
      if (budgetFilter) {
        conditions.push(budgetFilter.condition);
        values.push(budgetFilter.value);
      }

      const baseSql = `
        SELECT COALESCE(SUM(cost_total), 0) as total_cost
        FROM llm_events
        WHERE ${conditions.join(" AND ")}
      `;

      console.log(`[Aden Control] Budget analytics query for team ${teamId}, schema ${schema}:`);
      console.log(`[Aden Control] SQL: ${baseSql}`);
      console.log(`[Aden Control] Values:`, values);

      // Debug: check row count and cost
      const countResult = await client.query(`SELECT COUNT(*) as cnt FROM llm_events WHERE team_id = $1`, [String(teamId)]);
      console.log(`[Aden Control] Total rows in llm_events for team ${teamId}: ${countResult.rows[0]?.cnt}`);

      // Debug: check total cost regardless of timestamp filter
      const debugResult = await client.query(`SELECT SUM(cost_total) as total, MIN("timestamp") as min_ts, MAX("timestamp") as max_ts FROM llm_events WHERE team_id = $1`, [String(teamId)]);
      console.log(`[Aden Control] All-time cost: $${debugResult.rows[0]?.total}, timestamps: ${debugResult.rows[0]?.min_ts} to ${debugResult.rows[0]?.max_ts}`);

      const baseResult = await client.query(baseSql, values);
      console.log(`[Aden Control] Result:`, baseResult.rows[0]);

      spent += parseFloat(baseResult.rows[0]?.total_cost) || 0;
      console.log(`[Aden Control] Total spent for budget ${budget.name}: $${spent}`);

      // Calculate burn rate analytics
      const burnRate = daysElapsed > 0 ? spent / daysElapsed : 0;
      const projectedSpend = burnRate * daysInMonth;
      const remaining = Math.max(0, budget.limit - spent);
      const daysUntilLimit = burnRate > 0 ? remaining / burnRate : Infinity;
      const usagePercent = budget.limit > 0 ? (spent / budget.limit) * 100 : 0;
      const projectedPercent =
        budget.limit > 0 ? (projectedSpend / budget.limit) * 100 : 0;

      // Determine status based on projected spend and current usage
      let status = "healthy";
      if (usagePercent >= 100) {
        status = "exceeded";
      } else if (projectedPercent >= 100 || daysUntilLimit <= daysRemaining) {
        status = "at_risk";
      } else if (usagePercent >= 80 || projectedPercent >= 80) {
        status = "warning";
      }

      return {
        spent,
        burnRate,
        projectedSpend,
        daysUntilLimit: daysUntilLimit === Infinity ? null : daysUntilLimit,
        usagePercent,
        projectedPercent,
        status,
        source: usedCA ? "hybrid_ca" : "base_table",
        period: {
          daysInMonth,
          daysElapsed,
          daysRemaining,
          startOfMonth: startOfMonth.toISOString(),
          endOfMonth: endOfMonth.toISOString(),
        },
      };
    } finally {
      client.release();
    }
  } catch (error) {
    console.error(
      `[Aden Control] Failed to calculate budget analytics from TSDB:`,
      (error as Error).message
    );
    // Fall back to in-memory tracker with minimal analytics
    const tracker = budgetTracker.get(budget.id);
    const spent = tracker?.spent ?? budget.spent ?? 0;
    const burnRate = daysElapsed > 0 ? spent / daysElapsed : 0;
    const projectedSpend = burnRate * daysInMonth;

    return {
      spent,
      burnRate,
      projectedSpend,
      daysUntilLimit: burnRate > 0 ? Math.max(0, budget.limit - spent) / burnRate : null,
      usagePercent: budget.limit > 0 ? (spent / budget.limit) * 100 : 0,
      projectedPercent: budget.limit > 0 ? (projectedSpend / budget.limit) * 100 : 0,
      status: "unknown",
      source: "fallback",
      period: {
        daysInMonth,
        daysElapsed,
        daysRemaining,
        startOfMonth: startOfMonth.toISOString(),
        endOfMonth: endOfMonth.toISOString(),
      },
    };
  }
}

/**
 * Get policy for a team by policy ID
 */
async function getPolicy(teamId: string | number | null, policyId: string | null = null, userContext: UserContext | null = null): Promise<Policy> {
  if (!teamId) {
    teamId = userContext?.team_id ?? null;
  }
  if (!teamId) {
    throw new Error("team_id is required to get policy");
  }

  // Use "default" as the actual policy ID when not specified
  const actualPolicyId = policyId || "default";

  const collection = getPolicyCollection();
  let policyDoc = await collection.findOne({ team_id: teamId, id: actualPolicyId }) as Policy & { _id?: unknown } | null;

  if (!policyDoc) {
    // Create empty policy with the specified ID
    const newPolicy: Policy & { _id?: unknown } = {
      id: actualPolicyId,
      team_id: teamId,
      name: actualPolicyId === "default" ? "Default Policy" : "New Policy",
      version: randomUUID().slice(0, 8),
      budgets: [],
      throttles: [],
      blocks: [],
      degradations: [],
      alerts: [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      ...(userContext?.user_id && { created_by: userContext.user_id }),
    };
    await collection.insertOne(newPolicy as unknown as Record<string, unknown>);
    policyDoc = newPolicy;
  }

  // Remove MongoDB _id from response
  const { _id, ...policy } = policyDoc;

  // Enrich budget rules with actual spend and analytics from TSDB
  if (policy.budgets && policy.budgets.length > 0) {
    policy.budgets = await Promise.all(
      policy.budgets.map(async (budget) => {
        const analytics = await calculateBudgetAnalyticsFromTsdb(teamId!, budget);
        return {
          ...budget,
          spent: analytics.spent,
          analytics: {
            burnRate: analytics.burnRate,
            projectedSpend: analytics.projectedSpend,
            daysUntilLimit: analytics.daysUntilLimit,
            usagePercent: analytics.usagePercent,
            projectedPercent: analytics.projectedPercent,
            status: analytics.status,
            period: analytics.period,
          },
        };
      })
    );
  }

  return policy as Policy;
}

/**
 * Update policy for a team (or create new if policyId is null)
 */
async function updatePolicy(teamId: string | number | null, policyId: string | null, policyUpdate: Partial<Policy>, userContext: UserContext | null = null): Promise<Policy> {
  if (!teamId) {
    teamId = userContext?.team_id ?? null;
  }
  if (!teamId) {
    throw new Error("team_id is required to update policy");
  }

  // Use "default" as the actual policy ID when not specified
  const actualPolicyId = policyId || "default";

  const collection = getPolicyCollection();

  const updateFields = {
    ...policyUpdate,
    version: randomUUID().slice(0, 8),
    updated_at: new Date().toISOString(),
    ...(userContext?.user_id && { updated_by: userContext.user_id }),
  };

  // Build setOnInsert with only fields NOT in policyUpdate to avoid MongoDB conflicts
  // Fields in both $set and $setOnInsert cause "would create a conflict" errors
  const defaultName = actualPolicyId === "default" ? "Default Policy" : "New Policy";
  const setOnInsert: Record<string, unknown> = {
    id: actualPolicyId,
    team_id: teamId,
    ...(!policyUpdate.name && { name: defaultName }),
    ...(!("budgets" in policyUpdate) && { budgets: [] }),
    ...(!("throttles" in policyUpdate) && { throttles: [] }),
    ...(!("blocks" in policyUpdate) && { blocks: [] }),
    ...(!("degradations" in policyUpdate) && { degradations: [] }),
    ...(!("alerts" in policyUpdate) && { alerts: [] }),
    created_at: new Date().toISOString(),
    ...(userContext?.user_id && { created_by: userContext.user_id }),
  };

  await collection.updateOne(
    { team_id: teamId, id: actualPolicyId },
    {
      $set: updateFields,
      $setOnInsert: setOnInsert,
    },
    { upsert: true }
  );

  // Return the updated policy
  return getPolicy(teamId, actualPolicyId);
}

/**
 * Transform a metric event to TSDB format
 */
function transformMetricToTsdbEvent(event: Event, teamId: string | number, policyId: string | null): Record<string, unknown> {
  const data = event.data || {};
  const now = new Date();
  // Extract agent - metadata.agent takes precedence over top-level agent
  const effectiveAgent = (data.metadata?.agent as string) || data.agent || null;

  // Calculate cost for real-time streaming
  const cost = pricingService.calculateCostSync({
    model: data.model || "",
    provider: data.provider,
    input_tokens: data.input_tokens || 0,
    output_tokens: data.output_tokens || 0,
    cached_tokens: data.cached_tokens || 0,
  }).total;

  return {
    timestamp: event.timestamp || now.toISOString(),
    team_id: String(teamId),
    user_id: (data.metadata?.user_id as string) || null,
    trace_id: data.trace_id || event.trace_id || randomUUID(),
    span_id: data.span_id || null,
    request_id: data.request_id || null,
    provider: data.provider || null,
    call_sequence: data.call_sequence ?? 0,
    model: data.model || "",
    stream: Boolean(data.stream),
    agent: effectiveAgent,
    agent_name: event.agent_name || null,
    agent_stack: data.agent_stack || [],
    latency_ms: data.latency_ms || null,
    usage: {
      input_tokens: data.input_tokens || 0,
      output_tokens: data.output_tokens || 0,
      total_tokens: data.total_tokens || 0,
      cached_tokens: data.cached_tokens || 0,
      reasoning_tokens: data.reasoning_tokens || 0,
    },
    cost_total: cost,
    metadata: {
      ...data.metadata,
      policy_id: policyId,
      event_type: event.event_type,
    },
    // Layer 0 content capture (if enabled in SDK)
    content_capture: data.content_capture || null,
  };
}

/**
 * Process incoming events from SDK
 */
async function processEvents(teamId: string | number | null, policyId: string | null, events: Event[], userContext: UserContext | null = null): Promise<void> {
  if (!teamId) {
    teamId = userContext?.team_id ?? null;
  }
  if (!teamId) {
    throw new Error("team_id is required to process events");
  }

  const tsdbEvents: Record<string, unknown>[] = [];

  for (const event of events) {
    // Process specific event types
    switch (event.event_type) {
      case "metric":
        await processMetricEvent(teamId, policyId, event, userContext);
        // Transform and collect metric events for TSDB
        tsdbEvents.push(transformMetricToTsdbEvent(event, teamId, policyId));
        break;
      case "control":
        await processControlEvent(teamId, event, policyId);
        break;
      case "heartbeat":
        await processHeartbeatEvent(teamId, policyId, event);
        break;
      case "error":
        await processErrorEvent(teamId, event);
        break;
    }
  }

  // Store metric events in TSDB if we have team context
  if (tsdbEvents.length > 0) {
    try {
      const pool = await getTeamPool(teamId);
      const schema = buildSchemaName(teamId);
      const client = await pool.connect();
      try {
        // Explicitly set search_path to team schema before inserting
        await client.query(`CREATE SCHEMA IF NOT EXISTS ${schema}`);
        await client.query(`SET search_path TO ${schema}, public`);
        await tsdbService.ensureSchema(client);
        const result = await tsdbService.upsertEvents(tsdbEvents as unknown[], client);
        console.log(
          `[Aden Control] Stored ${result.rowsWritten} events in TSDB for team ${teamId}`
        );

        // Push to real-time WebSocket stream
        if (result.rowsWritten > 0) {
          llmEventBatcher.add(teamId, tsdbEvents as unknown[]);
        }
      } finally {
        client.release();
      }
    } catch (error) {
      console.error(`[Aden Control] Failed to store events in TSDB:`, (error as Error).message);
    }
  }
}

/**
 * Process a metric event - update budget tracking
 * Updates spend for all matching budgets based on their type
 */
async function processMetricEvent(teamId: string | number, policyId: string | null, event: Event, userContext: UserContext | null = null): Promise<void> {
  const metricData = event.data;
  if (!metricData) return;

  // Calculate cost from tokens (simplified pricing)
  const cost = estimateCost(metricData);

  // Get the policy to find matching budgets
  const policy = await getPolicy(teamId, policyId, userContext);
  let budgetUpdated = false;

  if (policy.budgets && policy.budgets.length > 0) {
    for (const budget of policy.budgets) {
      // Determine if this metric applies to this budget based on type
      const shouldApply = matchesBudgetType(budget, metricData);

      if (shouldApply) {
        const tracker = budgetTracker.get(budget.id) || {
          spent: 0,
          lastReset: new Date(),
        };
        tracker.spent += cost;
        budgetTracker.set(budget.id, tracker);
        budgetUpdated = true;

        // Check if budget alerts should be triggered
        checkBudgetAlerts(budget, tracker.spent, teamId, policyId);
      }
    }
  }

  // Push updated policy with new spend to SDK via WebSocket
  if (budgetUpdated && (global as unknown as Record<string, unknown>)._ADEN_CONTROL_EMITTER) {
    const updatedPolicy = await getPolicy(teamId, policyId);
    ((global as unknown as Record<string, unknown>)._ADEN_CONTROL_EMITTER as { emitPolicyUpdate: (teamId: string | number, policyId: string | null, policy: Policy) => void }).emitPolicyUpdate(teamId, policyId, updatedPolicy);
  }

  console.log(
    `[Aden Control] Metric: ${metricData.provider}/${metricData.model} - ${
      metricData.total_tokens
    } tokens, $${cost.toFixed(6)}`
  );
}

/**
 * Check if a metric event matches a budget's type criteria
 */
function matchesBudgetType(budget: Budget, metricData: MetricData): boolean {
  const metadata = metricData.metadata || {};
  // metadata.agent takes precedence over top-level agent
  const effectiveAgent = (metadata.agent as string) || metricData.agent;

  switch (budget.type) {
    case "global":
      // Global budgets apply to all metrics
      return true;

    case "agent":
      // Agent budgets apply when agent name matches (from top-level or metadata)
      return !!effectiveAgent && budget.name === effectiveAgent;

    case "tenant":
      // Tenant budgets apply when tenant_id matches
      return !!metadata.tenant_id && budget.name === metadata.tenant_id;

    case "customer":
      // Customer budgets apply when customer_id matches
      return !!metadata.customer_id && budget.name === metadata.customer_id;

    case "feature":
      // Feature budgets apply when feature name matches
      return !!metadata.feature && budget.name === metadata.feature;

    case "tag": {
      // Tag budgets apply when the tagCategory value matches budget name
      if (!budget.tagCategory || !metadata.tags) return false;
      const tagValue = (metadata.tags as Record<string, string>)[budget.tagCategory];
      return !!tagValue && budget.name === tagValue;
    }

    default:
      return false;
  }
}

/**
 * Send budget notifications via configured channels (email, webhook)
 * Includes cooldown logic to prevent notification spam.
 */
async function sendBudgetNotifications(budget: Budget, alertData: Record<string, unknown>, alertType: string = "threshold"): Promise<boolean> {
  const notifications = budget.notifications;
  if (!notifications) {
    console.log(
      `[Aden Control] No notifications configured for budget ${budget.name} (${budget.id})`
    );
    return false;
  }

  // Check if any notification channel is enabled
  if (!notifications.email && !notifications.webhook) {
    console.log(
      `[Aden Control] Notifications disabled for budget ${budget.name} (email: ${notifications.email}, webhook: ${notifications.webhook})`
    );
    return false;
  }

  // Check cooldown to prevent spam
  const cooldownKey = `${budget.id}:${alertType}:${
    alertData.threshold || alertData.action || "default"
  }`;
  const lastSent = notificationCooldowns.get(cooldownKey);
  const now = Date.now();

  if (lastSent && now - lastSent < NOTIFICATION_COOLDOWN_MS) {
    console.log(
      `[Aden Control] Notification for budget ${budget.name} (${alertType}) skipped - cooldown active`
    );
    return false;
  }

  const { spent, limit, threshold, action } = alertData as { spent: number; limit: number; threshold?: number; action?: string };
  const spentPercentage = limit > 0 ? ((spent / limit) * 100).toFixed(1) : "0";

  // Determine alert severity color
  const isLimitAction = alertType === "limit_action";
  const alertColor = isLimitAction
    ? "#dc2626"
    : parseFloat(spentPercentage) >= 90
    ? "#f59e0b"
    : "#3b82f6";
  const alertBgColor = isLimitAction
    ? "#fef2f2"
    : parseFloat(spentPercentage) >= 90
    ? "#fffbeb"
    : "#eff6ff";

  // Build notification content
  let title: string, description: string;
  if (isLimitAction) {
    title = "Budget Limit Triggered";
    description = `The budget <strong>${budget.name}</strong> has exceeded its limit and triggered a control action.`;
  } else {
    title = "Budget Threshold Alert";
    description = `The budget <strong>${budget.name}</strong> has reached ${threshold}% of its limit.`;
  }

  // Email subject and content prepared for future email notification implementation
  const _subject = isLimitAction
    ? `[Aden] Budget "${budget.name}" - ${(action || "").toUpperCase()}`
    : `[Aden] Budget "${budget.name}" at ${spentPercentage}%`;

  const _htmlContent = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f3f4f6; padding: 32px 16px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 480px; background-color: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
          <!-- Header -->
          <tr>
            <td style="padding: 24px 24px 16px; border-bottom: 1px solid #e5e7eb;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <span style="display: inline-block; background-color: ${alertBgColor}; color: ${alertColor}; font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 12px; text-transform: uppercase;">
                      ${isLimitAction ? action : "Alert"}
                    </span>
                  </td>
                </tr>
                <tr>
                  <td style="padding-top: 12px;">
                    <h1 style="margin: 0; font-size: 20px; font-weight: 600; color: #111827;">${title}</h1>
                  </td>
                </tr>
                <tr>
                  <td style="padding-top: 8px;">
                    <p style="margin: 0; font-size: 14px; color: #6b7280; line-height: 1.5;">${description}</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Progress Bar -->
          <tr>
            <td style="padding: 20px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="padding-bottom: 8px;">
                    <span style="font-size: 28px; font-weight: 700; color: ${alertColor};">${spentPercentage}%</span>
                    <span style="font-size: 14px; color: #9ca3af; margin-left: 4px;">of budget used</span>
                  </td>
                </tr>
                <tr>
                  <td>
                    <div style="background-color: #e5e7eb; border-radius: 4px; height: 8px; overflow: hidden;">
                      <div style="background-color: ${alertColor}; height: 100%; width: ${Math.min(100, parseFloat(spentPercentage))}%; border-radius: 4px;"></div>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Details -->
          <tr>
            <td style="padding: 0 24px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; border-radius: 6px;">
                <tr>
                  <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size: 13px; color: #6b7280;">Spent</td>
                        <td align="right" style="font-size: 14px; font-weight: 600; color: #111827;">$${(spent || 0).toFixed(4)}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size: 13px; color: #6b7280;">Limit</td>
                        <td align="right" style="font-size: 14px; font-weight: 600; color: #111827;">$${(limit || 0).toFixed(2)}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding: 12px 16px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size: 13px; color: #6b7280;">Budget Type</td>
                        <td align="right" style="font-size: 14px; font-weight: 600; color: #111827;">${budget.type}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
                ${alertData.model ? `
                <tr>
                  <td style="padding: 12px 16px; border-top: 1px solid #e5e7eb;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size: 13px; color: #6b7280;">Model</td>
                        <td align="right" style="font-size: 14px; font-weight: 600; color: #111827;">${alertData.model}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
                ` : ""}
              </table>
            </td>
          </tr>

          <!-- CTA Button -->
          <tr>
            <td style="padding: 0 24px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <a href="${_GLOBAL_CONST.ARP_URL}/agent-control"
                       style="display: inline-block; background-color: #3b82f6; color: #ffffff; font-size: 14px; font-weight: 600; text-decoration: none; padding: 12px 24px; border-radius: 6px;">
                      View Cost Control Center
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding: 16px 24px; background-color: #f9fafb; border-top: 1px solid #e5e7eb; border-radius: 0 0 8px 8px;">
              <p style="margin: 0; font-size: 12px; color: #9ca3af; text-align: center;">
                Sent by Aden Cost Control
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>`;

  // Send email notifications
  if (notifications.email) {
    if (!notifications.emailRecipients?.length) {
      console.log(
        `[Aden Control] Email enabled but no recipients configured for budget ${budget.name}`
      );
    } else {
      // TODO: Re-enable when mailService is integrated from @aden/administration
      console.log(
        `[Aden Control] Email notification skipped (mail service not configured) for budget ${budget.name}`
      );
    }
  }

  // Send webhook notifications
  if (notifications.webhook && notifications.webhookUrl) {
    try {
      const response = await fetch(notifications.webhookUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "budget_alert",
          alert_type: alertType,
          budget_id: budget.id,
          budget_name: budget.name,
          budget_type: budget.type,
          ...alertData,
          timestamp: new Date().toISOString(),
        }),
      });
      if (!response.ok) {
        console.error(`[Aden Control] Webhook returned ${response.status}`);
      } else {
        console.log(`[Aden Control] Sent webhook notification for budget ${budget.name}`);
      }
    } catch (err) {
      console.error(`[Aden Control] Failed to send webhook notification:`, (err as Error).message);
    }
  }

  // Record cooldown timestamp
  notificationCooldowns.set(cooldownKey, now);
  return true;
}

/**
 * Check budget alerts and emit notifications if thresholds are crossed
 */
async function checkBudgetAlerts(budget: Budget, currentSpent: number, teamId: string | number, policyId: string | null): Promise<void> {
  if (!budget.alerts || !budget.alerts.length || !budget.limit) return;

  const spentPercentage = (currentSpent / budget.limit) * 100;

  for (const alert of budget.alerts) {
    if (!alert.enabled) continue;
    if (spentPercentage >= alert.threshold) {
      const alertData = {
        budget_id: budget.id,
        budget_name: budget.name,
        threshold: alert.threshold,
        current_percentage: spentPercentage,
        spent: currentSpent,
        limit: budget.limit,
      };

      // Emit alert event via WebSocket (inApp notification)
      if ((global as unknown as Record<string, unknown>)._ADEN_CONTROL_EMITTER) {
        ((global as unknown as Record<string, unknown>)._ADEN_CONTROL_EMITTER as { emitAlert: (teamId: string | number, policyId: string | null, alert: Record<string, unknown>) => void }).emitAlert(teamId, policyId, {
          ...alertData,
          notifications: budget.notifications,
        });
      }

      // Send email/webhook notifications
      await sendBudgetNotifications(budget, alertData, "threshold");
    }
  }
}

/**
 * Estimate cost from metric data using unified pricing service
 */
function estimateCost(metricData: MetricData): number {
  const result = pricingService.calculateCostSync({
    model: metricData.model || "",
    provider: metricData.provider,
    input_tokens: metricData.input_tokens || 0,
    output_tokens: metricData.output_tokens || 0,
    cached_tokens: metricData.cached_tokens || 0,
  });
  return result.total;
}

/**
 * Process a control event - log control decisions and send notifications
 */
async function processControlEvent(teamId: string | number, event: Event, policyId: string | null = null): Promise<void> {
  console.log(
    `[Aden Control] Control action: ${event.action} on ${event.provider}/${
      event.original_model
    }${event.reason ? ` - ${event.reason}` : ""}`
  );

  // Check if this is a budget-related control action
  const isBudgetAction =
    event.budget_id ||
    event.reason?.includes("budget") ||
    ["kill", "throttle", "degrade", "block"].includes(event.action || "");

  // Fall back to default policy if not provided
  const effectivePolicyId = policyId || event.policy_id || "default";

  console.log(
    `[Aden Control] Control event notification check: isBudgetAction=${isBudgetAction}, policyId=${effectivePolicyId}, budget_id=${event.budget_id}`
  );

  if (isBudgetAction) {
    try {
      // Get the policy to find the budget
      const policy = await getPolicy(teamId, effectivePolicyId);
      console.log(
        `[Aden Control] Found policy with ${policy?.budgets?.length || 0} budgets`
      );

      if (policy?.budgets?.length) {
        // Find matching budget by ID or by type/name
        let budget = event.budget_id
          ? policy.budgets.find((b) => b.id === event.budget_id)
          : null;

        // If no budget_id, try to find by context (agent, etc.)
        if (!budget && event.agent) {
          budget = policy.budgets.find(
            (b) => b.type === "agent" && b.name === event.agent
          );
        }

        // Fallback to global budget
        if (!budget) {
          budget = policy.budgets.find((b) => b.type === "global");
        }

        console.log(
          `[Aden Control] Budget lookup result: ${
            budget ? `found "${budget.name}" (${budget.id})` : "not found"
          }`
        );

        if (budget) {
          const alertData = {
            action: event.action,
            reason: event.reason,
            model: event.original_model,
            provider: event.provider,
            spent: budget.spent || 0,
            limit: budget.limit || 0,
          };

          console.log(
            `[Aden Control] Sending notification for budget "${
              budget.name
            }", notifications: ${JSON.stringify(budget.notifications)}`
          );
          await sendBudgetNotifications(budget, alertData, "limit_action");
        }
      }
    } catch (err) {
      console.error(
        `[Aden Control] Failed to send control event notifications:`,
        (err as Error).message,
        (err as Error).stack
      );
    }
  } else {
    console.log(
      `[Aden Control] Skipping notification: isBudgetAction=${isBudgetAction}, policyId=${
        policyId || "null"
      }`
    );
  }
}

/**
 * Process a heartbeat event - track SDK health
 */
async function processHeartbeatEvent(
  teamId: string | number,
  policyId: string | null,
  event: Event
): Promise<void> {
  console.log(
    `[Aden Control] Heartbeat from ${event.agent_name || event.sdk_instance_id}: ${event.status}, ${event.requests_since_last} requests`
  );

  // Register/update HTTP agent tracking
  if (event.sdk_instance_id) {
    registerHttpAgent(
      teamId,
      event.sdk_instance_id,
      event.policy_id || policyId,
      event.agent_name || null,
      event.status || "unknown"
    );
  }
}

/**
 * Process an error event
 */
async function processErrorEvent(teamId: string | number, event: Event): Promise<void> {
  console.error(`[Aden Control] Error from SDK: ${event.message}`, event.stack);
}

/**
 * Get events for a team (for dashboard)
 */
async function getEvents(teamId: string | number, policyId: string | null = null, options: { limit?: number; offset?: number; start_date?: string; end_date?: string } = {}): Promise<unknown[]> {
  const { limit = 100, offset = 0, start_date, end_date } = options;

  if (!teamId) {
    console.warn(`[Aden Control] No team_id provided, returning empty events`);
    return [];
  }

  try {
    const pool = await getTeamPool(teamId);
    const schema = buildSchemaName(teamId);
    const client = await pool.connect();

    try {
      await client.query(`SET search_path TO ${schema}, public`);
      await tsdbService.ensureSchema(client);

      // Build query with filters
      const conditions = [`team_id = $1`];
      const values: unknown[] = [String(teamId)];
      let paramIndex = 2;

      // Filter by policy_id in metadata if provided
      if (policyId) {
        conditions.push(`metadata->>'policy_id' = $${paramIndex}`);
        values.push(policyId);
        paramIndex++;
      }

      if (start_date) {
        conditions.push(`"timestamp" >= $${paramIndex}`);
        values.push(new Date(start_date));
        paramIndex++;
      }

      if (end_date) {
        conditions.push(`"timestamp" <= $${paramIndex}`);
        values.push(new Date(end_date));
        paramIndex++;
      }

      const sql = `
        SELECT
          "timestamp",
          trace_id,
          span_id,
          provider,
          model,
          agent,
          latency_ms,
          usage_input_tokens as input_tokens,
          usage_output_tokens as output_tokens,
          usage_total_tokens as total_tokens,
          cost_total,
          metadata
        FROM llm_events
        WHERE ${conditions.join(" AND ")}
        ORDER BY "timestamp" DESC
        LIMIT $${paramIndex} OFFSET $${paramIndex + 1}
      `;

      values.push(limit, offset);

      const result = await client.query(sql, values);

      return result.rows.map((row: Record<string, unknown>) => ({
        timestamp: row.timestamp,
        trace_id: row.trace_id,
        span_id: row.span_id,
        provider: row.provider,
        model: row.model,
        agent: row.agent,
        latency_ms: row.latency_ms,
        input_tokens: row.input_tokens,
        output_tokens: row.output_tokens,
        total_tokens: row.total_tokens,
        cost_usd: row.cost_total,
        metadata: row.metadata,
      }));
    } finally {
      client.release();
    }
  } catch (error) {
    console.error(`[Aden Control] Failed to get events from TSDB:`, (error as Error).message);
    return [];
  }
}

/**
 * Get metrics summary for a team (for dashboard analytics)
 */
async function getMetricsSummary(teamId: string | number, options: { start_date?: string; end_date?: string; group_by?: string } = {}): Promise<{
  total_requests: number;
  total_cost: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  breakdown_by_model: Array<{ model: string; provider: string; requests: number; cost: number; tokens: number }>;
}> {
  const { start_date, end_date } = options;

  if (!teamId) {
    return { total_requests: 0, total_cost: 0, total_input_tokens: 0, total_output_tokens: 0, total_tokens: 0, breakdown_by_model: [] };
  }

  try {
    const pool = await getTeamPool(teamId);
    const schema = buildSchemaName(teamId);
    const client = await pool.connect();

    try {
      await client.query(`SET search_path TO ${schema}, public`);
      await tsdbService.ensureSchema(client);

      const conditions = [`team_id = $1`];
      const values: unknown[] = [String(teamId)];
      let paramIndex = 2;

      if (start_date) {
        conditions.push(`"timestamp" >= $${paramIndex}`);
        values.push(new Date(start_date));
        paramIndex++;
      }

      if (end_date) {
        conditions.push(`"timestamp" <= $${paramIndex}`);
        values.push(new Date(end_date));
        paramIndex++;
      }

      // Get totals
      const totalsSql = `
        SELECT
          COUNT(*) as total_requests,
          COALESCE(SUM(cost_total), 0) as total_cost,
          COALESCE(SUM(usage_input_tokens), 0) as total_input_tokens,
          COALESCE(SUM(usage_output_tokens), 0) as total_output_tokens,
          COALESCE(SUM(usage_total_tokens), 0) as total_tokens
        FROM llm_events
        WHERE ${conditions.join(" AND ")}
      `;

      const totalsResult = await client.query(totalsSql, values);
      const totals = totalsResult.rows[0] || {};

      // Get breakdown by model
      const breakdownSql = `
        SELECT
          model,
          provider,
          COUNT(*) as requests,
          COALESCE(SUM(cost_total), 0) as cost,
          COALESCE(SUM(usage_total_tokens), 0) as tokens
        FROM llm_events
        WHERE ${conditions.join(" AND ")}
        GROUP BY model, provider
        ORDER BY cost DESC
        LIMIT 20
      `;

      const breakdownResult = await client.query(breakdownSql, values);

      return {
        total_requests: parseInt(totals.total_requests) || 0,
        total_cost: parseFloat(totals.total_cost) || 0,
        total_input_tokens: parseInt(totals.total_input_tokens) || 0,
        total_output_tokens: parseInt(totals.total_output_tokens) || 0,
        total_tokens: parseInt(totals.total_tokens) || 0,
        breakdown_by_model: breakdownResult.rows.map((row: Record<string, unknown>) => ({
          model: row.model as string,
          provider: row.provider as string,
          requests: parseInt(row.requests as string) || 0,
          cost: parseFloat(row.cost as string) || 0,
          tokens: parseInt(row.tokens as string) || 0,
        })),
      };
    } finally {
      client.release();
    }
  } catch (error) {
    console.error(`[Aden Control] Failed to get metrics summary:`, (error as Error).message);
    return { total_requests: 0, total_cost: 0, total_input_tokens: 0, total_output_tokens: 0, total_tokens: 0, breakdown_by_model: [] };
  }
}

/**
 * Get budget status for a budget ID
 */
async function getBudgetStatus(budgetId: string): Promise<{ id: string; spent: number; last_reset: string | null }> {
  const tracker = budgetTracker.get(budgetId);
  return {
    id: budgetId,
    spent: tracker?.spent || 0,
    last_reset: tracker?.lastReset?.toISOString() || null,
  };
}

/**
 * Reset budget for a budget ID
 */
async function resetBudget(budgetId: string): Promise<void> {
  budgetTracker.set(budgetId, { spent: 0, lastReset: new Date() });
}

/**
 * Add a budget rule to a policy
 */
async function addBudgetRule(teamId: string | number, policyId: string | null, rule: Budget, userContext: UserContext | null = null): Promise<Policy> {
  const policy = await getPolicy(teamId, policyId, userContext);
  policy.budgets = policy.budgets || [];
  policy.budgets.push(rule);
  return updatePolicy(teamId, policyId, { budgets: policy.budgets }, userContext);
}

/**
 * Add a throttle rule to a policy
 */
async function addThrottleRule(teamId: string | number, policyId: string | null, rule: unknown, userContext: UserContext | null = null): Promise<Policy> {
  const policy = await getPolicy(teamId, policyId, userContext);
  policy.throttles = policy.throttles || [];
  policy.throttles.push(rule);
  return updatePolicy(teamId, policyId, { throttles: policy.throttles }, userContext);
}

/**
 * Add a block rule to a policy
 */
async function addBlockRule(teamId: string | number, policyId: string | null, rule: unknown, userContext: UserContext | null = null): Promise<Policy> {
  const policy = await getPolicy(teamId, policyId, userContext);
  policy.blocks = policy.blocks || [];
  policy.blocks.push(rule);
  return updatePolicy(teamId, policyId, { blocks: policy.blocks }, userContext);
}

/**
 * Add a degradation rule to a policy
 */
async function addDegradeRule(teamId: string | number, policyId: string | null, rule: unknown, userContext: UserContext | null = null): Promise<Policy> {
  const policy = await getPolicy(teamId, policyId, userContext);
  policy.degradations = policy.degradations || [];
  policy.degradations.push(rule);
  return updatePolicy(
    teamId,
    policyId,
    { degradations: policy.degradations },
    userContext
  );
}

/**
 * Add an alert rule to a policy
 */
async function addAlertRule(teamId: string | number, policyId: string | null, rule: unknown, userContext: UserContext | null = null): Promise<Policy> {
  const policy = await getPolicy(teamId, policyId, userContext);
  policy.alerts = policy.alerts || [];
  policy.alerts.push(rule);
  return updatePolicy(teamId, policyId, { alerts: policy.alerts }, userContext);
}

/**
 * Clear all rules from a policy
 */
async function clearPolicy(teamId: string | number, policyId: string | null, userContext: UserContext | null = null): Promise<Policy> {
  return updatePolicy(
    teamId,
    policyId,
    {
      budgets: [],
      throttles: [],
      blocks: [],
      degradations: [],
      alerts: [],
    },
    userContext
  );
}

/**
 * Delete a policy
 */
async function deletePolicy(teamId: string | number | null, policyId: string | null, userContext: UserContext | null = null): Promise<boolean> {
  if (!teamId) {
    teamId = userContext?.team_id ?? null;
  }
  if (!teamId) {
    throw new Error("team_id is required to delete policy");
  }
  if (!policyId) {
    throw new Error("policy_id is required to delete policy");
  }

  const collection = getPolicyCollection();
  const result = await collection.deleteOne({ team_id: teamId, id: policyId });

  if (result.deletedCount === 0) {
    throw new Error("Policy not found");
  }

  return true;
}

/**
 * Get all policies for a team
 */
async function getPoliciesByTeam(teamId: string | number, options: { limit?: number; offset?: number } = {}): Promise<Policy[]> {
  const { limit = 100, offset = 0 } = options;
  const collection = getPolicyCollection();

  const policies = await collection
    .find({ team_id: teamId })
    .sort({ updated_at: -1 })
    .skip(offset)
    .limit(limit)
    .toArray() as (Policy & { _id?: unknown })[];

  // Enrich each policy's budgets with actual spend and analytics from TSDB
  const enrichedPolicies = await Promise.all(
    policies.map(async ({ _id, ...policy }) => {
      if (policy.budgets && policy.budgets.length > 0) {
        policy.budgets = await Promise.all(
          policy.budgets.map(async (budget) => {
            const analytics = await calculateBudgetAnalyticsFromTsdb(teamId, budget);
            return {
              ...budget,
              spent: analytics.spent,
              analytics: {
                burnRate: analytics.burnRate,
                projectedSpend: analytics.projectedSpend,
                daysUntilLimit: analytics.daysUntilLimit,
                usagePercent: analytics.usagePercent,
                projectedPercent: analytics.projectedPercent,
                status: analytics.status,
                period: analytics.period,
              },
            };
          })
        );
      }
      return policy as Policy;
    })
  );

  return enrichedPolicies;
}

/**
 * Get usage breakdown for dashboard analytics
 */
async function getUsageBreakdown(teamId: string | number, options: { days?: number; context_id?: string; budget?: Budget } = {}): Promise<{
  daily: Array<{ date: Date; cost: number; requests: number; tokens: number }>;
  by_model: Array<{ model: string; provider: string; cost: number; requests: number; tokens: number }>;
  by_feature: Array<{ feature: string; cost: number; requests: number; tokens: number; percentage: number }>;
}> {
  const { days = 7, context_id, budget } = options;

  if (!teamId) {
    return { daily: [], by_model: [], by_feature: [] };
  }

  try {
    const pool = await getTeamPool(teamId);
    const schema = buildSchemaName(teamId);
    const client = await pool.connect();

    try {
      await client.query(`SET search_path TO ${schema}, public`);
      await tsdbService.ensureSchema(client);

      const startDate = new Date();
      startDate.setDate(startDate.getDate() - days);

      const conditions = [`team_id = $1`, `"timestamp" >= $2`];
      const values: unknown[] = [String(teamId), startDate];
      let paramIndex = 3;

      // Apply budget-specific filter based on budget type
      if (budget) {
        const budgetFilter = getBudgetFilter(budget, paramIndex);
        if (budgetFilter) {
          conditions.push(budgetFilter.condition);
          values.push(budgetFilter.value);
          paramIndex++;
        }
      } else if (context_id) {
        // Fallback to context_id filter
        conditions.push(`metadata->>'context_id' = $${paramIndex}`);
        values.push(context_id);
        paramIndex++;
      }

      // Daily usage breakdown
      const dailySql = `
        SELECT
          DATE_TRUNC('day', "timestamp") as date,
          COALESCE(SUM(cost_total), 0) as cost,
          COUNT(*) as requests,
          COALESCE(SUM(usage_total_tokens), 0) as tokens
        FROM llm_events
        WHERE ${conditions.join(" AND ")}
        GROUP BY DATE_TRUNC('day', "timestamp")
        ORDER BY date DESC
        LIMIT ${days}
      `;
      const dailyResult = await client.query(dailySql, values);

      // Usage by model
      const byModelSql = `
        SELECT
          model,
          provider,
          COALESCE(SUM(cost_total), 0) as cost,
          COUNT(*) as requests,
          COALESCE(SUM(usage_total_tokens), 0) as tokens
        FROM llm_events
        WHERE ${conditions.join(" AND ")}
        GROUP BY model, provider
        ORDER BY cost DESC
        LIMIT 10
      `;
      const byModelResult = await client.query(byModelSql, values);

      // Usage by feature (from metadata)
      const byFeatureSql = `
        SELECT
          COALESCE(metadata->>'feature', agent, 'unknown') as feature,
          COALESCE(SUM(cost_total), 0) as cost,
          COUNT(*) as requests,
          COALESCE(SUM(usage_total_tokens), 0) as tokens
        FROM llm_events
        WHERE ${conditions.join(" AND ")}
        GROUP BY COALESCE(metadata->>'feature', agent, 'unknown')
        ORDER BY cost DESC
        LIMIT 10
      `;
      const byFeatureResult = await client.query(byFeatureSql, values);

      // Calculate totals for percentages
      const totalCost = byFeatureResult.rows.reduce(
        (sum: number, row: Record<string, unknown>) => sum + parseFloat((row.cost as string) || "0"),
        0
      );

      return {
        daily: dailyResult.rows
          .map((row: Record<string, unknown>) => ({
            date: row.date as Date,
            cost: parseFloat(row.cost as string) || 0,
            requests: parseInt(row.requests as string) || 0,
            tokens: parseInt(row.tokens as string) || 0,
          }))
          .reverse(),
        by_model: byModelResult.rows.map((row: Record<string, unknown>) => ({
          model: row.model as string,
          provider: row.provider as string,
          cost: parseFloat(row.cost as string) || 0,
          requests: parseInt(row.requests as string) || 0,
          tokens: parseInt(row.tokens as string) || 0,
        })),
        by_feature: byFeatureResult.rows.map((row: Record<string, unknown>) => ({
          feature: row.feature as string,
          cost: parseFloat(row.cost as string) || 0,
          requests: parseInt(row.requests as string) || 0,
          tokens: parseInt(row.tokens as string) || 0,
          percentage: totalCost > 0 ? ((parseFloat(row.cost as string) || 0) / totalCost) * 100 : 0,
        })),
      };
    } finally {
      client.release();
    }
  } catch (error) {
    console.error(`[Aden Control] Failed to get usage breakdown:`, (error as Error).message);
    return { daily: [], by_model: [], by_feature: [] };
  }
}

/**
 * Get SQL filter condition for a budget based on its type
 */
function getBudgetFilter(budget: Budget, paramIndex: number): { condition: string; value: unknown } | null {
  switch (budget.type) {
    case "global":
      // Global budgets apply to all events - no filter needed
      return null;

    case "agent":
      // Agent budgets filter by agent column OR metadata.agent (for legacy data)
      return {
        condition: `(agent = $${paramIndex} OR metadata->>'agent' = $${paramIndex})`,
        value: budget.name,
      };

    case "tenant":
      // Tenant budgets filter by tenant_id in metadata
      return { condition: `metadata->>'tenant_id' = $${paramIndex}`, value: budget.name };

    case "customer":
      // Customer budgets filter by customer_id in metadata
      return {
        condition: `metadata->>'customer_id' = $${paramIndex}`,
        value: budget.name,
      };

    case "feature":
      // Feature budgets filter by feature in metadata or agent
      return {
        condition: `(metadata->>'feature' = $${paramIndex} OR agent = $${paramIndex})`,
        value: budget.name,
      };

    case "tag":
      // Tag budgets filter by tags array matching
      if (budget.tags && budget.tags.length > 0) {
        // Match if any of the budget's tags are in the event's tags array
        return {
          condition: `metadata->'tags' ?| $${paramIndex}`,
          value: budget.tags,
        };
      }
      return null;

    default:
      return null;
  }
}

/**
 * Get rate metrics for dashboard analytics
 */
async function getRateMetrics(teamId: string | number, options: { days?: number; context_id?: string; budget?: Budget } = {}): Promise<{
  peak_rate: number;
  p95_rate: number;
  avg_rate: number;
  min_rate: number;
  max_burst: number;
}> {
  const { days = 30, context_id, budget } = options;

  if (!teamId) {
    return {
      peak_rate: 0,
      p95_rate: 0,
      avg_rate: 0,
      min_rate: 0,
      max_burst: 0,
    };
  }

  try {
    const pool = await getTeamPool(teamId);
    const schema = buildSchemaName(teamId);
    const client = await pool.connect();

    try {
      await client.query(`SET search_path TO ${schema}, public`);
      await tsdbService.ensureSchema(client);

      const startDate = new Date();
      startDate.setDate(startDate.getDate() - days);

      const conditions = [`team_id = $1`, `"timestamp" >= $2`];
      const values: unknown[] = [String(teamId), startDate];
      let paramIndex = 3;

      // Apply budget-specific filter based on budget type
      if (budget) {
        const budgetFilter = getBudgetFilter(budget, paramIndex);
        if (budgetFilter) {
          conditions.push(budgetFilter.condition);
          values.push(budgetFilter.value);
          paramIndex++;
        }
      } else if (context_id) {
        conditions.push(`metadata->>'context_id' = $${paramIndex}`);
        values.push(context_id);
        paramIndex++;
      }

      // Calculate requests per second in 1-minute buckets
      const ratesSql = `
        WITH minute_buckets AS (
          SELECT
            DATE_TRUNC('minute', "timestamp") as minute,
            COUNT(*) as requests
          FROM llm_events
          WHERE ${conditions.join(" AND ")}
          GROUP BY DATE_TRUNC('minute', "timestamp")
        )
        SELECT
          MAX(requests / 60.0) as peak_rate,
          PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY requests / 60.0) as p95_rate,
          AVG(requests / 60.0) as avg_rate,
          MIN(requests / 60.0) as min_rate
        FROM minute_buckets
      `;
      const ratesResult = await client.query(ratesSql, values);
      const rates = ratesResult.rows[0] || {};

      // Calculate max burst in 5-second windows
      const burstSql = `
        WITH five_second_buckets AS (
          SELECT
            DATE_TRUNC('second', "timestamp") -
              (EXTRACT(SECOND FROM "timestamp")::integer % 5) * INTERVAL '1 second' as bucket,
            COUNT(*) as requests
          FROM llm_events
          WHERE ${conditions.join(" AND ")}
          GROUP BY DATE_TRUNC('second', "timestamp") -
            (EXTRACT(SECOND FROM "timestamp")::integer % 5) * INTERVAL '1 second'
        )
        SELECT MAX(requests) as max_burst
        FROM five_second_buckets
      `;
      const burstResult = await client.query(burstSql, values);
      const maxBurst = burstResult.rows[0]?.max_burst || 0;

      return {
        peak_rate: parseFloat(rates.peak_rate) || 0,
        p95_rate: parseFloat(rates.p95_rate) || 0,
        avg_rate: parseFloat(rates.avg_rate) || 0,
        min_rate: parseFloat(rates.min_rate) || 0,
        max_burst: parseInt(maxBurst) || 0,
      };
    } finally {
      client.release();
    }
  } catch (error) {
    console.error(`[Aden Control] Failed to get rate metrics:`, (error as Error).message);
    return {
      peak_rate: 0,
      p95_rate: 0,
      avg_rate: 0,
      min_rate: 0,
      max_burst: 0,
    };
  }
}

/**
 * Get detailed budget info including spend tracking
 */
async function getBudgetDetails(teamId: string | number, policyId: string | null, budgetId: string): Promise<Budget | null> {
  const policy = await getPolicy(teamId, policyId);
  const budget = policy.budgets?.find((b) => b.id === budgetId);

  if (!budget) {
    return null;
  }

  // Get real-time tracker status
  const tracker = budgetTracker.get(budgetId);
  const spent = tracker?.spent ?? budget.spent ?? 0;

  return {
    ...budget,
    spent,
  };
}

interface BudgetContext {
  agent?: string;
  metadata?: Record<string, unknown>;
  tenant_id?: string;
  customer_id?: string;
  feature?: string;
  tags?: string[];
}

/**
 * Find all budgets that match a given context
 * Used for multi-budget validation to check ALL applicable budgets
 */
function findMatchingBudgetsForContext(budgets: Budget[], context: BudgetContext = {}): Budget[] {
  if (!budgets || !Array.isArray(budgets)) return [];

  // metadata.agent takes precedence over top-level agent
  const metadata = context.metadata || {};
  const effectiveAgent = (metadata.agent as string) || context.agent;

  return budgets.filter((budget) => {
    switch (budget.type) {
      case "global":
        // Global budgets always match
        return true;

      case "agent":
        // Agent budgets match when agent name matches (from top-level or metadata)
        return !!effectiveAgent && budget.name === effectiveAgent;

      case "tenant":
        // Tenant budgets match when tenant_id matches
        return !!context.tenant_id && budget.name === context.tenant_id;

      case "customer":
        // Customer budgets match when customer_id matches
        return !!context.customer_id && budget.name === context.customer_id;

      case "feature":
        // Feature budgets match when feature name matches
        return !!context.feature && budget.name === context.feature;

      case "tag":
        // Tag budgets match when any budget tag is in context tags
        if (!budget.tags || !context.tags) return false;
        return budget.tags.some((t) => context.tags!.includes(t));

      default:
        return false;
    }
  });
}

interface BudgetValidationResult {
  budget_id: string;
  budget_name: string;
  budget_type: string;
  allowed: boolean;
  action: string;
  reason: string | null;
  authoritative_spend: number;
  budget_limit: number;
  usage_percent: number;
  projected_percent: number;
  degrade_to_model: string | null;
  degrade_to_provider: string | null;
}

interface MultiValidationResult {
  allowed: boolean;
  action: string;
  reason: string | undefined;
  authoritative_spend: number;
  budget_limit: number;
  usage_percent: number;
  projected_percent: number;
  degrade_to_model: string | undefined;
  degrade_to_provider: string | undefined;
  restricting_budget_id: string | undefined;
  restricting_budget_name: string | undefined;
  budgets_checked: BudgetValidationResult[];
}

/**
 * Validate multiple budgets and return the most restrictive result
 */
function validateMultipleBudgets(budgets: Budget[], estimatedCost: number, localSpend: number | null = null): MultiValidationResult {
  if (!budgets || budgets.length === 0) {
    return {
      allowed: true,
      action: "allow",
      reason: "No budgets to validate",
      authoritative_spend: 0,
      budget_limit: 0,
      usage_percent: 0,
      projected_percent: 0,
      degrade_to_model: undefined,
      degrade_to_provider: undefined,
      restricting_budget_id: undefined,
      restricting_budget_name: undefined,
      budgets_checked: [],
    };
  }

  // Action priority (higher = more restrictive)
  const actionPriority: Record<string, number> = { allow: 0, throttle: 1, degrade: 2, block: 3 };

  let mostRestrictiveResult: BudgetValidationResult | null = null;
  const budgetsChecked: BudgetValidationResult[] = [];

  for (const budget of budgets) {
    // Calculate projected spend
    const tsdbSpend = budget.spent || 0;
    const authoritativeSpend =
      typeof localSpend === "number" && localSpend > tsdbSpend ? localSpend : tsdbSpend;
    const projectedSpend = authoritativeSpend + estimatedCost;
    const usagePercent = budget.limit > 0 ? (authoritativeSpend / budget.limit) * 100 : 0;
    const projectedPercent = budget.limit > 0 ? (projectedSpend / budget.limit) * 100 : 0;

    // Determine action for this budget
    let allowed = true;
    let action = "allow";
    let reason: string | null = null;
    let degradeToModel: string | null = null;
    let degradeToProvider: string | null = null;

    if (projectedPercent >= 100) {
      const limitAction = budget.limitAction || "kill";

      switch (limitAction) {
        case "kill":
          allowed = false;
          action = "block";
          reason = `Budget "${budget.name}" exceeded: $${projectedSpend.toFixed(4)} > $${
            budget.limit
          } (${projectedPercent.toFixed(1)}%)`;
          break;
        case "degrade":
          allowed = true;
          action = "degrade";
          reason = `Budget "${budget.name}" at limit, degrading model`;
          degradeToModel = budget.degradeToModel || null;
          degradeToProvider = budget.degradeToProvider || null;
          break;
        case "throttle":
          allowed = true;
          action = "throttle";
          reason = `Budget "${budget.name}" at limit, throttling`;
          break;
        default:
          allowed = false;
          action = "block";
          reason = `Budget "${budget.name}" exceeded with unknown action`;
      }
    } else if (
      projectedPercent >= 90 &&
      budget.limitAction === "degrade" &&
      budget.degradeToModel
    ) {
      allowed = true;
      action = "degrade";
      reason = `Budget "${budget.name}" approaching limit (${projectedPercent.toFixed(
        1
      )}%), pre-emptive degradation`;
      degradeToModel = budget.degradeToModel;
      degradeToProvider = budget.degradeToProvider || null;
    }

    const budgetResult: BudgetValidationResult = {
      budget_id: budget.id,
      budget_name: budget.name,
      budget_type: budget.type,
      allowed,
      action,
      reason,
      authoritative_spend: authoritativeSpend,
      budget_limit: budget.limit,
      usage_percent: usagePercent,
      projected_percent: projectedPercent,
      degrade_to_model: degradeToModel,
      degrade_to_provider: degradeToProvider,
    };

    budgetsChecked.push(budgetResult);

    // Track most restrictive result
    if (
      !mostRestrictiveResult ||
      actionPriority[action] > actionPriority[mostRestrictiveResult.action]
    ) {
      mostRestrictiveResult = budgetResult;
    }
  }

  return {
    allowed: mostRestrictiveResult?.allowed ?? true,
    action: mostRestrictiveResult?.action ?? "allow",
    reason: mostRestrictiveResult?.reason ?? undefined,
    authoritative_spend: mostRestrictiveResult?.authoritative_spend ?? 0,
    budget_limit: mostRestrictiveResult?.budget_limit ?? 0,
    usage_percent: mostRestrictiveResult?.usage_percent ?? 0,
    projected_percent: mostRestrictiveResult?.projected_percent ?? 0,
    degrade_to_model: mostRestrictiveResult?.degrade_to_model ?? undefined,
    degrade_to_provider: mostRestrictiveResult?.degrade_to_provider ?? undefined,
    restricting_budget_id: mostRestrictiveResult?.budget_id,
    restricting_budget_name: mostRestrictiveResult?.budget_name,
    budgets_checked: budgetsChecked,
  };
}

// =============================================================================
// Content Storage (for Layer 0 content capture)
// =============================================================================

interface ContentItem {
  content_id: string;
  content_hash: string;
  content: string;
  byte_size: number;
}

/**
 * Get the MongoDB collection for content storage
 */
function getContentCollection(): MongoCollection {
  return _ACHO_MG_DB
    .db(_ACHO_MDB_CONFIG.ERP_DBNAME)
    .collection(_ACHO_MDB_COLLECTIONS.ADEN_CONTROL_CONTENT);
}

/**
 * Store large content items from SDK
 * Used by Layer 0 content capture for storing content that exceeds max_content_bytes threshold
 */
async function storeContent(teamId: string | number, items: ContentItem[]): Promise<{ stored: number }> {
  if (!items || items.length === 0) {
    return { stored: 0 };
  }

  const collection = getContentCollection();
  const now = new Date().toISOString();

  let stored = 0;
  for (const item of items) {
    try {
      await collection.updateOne(
        { content_id: item.content_id, team_id: teamId },
        {
          $set: {
            content_hash: item.content_hash,
            content: item.content,
            byte_size: item.byte_size,
            updated_at: now,
          },
          $setOnInsert: {
            content_id: item.content_id,
            team_id: teamId,
            created_at: now,
          },
        },
        { upsert: true }
      );
      stored++;
    } catch (error) {
      console.error(`[Aden Control] Failed to store content ${item.content_id}:`, (error as Error).message);
    }
  }

  console.log(`[Aden Control] Stored ${stored}/${items.length} content items for team ${teamId}`);
  return { stored };
}

/**
 * Retrieve content by ID
 */
async function getContent(teamId: string | number, contentId: string): Promise<ContentItem | null> {
  const collection = getContentCollection();
  const doc = await collection.findOne({ content_id: contentId, team_id: teamId }) as (ContentItem & { _id?: unknown }) | null;

  if (!doc) {
    return null;
  }

  const { _id, ...content } = doc;
  return content as ContentItem;
}

export default {
  getPolicy,
  updatePolicy,
  deletePolicy,
  processEvents,
  getEvents,
  getMetricsSummary,
  getUsageBreakdown,
  getRateMetrics,
  getBudgetStatus,
  getBudgetDetails,
  resetBudget,
  addBudgetRule,
  addThrottleRule,
  addBlockRule,
  addDegradeRule,
  addAlertRule,
  clearPolicy,
  getPoliciesByTeam,
  findMatchingBudgetsForContext,
  validateMultipleBudgets,
  storeContent,
  getContent,
};
