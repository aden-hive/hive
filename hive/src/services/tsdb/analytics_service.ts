/**
 * TSDB Analytics Service
 * Computes windowed aggregations from llm_events for dashboard analytics.
 */

import { PoolClient } from 'pg';
import pricingService from './pricing_service';
import { DailyCostRow, LatencyStatsRow, LatencyBucketRow, ModelCostRow, AgentCostRow, LLMEventRow } from './analytics_types';

const BUCKETS = [
  { label: '0-1s', min: 0, max: 1000 },
  { label: '1-2s', min: 1000, max: 2000 },
  { label: '2-5s', min: 2000, max: 5000 },
  { label: '5-10s', min: 5000, max: 10000 },
  { label: '10-20s', min: 10000, max: 20000 },
  { label: '20s+', min: 20000, max: null as number | null },
];

interface WindowDef {
  label: string;
  start: Date | null;
  end: Date;
}

interface DailyRow {
  bucket: string;
  requests: number;
  cost_total: number;
  tokens: {
    total: number;
    input: number;
    output: number;
    cached: number;
  };
}

interface LatencyRow {
  bucket: string;
  count: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
}

interface ModelCostRow {
  model: string;
  cost_total: number;
  cached_tokens: number;
}

interface AgentCostRow {
  agent: string;
  requests: number;
  cost_total: number;
  input_tokens: number;
  output_tokens: number;
  avg_latency_ms: number | null;
}

const toNumber = (val: unknown, fallback = 0): number => {
  const n = Number(val);
  return Number.isFinite(n) ? n : fallback;
};

const percentile = (values: number[], pct: number): number | null => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length === 1) return sorted[0];
  const idx = Math.max(0, Math.min(sorted.length - 1, Math.floor(pct * (sorted.length - 1))));
  return sorted[idx];
};

const startOfWeekUtc = (d: Date): Date => {
  const day = d.getUTCDay();
  const diff = (day + 6) % 7;
  const monday = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 0, 0, 0, 0));
  monday.setUTCDate(monday.getUTCDate() - diff);
  return monday;
};

const startOfMonthUtc = (d: Date): Date =>
  new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1, 0, 0, 0, 0));

const startOfDayUtc = (d: Date): Date =>
  new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 0, 0, 0, 0));

export const parseAnalyticsWindow = (label: string): WindowDef => {
  const now = new Date();
  switch ((label || '').toLowerCase()) {
    case 'all_time':
    case 'all-time':
    case 'alltime':
      return { label: 'all_time', start: null, end: now };
    case 'today': {
      const start = startOfDayUtc(now);
      return { label: 'today', start, end: now };
    }
    case 'last_2_weeks':
    case 'last-2-weeks':
    case 'last2weeks': {
      const start = new Date(now.getTime() - 14 * 24 * 3600 * 1000);
      return { label: 'last_2_weeks', start, end: now };
    }
    case 'this_week': {
      const start = startOfWeekUtc(now);
      return { label: 'this_week', start, end: now };
    }
    case 'this_month':
    default: {
      const start = startOfMonthUtc(now);
      return { label: 'this_month', start, end: now };
    }
  }
};

const bucketLatency = (latMs: number, buckets: typeof BUCKETS): string | null => {
  if (latMs === null || latMs === undefined) return null;
  for (const b of buckets) {
    if (b.max === null) {
      if (latMs >= b.min) return b.label;
    } else if (latMs >= b.min && latMs < b.max) {
      return b.label;
    }
  }
  return null;
};

const buildLatencyDistribution = (rows: { bucket: string; count: number }[]) => {
  const counts = new Map(rows.map((r) => [r.bucket, r.count]));
  const total = rows.reduce((acc, r) => acc + (r.count || 0), 0);
  return BUCKETS.map((b) => {
    const count = counts.get(b.label) || 0;
    return {
      bucket: b.label,
      count,
      share: total ? count / total : null,
    };
  });
};

