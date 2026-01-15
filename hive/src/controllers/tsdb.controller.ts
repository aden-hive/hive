/**
 * TSDB ingestion and preview endpoints (protected)
 */
import express, { Request, Response } from "express";
import passport from "passport";
import type { PoolClient } from "pg";

import {
  ensureSchema,
  upsertEvents,
} from "../services/tsdb/tsdb_service";
import pricingService from "../services/tsdb/pricing_service";
import { parseToken, getTeamPool, buildSchemaName } from "../services/tsdb/team_context";
import { buildAnalytics } from "../services/tsdb/analytics_service";

const router = express.Router();

const AUTH_MIDDLEWARE = passport.authenticate("jwt", { session: false });


interface TokenContext {
  team_id: string;
  user_id?: string;
}

interface QueryRow {
  [key: string]: unknown;
}


interface MetricRow {
  period: string;
  total_requests: string | number;
  unique_traces: string | number;
  unique_users: string | number;
  total_input_tokens: string | number;
  total_output_tokens: string | number;
  total_tokens: string | number;
  cached_tokens: string | number;
  reasoning_tokens: string | number;
  total_cost: string | number;
  avg_latency_ms: string | number;
  p50_latency_ms: string | number;
  p95_latency_ms: string | number;
  p99_latency_ms: string | number;
  max_latency_ms: string | number;
  streaming_requests: string | number;
}

interface LLMEventRow {
  timestamp: Date;
  trace_id: string;
  call_sequence: number;
  model: string;
  provider: string;
  usage_input_tokens: number;
  usage_output_tokens: number;
  usage_cached_tokens: number;
  cost_total: string | number;
}

interface MergedRow {
  request_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  total_cost: number;
  avg_latency_ms: number;
  latency_sum: number;
  first_seen: Date;
  last_seen: Date;
  [key: string]: unknown;
}

const getAuthorizationHeader = (req: Request): string | undefined => {
  return req.headers.authorization || (req.headers as Record<string, string>).Authorization;
};

const getTokenContext = (req: Request): TokenContext | null => {
  return parseToken(getAuthorizationHeader(req)) as TokenContext | null;
};

const connectTeamClient = async (teamId: string | number): Promise<PoolClient> => {
  const pool = await getTeamPool(teamId, {});
  const schema = buildSchemaName(teamId);
  const client = await pool.connect();
  await client.query(`CREATE SCHEMA IF NOT EXISTS ${schema}`);
  await client.query(`SET search_path TO ${schema}, public`);
  await ensureSchema(client);
  return client;
};

router.post("/events", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let client: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ error: "invalid_token", detail: "Missing team_id in token" });
    }
    const payload = Array.isArray(req.body) ? req.body : req.body?.events;
    if (!Array.isArray(payload) || payload.length === 0) {
      return res.status(400).json({ error: "events array required" });
    }
    if (payload.length > 2000) {
      return res.status(400).json({ error: "events array too large (max 2000)" });
    }

    client = await connectTeamClient(ctx.team_id);
    const enriched = payload.map((e: Record<string, unknown>) => ({ ...e, team_id: ctx.team_id, user_id: (ctx.user_id || e.user_id) as string | undefined }));
    const result = await upsertEvents(enriched, client);
    return res.json({
      message: "ingested",
      rows_written: result.rowsWritten,
      normalized: result.normalized,
    });
  } catch (err) {
    console.error("[tsdb] ingest error", err);
    return res.status(500).json({ error: "ingest_failed", detail: (err as Error).message });
  } finally {
    if (client) client.release();
  }
});

router.get("/sample", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let client: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ error: "invalid_token", detail: "Missing team_id in token" });
    }
    client = await connectTeamClient(ctx.team_id);
    const limit = Math.min(parseInt((req.query.limit as string) || "20", 10), 100);
    const { rows } = await client.query(
      'SELECT * FROM llm_events ORDER BY "timestamp" DESC LIMIT $1',
      [limit]
    );
    return res.json({ rows });
  } catch (err) {
    console.error("[tsdb] sample error", err);
    return res.status(500).json({ error: "sample_failed", detail: (err as Error).message });
  } finally {
    if (client) client.release();
  }
});

router.get("/counts", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let client: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ error: "invalid_token", detail: "Missing team_id in token" });
    }
    client = await connectTeamClient(ctx.team_id);
    const window = (req.query.window as string) || "1 day";
    const { rows } = await client.query(
      'SELECT COUNT(*)::bigint AS count FROM llm_events WHERE "timestamp" >= NOW() - $1::interval',
      [window]
    );
    return res.json({ window, count: Number(rows[0].count) });
  } catch (err) {
    console.error("[tsdb] counts error", err);
    return res.status(500).json({ error: "counts_failed", detail: (err as Error).message });
  } finally {
    if (client) client.release();
  }
});

router.get("/health", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let client: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ status: "error", detail: "Missing team_id in token" });
    }
    client = await connectTeamClient(ctx.team_id);
    const { rows } = await client.query("SELECT NOW() AS now");
    return res.json({ status: "ok", now: rows[0].now });
  } catch (err) {
    console.error("[tsdb] health error", err);
    return res.status(500).json({ status: "error", detail: (err as Error).message });
  } finally {
    if (client) client.release();
  }
});

