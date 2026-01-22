import { useState, useEffect } from 'react'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import {
  DollarSign,
  Bot,
  User,
  LayoutGrid,
  Tag,
  Trash2,
  Plus,
  X,
  Bell,
  Mail,
} from 'lucide-react'
import { useUpdateBudget, useDeleteBudget } from '@/hooks/queries/useBudgets'
import { useNotificationStore } from '@/stores/notificationStore'
import type { BudgetConfig, BudgetType, LimitAction } from '@/types/agentControl'

interface BudgetDetailPanelProps {
  budget: BudgetConfig | null
  open: boolean
  onOpenChange: (open: boolean) => void
  policyId: string | null
  existingBudgets: BudgetConfig[]
}

const typeIcons: Record<BudgetType, React.ElementType> = {
  global: DollarSign,
  agent: Bot,
  customer: User,
  feature: LayoutGrid,
  tag: Tag,
}

const typeColors: Record<BudgetType, string> = {
  global: 'bg-blue-100 text-blue-700',
  agent: 'bg-red-100 text-red-700',
  customer: 'bg-purple-100 text-purple-700',
  feature: 'bg-orange-100 text-orange-700',
  tag: 'bg-green-100 text-green-700',
}

const limitActions: { value: LimitAction; label: string; description: string }[] = [
  { value: 'throttle', label: 'Throttle', description: 'Rate limit requests when budget is exceeded' },
  { value: 'kill', label: 'Block', description: 'Stop all requests when budget is exceeded' },
]

/**
 * Right-side slide-over panel for viewing and editing budget details.
 */
