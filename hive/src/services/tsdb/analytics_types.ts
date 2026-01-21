/**
 * Database Query Result Row Types for Analytics Service
 * These interfaces define the structure of database query results,
 * eliminating the need for 'any' types and providing full TypeScript safety.
 */

/**
 * Raw database row from fetchDailyCA query
 * Represents daily cost and aggregated metrics from llm_events_daily_ca table
 */
export interface DailyCostRow {
  bucket: string | Date;
  requests: number | string;
  cost_total: number | string;
  input_tokens: number | string;
  output_tokens: number | string;
  total_tokens: number | string;
  cached_tokens: number | string;
}

/**
 * Raw database row from fetchLatencyDaily query
 * Represents latency statistics computed from llm_events table
 */
export interface LatencyStatsRow {
  bucket: string | Date;
  count: number | string;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
}

/**
 * Raw database row from fetchLatencyDistributionDaily query
 * Represents the distribution of latency buckets
 */
export interface LatencyBucketRow {
  bucket: string;
  count: number | string;
}

/**
 * Raw database row from fetchModelCost query
 * Represents per-model cost aggregation
 */
export interface ModelCostRow {
  model: string;
  cost_total: number | string | null;
  cached_tokens: number | string | null;
}

/**
 * Raw database row from fetchAgentCost query
 * Represents per-agent cost and performance metrics
 */
export interface AgentCostRow {
  agent: string;
  requests: number | string;
  cost_total: number | string | null;
  input_tokens: number | string | null;
  output_tokens: number | string | null;
  avg_latency_ms: number | null;
}

/**
 * Raw database row from buildAnalytics base table fallback query
 * Represents a single event row from llm_events table
 */
export interface LLMEventRow {
  timestamp: string | Date | null;
  model: string | null;
  agent: string | null;
  latency_ms: number | null;
  cost_total: number | string;
  usage_input_tokens: number | string;
  usage_output_tokens: number | string;
  usage_total_tokens: number | string;
  usage_cached_tokens: number | string;
}