const bucketLabel = (date: Date, resolution: string): string => {
  if (resolution === 'hour') {
    const h = new Date(
      Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate(), date.getUTCHours(), 0, 0, 0)
    );
    return h.toISOString().slice(0, 13) + ':00:00Z';
  }
  return date.toISOString().slice(0, 10);
};

const fetchDailyCA = async ({
  client,
  start,
  end,
}: {
  client: PoolClient;
  start: Date | null;
  end: Date | null;
}): Promise<DailyRow[]> => {
  const params: (Date | null)[] = [];
  const conds: string[] = [];
  if (start) {
    params.push(start);
    conds.push(`bucket >= $${params.length}`);
  }
  if (end) {
    params.push(end);
    conds.push(`bucket < $${params.length}`);
  }
  const sql = `
    SELECT bucket, requests, cost_total, input_tokens, output_tokens, total_tokens, cached_tokens
    FROM llm_events_daily_ca
    ${conds.length ? `WHERE ${conds.join(' AND ')}` : ''}
    ORDER BY bucket ASC
  `;
  const { rows } = await client.query<DailyCostRow>(sql, params);
  return rows.map((r) => ({    bucket: r.bucket instanceof Date ? r.bucket.toISOString().slice(0, 10) : r.bucket,
    requests: Number(r.requests) || 0,
    cost_total: toNumber(r.cost_total, 0),
    tokens: {
      total: toNumber(r.total_tokens, 0),
      input: toNumber(r.input_tokens, 0),
      output: toNumber(r.output_tokens, 0),
      cached: toNumber(r.cached_tokens, 0),
    },
  }));
};

const fetchTodayFromBaseTable = async ({
  client,
  todayStart,
  end,
}: {
  client: PoolClient;
  todayStart: Date;
  end: Date;
}): Promise<DailyRow | null> => {
  const sql = `
    SELECT
      $1::date as bucket,
      COUNT(*) as requests,
      COALESCE(SUM(cost_total), 0) as cost_total,
      COALESCE(SUM(usage_input_tokens), 0) as input_tokens,
      COALESCE(SUM(usage_output_tokens), 0) as output_tokens,
      COALESCE(SUM(COALESCE(usage_total_tokens, usage_input_tokens + usage_output_tokens)), 0) as total_tokens,
      COALESCE(SUM(usage_cached_tokens), 0) as cached_tokens
    FROM llm_events
    WHERE "timestamp" >= $1 AND "timestamp" <= $2
  `;
  const { rows } = await client.query(sql, [todayStart, end]);
  if (!rows.length || rows[0].requests === 0 || rows[0].requests === '0') {
    return null;
  }
  const r = rows[0];
  return {
    bucket: todayStart.toISOString().slice(0, 10),
    requests: Number(r.requests) || 0,
    cost_total: toNumber(r.cost_total, 0),
    tokens: {
      total: toNumber(r.total_tokens, 0),
      input: toNumber(r.input_tokens, 0),
      output: toNumber(r.output_tokens, 0),
      cached: toNumber(r.cached_tokens, 0),
    },
  };
};

const fetchLatencyDaily = async ({
  client,
  start,
  end,
}: {
  client: PoolClient;
  start: Date | null;
  end: Date | null;
}): Promise<LatencyRow[]> => {
  const params: (string | Date)[] = ['1 day'];
  const conds = ['latency_ms IS NOT NULL'];
  if (start) {
    params.push(start);
    conds.push(`"timestamp" >= $${params.length}`);
  }
  if (end) {
    params.push(end);
    conds.push(`"timestamp" < $${params.length}`);
  }
  const sql = `
    SELECT
      time_bucket($1::interval, "timestamp") AS bucket,
      COUNT(latency_ms) AS count,
      AVG(latency_ms) AS avg_ms,
      percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,
      percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms,
      percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99_ms
    FROM llm_events
    WHERE ${conds.join(' AND ')}
    GROUP BY 1
    ORDER BY 1 ASC
  `;
  const { rows } = await client.query<LatencyStatsRow>(sql, params);
  return rows.map((r) => ({    bucket: r.bucket instanceof Date ? r.bucket.toISOString().slice(0, 10) : r.bucket,
    count: Number(r.count) || 0,
    avg_ms: r.avg_ms === null ? null : Number(r.avg_ms),
    p50_ms: r.p50_ms === null ? null : Number(r.p50_ms),
    p95_ms: r.p95_ms === null ? null : Number(r.p95_ms),
    p99_ms: r.p99_ms === null ? null : Number(r.p99_ms),
  }));
};