// GET /tsdb/logs?start=2025-01-01T00:00:00Z&end=2025-01-02T00:00:00Z&limit=500&offset=0
// Optional: group_by=model|agent|model,agent for aggregation
router.get("/logs", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let poolClient: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ error: "invalid_token", detail: "Missing team_id in token" });
    }
    const { start, end, group_by } = req.query as { start?: string; end?: string; group_by?: string };
    const startDate = start ? new Date(start) : null;
    const endDate = end ? new Date(end) : null;
    if (!startDate || Number.isNaN(startDate.getTime()) || !endDate || Number.isNaN(endDate.getTime())) {
      return res.status(400).json({ error: "invalid_time_window", detail: "start and end must be valid ISO dates" });
    }

    const limit = Math.min(parseInt((req.query.limit as string) || "500", 10), 5000);
    const offset = Math.max(parseInt((req.query.offset as string) || "0", 10), 0);

    poolClient = await connectTeamClient(ctx.team_id);

    // Handle aggregation if group_by is specified
    if (group_by) {
      const validGroupFields = ["model", "agent", "provider"];
      const groupFields = group_by.split(",").map((f) => f.trim()).filter((f) => validGroupFields.includes(f));

      if (groupFields.length === 0) {
        return res.status(400).json({
          error: "invalid_group_by",
          detail: `group_by must be one or more of: ${validGroupFields.join(", ")}`,
        });
      }

      // Try to use continuous aggregates for better performance
      // Use CA when: single group field (model or agent) and provider not requested
      // Hybrid approach: CA for completed days + base table for today's partial data
      const useModelCA = groupFields.length === 1 && groupFields[0] === "model";
      const useModelProviderCA = groupFields.length === 2 && groupFields.includes("model") && groupFields.includes("provider");
      const useAgentCA = groupFields.length === 1 && groupFields[0] === "agent";

      let rows: QueryRow[];
      let usedCA = false;

      const utcDayStart = (d: Date): Date => {
        const x = new Date(d);
        x.setUTCHours(0, 0, 0, 0);
        return x;
      };

      const addUtcDays = (d: Date, days: number): Date => {
        return new Date(d.getTime() + days * 24 * 60 * 60 * 1000);
      };

      const startDayStart = utcDayStart(startDate);
      const endDayStart = utcDayStart(endDate);

      const fullBucketStart = startDate.getTime() === startDayStart.getTime()
        ? startDayStart
        : addUtcDays(startDayStart, 1);

      const fullBucketEnd = endDayStart;

      const hasFullBuckets = fullBucketStart < fullBucketEnd;

      const partialRanges: Array<{ start: Date; end: Date }> = [];
      const pushRange = (rangeStart: Date, rangeEnd: Date): void => {
        if (rangeEnd.getTime() <= rangeStart.getTime()) return;
        partialRanges.push({ start: rangeStart, end: rangeEnd });
      };

      pushRange(startDate, new Date(Math.min(endDate.getTime(), fullBucketStart.getTime())));
      pushRange(new Date(Math.max(startDate.getTime(), fullBucketEnd.getTime())), endDate);

      const mergeResults = (caRows: QueryRow[], baseRows: QueryRow[], keyFields: string[]): MergedRow[] => {
        const merged = new Map<string, MergedRow>();

        const addRow = (row: QueryRow): void => {
          const key = keyFields.map((f) => row[f]).join("|");
          const requestCount = parseInt(row.request_count as string) || 0;
          const inputTokens = parseInt(row.total_input_tokens as string) || 0;
          const outputTokens = parseInt(row.total_output_tokens as string) || 0;
          const totalTokens = parseInt(row.total_tokens as string) || 0;
          const totalCost = parseFloat(row.total_cost as string) || 0;
          const avgLatency = parseFloat(row.avg_latency_ms as string) || 0;
          const firstSeen = row.first_seen as Date;
          const lastSeen = row.last_seen as Date;

          const existing = merged.get(key);
          if (!existing) {
            merged.set(key, {
              ...Object.fromEntries(keyFields.map((f) => [f, row[f]])),
              request_count: requestCount,
              total_input_tokens: inputTokens,
              total_output_tokens: outputTokens,
              total_tokens: totalTokens,
              total_cost: totalCost,
              avg_latency_ms: avgLatency,
              latency_sum: avgLatency * requestCount,
              first_seen: firstSeen,
              last_seen: lastSeen,
            });
            return;
          }

          const newCount = existing.request_count + requestCount;
          const newLatencySum = existing.latency_sum + avgLatency * requestCount;

          merged.set(key, {
            ...existing,
            request_count: newCount,
            total_input_tokens: existing.total_input_tokens + inputTokens,
            total_output_tokens: existing.total_output_tokens + outputTokens,
            total_tokens: existing.total_tokens + totalTokens,
            total_cost: existing.total_cost + totalCost,
            avg_latency_ms: newCount > 0 ? newLatencySum / newCount : 0,
            latency_sum: newLatencySum,
            first_seen: existing.first_seen < firstSeen ? existing.first_seen : firstSeen,
            last_seen: existing.last_seen > lastSeen ? existing.last_seen : lastSeen,
          });
        };

        for (const row of caRows) addRow(row);
        for (const row of baseRows) addRow(row);

        // Convert to array and sort by cost desc
        return Array.from(merged.values())
          .map(({ latency_sum: _latency_sum, ...rest }) => ({ ...rest, latency_sum: 0 }))
          .sort((a, b) => b.total_cost - a.total_cost);
      };

      const getBaseAggData = async (rangeStart: Date, rangeEnd: Date, selectFields: string, groupByClause: string): Promise<QueryRow[]> => {
        if (rangeEnd.getTime() <= rangeStart.getTime()) return [];

        const baseSql = `
          SELECT
            ${selectFields},
            COUNT(*) as request_count,
            COALESCE(SUM(COALESCE(usage_input_tokens, 0)), 0) as total_input_tokens,
            COALESCE(SUM(COALESCE(usage_output_tokens, 0)), 0) as total_output_tokens,
            COALESCE(SUM(COALESCE(usage_total_tokens, COALESCE(usage_input_tokens, 0) + COALESCE(usage_output_tokens, 0))), 0) as total_tokens,
            COALESCE(SUM(cost_total), 0) as total_cost,
            COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
            MIN("timestamp") as first_seen,
            MAX("timestamp") as last_seen
          FROM llm_events
          WHERE "timestamp" >= $1 AND "timestamp" <= $2 AND team_id = $3
          GROUP BY ${groupByClause}
        `;

        const result = await poolClient.query(baseSql, [rangeStart.toISOString(), rangeEnd.toISOString(), String(ctx.team_id)]);
        return result.rows;
      };

      if (useModelCA || useModelProviderCA) {
        // Try model CA - includes provider so works for both cases
        try {
          const keyFields = useModelProviderCA ? ["model", "provider"] : ["model"];

          const selectFields = useModelProviderCA ? "model, provider" : "model";

          const baseRows = (await Promise.all(
            partialRanges.map((r) => getBaseAggData(r.start, r.end, selectFields, selectFields))
          )).flat();

          let caRows: QueryRow[] = [];
          if (hasFullBuckets) {
            const caSql = `
              SELECT
                model,
                ${useModelProviderCA ? "provider," : ""}
                SUM(requests) as request_count,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                (COALESCE(SUM(input_tokens), 0) + COALESCE(SUM(output_tokens), 0)) as total_tokens,
                COALESCE(SUM(cost_total), 0) as total_cost,
                COALESCE(SUM(avg_latency_ms * requests) / NULLIF(SUM(requests), 0), 0) as avg_latency_ms,
                MIN(bucket) as first_seen,
                MAX(bucket) as last_seen
              FROM llm_events_daily_by_model_ca
              WHERE bucket >= $1 AND bucket < $2
              GROUP BY model${useModelProviderCA ? ", provider" : ""}
            `;
            const result = await poolClient.query(caSql, [fullBucketStart.toISOString(), fullBucketEnd.toISOString()]);
            caRows = result.rows;
          }

          rows = mergeResults(caRows, baseRows, keyFields).slice(offset, offset + limit) as unknown as QueryRow[];
          usedCA = hasFullBuckets;
        } catch (err) {
          // CA not available, fall through to base table query
        }
      } else if (useAgentCA) {
        // Try agent CA
        try {
          const baseRows = (await Promise.all(
            partialRanges.map((r) => getBaseAggData(r.start, r.end, "agent", "agent"))
          )).flat();

          let caRows: QueryRow[] = [];
          if (hasFullBuckets) {
            const caSql = `
              SELECT
                agent,
                SUM(requests) as request_count,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                (COALESCE(SUM(input_tokens), 0) + COALESCE(SUM(output_tokens), 0)) as total_tokens,
                COALESCE(SUM(cost_total), 0) as total_cost,
                COALESCE(SUM(avg_latency_ms * requests) / NULLIF(SUM(requests), 0), 0) as avg_latency_ms,
                MIN(bucket) as first_seen,
                MAX(bucket) as last_seen
              FROM llm_events_daily_by_agent_ca
              WHERE bucket >= $1 AND bucket < $2
              GROUP BY agent
            `;
            const result = await poolClient.query(caSql, [fullBucketStart.toISOString(), fullBucketEnd.toISOString()]);
            caRows = result.rows;
          }

          rows = mergeResults(caRows, baseRows, ["agent"]).slice(offset, offset + limit) as unknown as QueryRow[];
          usedCA = hasFullBuckets;
        } catch (err) {
          // CA not available, fall through to base table query
        }
      }

      // Fallback to base table query if CA not used or failed
      if (!usedCA) {
        const groupByClause = groupFields.join(", ");
        const selectFields = groupFields.map((f) => f).join(", ");

        const aggSql = `
          SELECT
            ${selectFields},
            COUNT(*) as request_count,
            COALESCE(SUM(COALESCE(usage_input_tokens, 0)), 0) as total_input_tokens,
            COALESCE(SUM(COALESCE(usage_output_tokens, 0)), 0) as total_output_tokens,
            COALESCE(SUM(COALESCE(usage_total_tokens, COALESCE(usage_input_tokens, 0) + COALESCE(usage_output_tokens, 0))), 0) as total_tokens,
            COALESCE(SUM(cost_total), 0) as total_cost,
            COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
            MIN("timestamp") as first_seen,
            MAX("timestamp") as last_seen
          FROM llm_events
          WHERE "timestamp" >= $1 AND "timestamp" <= $2 AND team_id = $3
          GROUP BY ${groupByClause}
          ORDER BY total_cost DESC
          LIMIT $4 OFFSET $5
        `;
        const result = await poolClient.query(aggSql, [startDate.toISOString(), endDate.toISOString(), String(ctx.team_id), limit, offset]);
        rows = result.rows;
      }

      return res.json({
        window: { start: startDate.toISOString(), end: endDate.toISOString() },
        group_by: groupFields,
        count: rows!.length,
        source: usedCA ? "continuous_aggregate" : "base_table",
        aggregations: rows!.map((row) => ({
          ...Object.fromEntries(groupFields.map((f) => [f, row[f]])),
          request_count: parseInt(row.request_count as string) || 0,
          total_input_tokens: parseInt(row.total_input_tokens as string) || 0,
          total_output_tokens: parseInt(row.total_output_tokens as string) || 0,
          total_tokens: parseInt(row.total_tokens as string) || 0,
          total_cost: parseFloat(row.total_cost as string) || 0,
          avg_latency_ms: parseFloat(row.avg_latency_ms as string) || 0,
          first_seen: row.first_seen,
          last_seen: row.last_seen,
        })),
      });
    }

    // Default: return raw rows with derived type and success fields
    const { type: typeFilter, success: successFilter } = req.query as { type?: string; success?: string };

    // Build WHERE conditions for optional filters
    const whereConditions = [
      '"timestamp" >= $1',
      '"timestamp" <= $2',
      'team_id = $3',
    ];
    const params: (string | number | boolean)[] = [startDate.toISOString(), endDate.toISOString(), String(ctx.team_id)];

    // Add type filter if specified
    if (typeFilter && typeFilter !== 'all') {
      if (typeFilter === 'tool_call') {
        whereConditions.push('COALESCE(tool_call_count, 0) > 0');
      } else if (typeFilter === 'error') {
        whereConditions.push('(finish_reason IS NULL OR finish_reason IN (\'error\', \'content_filter\'))');
      } else if (typeFilter === 'llm_request') {
        whereConditions.push('COALESCE(tool_call_count, 0) = 0');
        whereConditions.push('(finish_reason IS NOT NULL AND finish_reason NOT IN (\'error\', \'content_filter\'))');
      }
    }

    // Add success filter if specified
    if (successFilter !== undefined && successFilter !== '') {
      const isSuccess = successFilter === 'true';
      if (isSuccess) {
        whereConditions.push('finish_reason IN (\'stop\', \'end_turn\', \'tool_calls\', \'length\')');
      } else {
        whereConditions.push('(finish_reason IS NULL OR finish_reason NOT IN (\'stop\', \'end_turn\', \'tool_calls\', \'length\'))');
      }
    }

    params.push(limit, offset);

    const sql = `
      SELECT *,
        CASE
          WHEN COALESCE(tool_call_count, 0) > 0 THEN 'tool_call'
          WHEN finish_reason IS NULL OR finish_reason IN ('error', 'content_filter') THEN 'error'
          ELSE 'llm_request'
        END as derived_type,
        CASE
          WHEN finish_reason IN ('stop', 'end_turn', 'tool_calls', 'length') THEN true
          ELSE false
        END as derived_success
      FROM llm_events
      WHERE ${whereConditions.join(' AND ')}
      ORDER BY "timestamp" DESC
      LIMIT $${params.length - 1} OFFSET $${params.length}
    `;
    const { rows } = await poolClient.query(sql, params);
    return res.json({
      window: { start: startDate.toISOString(), end: endDate.toISOString() },
      count: rows.length,
      filters: { type: typeFilter || 'all', success: successFilter },
      rows,
    });
  } catch (err) {
    console.error("[tsdb] logs error", err);
    return res.status(500).json({ error: "logs_failed", detail: (err as Error).message });
  } finally {
    if (poolClient) poolClient.release();
  }
});

