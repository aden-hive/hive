import { memo } from "react";
import { Bot } from "lucide-react";

interface StreamingBubbleProps {
  content: string;
}

function renderStreamingMarkdown(content: string) {
  const lines = content.split("\n");
  const elements: JSX.Element[] = [];
  let inCodeBlock = false;
  let codeLines: string[] = [];
  let codeLang = "";
  let codeBlockKey = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith("```")) {
      if (inCodeBlock) {
        elements.push(
          <div key={`code-${codeBlockKey++}`} className="my-3 rounded-lg border border-border overflow-hidden">
            {codeLang && (
              <div className="px-3 py-1.5 bg-muted/60 border-b border-border/50">
                <span className="text-[10px] font-mono font-medium text-muted-foreground uppercase tracking-wide">{codeLang}</span>
              </div>
            )}
            <pre className="bg-muted/40 p-3.5 overflow-x-auto text-[12px] font-mono leading-relaxed text-foreground/80">
              <code>{codeLines.join("\n")}</code>
            </pre>
          </div>
        );
        codeLines = [];
        codeLang = "";
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
        codeLang = line.replace("```", "").trim();
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    if (line.startsWith("### ")) {
      elements.push(
        <h3 key={i} className="text-[13px] font-bold text-foreground mt-4 mb-1 font-display tracking-tight">
          {line.replace("### ", "")}
        </h3>
      );
    } else if (line.startsWith("- ")) {
      const formatted = line
        .replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-muted rounded text-[11px] font-mono text-foreground/80 border border-border/40">$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-foreground">$1</strong>');
      elements.push(
        <div key={i} className="flex gap-2 ml-0.5 my-0.5 text-foreground/85">
          <span className="text-primary/40 mt-[3px] select-none text-[10px]">●</span>
          <span dangerouslySetInnerHTML={{ __html: formatted.replace("- ", "") }} />
        </div>
      );
    } else if (line.startsWith("> ")) {
      const formatted = line.replace(/> /, "").replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold">$1</strong>');
      elements.push(
        <blockquote
          key={i}
          className="border-l-2 border-warning/40 bg-warning/5 pl-3 pr-3 py-2 my-2.5 text-foreground/80 rounded-r-md text-[12.5px]"
          dangerouslySetInnerHTML={{ __html: formatted }}
        />
      );
    } else if (line.trim() === "") {
      elements.push(<div key={i} className="h-2" />);
    } else {
      const formatted = line
        .replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-muted rounded text-[11px] font-mono text-foreground/80 border border-border/40">$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-foreground">$1</strong>');
      elements.push(<p key={i} className="text-foreground/85" dangerouslySetInnerHTML={{ __html: formatted }} />);
    }
  }

  if (inCodeBlock && codeLines.length > 0) {
    elements.push(
      <div key={`code-partial-${codeBlockKey}`} className="my-3 rounded-lg border border-border overflow-hidden">
        {codeLang && (
          <div className="px-3 py-1.5 bg-muted/60 border-b border-border/50">
            <span className="text-[10px] font-mono font-medium text-muted-foreground uppercase tracking-wide">{codeLang}</span>
          </div>
        )}
        <pre className="bg-muted/40 p-3.5 overflow-x-auto text-[12px] font-mono leading-relaxed text-foreground/80">
          <code>{codeLines.join("\n")}</code>
          <span className="inline-block w-1 h-3.5 bg-primary/50 animate-pulse ml-0.5 align-middle rounded-sm" />
        </pre>
      </div>
    );
  }

  return elements;
}

export const StreamingBubble = memo(function StreamingBubble({ content }: StreamingBubbleProps) {
  return (
    <div className="flex gap-2.5 justify-start">
      <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
        <Bot size={14} className="text-primary" />
      </div>
      <div className="max-w-[82%] lg:max-w-[68%]">
        <div className="bg-card border border-border shadow-card rounded-2xl rounded-bl-md px-4 py-3.5 text-[13px] leading-[1.75] text-foreground/90">
          <div className="space-y-0">
            {renderStreamingMarkdown(content)}
            <span className="inline-block w-1 h-3.5 bg-primary/50 animate-pulse ml-0.5 align-middle rounded-sm" />
          </div>
        </div>
      </div>
    </div>
  );
});