export function BudgetDetailPanel({
  budget,
  open,
  onOpenChange,
  policyId,
  existingBudgets,
}: BudgetDetailPanelProps) {
  // Local state for editing
  const [limit, setLimit] = useState('')
  const [limitAction, setLimitAction] = useState<LimitAction>('throttle')
  const [throttleRate, setThrottleRate] = useState('1.0')
  const [alerts, setAlerts] = useState<{ threshold: number; enabled: boolean }[]>([])
  const [newThreshold, setNewThreshold] = useState('')
  const [emailEnabled, setEmailEnabled] = useState(false)
  const [emailRecipients, setEmailRecipients] = useState<string[]>([])
  const [newEmail, setNewEmail] = useState('')
  const [inAppEnabled, setInAppEnabled] = useState(false)
  const [isDirty, setIsDirty] = useState(false)

  const updateBudget = useUpdateBudget()
  const deleteBudgetMutation = useDeleteBudget()
  const addNotification = useNotificationStore((state) => state.addNotification)

  // Reset form when budget changes
  useEffect(() => {
    if (budget) {
      setLimit(budget.limit.toString())
      setLimitAction(budget.limitAction)
      setThrottleRate(budget.throttleRate?.toString() ?? '1.0')
      setAlerts([...budget.alerts])
      setEmailEnabled(budget.notifications.email)
      setEmailRecipients([...budget.notifications.emailRecipients])
      setInAppEnabled(budget.notifications.inApp)
      setIsDirty(false)
      setNewThreshold('')
      setNewEmail('')
    }
  }, [budget])

  if (!budget) return null

  const percentage = budget.limit > 0 ? (budget.spent / budget.limit) * 100 : 0
  const status = percentage >= 100 ? 'critical' : percentage >= 80 ? 'warning' : 'healthy'
  const remaining = Math.max(0, budget.limit - budget.spent)

  const TypeIcon = typeIcons[budget.type] || DollarSign

  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)

  const handleChange = () => {
    setIsDirty(true)
  }

  const handleAddThreshold = () => {
    const threshold = parseInt(newThreshold)
    if (threshold > 0 && threshold <= 100 && !alerts.some(a => a.threshold === threshold)) {
      setAlerts([...alerts, { threshold, enabled: true }].sort((a, b) => a.threshold - b.threshold))
      setNewThreshold('')
      handleChange()
    }
  }

  const handleRemoveThreshold = (threshold: number) => {
    setAlerts(alerts.filter(a => a.threshold !== threshold))
    handleChange()
  }

  const handleToggleThreshold = (threshold: number) => {
    setAlerts(alerts.map(a =>
      a.threshold === threshold ? { ...a, enabled: !a.enabled } : a
    ))
    handleChange()
  }

  const handleSubmit = async () => {
    if (!policyId || !budget) return

    try {
      await updateBudget.mutateAsync({
        policyId,
        budgetId: budget.id,
        updates: {
          limit: parseFloat(limit),
          limitAction,
          throttleRate: limitAction === 'throttle' ? parseFloat(throttleRate) : undefined,
          alerts,
          notifications: {
            inApp: inAppEnabled,
            email: emailEnabled,
            emailRecipients,
            webhook: budget.notifications.webhook,
          },
        },
        existingBudgets,
      })
      addNotification({
        type: 'success',
        title: 'Budget updated',
        message: `"${budget.name}" has been updated successfully.`,
      })
      onOpenChange(false)
    } catch (error: unknown) {
      console.error('Failed to update budget:', error)
      addNotification({
        type: 'error',
        title: 'Update failed',
        message: 'Failed to update budget. Please try again.',
      })
    }
  }

  const handleDelete = async () => {
    if (!policyId || !budget) return

    if (confirm(`Are you sure you want to delete "${budget.name}"? This action cannot be undone.`)) {
      try {
        await deleteBudgetMutation.mutateAsync({
          policyId,
          budgetId: budget.id,
          existingBudgets,
        })
        addNotification({
          type: 'success',
          title: 'Budget deleted',
          message: `"${budget.name}" has been deleted.`,
        })
        onOpenChange(false)
      } catch (error: unknown) {
        console.error('Failed to delete budget:', error)
        addNotification({
          type: 'error',
          title: 'Delete failed',
          message: 'Failed to delete budget. Please try again.',
        })
      }
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[450px] sm:max-w-[450px] flex flex-col p-0">
        {/* Header */}
        <SheetHeader className="px-6 py-4 border-b">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
              <TypeIcon className="h-5 w-5 text-primary" />
            </div>
            <div className="min-w-0 flex-1">
              <SheetTitle className="text-left truncate">{budget.name}</SheetTitle>
              <div className="flex items-center gap-1.5 mt-1">
                <Badge variant="secondary" className={cn('text-xs capitalize', typeColors[budget.type])}>
                  {budget.type}
                </Badge>
                {budget.tagCategory && (
                  <Badge variant="secondary" className="text-xs bg-muted text-muted-foreground">
                    {budget.tagCategory}
                  </Badge>
                )}
              </div>
            </div>
          </div>
          <p className="text-sm text-muted-foreground mt-2">
            {formatCurrency(budget.spent)} of {formatCurrency(budget.limit)} used
          </p>
        </SheetHeader>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          {/* Budget Usage Section */}
          <div className="space-y-3">
            <h3 className="text-sm font-medium">Budget Usage</h3>
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Progress</span>
                <Badge
                  variant="secondary"
                  className={cn(
                    'text-xs font-semibold',
                    status === 'healthy' && 'bg-green-100 text-green-700',
                    status === 'warning' && 'bg-orange-100 text-orange-700',
                    status === 'critical' && 'bg-red-100 text-red-700'
                  )}
                >
                  {Math.round(percentage)}%
                </Badge>
              </div>
              <Progress
                value={Math.min(percentage, 100)}
                className={cn(
                  'h-2',
                  status === 'healthy' && '[&>div]:bg-green-500',
                  status === 'warning' && '[&>div]:bg-orange-500',
                  status === 'critical' && '[&>div]:bg-red-500'
                )}
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Spent: {formatCurrency(budget.spent)}</span>
                <span>Remaining: {formatCurrency(remaining)}</span>
              </div>
            </div>
          </div>

          <Separator />

          {/* Monthly Limit Section */}
          <div className="space-y-3">
            <Label htmlFor="limit" className="text-sm font-medium">Monthly Limit</Label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">$</span>
              <Input
                id="limit"
                type="number"
                min="0"
                step="100"
                value={limit}
                onChange={(e) => {
                  setLimit(e.target.value)
                  handleChange()
                }}
                className="pl-7"
              />
            </div>
          </div>

          <Separator />

          {/* At Limit Action Section */}
          <div className="space-y-3">
            <Label className="text-sm font-medium">At Limit Action</Label>
            <Select
              value={limitAction}
              onValueChange={(value) => {
                setLimitAction(value as LimitAction)
                handleChange()
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {limitActions.map((action) => (
                  <SelectItem key={action.value} value={action.value}>
                    <div className="flex flex-col">
                      <span>{action.label}</span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {limitActions.find(a => a.value === limitAction)?.description}
            </p>

            {/* Throttle Rate Config - shown when throttle is selected */}
            {limitAction === 'throttle' && (
              <div className="mt-3 p-3 rounded-md bg-amber-50 border border-amber-200 space-y-2">
                <Label htmlFor="throttleRate" className="text-sm font-medium">
                  Throttle Limit (req/sec)
                </Label>
                <Input
                  id="throttleRate"
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={throttleRate}
                  onChange={(e) => {
                    setThrottleRate(e.target.value)
                    handleChange()
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  Maximum requests per second when budget limit is reached
                </p>
              </div>
            )}
          </div>

          <Separator />

          {/* Alert Thresholds Section */}
          <div className="space-y-3">
            <Label className="text-sm font-medium">Alert Thresholds</Label>

            {alerts.length === 0 ? (
              <p className="text-sm text-muted-foreground">No alert thresholds configured</p>
            ) : (
              <div className="space-y-2">
                {alerts.map((alert) => (
                  <div
                    key={alert.threshold}
                    className="flex items-center justify-between p-2 rounded-md border bg-muted/30"
                  >
                    <div className="flex items-center gap-3">
                      <Switch
                        checked={alert.enabled}
                        onCheckedChange={() => handleToggleThreshold(alert.threshold)}
                      />
                      <span className={cn(
                        'text-sm font-medium',
                        !alert.enabled && 'text-muted-foreground'
                      )}>
                        {alert.threshold}%
                      </span>
                      <span className="text-xs text-muted-foreground">
                        ({formatCurrency(budget.limit * alert.threshold / 100)})
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={() => handleRemoveThreshold(alert.threshold)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            )}

            {/* Add new threshold */}
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Input
                  type="number"
                  min="1"
                  max="100"
                  placeholder="Enter threshold"
                  value={newThreshold}
                  onChange={(e) => setNewThreshold(e.target.value)}
                  className="pr-8"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">%</span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleAddThreshold}
                disabled={!newThreshold || parseInt(newThreshold) < 1 || parseInt(newThreshold) > 100}
              >
                <Plus className="h-4 w-4 mr-1" />
                Add
              </Button>
            </div>
          </div>

          <Separator />

          {/* Notification Channels Section */}
          <div className="space-y-3">
            <Label className="text-sm font-medium">Notification Channels</Label>
            <div className="grid grid-cols-2 gap-2">
              <Button
                variant={inAppEnabled ? 'default' : 'outline'}
                className="justify-start"
                onClick={() => {
                  setInAppEnabled(!inAppEnabled)
                  handleChange()
                }}
              >
                <Bell className="h-4 w-4 mr-2" />
                In-App
              </Button>
              <Button
                variant={emailEnabled ? 'default' : 'outline'}
                className="justify-start"
                onClick={() => {
                  setEmailEnabled(!emailEnabled)
                  handleChange()
                }}
              >
                <Mail className="h-4 w-4 mr-2" />
                Email
              </Button>
            </div>
            {emailEnabled && (
              <div className="space-y-3 mt-3">
                {emailRecipients.length > 0 && (
                  <div className="space-y-2">
                    {emailRecipients.map((email) => (
                      <div
                        key={email}
                        className="flex items-center justify-between p-2 rounded-md border bg-muted/30"
                      >
                        <span className="text-sm truncate">{email}</span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive flex-shrink-0"
                          onClick={() => {
                            setEmailRecipients(emailRecipients.filter(e => e !== email))
                            handleChange()
                          }}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <Input
                    type="email"
                    placeholder="Enter email address"
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        const email = newEmail.trim().toLowerCase()
                        if (email && email.includes('@') && !emailRecipients.includes(email)) {
                          setEmailRecipients([...emailRecipients, email])
                          setNewEmail('')
                          handleChange()
                        }
                      }
                    }}
                    className="flex-1"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      const email = newEmail.trim().toLowerCase()
                      if (email && email.includes('@') && !emailRecipients.includes(email)) {
                        setEmailRecipients([...emailRecipients, email])
                        setNewEmail('')
                        handleChange()
                      }
                    }}
                    disabled={!newEmail.trim() || !newEmail.includes('@') || emailRecipients.includes(newEmail.trim().toLowerCase())}
                  >
                    <Plus className="h-4 w-4 mr-1" />
                    Add
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <SheetFooter className="px-6 py-4 border-t flex-row">
          <Button
            variant="destructive"
            size="sm"
            onClick={handleDelete}
            disabled={deleteBudgetMutation.isPending}
          >
            <Trash2 className="h-4 w-4 mr-2" />
            {deleteBudgetMutation.isPending ? 'Deleting...' : 'Delete'}
          </Button>
          <div className="flex-1" />
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSubmit} disabled={updateBudget.isPending || !isDirty}>
            {updateBudget.isPending ? 'Saving...' : 'Save Changes'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