// GET /tsdb/metrics?days=30
// Returns summary metrics with period-over-period % change
router.get("/metrics", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let client: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ error: "invalid_token", detail: "Missing team_id in token" });
    }

    const days = Math.min(parseInt((req.query.days as string) || "30", 10), 365);

    client = await connectTeamClient(ctx.team_id);

    // Calculate date ranges for current and previous periods
    const now = new Date();
    const currentStart = new Date(now);
    currentStart.setDate(currentStart.getDate() - days);
    const previousStart = new Date(currentStart);
    previousStart.setDate(previousStart.getDate() - days);

    // Query metrics for both periods in a single query using CASE statements
    const metricsSql = `
      WITH period_data AS (
        SELECT
          CASE
            WHEN "timestamp" >= $2 THEN 'current'
            ELSE 'previous'
          END as period,
          1 as request,
          COALESCE(usage_input_tokens, 0) as input_tokens,
          COALESCE(usage_output_tokens, 0) as output_tokens,
          COALESCE(
            usage_total_tokens,
            COALESCE(usage_input_tokens, 0) + COALESCE(usage_output_tokens, 0),
            0
          ) as total_tokens,
          COALESCE(usage_cached_tokens, 0) as cached_tokens,
          COALESCE(usage_reasoning_tokens, 0) as reasoning_tokens,
          COALESCE(cost_total, 0) as cost,
          latency_ms,
          trace_id,
          user_id,
          CASE WHEN stream = true THEN 1 ELSE 0 END as is_streaming
        FROM llm_events
        WHERE "timestamp" >= $1 AND "timestamp" <= $3 AND team_id = $4
      ),
      aggregated AS (
        SELECT
          period,
          COUNT(*) as total_requests,
          COUNT(DISTINCT trace_id) as unique_traces,
          COUNT(DISTINCT user_id) as unique_users,
          SUM(input_tokens) as total_input_tokens,
          SUM(output_tokens) as total_output_tokens,
          SUM(total_tokens) as total_tokens,
          SUM(cached_tokens) as cached_tokens,
          SUM(reasoning_tokens) as reasoning_tokens,
          SUM(cost) as total_cost,
          AVG(latency_ms) as avg_latency_ms,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms) as p50_latency_ms,
          PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) as p95_latency_ms,
          PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms) as p99_latency_ms,
          MAX(latency_ms) as max_latency_ms,
          SUM(is_streaming) as streaming_requests
        FROM period_data
        GROUP BY period
      )
      SELECT * FROM aggregated
    `;

    const { rows } = await client.query<MetricRow>(metricsSql, [
      previousStart.toISOString(),
      currentStart.toISOString(),
      now.toISOString(),
      String(ctx.team_id),
    ]);

    // Parse results into current and previous periods
    const current = rows.find((r) => r.period === "current") || {} as Partial<MetricRow>;
    const previous = rows.find((r) => r.period === "previous") || {} as Partial<MetricRow>;

    // Helper to calculate % change
    const pctChange = (curr: string | number | undefined, prev: string | number | undefined): number => {
      const c = parseFloat(curr as string) || 0;
      const p = parseFloat(prev as string) || 0;
      if (p === 0) return c > 0 ? 100 : 0;
      return ((c - p) / p) * 100;
    };

    // Helper to safely parse numbers
    const num = (val: string | number | undefined): number => parseFloat(val as string) || 0;
    const int = (val: string | number | undefined): number => parseInt(val as string) || 0;

    // Calculate derived metrics
    const totalRequests = int(current.total_requests);
    const totalTokens = num(current.total_tokens);
    const cachedTokens = num(current.cached_tokens);
    const inputTokens = num(current.total_input_tokens);
    const uniqueTraces = int(current.unique_traces);
    const streamingRequests = int(current.streaming_requests);

    const cacheHitRate = inputTokens > 0 ? (cachedTokens / inputTokens) * 100 : 0;
    const prevCacheHitRate = num(previous.total_input_tokens) > 0
      ? (num(previous.cached_tokens) / num(previous.total_input_tokens)) * 100
      : 0;

    const streamingRate = totalRequests > 0 ? (streamingRequests / totalRequests) * 100 : 0;
    const prevStreamingRate = int(previous.total_requests) > 0
      ? (int(previous.streaming_requests) / int(previous.total_requests)) * 100
      : 0;

    const avgCallsPerTrace = uniqueTraces > 0 ? totalRequests / uniqueTraces : 0;
    const prevAvgCallsPerTrace = int(previous.unique_traces) > 0
      ? int(previous.total_requests) / int(previous.unique_traces)
      : 0;

    const totalCost = num(current.total_cost);
    const costPer1kTokens = totalTokens > 0 ? (totalCost / (totalTokens / 1000)) : 0;
    const prevTotalTokens = num(previous.total_tokens);
    const prevCostPer1kTokens = prevTotalTokens > 0
      ? (num(previous.total_cost) / (prevTotalTokens / 1000))
      : 0;

    const metrics = {
      period: {
        days,
        current: { start: currentStart.toISOString(), end: now.toISOString() },
        previous: { start: previousStart.toISOString(), end: currentStart.toISOString() },
      },
      volume: {
        total_requests: {
          value: totalRequests,
          unit: "requests",
          change_pct: pctChange(current.total_requests, previous.total_requests),
        },
        unique_traces: {
          value: uniqueTraces,
          unit: "traces",
          change_pct: pctChange(current.unique_traces, previous.unique_traces),
        },
        unique_users: {
          value: int(current.unique_users),
          unit: "users",
          change_pct: pctChange(current.unique_users, previous.unique_users),
        },
        avg_calls_per_trace: {
          value: Math.round(avgCallsPerTrace * 100) / 100,
          unit: "calls/trace",
          change_pct: pctChange(avgCallsPerTrace, prevAvgCallsPerTrace),
        },
      },
      tokens: {
        total_input_tokens: {
          value: int(current.total_input_tokens),
          unit: "tokens",
          change_pct: pctChange(current.total_input_tokens, previous.total_input_tokens),
        },
        total_output_tokens: {
          value: int(current.total_output_tokens),
          unit: "tokens",
          change_pct: pctChange(current.total_output_tokens, previous.total_output_tokens),
        },
        total_tokens: {
          value: int(totalTokens),
          unit: "tokens",
          change_pct: pctChange(current.total_tokens, previous.total_tokens),
        },
        cached_tokens: {
          value: int(cachedTokens),
          unit: "tokens",
          change_pct: pctChange(current.cached_tokens, previous.cached_tokens),
        },
        reasoning_tokens: {
          value: int(current.reasoning_tokens),
          unit: "tokens",
          change_pct: pctChange(current.reasoning_tokens, previous.reasoning_tokens),
        },
        cache_hit_rate: {
          value: Math.round(cacheHitRate * 100) / 100,
          unit: "%",
          change_pct: pctChange(cacheHitRate, prevCacheHitRate),
        },
        avg_tokens_per_request: {
          value: totalRequests > 0 ? Math.round(totalTokens / totalRequests) : 0,
          unit: "tokens/req",
          change_pct: pctChange(
            totalRequests > 0 ? totalTokens / totalRequests : 0,
            int(previous.total_requests) > 0 ? prevTotalTokens / int(previous.total_requests) : 0
          ),
        },
      },
      performance: {
        avg_latency_ms: {
          value: Math.round(num(current.avg_latency_ms) * 100) / 100,
          unit: "ms",
          change_pct: pctChange(current.avg_latency_ms, previous.avg_latency_ms),
        },
        p50_latency_ms: {
          value: Math.round(num(current.p50_latency_ms) * 100) / 100,
          unit: "ms",
          change_pct: pctChange(current.p50_latency_ms, previous.p50_latency_ms),
        },
        p95_latency_ms: {
          value: Math.round(num(current.p95_latency_ms) * 100) / 100,
          unit: "ms",
          change_pct: pctChange(current.p95_latency_ms, previous.p95_latency_ms),
        },
        p99_latency_ms: {
          value: Math.round(num(current.p99_latency_ms) * 100) / 100,
          unit: "ms",
          change_pct: pctChange(current.p99_latency_ms, previous.p99_latency_ms),
        },
        max_latency_ms: {
          value: Math.round(num(current.max_latency_ms) * 100) / 100,
          unit: "ms",
          change_pct: pctChange(current.max_latency_ms, previous.max_latency_ms),
        },
      },
      cost: {
        total_cost: {
          value: Math.round(totalCost * 100) / 100,
          unit: "USD",
          change_pct: pctChange(current.total_cost, previous.total_cost),
        },
        avg_cost_per_request: {
          value: totalRequests > 0 ? Math.round((totalCost / totalRequests) * 10000) / 10000 : 0,
          unit: "USD/req",
          change_pct: pctChange(
            totalRequests > 0 ? totalCost / totalRequests : 0,
            int(previous.total_requests) > 0 ? num(previous.total_cost) / int(previous.total_requests) : 0
          ),
        },
        cost_per_1k_tokens: {
          value: Math.round(costPer1kTokens * 10000) / 10000,
          unit: "USD/1k tokens",
          change_pct: pctChange(costPer1kTokens, prevCostPer1kTokens),
        },
      },
      usage_patterns: {
        streaming_rate: {
          value: Math.round(streamingRate * 100) / 100,
          unit: "%",
          change_pct: pctChange(streamingRate, prevStreamingRate),
        },
      },
    };

    return res.json(metrics);
  } catch (err) {
    console.error("[tsdb] metrics error", err);
    return res.status(500).json({ error: "metrics_failed", detail: (err as Error).message });
  } finally {
    if (client) client.release();
  }
});

