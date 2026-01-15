import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { TopAgentData } from '@/types/agentControl'

interface TopAgentsChartProps {
  data: TopAgentData[]
  title?: string
  className?: string
}

/**
 * Horizontal bar chart showing top agents by spend.
 */
export function TopAgentsChart({
  data,
  title = 'Top Agents by Spend',
  className,
}: TopAgentsChartProps) {
  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)

  // Sort by spend descending and take top 10
  const sortedData = [...data].sort((a, b) => b.spend - a.spend).slice(0, 10)

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={sortedData}
              layout="vertical"
              margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" horizontal={false} />
              <XAxis
                type="number"
                tickFormatter={formatCurrency}
                tick={{ fontSize: 12 }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                width={100}
              />
              <Tooltip
                formatter={(value, name) => {
                  const numValue = Number(value) || 0
                  if (name === 'spend') return [formatCurrency(numValue), 'Spend']
                  return [numValue, String(name)]
                }}
                contentStyle={{
                  backgroundColor: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '6px',
                }}
              />
              <Bar dataKey="spend" radius={[0, 4, 4, 0]}>
                {sortedData.map((entry, index) => {
                  // Color based on limit usage
                  const limitRatio = entry.limit ? entry.spend / entry.limit : 0
                  let fill = 'hsl(var(--primary))'
                  if (limitRatio >= 0.9) fill = 'hsl(var(--destructive))'
                  else if (limitRatio >= 0.75) fill = 'hsl(38 92% 50%)'

                  return <Cell key={`cell-${index}`} fill={fill} />
                })}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
