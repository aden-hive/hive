/**
 * Data transformation utilities for converting API responses to chart-ready data.
 * Based on patterns from acho-launchpad's useAgentControlData.ts
 */

// Color palette for models (matches launchpad)
export const MODEL_COLORS = ['#263A99', '#22c55e', '#6b21a8', '#f59e0b', '#c1392b', '#06b6d4']

// =============================================================================
// API Response Types (for type safety with unknown API data)
// =============================================================================

interface TimelineCostItem {
  bucket: string
  cost_total?: number
}

interface TimelineRequestItem {
  bucket: string
  requests?: number
}

interface TimelineTokenItem {
  bucket: string
  input_tokens?: number
  output_tokens?: number
}

interface TimelineLatencyItem {
  bucket: string
  p50_ms?: number
  p95_ms?: number
  p99_ms?: number
}

interface TimelineData {
  cost?: TimelineCostItem[]
  requests?: TimelineRequestItem[]
  tokens?: TimelineTokenItem[]
  latency_percentiles?: TimelineLatencyItem[]
}

interface CostByModelItem {
  model?: string
  cost_total?: number
  share?: number
}

interface CostByModelResponse {
  models?: CostByModelItem[]
}

interface LatencyBucketItem {
  bucket: string
  count?: number
}

interface LatencyDistributionResponse {
  buckets?: LatencyBucketItem[]
}

interface CostByAgentItem {
  agent?: string
  cost_total?: number
  requests?: number
}

interface CostByAgentResponse {
  agents?: CostByAgentItem[]
}

interface AnalyticsData {
  analytics?: {
    timeline?: {
      resolution?: string
      hourly?: TimelineData
      daily?: TimelineData
    }
    cost_by_model?: CostByModelResponse
    latency_distribution?: LatencyDistributionResponse
    cost_by_agent?: CostByAgentResponse
  }
}

// =============================================================================
// Types for transformed chart data
// =============================================================================

export interface CostTrendData {
  date: string
  cost: number
  requests: number
  budget?: number
}

export interface TokenUsageData {
  date: string
  type: 'Input' | 'Output'
  tokens: number
}

export interface CostByModelData {
  name: string
  cost: number
  value: number // percentage
  color: string
}

export interface LatencyDistributionData {
  range: string
  count: number
}

export interface LatencyPercentilesData {
  date: string
  percentile: 'P50' | 'P95' | 'P99'
  latency: number
}

export interface TopAgentData {
  name: string
  spend: number
  requests: number
  avgCost: number
}

// =============================================================================
// Format helpers
// =============================================================================

/**
 * Format bucket label based on resolution
 * For hourly: "2 PM", "3 PM", etc.
 * For daily: "Dec 14", "Dec 15", etc.
 */