const fetchLatencyDistributionDaily = async ({
  client,
  start,
  end,
}: {
  client: PoolClient;
  start: Date | null;
  end: Date | null;
}): Promise<{ bucket: string; count: number }[]> => {
  const params: Date[] = [];
  const conds = ['latency_ms IS NOT NULL'];
  if (start) {
    params.push(start);
    conds.push(`"timestamp" >= $${params.length}`);
  }
  if (end) {
    params.push(end);
    conds.push(`"timestamp" < $${params.length}`);
  }
  const sql = `
    SELECT
      CASE
        WHEN latency_ms < 1000 THEN '0-1s'
        WHEN latency_ms < 2000 THEN '1-2s'
        WHEN latency_ms < 5000 THEN '2-5s'
        WHEN latency_ms < 10000 THEN '5-10s'
        WHEN latency_ms < 20000 THEN '10-20s'
        ELSE '20s+'
      END AS bucket,
      COUNT(*) AS count
    FROM llm_events
    WHERE ${conds.join(' AND ')}
    GROUP BY 1
  `;
  const { rows } = await client.query<LatencyBucketRow>(sql, params);
  return rows.map((r) => {{ bucket: r.bucket, count: Number(r.count) || 0 }});};

const fetchModelCost = async ({
  client,
  start,
  end,
}: {
  client: PoolClient;
  start: Date | null;
  end: Date | null;
}): Promise<ModelCostRow[]> => {
  const params: Date[] = [];
  const conds: string[] = [];
  if (start) {
    params.push(start);
    conds.push(`"timestamp" >= $${params.length}`);
  }
  if (end) {
    params.push(end);
    conds.push(`"timestamp" < $${params.length}`);
  }
  const sql = `
    SELECT model,
           SUM(cost_total) AS cost_total,
           SUM(usage_cached_tokens) AS cached_tokens
    FROM llm_events
    ${conds.length ? `WHERE ${conds.join(' AND ')}` : ''}
    GROUP BY model
  `;
  const { rows } = await client.query(sql, params);
  return rows
    .filter((r: any) => r.model)
    .map((r: any) => ({
      model: r.model,
      cost_total: toNumber(r.cost_total, 0),
      cached_tokens: toNumber(r.cached_tokens, 0),
    }));
};

const fetchAgentCost = async ({
  client,
  start,
  end,
}: {
  client: PoolClient;
  start: Date | null;
  end: Date | null;
}): Promise<AgentCostRow[]> => {
  const params: Date[] = [];
  const conds: string[] = [];
  if (start) {
    params.push(start);
    conds.push(`"timestamp" >= $${params.length}`);
  }
  if (end) {
    params.push(end);
    conds.push(`"timestamp" < $${params.length}`);
  }
  const sql = `
    SELECT agent,
           COUNT(*) AS requests,
           SUM(cost_total) AS cost_total,
           SUM(usage_input_tokens) AS input_tokens,
           SUM(usage_output_tokens) AS output_tokens,
           AVG(latency_ms) AS avg_latency_ms
    FROM llm_events
    ${conds.length ? `WHERE ${conds.join(' AND ')}` : ''}
    GROUP BY agent
  `;
  const { rows } = await client.query(sql, params);
  return rows
    .filter((r: any) => r.agent)
    .map((r: any) => ({
      agent: r.agent,
      requests: Number(r.requests) || 0,
      cost_total: toNumber(r.cost_total, 0),
      input_tokens: toNumber(r.input_tokens, 0),
      output_tokens: toNumber(r.output_tokens, 0),
      avg_latency_ms: r.avg_latency_ms === null ? null : Number(r.avg_latency_ms),
    }));
};

