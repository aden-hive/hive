import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { TokenUsageData } from '@/types/agentControl'

interface TokenUsageChartProps {
  data: TokenUsageData[]
  title?: string
  className?: string
}

/**
 * Stacked bar chart showing input/output token usage over time.
 */
export function TokenUsageChart({
  data,
  title = 'Token Usage',
  className,
}: TokenUsageChartProps) {
  const formatNumber = (value: number) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`
    return value.toString()
  }

  const formatDate = (label: ReactNode) => {
    if (typeof label !== 'string') return String(label || '')
    const date = new Date(label)
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[250px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                tick={{ fontSize: 12 }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                tickFormatter={formatNumber}
                tick={{ fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                width={50}
              />
              <Tooltip
                formatter={(value, name) => [
                  formatNumber(Number(value) || 0),
                  name === 'input' ? 'Input Tokens' : 'Output Tokens',
                ]}
                labelFormatter={formatDate}
                contentStyle={{
                  backgroundColor: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '6px',
                }}
              />
              <Legend />
              <Bar
                dataKey="input"
                name="Input"
                stackId="tokens"
                fill="hsl(var(--primary))"
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="output"
                name="Output"
                stackId="tokens"
                fill="hsl(var(--primary) / 0.5)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