// POST /tsdb/refresh-aggregates
// Manually refresh all continuous aggregates to ensure data is up-to-date
router.post("/refresh-aggregates", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let client: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ error: "invalid_token", detail: "Missing team_id in token" });
    }

    client = await connectTeamClient(ctx.team_id);

    const results: Array<{ ca: string; status: string; error?: string }> = [];

    // Refresh all CAs from beginning of time to now
    const cas = [
      "llm_events_daily_ca",
      "llm_events_daily_by_model_ca",
      "llm_events_daily_by_agent_ca",
    ];

    for (const ca of cas) {
      try {
        await client.query(`CALL refresh_continuous_aggregate('${ca}', NULL, NOW())`);
        results.push({ ca, status: "refreshed" });
      } catch (err) {
        results.push({ ca, status: "error", error: (err as Error).message });
      }
    }

    return res.json({
      message: "Continuous aggregates refresh completed",
      results,
      refreshed_at: new Date().toISOString(),
    });
  } catch (err) {
    console.error("[tsdb] refresh-aggregates error", err);
    return res.status(500).json({ error: "refresh_failed", detail: (err as Error).message });
  } finally {
    if (client) client.release();
  }
});

// ==================== PRICING CRUD ENDPOINTS ====================

// GET /tsdb/pricing - List all pricing
// Optional: ?group_by=provider to group by provider
router.get("/pricing", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  try {
    const { group_by } = req.query;

    if (group_by === "provider") {
      const pricing = await pricingService.getPricingByProvider();
      return res.json({ pricing, grouped_by: "provider" });
    }

    const pricing = await pricingService.getAllPricing();
    return res.json({ pricing, count: Object.keys(pricing).length });
  } catch (err) {
    console.error("[tsdb] pricing list error", err);
    return res.status(500).json({ error: "pricing_list_failed", detail: (err as Error).message });
  }
});

