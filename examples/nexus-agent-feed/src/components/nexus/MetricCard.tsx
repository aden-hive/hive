import { type LucideIcon } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string;
  trend: string;
  trendUp: boolean | null;
  icon: LucideIcon;
}

export function MetricCard({ label, value, trend, trendUp, icon: Icon }: MetricCardProps) {
  return (
    <div className="bg-card border border-border rounded-xl p-5 shadow-card hover:shadow-elevated transition-shadow duration-200">
      <div className="flex justify-between items-start mb-4">
        <div className="w-9 h-9 bg-primary/8 rounded-lg flex items-center justify-center text-primary">
          <Icon size={18} strokeWidth={1.75} />
        </div>
        <span
          className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
            trendUp === true
              ? "bg-success/10 text-success"
              : trendUp === false
              ? "bg-destructive/10 text-destructive"
              : "bg-muted text-muted-foreground"
          }`}
        >
          {trend}
        </span>
      </div>
      <p className="text-2xl font-bold tabular-nums text-foreground font-display tracking-tight">{value}</p>
      <p className="text-[11px] text-muted-foreground mt-1 font-medium">{label}</p>
    </div>
  );
}
