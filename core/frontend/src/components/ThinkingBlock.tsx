import { useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import MarkdownContent from "./MarkdownContent";

interface ThinkingBlockProps {
  content: string;
  defaultExpanded?: boolean;
}

export default function ThinkingBlock({ content, defaultExpanded = false }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="my-1.5 rounded-lg border border-border/30 bg-muted/15 overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-1.5 w-full px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        {expanded
          ? <ChevronDown className="w-3 h-3 shrink-0" />
          : <ChevronRight className="w-3 h-3 shrink-0" />}
        <span className="font-medium">Thinking</span>
      </button>
      {expanded && (
        <div className="px-2.5 pb-2 text-xs text-muted-foreground border-t border-border/15">
          <MarkdownContent content={content} />
        </div>
      )}
    </div>
  );
}
