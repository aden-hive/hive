import { useRef, useEffect, useState } from 'react'
import vegaEmbed, { type Result, type VisualizationSpec, type EmbedOptions } from 'vega-embed'
import { cn } from '@/lib/utils'

interface VegaLiteChartProps {
  spec: VisualizationSpec
  className?: string
  options?: EmbedOptions
}

/**
 * React wrapper component for VegaLite charts using vega-embed.
 * Uses ResizeObserver to ensure container has valid dimensions before rendering.
 * Handles mounting, updating, and cleanup of Vega views.
 */
export function VegaLiteChart({ spec, className, options }: VegaLiteChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const vegaResultRef = useRef<Result | null>(null)
  const [isReady, setIsReady] = useState(false)

  // Wait for container to be ready with valid dimensions
  useEffect(() => {
    if (!containerRef.current) return

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0) {
          setIsReady(true)
        }
      }
    })

    resizeObserver.observe(containerRef.current)

    // Check initial dimensions
    if (containerRef.current.clientWidth > 0) {
      setIsReady(true)
    }

    return () => resizeObserver.disconnect()
  }, [])

  // Render chart when ready
  useEffect(() => {
    if (!containerRef.current || !spec || !isReady) return

    const renderChart = async () => {
      // Cleanup previous render to prevent memory leaks
      if (vegaResultRef.current) {
        vegaResultRef.current.finalize()
        vegaResultRef.current = null
      }

      try {
        const result = await vegaEmbed(containerRef.current!, spec, {
          actions: false,
          tooltip: { theme: 'dark' },
          ...options,
        })
        vegaResultRef.current = result
      } catch (error: unknown) {
        console.error('Failed to render VegaLite chart:', error)
      }
    }

    renderChart()

    return () => {
      // Cleanup on unmount or before re-render
      if (vegaResultRef.current) {
        vegaResultRef.current.finalize()
        vegaResultRef.current = null
      }
    }
  }, [spec, options, isReady])

  return <div ref={containerRef} className={cn("w-full", className)} />
}
