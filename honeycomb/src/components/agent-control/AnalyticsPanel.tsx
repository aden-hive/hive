import { useMemo } from 'react'
import { Card } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { KpiCard } from './shared/KpiCard'
import { LiveIndicator } from './shared/LiveIndicator'
import { VegaLiteChart } from './charts/VegaLiteChart'
import { useAnalytics } from '@/hooks/queries/useAnalytics'
import { useAgentControlStore } from '@/stores/agentControlStore'
import { usePersistedTimeRange } from '@/hooks/usePersistedSettings'
import type { TimeRange } from '@/types/settings'
import { transformAnalyticsData, type CostByModelData } from './charts/transformers'
import {
  createCostTrendSpec,
  createTokenUsageSpec,
  createCostByModelSpec,
  createLatencyDistributionSpec,
} from './charts/specs'
import type { RawJsonData, KPIValues } from '@/types/agentControl'

// Shape of analytics API response for type safety
interface AnalyticsResponse extends RawJsonData {
  analytics?: {
    summary?: {
      total_cost?: number
      total_requests?: number
      total_tokens?: number
      avg_latency_ms?: number
      cache_savings?: number
    }
  }
  kpis?: Record<string, unknown>
  summary?: Record<string, unknown>
}

const timeRangeOptions: { value: TimeRange; label: string }[] = [
  { value: 'all', label: 'All Time' },
  { value: 'month', label: 'Last Month' },
  { value: 'twoWeeks', label: 'Last 2 Weeks' },
  { value: 'week', label: 'Last Week' },
  { value: 'today', label: 'Today' },
]

// Helper to safely extract KPI values from raw API response
function extractKpis(data: RawJsonData | undefined): KPIValues {
  const defaults: KPIValues = {
    totalCost: 0,
    projectedMonthlyCost: 0,
    totalRequests: 0,
    totalTokens: 0,
    successRate: 0.99,
    avgLatency: 0,
    cacheSavings: 0,
  }

  if (!data) return defaults

  // Handle new analytics response shape
  const analyticsData = data as AnalyticsResponse
  if (analyticsData?.analytics?.summary) {
    const summary = analyticsData.analytics.summary
    return {
      totalCost: Number(summary.total_cost || 0),
      projectedMonthlyCost: Number(summary.total_cost || 0) * 30,
      totalRequests: Number(summary.total_requests || 0),
      totalTokens: Number(summary.total_tokens || 0),
      successRate: 0.99, // Not provided in new API
      avgLatency: Number(summary.avg_latency_ms || 0),
      cacheSavings: Number(summary.cache_savings || 0),
    }
  }

  // Fallback to old response shapes
  const kpis = (data.kpis || data.summary || data) as Record<string, unknown>

  return {
    totalCost: Number(kpis.totalCost || kpis.total_cost || 0),
    projectedMonthlyCost: Number(kpis.projectedMonthlyCost || kpis.projected_cost || 0),
    totalRequests: Number(kpis.totalRequests || kpis.total_requests || 0),
    totalTokens: Number(kpis.totalTokens || kpis.total_tokens || 0),
    successRate: Number(kpis.successRate || kpis.success_rate || 0.99),
    avgLatency: Number(kpis.avgLatency || kpis.avg_latency || 0),
    cacheSavings: Number(kpis.cacheSavings || kpis.cache_savings || 0),
  }
}

/**
 * Main analytics dashboard with KPIs and VegaLite charts.
 */
