import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCreateBudget } from '@/hooks/queries/useBudgets'
import { useNotificationStore } from '@/stores/notificationStore'
import type { BudgetType } from '@/types/agentControl'

interface AddBudgetDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  policyId: string | null
}

const budgetTypes: { value: BudgetType; label: string }[] = [
  { value: 'global', label: 'Global' },
  { value: 'agent', label: 'Agent' },
  { value: 'customer', label: 'Customer' },
  { value: 'feature', label: 'Feature' },
  { value: 'tag', label: 'Tag' },
]

/**
 * Dialog for creating a new budget configuration.
 */
export function AddBudgetDialog({ open, onOpenChange, policyId }: AddBudgetDialogProps) {
  const [name, setName] = useState('')
  const [type, setType] = useState<BudgetType>('agent')
  const [limit, setLimit] = useState('100')
  const [error, setError] = useState<string | null>(null)

  const createBudget = useCreateBudget()
  const addNotification = useNotificationStore((state) => state.addNotification)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!policyId) {
      setError('No policy available. Please try again later.')
      return
    }

    if (!name.trim()) {
      setError('Name is required')
      return
    }

    const limitValue = parseFloat(limit)
    if (isNaN(limitValue) || limitValue <= 0) {
      setError('Limit must be greater than 0')
      return
    }

    try {
      await createBudget.mutateAsync({
        policyId,
        budget: {
          id: name.trim().toLowerCase().replace(/\s+/g, '-'),
          name: name.trim(),
          type,
          limit: limitValue,
          spent: 0,
          limitAction: 'throttle',
          throttleRate: 1.0,
          alerts: [
            { threshold: 80, enabled: true },
            { threshold: 100, enabled: true },
          ],
          notifications: {
            inApp: true,
            email: false,
            emailRecipients: [],
            webhook: false,
          },
        },
      })
      addNotification({
        type: 'success',
        title: 'Budget created',
        message: `"${name.trim()}" has been created successfully.`,
      })
      handleClose()
    } catch (err: unknown) {
      addNotification({
        type: 'error',
        title: 'Creation failed',
        message: err instanceof Error ? err.message : 'Failed to create budget',
      })
    }
  }

  const handleClose = () => {
    setName('')
    setType('agent')
    setLimit('100')
    setError(null)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Create Budget</DialogTitle>
          <DialogDescription>
            Set up a new budget to control costs for agents, models, or features.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="text-sm text-red-500 bg-red-50 p-2 rounded">
              {error}
            </div>
          )}

          {/* Name */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Name</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Production Agent Budget"
            />
          </div>

          {/* Type */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Type</label>
            <Select value={type} onValueChange={(value) => setType(value as BudgetType)}>
              <SelectTrigger>
                <SelectValue placeholder="Select type" />
              </SelectTrigger>
              <SelectContent>
                {budgetTypes.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Limit */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Budget Limit ($)</label>
            <Input
              type="number"
              step="0.01"
              min="0"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              placeholder="100.00"
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={createBudget.isPending}>
              {createBudget.isPending ? 'Creating...' : 'Create Budget'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
