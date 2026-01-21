import { useState, useRef, useCallback, useEffect } from 'react'
import type { AgentStatus } from '@/types/agentControl'

const HIVE_URL = import.meta.env.VITE_API_URL || 'http://localhost:4000'
// Delay before attempting to reconnect after SSE stream disconnection or error
// 5 seconds provides a reasonable balance between responsiveness and avoiding
// rapid retry loops.
const RECONNECT_DELAY_MS = 5000

interface UseAgentStatusOptions {
  /** Auto-connect on mount (default: false) */
  autoConnect?: boolean
  /** Enable auto-reconnect on error (default: true) */
  autoReconnect?: boolean
}

interface UseAgentStatusReturn {
  status: AgentStatus | null
  isConnected: boolean
  error: string | null
  hasActiveAgents: boolean
  agentCount: number
  connect: () => void
  disconnect: () => void
}

export function useAgentStatus(
  options: UseAgentStatusOptions = {}
): UseAgentStatusReturn {
  const { autoConnect = false, autoReconnect = true } = options

  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortControllerRef = useRef<AbortController | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }

    setIsConnected(false)
  }, [])

  const connect = useCallback(async () => {
    // Prevent duplicate connections
    if (abortControllerRef.current) {
      return
    }

    // Clear any pending reconnect
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    const token = localStorage.getItem('token')
    if (!token) {
      setError('No authentication token')
      return
    }

    try {
      abortControllerRef.current = new AbortController()
      setError(null)

      const response = await fetch(`${HIVE_URL}/v1/control/agent-status/stream`, {
        method: 'GET',
        headers: {
          Authorization: token,
          Accept: 'text/event-stream',
        },
        signal: abortControllerRef.current.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No response body')
      }

      setIsConnected(true)

      const decoder = new TextDecoder()
      let buffer = ''

      // Read SSE stream
      let streamActive = true
      while (streamActive) {
        const { done, value } = await reader.read()
        if (done) {
          streamActive = false
          continue
        }

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE events (format: "data: {...}\n\n")
        const messages = buffer.split('\n\n')
        buffer = messages.pop() || ''

        for (const message of messages) {
          if (message.startsWith('data: ')) {
            try {
              const data: AgentStatus = JSON.parse(message.slice(6))
              setStatus(data)
              if (data.error) {
                setError(data.error)
              } else {
                setError(null)
              }
            } catch (parseError) {
              console.error('[useAgentStatus] Failed to parse:', parseError)
            }
          }
        }
      }

      // Stream ended - clean up and potentially reconnect
      abortControllerRef.current = null
      setIsConnected(false)

      if (autoReconnect) {
        reconnectTimeoutRef.current = setTimeout(() => connect(), RECONNECT_DELAY_MS)
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // User intentionally disconnected
        return
      }

      console.error('[useAgentStatus] Stream error:', err)
      setError(err instanceof Error ? err.message : 'Connection failed')
      setIsConnected(false)
      abortControllerRef.current = null

      if (autoReconnect) {
        reconnectTimeoutRef.current = setTimeout(() => connect(), RECONNECT_DELAY_MS)
      }
    }
  }, [autoReconnect])

  // Auto-connect on mount if requested
  useEffect(() => {
    if (autoConnect) {
      connect()
    }

    return () => {
      disconnect()
    }
  }, [autoConnect, connect, disconnect])

  const hasActiveAgents = status?.active === true && (status?.count ?? 0) > 0
  const agentCount = status?.count ?? 0

  return {
    status,
    isConnected,
    error,
    hasActiveAgents,
    agentCount,
    connect,
    disconnect,
  }
}