// GET /tsdb/pricing/:model - Get specific model pricing
router.get("/pricing/:model", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  try {
    const { model } = req.params;
    const { provider } = req.query;

    const pricing = await pricingService.getModelPricing(model, provider as string | undefined);
    return res.json({ pricing });
  } catch (err) {
    console.error("[tsdb] pricing get error", err);
    return res.status(500).json({ error: "pricing_get_failed", detail: (err as Error).message });
  }
});

// POST /tsdb/pricing - Add new model pricing
router.post("/pricing", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  try {
    const ctx = getTokenContext(req);
    const { model, provider, input_per_1m, output_per_1m, cached_input_per_1m, aliases } = req.body;

    if (!model) {
      return res.status(400).json({ error: "model is required" });
    }
    if (input_per_1m === undefined || output_per_1m === undefined) {
      return res.status(400).json({ error: "input_per_1m and output_per_1m are required" });
    }

    const result = await pricingService.upsertPricing(
      model,
      {
        provider,
        input_per_1m,
        output_per_1m,
        cached_input_per_1m: cached_input_per_1m ?? input_per_1m * 0.5,
        aliases: aliases || [],
      },
      ctx?.user_id
    );

    return res.json({ message: "pricing_created", pricing: result });
  } catch (err) {
    console.error("[tsdb] pricing create error", err);
    return res.status(500).json({ error: "pricing_create_failed", detail: (err as Error).message });
  }
});

