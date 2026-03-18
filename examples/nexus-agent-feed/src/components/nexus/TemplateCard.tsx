import {
  Headphones,
  Search,
  Code,
  BarChart3,
  Calendar,
  PenTool,
} from "lucide-react";
import { NexusCard } from "./NexusCard";
import type { AgentTemplate } from "@/data/mock-data";

const ICON_MAP: Record<string, typeof Headphones> = {
  headphones: Headphones,
  search: Search,
  code: Code,
  "bar-chart": BarChart3,
  calendar: Calendar,
  "pen-tool": PenTool,
};

interface TemplateCardProps {
  template: AgentTemplate;
  onSelect: (template: AgentTemplate) => void;
  isActive?: boolean;
}

export function TemplateCard({ template, onSelect, isActive }: TemplateCardProps) {
  const Icon = ICON_MAP[template.icon] || Search;

  return (
    <NexusCard
      className={`flex flex-col h-full hover:shadow-elevated transition-all duration-200 cursor-pointer group ${
        isActive ? "ring-2 ring-primary border-primary/30" : ""
      }`}
    >
      <div onClick={() => onSelect(template)} className="flex-1">
        <div className="flex items-start justify-between mb-3">
          <div className="p-2.5 bg-primary/8 rounded-lg text-primary group-hover:bg-primary/12 transition-colors">
            <Icon size={22} />
          </div>
          <span className="text-[10px] font-bold text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
            {template.popularity}% popular
          </span>
        </div>

        <h3 className="text-sm font-bold text-foreground mb-1.5 font-display">{template.title}</h3>
        <p className="text-xs text-muted-foreground leading-relaxed mb-3">
          {template.description}
        </p>

        <div className="flex flex-wrap gap-1.5 mb-4">
          {template.tags.map((tag) => (
            <span
              key={tag}
              className="text-[10px] font-medium px-2 py-0.5 bg-muted text-muted-foreground rounded-full"
            >
              {tag}
            </span>
          ))}
        </div>
      </div>

      <button
        onClick={(e) => { e.stopPropagation(); onSelect(template); }}
        className="w-full py-2 text-sm font-medium text-primary border border-primary/20 rounded-lg hover:bg-primary hover:text-primary-foreground transition-all"
      >
        View Template
      </button>
    </NexusCard>
  );
}
