import { hiveClient } from './api'
import type {
  BudgetConfig,
  BudgetAlert,
  BudgetNotifications,
  RawJsonData,
} from '@/types/agentControl'

// =============================================================================
// Time Range Mappings
// =============================================================================

/**
 * Maps UI time range to analytics-wide endpoint window parameter
 */
export const analyticsWindowMap: Record<string, string> = {
  all: 'all_time',
  month: 'this_month',
  twoWeeks: 'last_2_weeks',
  week: 'this_week',
}

/**
 * Maps UI time range to general window parameter (for legacy endpoints)
 */
export const windowMap: Record<string, string> = {
  all: '30d',
  month: '30d',
  twoWeeks: '14d',
  week: '7d',
  today: '1d',
}

// =============================================================================
// Analytics Endpoints
// =============================================================================

/**
 * Get analytics data - routes to narrow or wide based on time range
 * @param timeRange - 'today' | 'week' | 'twoWeeks' | 'month' | 'all'
 */
export function getAnalytics(timeRange: string): Promise<RawJsonData> {
  if (timeRange === 'today') {
    return getAnalyticsNarrow()
  }
  return getAnalyticsWide(timeRange)
}

/**
 * Get daily resolution analytics (all time ranges except "today")
 * @param window - Time window from analyticsWindowMap
 */
export function getAnalyticsWide(window: string): Promise<RawJsonData> {
  const mappedWindow = analyticsWindowMap[window] || window
  return hiveClient.get(`/tsdb/analytics-wide?window=${mappedWindow}`)
}

/**
 * Get hourly resolution analytics (for "today" only)
 */
export function getAnalyticsNarrow(): Promise<RawJsonData> {
  return hiveClient.get('/tsdb/analytics-narrow')
}

// =============================================================================
// Logs Endpoints
// =============================================================================

// Default pagination limits for log queries.

// Higher limit for raw logs - balances data completeness with response size.
const DEFAULT_LOGS_LIMIT = 500

// Lower limit for grouped results - typically fewer unique groups needed.
const DEFAULT_AGGREGATED_LOGS_LIMIT = 100

/**
 * Get raw logs for a time range
 * @param start - ISO date string
 * @param end - ISO date string
 * @param limit - Max records to return (default: 500)
 * @param offset - Pagination offset (default: 0)
 * @param filters - Optional filters for type and success
 */
export function getLogs(
  start: string,
  end: string,
  limit = DEFAULT_LOGS_LIMIT,
  offset = 0,
  filters?: { type?: string; success?: string }
): Promise<RawJsonData> {
  const params = new URLSearchParams()
  params.set('start', start)
  params.set('end', end)
  params.set('limit', limit.toString())
  params.set('offset', offset.toString())
  if (filters?.type) params.set('type', filters.type)
  if (filters?.success !== undefined) params.set('success', filters.success)
  return hiveClient.get(`/tsdb/logs?${params.toString()}`)
}

/**
 * Get aggregated logs grouped by a field
 * Used for model usage and agent activity tables
 * @param start - ISO date string
 * @param end - ISO date string
 * @param groupBy - Field to group by (e.g., 'model', 'agent')
 * @param limit - Max records to return (default: 100)
 */
export function getLogsAggregated(
  start: string,
  end: string,
  groupBy: string,
  limit = DEFAULT_AGGREGATED_LOGS_LIMIT
): Promise<RawJsonData> {
  return hiveClient.get(
    `/tsdb/logs?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&group_by=${groupBy}&limit=${limit}`
  )
}

// =============================================================================
// Metrics & Insights Endpoints
// =============================================================================

/**
 * Get metrics summary for the metrics table
 * @param days - Number of days to aggregate (default: 30)
 */
export function getMetricsSummary(days = 30): Promise<RawJsonData> {
  return hiveClient.get(`/tsdb/metrics?days=${days}`)
}

/**
 * Get AI-generated insights based on usage patterns
 * @param days - Number of days to analyze (default: 30)
 */
export function getInsights(days = 30): Promise<RawJsonData> {
  return hiveClient.get(`/tsdb/insights?days=${days}`)
}

// =============================================================================
// Policy & Budget Endpoints
// =============================================================================

/**
 * Get all control policies
 */
export function getPolicies(): Promise<RawJsonData> {
  return hiveClient.get('/v1/control/policies')
}

/**
 * Update a control policy
 * @param policyId - Policy ID to update
 * @param policy - Updated policy data
 */
export function updateControlPolicy(
  policyId: string,
  policy: {
    budgets?: BudgetConfig[]
    alerts?: Array<{
      trigger: string
      level: string
      message: string
    }>
  }
): Promise<RawJsonData> {
  return hiveClient.put(`/v1/control/policies/${policyId}`, policy)
}

/**
 * Add a budget rule to a policy
 * @param policyId - Policy ID to add budget to
 * @param budget - Budget configuration
 */
export function addBudgetRule(
  policyId: string,
  budget: {
    id: string
    name: string
    type: 'global' | 'agent' | 'customer' | 'feature' | 'tag'
    tagCategory?: string
    tags?: string[]
    limit: number
    spent: number
    limitAction: 'kill' | 'throttle' | 'degrade' | 'notify'
    degradeToModel?: string
    throttleRate?: number
    alerts: BudgetAlert[]
    notifications: BudgetNotifications
  }
): Promise<RawJsonData> {
  return hiveClient.post(`/v1/control/policies/${policyId}/budgets`, budget)
}

/**
 * Get budget usage breakdown
 * @param policyId - Policy ID
 * @param budgetId - Budget ID
 * @param options - Query options
 */
export function getBudgetUsageBreakdown(
  policyId: string,
  budgetId: string,
  options?: { days?: number }
): Promise<RawJsonData> {
  const params = new URLSearchParams()
  if (options?.days) params.set('days', options.days.toString())
  const query = params.toString() ? `?${params.toString()}` : ''
  return hiveClient.get(`/v1/control/policies/${policyId}/budgets/${budgetId}/usage${query}`)
}

/**
 * Get budget rate metrics
 * @param policyId - Policy ID
 * @param budgetId - Budget ID
 * @param options - Query options
 */
export function getBudgetRateMetrics(
  policyId: string,
  budgetId: string,
  options?: { days?: number }
): Promise<RawJsonData> {
  const params = new URLSearchParams()
  if (options?.days) params.set('days', options.days.toString())
  const query = params.toString() ? `?${params.toString()}` : ''
  return hiveClient.get(`/v1/control/policies/${policyId}/budgets/${budgetId}/rates${query}`)
}

/**
 * Get budget status for a context
 * @param contextId - Context ID to check budget for
 */
export function getBudgetStatus(contextId: string): Promise<RawJsonData> {
  return hiveClient.get(`/v1/control/budget/${contextId}`)
}

// =============================================================================
// Alert Endpoints
// =============================================================================

/**
 * Add an alert rule to a policy
 * @param policyId - Policy ID to add alert to
 * @param alert - Alert configuration
 */
export function addAlertRule(
  policyId: string,
  alert: {
    trigger: 'budget_threshold' | 'model_usage' | 'always'
    level: 'info' | 'warning' | 'critical'
    message: string
    threshold_percent?: number
  }
): Promise<RawJsonData> {
  return hiveClient.post(`/v1/control/policies/${policyId}/alerts`, alert)
}