// PUT /tsdb/pricing/:model - Update model pricing
router.put("/pricing/:model", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  try {
    const ctx = getTokenContext(req);
    const { model } = req.params;
    const { provider, input_per_1m, output_per_1m, cached_input_per_1m, aliases } = req.body;

    const result = await pricingService.upsertPricing(
      model,
      {
        provider,
        input_per_1m,
        output_per_1m,
        cached_input_per_1m,
        aliases,
      },
      ctx?.user_id
    );

    return res.json({ message: "pricing_updated", pricing: result });
  } catch (err) {
    console.error("[tsdb] pricing update error", err);
    return res.status(500).json({ error: "pricing_update_failed", detail: (err as Error).message });
  }
});

// DELETE /tsdb/pricing/:model - Remove model pricing
router.delete("/pricing/:model", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  try {
    const { model } = req.params;
    const deleted = await pricingService.deletePricing(model);

    if (!deleted) {
      return res.status(404).json({ error: "pricing_not_found", model });
    }

    return res.json({ message: "pricing_deleted", model });
  } catch (err) {
    console.error("[tsdb] pricing delete error", err);
    return res.status(500).json({ error: "pricing_delete_failed", detail: (err as Error).message });
  }
});

// POST /tsdb/pricing/seed - Seed default pricing to DB
router.post("/pricing/seed", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  try {
    const ctx = getTokenContext(req);
    const { overwrite } = req.body;

    const result = await pricingService.seedDefaultPricing(ctx?.user_id, overwrite === true);

    return res.json({
      message: "pricing_seeded",
      ...result,
    });
  } catch (err) {
    console.error("[tsdb] pricing seed error", err);
    return res.status(500).json({ error: "pricing_seed_failed", detail: (err as Error).message });
  }
});

