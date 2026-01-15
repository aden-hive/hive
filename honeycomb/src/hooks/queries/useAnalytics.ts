import { useQuery } from '@tanstack/react-query'
import {
  getAnalytics,
  getLogsAggregated,
  getMetricsSummary,
} from '@/services/agentControlApi'
import { useSettingsStore } from '@/stores/settingsStore'

// =============================================================================
// Analytics Hook
// =============================================================================

/**
 * Main analytics hook - fetches data based on current time range
 * Routes to narrow (hourly) or wide (daily) endpoint automatically
 */
export function useAnalytics() {
  const timeRange = useSettingsStore((state) => state.performanceDashboardTimeRange)

  return useQuery({
    queryKey: ['analytics', timeRange],
    queryFn: () => getAnalytics(timeRange),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

/**
 * Analytics with explicit time range (for components that don't use store)
 */
export function useAnalyticsWithRange(timeRange: string) {
  return useQuery({
    queryKey: ['analytics', timeRange],
    queryFn: () => getAnalytics(timeRange),
    staleTime: 5 * 60 * 1000,
  })
}

// =============================================================================
// Aggregation Hooks
// =============================================================================

/**
 * Model usage aggregation - groups logs by model
 */
export function useModelUsage(start: string, end: string, enabled = true) {
  return useQuery({
    queryKey: ['modelUsage', start, end],
    queryFn: () => getLogsAggregated(start, end, 'model', 100),
    enabled,
    staleTime: 5 * 60 * 1000,
  })
}

/**
 * Agent activity aggregation - groups logs by agent
 */
export function useAgentActivity(start: string, end: string, enabled = true) {
  return useQuery({
    queryKey: ['agentActivity', start, end],
    queryFn: () => getLogsAggregated(start, end, 'agent', 100),
    enabled,
    staleTime: 5 * 60 * 1000,
  })
}

// =============================================================================
// Metrics Hook
// =============================================================================

/**
 * Metrics summary for dashboard cards
 */
export function useMetricsSummary(days = 30) {
  return useQuery({
    queryKey: ['metrics', days],
    queryFn: () => getMetricsSummary(days),
    staleTime: 10 * 60 * 1000, // 10 minutes
  })
}
