import {
  Globe,
  Search,
  MessageSquare,
  Terminal,
  Hexagon,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Template } from "@/types/colony";

const ICON_MAP: Record<string, LucideIcon> = {
  Globe,
  Search,
  MessageSquare,
  Terminal,
};

interface TemplateCardProps {
  template: Template;
  onClick: () => void;
}

export default function TemplateCard({ template, onClick }: TemplateCardProps) {
  const Icon = ICON_MAP[template.icon] || Hexagon;

  return (
    <button
      onClick={onClick}
      className="text-left rounded-xl border border-border/60 p-5 transition-all duration-200 hover:border-primary/30 hover:bg-primary/[0.03] group flex gap-4 items-start"
    >
      <div className="w-9 h-9 rounded-lg bg-muted/50 flex items-center justify-center flex-shrink-0 border border-border/40">
        <Icon className="w-4 h-4 text-muted-foreground" />
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors mb-1">
          {template.title}
        </h3>
        <p className="text-xs text-muted-foreground leading-relaxed mb-2 line-clamp-2">
          {template.description}
        </p>
        <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground">
          {template.category}
        </span>
      </div>
    </button>
  );
}