// POST /tsdb/pricing/refresh - Force refresh pricing cache
router.post("/pricing/refresh", AUTH_MIDDLEWARE, async (_req: Request, res: Response) => {
  try {
    await pricingService.loadPricingFromDb(true);
    const pricing = await pricingService.getAllPricing();

    return res.json({
      message: "cache_refreshed",
      count: Object.keys(pricing).length,
      refreshed_at: new Date().toISOString(),
    });
  } catch (err) {
    console.error("[tsdb] pricing refresh error", err);
    return res.status(500).json({ error: "pricing_refresh_failed", detail: (err as Error).message });
  }
});

router.get("/analytics-wide", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let client: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ error: "invalid_token", detail: "Missing team_id in token" });
    }

    const windowLabel = (req.query.window as string) || "this_month";

    client = await connectTeamClient(ctx.team_id);

    const analytics = await buildAnalytics({
      windowLabel,
      client,
      resolution: "day",
    });

    return res.json({ analytics });
  } catch (err) {
    console.error("[tsdb] analytics-wide error", err);
    return res.status(500).json({ error: "analytics_failed", detail: (err as Error).message });
  } finally {
    if (client) client.release();
  }
});

router.get("/analytics-narrow", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let client: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ error: "invalid_token", detail: "Missing team_id in token" });
    }

    client = await connectTeamClient(ctx.team_id);

    const analytics = await buildAnalytics({
      windowLabel: "today",
      client,
      resolution: "hour",
    });

    return res.json({ analytics });
  } catch (err) {
    console.error("[tsdb] analytics-narrow error", err);
    return res.status(500).json({ error: "analytics_failed", detail: (err as Error).message });
  } finally {
    if (client) client.release();
  }
});

