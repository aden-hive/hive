import { useQuery, useInfiniteQuery } from '@tanstack/react-query'
import { getLogs, getLogsAggregated } from '@/services/agentControlApi'

// =============================================================================
// Types
// =============================================================================

interface LogsResponse {
  rows?: unknown[]
  [key: string]: unknown
}

export interface LogsFilters {
  type?: string
  success?: string
}

// =============================================================================
// Query Hooks
// =============================================================================

/**
 * Basic logs fetch - single page
 */
export function useLogs(
  start: string,
  end: string,
  limit = 500,
  enabled = true,
  filters?: LogsFilters
) {
  return useQuery({
    queryKey: ['logs', start, end, limit, filters],
    queryFn: () => getLogs(start, end, limit, 0, filters),
    enabled,
    staleTime: 1 * 60 * 1000, // 1 minute
  })
}

/**
 * Infinite scroll logs - for paginated loading
 */
export function useLogsInfinite(
  start: string,
  end: string,
  pageSize = 500,
  enabled = true,
  filters?: LogsFilters
) {
  return useInfiniteQuery({
    queryKey: ['logs', 'infinite', start, end, filters],
    queryFn: ({ pageParam }) =>
      getLogs(start, end, pageSize, pageParam, filters) as Promise<LogsResponse>,
    getNextPageParam: (lastPage, allPages) => {
      // If we got fewer rows than pageSize, there's no more data
      const rowCount = lastPage.rows?.length ?? 0
      if (rowCount < pageSize) {
        return undefined
      }
      // Return the next offset
      return allPages.length * pageSize
    },
    initialPageParam: 0,
    enabled,
    staleTime: 1 * 60 * 1000,
  })
}

/**
 * Aggregated logs - grouped by model or agent
 */
export function useLogsAggregated(
  start: string,
  end: string,
  groupBy: 'model' | 'agent',
  limit = 100,
  enabled = true
) {
  return useQuery({
    queryKey: ['logs', 'aggregated', start, end, groupBy, limit],
    queryFn: () => getLogsAggregated(start, end, groupBy, limit),
    enabled,
    staleTime: 1 * 60 * 1000,
  })
}