export const buildAnalytics = async ({
  windowLabel,
  client,
  resolution = 'day',
}: {
  windowLabel: string;
  client: PoolClient;
  resolution?: 'day' | 'hour';
}) => {
  const windowDef = parseAnalyticsWindow(windowLabel);

  if (resolution === 'day') {
    try {
      const now = windowDef.end || new Date();
      const todayMidnight = new Date(
        Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 0, 0, 0)
      );

      const caRows = await fetchDailyCA({ client, start: windowDef.start, end: todayMidnight });

      let todayData: DailyRow | null = null;
      if (now >= todayMidnight) {
        try {
          todayData = await fetchTodayFromBaseTable({ client, todayStart: todayMidnight, end: now });
        } catch {
          // Ignore errors fetching today's data
        }
      }

      const allRows = [...(caRows || [])];
      if (todayData) {
        const todayBucket = todayData.bucket;
        const existingIdx = allRows.findIndex((r) => r.bucket === todayBucket);
        if (existingIdx >= 0) {
          allRows[existingIdx] = todayData;
        } else {
          allRows.push(todayData);
        }
      }

      if (allRows && allRows.length) {
        const total_cost = allRows.reduce((acc, r) => acc + (r.cost_total || 0), 0);
        const total_requests = allRows.reduce((acc, r) => acc + (r.requests || 0), 0);
        const total_tokens = allRows.reduce((acc, r) => acc + (r.tokens.total || 0), 0);

        const bucket_cost = allRows.map((r) => ({ bucket: r.bucket, cost_total: r.cost_total }));
        const bucket_requests = allRows.map((r) => ({ bucket: r.bucket, requests: r.requests }));
        const bucket_tokens = allRows.map((r) => ({
          bucket: r.bucket,
          total_tokens: r.tokens.total,
          input_tokens: r.tokens.input,
          output_tokens: r.tokens.output,
          cached_tokens: r.tokens.cached,
        }));

        const latencyBuckets = await fetchLatencyDaily({
          client,
          start: windowDef.start,
          end: windowDef.end,
        });
        const latencyDistributionRows = await fetchLatencyDistributionDaily({
          client,
          start: windowDef.start,
          end: windowDef.end,
        });
        const latency_distribution = buildLatencyDistribution(latencyDistributionRows);
        const latency_total = latencyDistributionRows.reduce((acc, r) => acc + (r.count || 0), 0);
        const avg_latency_ms =
          latencyBuckets.reduce(
            (acc, r) => acc + (r.avg_ms !== null ? r.avg_ms * (r.count || 0) : 0),
            0
          ) / (latency_total || 1);

        const modelRows = await fetchModelCost({ client, start: windowDef.start, end: windowDef.end });
        const models = modelRows
          .sort((a, b) => (b.cost_total || 0) - (a.cost_total || 0))
          .map((r) => ({
            model: r.model,
            cost_total: r.cost_total,
            share: total_cost ? r.cost_total / total_cost : null,
          }));
        const cache_savings = modelRows.reduce((acc, r) => {
          const pricing = pricingService.getModelPricingSync(r.model || '');
          return acc + (r.cached_tokens / 1_000_000) * pricing.input;
        }, 0);

        const agentRows = await fetchAgentCost({ client, start: windowDef.start, end: windowDef.end });
        const agents = agentRows
          .sort((a, b) => (b.cost_total || 0) - (a.cost_total || 0))
          .map((r) => ({
            agent: r.agent,
            requests: r.requests,
            cost_total: r.cost_total,
            share: total_cost ? r.cost_total / total_cost : null,
            avg_latency_ms: r.avg_latency_ms,
          }));

        return {
          window: {
            label: windowDef.label,
            start: windowDef.start ? windowDef.start.toISOString() : null,
            end: windowDef.end ? windowDef.end.toISOString() : null,
          },
          summary: {
            total_cost,
            total_requests,
            total_tokens,
            avg_latency_ms: Number.isFinite(avg_latency_ms) ? avg_latency_ms : null,
            cache_savings,
          },
          timeline: {
            resolution: 'day',
            daily: {
              cost: bucket_cost,
              requests: bucket_requests,
              tokens: bucket_tokens,
              latency_percentiles: latencyBuckets,
            },
          },
          cost_by_model: {
            total_cost,
            models,
          },
          cost_by_agent: {
            total_cost,
            agents,
          },
          latency_distribution: {
            total: latency_total,
            buckets: latency_distribution,
          },
        };
      }
    } catch (err) {
      // Fall through to base-table path
    }
  }

  // Fallback: scan base table directly
  const params: Date[] = [];
  const conditions: string[] = [];
  if (windowDef.start) {
    params.push(windowDef.start);
    conditions.push(`"timestamp" >= $${params.length}`);
  }
  if (windowDef.end) {
    params.push(windowDef.end);
    conditions.push(`"timestamp" < $${params.length}`);
  }

  const sql = `
    SELECT
      "timestamp",
      model,
      agent,
      latency_ms,
      cost_total,
      usage_input_tokens,
      usage_output_tokens,
      usage_total_tokens,
      usage_cached_tokens
    FROM llm_events
    ${conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''}
    ORDER BY "timestamp" ASC
  `;

  const { rows } = await client.query(sql, params);

  const bucketCost = new Map<string, number>();
  const bucketRequests = new Map<string, number>();
  const bucketTokens = new Map<string, { total: number; input: number; output: number; cached: number }>();
  const bucketLatencies = new Map<string, number[]>();
  const modelCost = new Map<string, number>();
  const agentStats = new Map<string, { cost: number; requests: number; latencies: number[] }>();
  const latencyBucketCounts = new Map<string, number>();

  let totalCost = 0;
  let totalRequests = 0;
  let totalTokens = 0;
  let totalLatency = 0;
  let latencyCount = 0;
  let cacheSavings = 0;

  rows.forEach((r: any) => {
    const ts = r.timestamp instanceof Date ? r.timestamp : new Date(r.timestamp);
    if (!ts || Number.isNaN(ts.getTime())) return;
    const bucket = bucketLabel(ts, resolution);

    const cost = toNumber(r.cost_total, 0);
    const inTok = toNumber(r.usage_input_tokens, 0);
    const outTok = toNumber(r.usage_output_tokens, 0);
    const totalTokRaw = toNumber(r.usage_total_tokens, inTok + outTok);
    const cachedTok = toNumber(r.usage_cached_tokens, 0);
    const lat = r.latency_ms === null || r.latency_ms === undefined ? null : Number(r.latency_ms);

    totalRequests += 1;
    totalCost += cost;
    totalTokens += totalTokRaw;
    if (lat !== null && !Number.isNaN(lat)) {
      totalLatency += lat;
      latencyCount += 1;
    }

    bucketCost.set(bucket, (bucketCost.get(bucket) || 0) + cost);
    bucketRequests.set(bucket, (bucketRequests.get(bucket) || 0) + 1);
    const tok = bucketTokens.get(bucket) || { total: 0, input: 0, output: 0, cached: 0 };
    tok.total += totalTokRaw;
    tok.input += inTok;
    tok.output += outTok;
    tok.cached += cachedTok;
    bucketTokens.set(bucket, tok);

    if (lat !== null && !Number.isNaN(lat)) {
      const arr = bucketLatencies.get(bucket) || [];
      arr.push(lat);
      bucketLatencies.set(bucket, arr);

      const latBucket = bucketLatency(lat, BUCKETS);
      if (latBucket) latencyBucketCounts.set(latBucket, (latencyBucketCounts.get(latBucket) || 0) + 1);
    }

    if (r.model) {
      modelCost.set(r.model, (modelCost.get(r.model) || 0) + cost);
    }

    if (r.agent) {
      const stats = agentStats.get(r.agent) || { cost: 0, requests: 0, latencies: [] };
      stats.cost += cost;
      stats.requests += 1;
      if (lat !== null && !Number.isNaN(lat)) {
        stats.latencies.push(lat);
      }
      agentStats.set(r.agent, stats);
    }

    if (cachedTok > 0) {
      const pricing = pricingService.getModelPricingSync(r.model || '');
      cacheSavings += (cachedTok / 1_000_000) * pricing.input;
    }
  });

  const sortedBuckets = Array.from(
    new Set([
      ...bucketCost.keys(),
      ...bucketRequests.keys(),
      ...bucketTokens.keys(),
      ...bucketLatencies.keys(),
    ])
  ).sort();

  const bucket_cost = sortedBuckets.map((key) => ({ bucket: key, cost_total: bucketCost.get(key) || 0 }));
  const bucket_requests = sortedBuckets.map((key) => ({
    bucket: key,
    requests: bucketRequests.get(key) || 0,
  }));
  const bucket_tokens = sortedBuckets.map((key) => {
    const tok = bucketTokens.get(key) || { total: 0, input: 0, output: 0, cached: 0 };
    return {
      bucket: key,
      total_tokens: tok.total,
      input_tokens: tok.input,
      output_tokens: tok.output,
      cached_tokens: tok.cached,
    };
  });
  const bucket_latency_percentiles = sortedBuckets.map((key) => {
    const lats = bucketLatencies.get(key) || [];
    return {
      bucket: key,
      count: lats.length,
      avg_ms: lats.length ? lats.reduce((a, b) => a + b, 0) / lats.length : null,
      p50_ms: percentile(lats, 0.5),
      p95_ms: percentile(lats, 0.95),
      p99_ms: percentile(lats, 0.99),
    };
  });

  const latency_total = Array.from(latencyBucketCounts.values()).reduce((a, b) => a + b, 0);
  const latency_distribution = BUCKETS.map((b) => {
    const count = latencyBucketCounts.get(b.label) || 0;
    return {
      bucket: b.label,
      count,
      share: latency_total ? count / latency_total : null,
    };
  });

  const models = Array.from(modelCost.entries())
    .sort((a, b) => (b[1] || 0) - (a[1] || 0))
    .map(([model, cost]) => ({
      model,
      cost_total: cost,
      share: totalCost ? cost / totalCost : null,
    }));

  const agents = Array.from(agentStats.entries())
    .sort((a, b) => (b[1].cost || 0) - (a[1].cost || 0))
    .map(([agent, stats]) => ({
      agent,
      requests: stats.requests,
      cost_total: stats.cost,
      share: totalCost ? stats.cost / totalCost : null,
      avg_latency_ms: stats.latencies.length
        ? stats.latencies.reduce((a, b) => a + b, 0) / stats.latencies.length
        : null,
    }));

  return {
    window: {
      label: windowDef.label,
      start: windowDef.start ? windowDef.start.toISOString() : null,
      end: windowDef.end ? windowDef.end.toISOString() : null,
    },
    summary: {
      total_cost: totalCost,
      total_requests: totalRequests,
      total_tokens: totalTokens,
      avg_latency_ms: latencyCount ? totalLatency / latencyCount : null,
      cache_savings: cacheSavings,
    },
    timeline:
      resolution === 'hour'
        ? {
            resolution: 'hour',
            hourly: {
              cost: bucket_cost,
              requests: bucket_requests,
              tokens: bucket_tokens,
              latency_percentiles: bucket_latency_percentiles,
            },
          }
        : {
            resolution: 'day',
            daily: {
              cost: bucket_cost,
              requests: bucket_requests,
              tokens: bucket_tokens,
              latency_percentiles: bucket_latency_percentiles,
            },
          },
    cost_by_model: {
      total_cost: totalCost,
      models,
    },
    cost_by_agent: {
      total_cost: totalCost,
      agents,
    },
    latency_distribution: {
      total: latency_total,
      buckets: latency_distribution,
    },
  };
};

export default {
  buildAnalytics,
  parseAnalyticsWindow,
};
