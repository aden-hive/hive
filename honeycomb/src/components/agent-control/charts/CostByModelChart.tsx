import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { CostByModelData } from '@/types/agentControl'

// Extended type with index signature for recharts compatibility
interface ChartData extends CostByModelData {
  [key: string]: string | number | undefined
}

interface CostByModelChartProps {
  data: CostByModelData[]
  title?: string
  className?: string
}

const COLORS = [
  'hsl(var(--primary))',
  'hsl(var(--primary) / 0.8)',
  'hsl(var(--primary) / 0.6)',
  'hsl(var(--primary) / 0.4)',
  'hsl(220 70% 50%)',
  'hsl(280 70% 50%)',
  'hsl(340 70% 50%)',
  'hsl(160 70% 50%)',
]

/**
 * Donut chart showing cost distribution by model.
 */
export function CostByModelChart({
  data,
  title = 'Cost by Model',
  className,
}: CostByModelChartProps) {
  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(value)

  const formatPercent = (value: number) => `${(value * 100).toFixed(1)}%`

  const totalCost = data.reduce((sum, item) => sum + item.cost, 0)

  // Cast data to chart-compatible type
  const chartData: ChartData[] = data.map((d) => ({ ...d }))

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[250px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={80}
                paddingAngle={2}
                dataKey="cost"
                nameKey="name"
              >
                {data.map((item, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={item.color || COLORS[index % COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip
                formatter={(value) => [formatCurrency(Number(value) || 0), 'Cost']}
                contentStyle={{
                  backgroundColor: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '6px',
                }}
              />
              <Legend
                layout="vertical"
                align="right"
                verticalAlign="middle"
                wrapperStyle={{
                  maxWidth: '45%',
                  overflow: 'hidden',
                }}
                formatter={(value) => {
                  const item = data.find((d) => d.name === value)
                  return (
                    <span className="text-sm block truncate max-w-[120px]" title={String(value)}>
                      {value}{' '}
                      <span className="text-muted-foreground">
                        ({item ? formatPercent(item.cost / totalCost) : ''})
                      </span>
                    </span>
                  )
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="text-center mt-2">
          <span className="text-2xl font-semibold">{formatCurrency(totalCost)}</span>
          <span className="text-sm text-muted-foreground block">Total Cost</span>
        </div>
      </CardContent>
    </Card>
  )
}