export function formatBucketLabel(bucket: string, resolution: 'day' | 'hour'): string {
  const date = new Date(bucket)
  if (resolution === 'hour') {
    return date.toLocaleTimeString('en-US', { hour: 'numeric', hour12: true })
  }
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// =============================================================================
// Data transformers
// =============================================================================

/**
 * Transform analytics API response to chart-ready data
 */
export function transformAnalyticsData(data: AnalyticsData | undefined) {
  if (!data?.analytics) {
    return {
      costTrends: [],
      tokenUsage: [],
      costByModel: [],
      latencyDistribution: [],
      latencyPercentiles: [],
      topAgents: [],
    }
  }

  const analytics = data.analytics
  const resolution: 'day' | 'hour' = analytics.timeline?.resolution === 'hour' ? 'hour' : 'day'
  const timeline = resolution === 'hour' ? analytics.timeline?.hourly : analytics.timeline?.daily

  return {
    costTrends: transformCostTrends(timeline, resolution),
    tokenUsage: transformTokenUsage(timeline, resolution),
    costByModel: transformCostByModel(analytics.cost_by_model),
    latencyDistribution: transformLatencyDistribution(analytics.latency_distribution),
    latencyPercentiles: transformLatencyPercentiles(timeline, resolution),
    topAgents: transformTopAgents(analytics.cost_by_agent),
  }
}

/**
 * Transform cost timeline to cost trend data
 */
function transformCostTrends(
  timeline: TimelineData | undefined,
  resolution: 'day' | 'hour'
): CostTrendData[] {
  if (!timeline?.cost || !Array.isArray(timeline.cost)) {
    return []
  }

  // Create requests lookup map
  const requestsMap = new Map<string, number>(
    (timeline.requests || []).map((r: TimelineRequestItem) => [r.bucket, r.requests ?? 0])
  )

  return timeline.cost.map((d: TimelineCostItem) => ({
    date: formatBucketLabel(d.bucket, resolution),
    cost: d.cost_total || 0,
    requests: requestsMap.get(d.bucket) || 0,
    budget: 66.67, // Default daily budget (~$2000/month / 30 days)
  }))
}

/**
 * Transform token timeline to stacked bar chart data (flattened)
 */
function transformTokenUsage(
  timeline: TimelineData | undefined,
  resolution: 'day' | 'hour'
): TokenUsageData[] {
  if (!timeline?.tokens || !Array.isArray(timeline.tokens)) {
    return []
  }

  return timeline.tokens.flatMap((d: TimelineTokenItem) => [
    {
      date: formatBucketLabel(d.bucket, resolution),
      type: 'Input' as const,
      tokens: d.input_tokens || 0,
    },
    {
      date: formatBucketLabel(d.bucket, resolution),
      type: 'Output' as const,
      tokens: d.output_tokens || 0,
    },
  ])
}

/**
 * Transform cost by model to pie/donut chart data
 */
function transformCostByModel(costByModel: CostByModelResponse | undefined): CostByModelData[] {
  if (!costByModel?.models || !Array.isArray(costByModel.models)) {
    return []
  }

  return costByModel.models.map((m: CostByModelItem, i: number) => ({
    name: m.model?.split('/').pop() || m.model || 'Unknown',
    cost: m.cost_total || 0,
    value: Math.round((m.share || 0) * 100),
    color: MODEL_COLORS[i % MODEL_COLORS.length],
  }))
}

/**
 * Aggregate API latency buckets to UI buckets
 * API: 0-1s, 1-2s, 2-5s, 5-10s, 10-20s, 20s+
 * UI:  0-2s, 2-5s, 5-10s, 10-20s, 20s+
 */
function transformLatencyDistribution(
  latencyDistribution: LatencyDistributionResponse | undefined
): LatencyDistributionData[] {
  if (!latencyDistribution?.buckets || !Array.isArray(latencyDistribution.buckets)) {
    return []
  }

  const aggregated: Record<string, number> = {
    '0-2s': 0,
    '2-5s': 0,
    '5-10s': 0,
    '10-20s': 0,
    '20s+': 0,
  }

  latencyDistribution.buckets.forEach((b: LatencyBucketItem) => {
    switch (b.bucket) {
      case '0-1s':
      case '1-2s':
        aggregated['0-2s'] += b.count || 0
        break
      case '2-5s':
        aggregated['2-5s'] += b.count || 0
        break
      case '5-10s':
        aggregated['5-10s'] += b.count || 0
        break
      case '10-20s':
        aggregated['10-20s'] += b.count || 0
        break
      case '20s+':
        aggregated['20s+'] += b.count || 0
        break
    }
  })

  // Only return data if there are actual counts
  const totalCount = Object.values(aggregated).reduce((sum, count) => sum + count, 0)
  if (totalCount === 0) {
    return []
  }

  return Object.entries(aggregated).map(([range, count]) => ({ range, count }))
}

/**
 * Transform latency percentiles to multi-line chart data (flattened)
 */
function transformLatencyPercentiles(
  timeline: TimelineData | undefined,
  resolution: 'day' | 'hour'
): LatencyPercentilesData[] {
  if (!timeline?.latency_percentiles || !Array.isArray(timeline.latency_percentiles)) {
    return []
  }

  return timeline.latency_percentiles.flatMap((d: TimelineLatencyItem) => [
    {
      date: formatBucketLabel(d.bucket, resolution),
      percentile: 'P50' as const,
      latency: d.p50_ms || 0,
    },
    {
      date: formatBucketLabel(d.bucket, resolution),
      percentile: 'P95' as const,
      latency: d.p95_ms || 0,
    },
    {
      date: formatBucketLabel(d.bucket, resolution),
      percentile: 'P99' as const,
      latency: d.p99_ms || d.p95_ms || 0,
    },
  ])
}

/**
 * Transform cost by agent to top agents list
 */
function transformTopAgents(costByAgent: CostByAgentResponse | undefined): TopAgentData[] {
  if (!costByAgent?.agents || !Array.isArray(costByAgent.agents)) {
    return []
  }

  return costByAgent.agents.map((a: CostByAgentItem) => {
    const requests = a.requests || 0
    return {
      name: a.agent || 'Unknown',
      spend: a.cost_total || 0,
      requests,
      avgCost: requests > 0 ? (a.cost_total || 0) / requests : 0,
    }
  })
}