export function AnalyticsPanel() {
  const { timeRange, setTimeRange } = usePersistedTimeRange()
  const hasActiveAgents = useAgentControlStore((state) => state.eventsBuffer.length > 0)

  const { data: analytics, isLoading } = useAnalytics()

  const kpis = extractKpis(analytics as RawJsonData | undefined)

  // Transform API data to chart-ready format
  const chartData = useMemo(
    () => transformAnalyticsData(analytics),
    [analytics]
  )

  // Create chart specs with memoization
  const costTrendSpec = useMemo(
    () => (chartData.costTrends.length > 0 ? createCostTrendSpec(chartData.costTrends) : null),
    [chartData.costTrends]
  )

  const tokenUsageSpec = useMemo(
    () => (chartData.tokenUsage.length > 0 ? createTokenUsageSpec(chartData.tokenUsage) : null),
    [chartData.tokenUsage]
  )

  const costByModelSpec = useMemo(
    () => (chartData.costByModel.length > 0 ? createCostByModelSpec(chartData.costByModel) : null),
    [chartData.costByModel]
  )

  const latencyDistributionSpec = useMemo(
    () =>
      chartData.latencyDistribution.length > 0
        ? createLatencyDistributionSpec(chartData.latencyDistribution)
        : null,
    [chartData.latencyDistribution]
  )

  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(value)

  const formatNumber = (value: number) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`
    return value.toLocaleString()
  }

  const formatPercent = (value: number) => `${(value * 100).toFixed(1)}%`

  return (
    <div className="space-y-6 pr-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">Analytics</h2>
          <LiveIndicator isLive={hasActiveAgents} />
        </div>
        <Select value={timeRange} onValueChange={(v) => setTimeRange(v as TimeRange)}>
          <SelectTrigger className="w-[150px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {timeRangeOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* KPI Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <KpiCard
          label="Total Cost"
          value={formatCurrency(kpis.totalCost)}
          loading={isLoading}
          icon={
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path d="M8.433 7.418c.155-.103.346-.196.567-.267v1.698a2.305 2.305 0 01-.567-.267C8.07 8.34 8 8.114 8 8c0-.114.07-.34.433-.582zM11 12.849v-1.698c.22.071.412.164.567.267.364.243.433.468.433.582 0 .114-.07.34-.433.582a2.305 2.305 0 01-.567.267z" />
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-13a1 1 0 10-2 0v.092a4.535 4.535 0 00-1.676.662C6.602 6.234 6 7.009 6 8c0 .99.602 1.765 1.324 2.246.48.32 1.054.545 1.676.662v1.941c-.391-.127-.68-.317-.843-.504a1 1 0 10-1.51 1.31c.562.649 1.413 1.076 2.353 1.253V15a1 1 0 102 0v-.092a4.535 4.535 0 001.676-.662C13.398 13.766 14 12.991 14 12c0-.99-.602-1.765-1.324-2.246A4.535 4.535 0 0011 9.092V7.151c.391.127.68.317.843.504a1 1 0 101.511-1.31c-.563-.649-1.413-1.076-2.354-1.253V5z"
                clipRule="evenodd"
              />
            </svg>
          }
        />
        <KpiCard
          label="Total Requests"
          value={formatNumber(kpis.totalRequests)}
          loading={isLoading}
          icon={
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M3 3a1 1 0 000 2v8a2 2 0 002 2h2.586l-1.293 1.293a1 1 0 101.414 1.414L10 15.414l2.293 2.293a1 1 0 001.414-1.414L12.414 15H15a2 2 0 002-2V5a1 1 0 100-2H3zm11.707 4.707a1 1 0 00-1.414-1.414L10 9.586 8.707 8.293a1 1 0 00-1.414 0l-2 2a1 1 0 101.414 1.414L8 10.414l1.293 1.293a1 1 0 001.414 0l4-4z"
                clipRule="evenodd"
              />
            </svg>
          }
        />
        <KpiCard
          label="Total Tokens"
          value={formatNumber(kpis.totalTokens)}
          loading={isLoading}
          icon={
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M12.316 3.051a1 1 0 01.633 1.265l-4 12a1 1 0 11-1.898-.632l4-12a1 1 0 011.265-.633zM5.707 6.293a1 1 0 010 1.414L3.414 10l2.293 2.293a1 1 0 11-1.414 1.414l-3-3a1 1 0 010-1.414l3-3a1 1 0 011.414 0zm8.586 0a1 1 0 011.414 0l3 3a1 1 0 010 1.414l-3 3a1 1 0 11-1.414-1.414L16.586 10l-2.293-2.293a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          }
        />
        <KpiCard
          label="Success Rate"
          value={formatPercent(kpis.successRate)}
          loading={isLoading}
          highlight={kpis.successRate < 0.95}
          icon={
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                clipRule="evenodd"
              />
            </svg>
          }
        />
        <KpiCard
          label="Avg Latency"
          value={`${kpis.avgLatency.toFixed(0)}ms`}
          loading={isLoading}
          icon={
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z"
                clipRule="evenodd"
              />
            </svg>
          }
        />
      </div>

      {/* Charts Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[...Array(4)].map((_, i) => (
            <Card key={i} className="p-4">
              <Skeleton className="h-6 w-32 mb-4" />
              <Skeleton className="h-[250px]" />
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Cost Trend Chart */}
          <Card className="p-6">
            <h3 className="font-medium mb-4">Cost Trend</h3>
            {costTrendSpec ? (
              <VegaLiteChart spec={costTrendSpec} className="h-[250px]" />
            ) : (
              <div className="h-[250px] flex items-center justify-center text-muted-foreground">
                No cost data available
              </div>
            )}
          </Card>

          {/* Token Usage Chart */}
          <Card className="p-6">
            <h3 className="font-medium mb-4">Token Usage</h3>
            {tokenUsageSpec ? (
              <VegaLiteChart spec={tokenUsageSpec} className="h-[250px]" />
            ) : (
              <div className="h-[250px] flex items-center justify-center text-muted-foreground">
                No token data available
              </div>
            )}
          </Card>

          {/* Cost by Model Chart */}
          <Card className="p-6">
            <h3 className="font-medium mb-4">Cost by Model</h3>
            {costByModelSpec ? (
              <div className="flex items-center gap-6">
                <VegaLiteChart spec={costByModelSpec} className="h-[200px] w-[200px] flex-shrink-0" />
                <div className="flex-1 space-y-2">
                  {chartData.costByModel.map((model: CostByModelData) => (
                    <div key={model.name} className="flex items-center gap-2 text-sm">
                      <div
                        className="w-3 h-3 rounded-sm flex-shrink-0"
                        style={{ backgroundColor: model.color }}
                      />
                      <span className="truncate flex-1">{model.name}</span>
                      <span className="text-muted-foreground">{model.value}%</span>
                      <span className="font-medium">${model.cost.toFixed(4)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="h-[250px] flex items-center justify-center text-muted-foreground">
                No model data available
              </div>
            )}
          </Card>

          {/* Latency Distribution Chart */}
          <Card className="p-6">
            <h3 className="font-medium mb-4">Latency Distribution</h3>
            {latencyDistributionSpec ? (
              <VegaLiteChart spec={latencyDistributionSpec} className="h-[250px]" />
            ) : (
              <div className="h-[250px] flex items-center justify-center text-muted-foreground">
                No latency data available
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
