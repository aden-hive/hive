import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { KpiCard } from './shared/KpiCard'
import { WorkerProfilePanel } from './workers/WorkerProfilePanel'
import { useAgentControlStore } from '@/stores/agentControlStore'
import { getAgents } from '@/services/controlApi'
import { cn } from '@/lib/utils'
import type { AgentInfo, LLMEvent } from '@/types/agentControl'

// Derive workers from events buffer
function deriveWorkersFromEvents(events: LLMEvent[]): AgentInfo[] {
  const workerMap = new Map<string, AgentInfo>()

  for (const event of events) {
    const existing = workerMap.get(event.agent)
    if (existing) {
      existing.total_requests++
      existing.total_cost += event.cost
      if (new Date(event.timestamp) > new Date(existing.last_seen)) {
        existing.last_seen = event.timestamp
      }
    } else {
      workerMap.set(event.agent, {
        agent: event.agent,
        agent_name: null,
        status: 'connected',
        connection_type: 'websocket',
        instance_id: null,
        first_seen: event.timestamp,
        last_seen: event.timestamp,
        total_requests: 1,
        total_cost: event.cost,
      })
    }
  }

  return Array.from(workerMap.values())
}

/**
 * Worker/Agent management grid with status indicators.
 */
export function WorkersPanel() {
  const [selectedWorker, setSelectedWorker] = useState<AgentInfo | null>(null)
  const [profileOpen, setProfileOpen] = useState(false)

  // Fetch agents from API (past week)
  const { data: agentsData, isLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: async () => {
      const oneWeekAgo = new Date()
      oneWeekAgo.setDate(oneWeekAgo.getDate() - 7)
      return getAgents(oneWeekAgo.toISOString())
    },
  })

  // Get real-time events from store
  const eventsBuffer = useAgentControlStore((state) => state.eventsBuffer)
  const realtimeAgents = useMemo(() => deriveWorkersFromEvents(eventsBuffer), [eventsBuffer])

  // Merge API agents with real-time updates (real-time overrides API data)
  const workers = useMemo(() => {
    const apiAgents = agentsData?.agents || []
    const agentMap = new Map<string, AgentInfo>()
    // Add API agents first
    for (const agent of apiAgents) {
      agentMap.set(agent.agent, agent)
    }
    // Override with real-time data
    for (const agent of realtimeAgents) {
      agentMap.set(agent.agent, agent)
    }
    return Array.from(agentMap.values())
  }, [agentsData?.agents, realtimeAgents])

  // Compute summary stats
  const onlineCount = workers.filter((w: AgentInfo) => w.status === 'connected').length
  const offlineCount = workers.filter((w: AgentInfo) => w.status === 'disconnected').length
  const totalRequests = workers.reduce((sum: number, w: AgentInfo) => sum + w.total_requests, 0)

  const handleWorkerClick = (worker: AgentInfo) => {
    setSelectedWorker(worker)
    setProfileOpen(true)
  }

  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
    }).format(value)

  return (
    <div className="space-y-6 pr-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Total Agents"
          value={workers.length}
          loading={isLoading}
          icon={
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v3h8v-3zM6 8a2 2 0 11-4 0 2 2 0 014 0zM16 18v-3a5.972 5.972 0 00-.75-2.906A3.005 3.005 0 0119 15v3h-3zM4.75 12.094A5.973 5.973 0 004 15v3H1v-3a3 3 0 013.75-2.906z" />
            </svg>
          }
        />
        <KpiCard
          label="Online"
          value={onlineCount}
          loading={isLoading}
          highlight={onlineCount > 0}
          icon={
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5 text-green-500"
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
          label="Offline"
          value={offlineCount}
          loading={isLoading}
          icon={
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5 text-gray-400"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                clipRule="evenodd"
              />
            </svg>
          }
        />
        <KpiCard
          label="Total Requests"
          value={totalRequests.toLocaleString()}
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
      </div>

      {/* Workers Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      ) : workers.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <p>No agents found</p>
          <p className="text-sm mt-1">
            Agents will appear here when they connect and send events
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {workers.map((worker: AgentInfo) => (
            <WorkerCard
              key={worker.agent}
              worker={worker}
              onClick={() => handleWorkerClick(worker)}
              formatCurrency={formatCurrency}
            />
          ))}
        </div>
      )}

      {/* Worker Profile Panel */}
      <WorkerProfilePanel
        worker={selectedWorker}
        open={profileOpen}
        onOpenChange={setProfileOpen}
      />
    </div>
  )
}

interface WorkerCardProps {
  worker: AgentInfo
  onClick: () => void
  formatCurrency: (value: number) => string
}

function WorkerCard({ worker, onClick, formatCurrency }: WorkerCardProps) {
  const isOnline = worker.status === 'connected'

  return (
    <Card
      className="cursor-pointer transition-all hover:shadow-md"
      onClick={onClick}
    >
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <Avatar className="h-10 w-10">
            <AvatarFallback
              className={cn(
                isOnline ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'
              )}
            >
              {(worker.agent_name || worker.agent).slice(0, 2).toUpperCase()}
            </AvatarFallback>
          </Avatar>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-medium truncate">
                {worker.agent_name || worker.agent}
              </span>
              <Badge
                variant="secondary"
                className={cn(
                  'text-xs shrink-0',
                  isOnline
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-100 text-gray-600'
                )}
              >
                {isOnline ? 'Online' : 'Offline'}
              </Badge>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
              <div>
                <span className="block">Requests</span>
                <span className="font-medium text-foreground">
                  {worker.total_requests.toLocaleString()}
                </span>
              </div>
              <div>
                <span className="block">Cost</span>
                <span className="font-medium text-foreground">
                  {formatCurrency(worker.total_cost)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
