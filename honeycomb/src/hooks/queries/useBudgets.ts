import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getPolicies,
  updateControlPolicy,
  addBudgetRule,
  getBudgetUsageBreakdown,
  getBudgetRateMetrics,
} from '@/services/agentControlApi'
import type {
  BudgetConfig,
  BudgetAlert,
  BudgetNotifications,
} from '@/types/agentControl'

// =============================================================================
// Types
// =============================================================================

interface CreateBudgetParams {
  policyId: string
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
}

interface UpdatePolicyParams {
  policyId: string
  policy: {
    budgets?: BudgetConfig[]
    alerts?: Array<{
      trigger: string
      level: string
      message: string
    }>
  }
}

// =============================================================================
// Query Hooks
// =============================================================================

/**
 * Fetch all budgets from policies
 */
export function useBudgets() {
  return useQuery({
    queryKey: ['budgets'],
    queryFn: getPolicies,
    staleTime: 2 * 60 * 1000, // 2 minutes
  })
}

/**
 * Budget usage breakdown for a specific budget
 */
export function useBudgetUsage(
  policyId: string | null,
  budgetId: string | null,
  days = 7
) {
  return useQuery({
    queryKey: ['budgetUsage', policyId, budgetId, days],
    queryFn: () => getBudgetUsageBreakdown(policyId!, budgetId!, { days }),
    enabled: !!policyId && !!budgetId,
    staleTime: 5 * 60 * 1000,
  })
}

/**
 * Budget rate metrics for a specific budget
 */
export function useBudgetRates(
  policyId: string | null,
  budgetId: string | null,
  days = 30
) {
  return useQuery({
    queryKey: ['budgetRates', policyId, budgetId, days],
    queryFn: () => getBudgetRateMetrics(policyId!, budgetId!, { days }),
    enabled: !!policyId && !!budgetId,
    staleTime: 5 * 60 * 1000,
  })
}

// =============================================================================
// Mutation Hooks
// =============================================================================

/**
 * Create a new budget
 */
export function useCreateBudget() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ policyId, budget }: CreateBudgetParams) =>
      addBudgetRule(policyId, budget),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['budgets'] })
    },
  })
}

/**
 * Update a policy (used for updating budgets within a policy)
 */
export function useUpdatePolicy() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ policyId, policy }: UpdatePolicyParams) =>
      updateControlPolicy(policyId, policy),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['budgets'] })
    },
  })
}

/**
 * Update a single budget within a policy
 * This is a convenience wrapper that handles the policy update
 */
export function useUpdateBudget() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      policyId,
      budgetId,
      updates,
      existingBudgets,
    }: {
      policyId: string
      budgetId: string
      updates: Partial<BudgetConfig>
      existingBudgets: BudgetConfig[]
    }) => {
      const updatedBudgets = existingBudgets.map((b) =>
        b.id === budgetId ? { ...b, ...updates } : b
      )
      return updateControlPolicy(policyId, { budgets: updatedBudgets })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['budgets'] })
    },
  })
}

/**
 * Delete a budget from a policy
 */
export function useDeleteBudget() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      policyId,
      budgetId,
      existingBudgets,
    }: {
      policyId: string
      budgetId: string
      existingBudgets: BudgetConfig[]
    }) => {
      const filteredBudgets = existingBudgets.filter((b) => b.id !== budgetId)
      return updateControlPolicy(policyId, { budgets: filteredBudgets })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['budgets'] })
    },
  })
}