// POST /tsdb/recalculate-costs - Recalculate historical costs with current pricing
router.post("/recalculate-costs", AUTH_MIDDLEWARE, async (req: Request, res: Response) => {
  let poolClient: PoolClient | undefined;
  try {
    const ctx = getTokenContext(req);
    if (!ctx || !ctx.team_id) {
      return res.status(401).json({ error: "invalid_token", detail: "Missing team_id in token" });
    }

    const { start, end, batch_size = 1000 } = req.body;

    if (!start || !end) {
      return res.status(400).json({ error: "start and end dates are required" });
    }

    const startDate = new Date(start);
    const endDate = new Date(end);

    if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) {
      return res.status(400).json({ error: "invalid_dates", detail: "start and end must be valid ISO dates" });
    }

    if (endDate < startDate) {
      return res.status(400).json({ error: "invalid_range", detail: "end must be after start" });
    }

    poolClient = await connectTeamClient(ctx.team_id);

    // Ensure pricing is loaded
    await pricingService.loadPricingFromDb(true);

    const results: {
      updated: number;
      processed: number;
      errors: Array<{ trace_id?: string; call_sequence?: number; batch?: number; error?: string; warning?: string }>;
      batches: number;
    } = {
      updated: 0,
      processed: 0,
      errors: [],
      batches: 0,
    };

    const startTime = Date.now();
    let offset = 0;
    let hasMore = true;

    // Process in batches
    while (hasMore) {
      // Fetch batch of events
      const selectSql = `
        SELECT
          "timestamp",
          trace_id,
          call_sequence,
          model,
          provider,
          usage_input_tokens,
          usage_output_tokens,
          usage_cached_tokens,
          cost_total
        FROM llm_events
        WHERE "timestamp" >= $1 AND "timestamp" <= $2 AND team_id = $3
        ORDER BY "timestamp"
        LIMIT $4 OFFSET $5
      `;

      const { rows } = await poolClient.query<LLMEventRow>(selectSql, [
        startDate.toISOString(),
        endDate.toISOString(),
        String(ctx.team_id),
        batch_size,
        offset,
      ]);

      if (rows.length === 0) {
        hasMore = false;
        break;
      }

      results.batches++;

      // Calculate new costs and prepare updates
      const updates: Array<{ timestamp: Date; trace_id: string; call_sequence: number; new_cost: number }> = [];
      for (const row of rows) {
        try {
          const costResult = pricingService.calculateCostSync({
            model: row.model || "",
            provider: row.provider,
            input_tokens: row.usage_input_tokens || 0,
            output_tokens: row.usage_output_tokens || 0,
            cached_tokens: row.usage_cached_tokens || 0,
          });

          // Only update if cost changed
          const oldCost = parseFloat(row.cost_total as string) || 0;
          const newCost = costResult.total;

          if (Math.abs(newCost - oldCost) > 0.000001) {
            updates.push({
              timestamp: row.timestamp,
              trace_id: row.trace_id,
              call_sequence: row.call_sequence,
              new_cost: newCost,
            });
          }

          results.processed++;
        } catch (err) {
          results.errors.push({
            trace_id: row.trace_id,
            call_sequence: row.call_sequence,
            error: (err as Error).message,
          });
        }
      }

      // Apply batch updates
      if (updates.length > 0) {
        // Use a single UPDATE with CASE for efficiency
        const updateSql = `
          UPDATE llm_events
          SET cost_total = updates.new_cost
          FROM (VALUES ${updates.map((_, i) => `($${i * 4 + 1}::timestamptz, $${i * 4 + 2}::text, $${i * 4 + 3}::integer, $${i * 4 + 4}::numeric)`).join(", ")}) AS updates(ts, tid, cs, new_cost)
          WHERE llm_events."timestamp" = updates.ts
            AND llm_events.trace_id = updates.tid
            AND llm_events.call_sequence = updates.cs
        `;

        const updateValues = updates.flatMap((u) => [u.timestamp, u.trace_id, u.call_sequence, u.new_cost]);

        try {
          await poolClient.query(updateSql, updateValues);
          results.updated += updates.length;
        } catch (err) {
          results.errors.push({ batch: results.batches, error: (err as Error).message });
        }
      }

      offset += batch_size;

      // Safety check - stop if taking too long (5 minutes)
      if (Date.now() - startTime > 5 * 60 * 1000) {
        results.errors.push({ warning: "Timeout reached after 5 minutes. Partial recalculation completed." });
        hasMore = false;
      }
    }

    // Refresh continuous aggregates after recalculation
    const caRefreshResults: Array<{ ca: string; status: string; error?: string }> = [];
    const cas = ["llm_events_daily_ca", "llm_events_daily_by_model_ca", "llm_events_daily_by_agent_ca"];

    for (const ca of cas) {
      try {
        await poolClient.query(`CALL refresh_continuous_aggregate('${ca}', $1::timestamptz, $2::timestamptz)`, [
          startDate.toISOString(),
          endDate.toISOString(),
        ]);
        caRefreshResults.push({ ca, status: "refreshed" });
      } catch (err) {
        caRefreshResults.push({ ca, status: "error", error: (err as Error).message });
      }
    }

    return res.json({
      message: "recalculation_complete",
      period: { start: startDate.toISOString(), end: endDate.toISOString() },
      stats: {
        processed: results.processed,
        updated: results.updated,
        batches: results.batches,
        duration_ms: Date.now() - startTime,
      },
      continuous_aggregates: caRefreshResults,
      errors: results.errors.slice(0, 10), // Limit error output
      error_count: results.errors.length,
    });
  } catch (err) {
    console.error("[tsdb] recalculate-costs error", err);
    return res.status(500).json({ error: "recalculate_failed", detail: (err as Error).message });
  } finally {
    if (poolClient) poolClient.release();
  }
});

export default router;
