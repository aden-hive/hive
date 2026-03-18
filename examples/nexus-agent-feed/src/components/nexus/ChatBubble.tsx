import { Copy, RotateCcw, Bot, User } from "lucide-react";
import { toast } from "sonner";
import type { ChatMessage } from "@/data/mock-data";

interface ChatBubbleProps {
  message: ChatMessage;
}

function renderMarkdown(content: string) {
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
              <div className="px-3 py-1.5 bg-muted/60 border-b border-border/50 flex items-center justify-between">
                <span className="text-[10px] font-mono font-medium text-muted-foreground uppercase tracking-wide">{codeLang}</span>
                <button
                  onClick={() => { navigator.clipboard.writeText(codeLines.join("\n")); toast.success("Code copied"); }}
                  className="text-[10px] text-muted-foreground/50 hover:text-muted-foreground transition-colors flex items-center gap-1"
                >
                  <Copy size={10} /> Copy
                </button>
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
    } else if (line.startsWith("**") && line.endsWith("**")) {
      elements.push(
        <p key={i} className="font-semibold text-foreground mt-2">
          {line.replace(/\*\*/g, "")}
        </p>
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
    } else if (line.startsWith("| ")) {
      const tableRows: string[] = [line];
      let j = i + 1;
      while (j < lines.length && lines[j].startsWith("|")) {
        tableRows.push(lines[j]);
        j++;
      }
      i = j - 1;

      const dataRows = tableRows.filter((r) => !r.match(/^\|[\s-|]+\|$/));
      if (dataRows.length > 0) {
        const headers = dataRows[0].split("|").filter(Boolean).map((h) => h.trim());
        const body = dataRows.slice(1).map((r) => r.split("|").filter(Boolean).map((c) => c.trim()));

        elements.push(
          <div key={`table-${i}`} className="overflow-x-auto my-3 rounded-lg border border-border">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="bg-muted/50">
                  {headers.map((h, hi) => (
                    <th key={hi} className="text-left py-2 px-3 font-semibold text-foreground text-[10px] uppercase tracking-wider">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.map((row, ri) => (
                  <tr key={ri} className="border-t border-border/40">
                    {row.map((cell, ci) => (
                      <td key={ci} className="py-2 px-3 tabular-nums text-foreground/75">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
    } else if (line.match(/^\d+\. /)) {
      const formatted = line.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-foreground">$1</strong>');
      elements.push(
        <div key={i} className="ml-0.5 my-0.5 text-foreground/85" dangerouslySetInnerHTML={{ __html: formatted }} />
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

  return elements;
}

export function ChatBubble({ message }: ChatBubbleProps) {
  const isUser = message.role === "user";

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    toast.success("Copied to clipboard");
  };

  return (
    <div className={`flex gap-2.5 ${isUser ? "justify-end" : "justify-start"} group`}>
      {/* Avatar */}
      {!isUser && (
        <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
          <Bot size={14} className="text-primary" />
        </div>
      )}

      <div className={`max-w-[82%] lg:max-w-[68%] relative`}>
        <div
          className={`text-[13px] leading-[1.75] ${
            isUser
              ? "bg-primary text-primary-foreground px-4 py-2.5 rounded-2xl rounded-br-md shadow-sm"
              : "bg-card border border-border shadow-card px-4 py-3.5 rounded-2xl rounded-bl-md"
          }`}
        >
          {isUser ? (
            <p>{message.content}</p>
          ) : (
            <div className="space-y-0 text-foreground/90">{renderMarkdown(message.content)}</div>
          )}
        </div>

        {!isUser && (
          <div className="flex items-center gap-0.5 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
            <button onClick={handleCopy} className="p-1.5 text-muted-foreground/40 hover:text-foreground hover:bg-muted rounded-md transition-colors" title="Copy response">
              <Copy size={12} />
            </button>
            <button className="p-1.5 text-muted-foreground/40 hover:text-foreground hover:bg-muted rounded-md transition-colors" title="Retry">
              <RotateCcw size={12} />
            </button>
            <span className="text-[10px] tabular-nums text-muted-foreground/30 ml-2 font-medium">{message.timestamp}</span>
          </div>
        )}

        {isUser && (
          <div className="flex justify-end mt-1">
            <span className="text-[10px] tabular-nums text-muted-foreground/30 font-medium">{message.timestamp}</span>
          </div>
        )}
      </div>

      {/* User avatar */}
      {isUser && (
        <div className="w-7 h-7 rounded-lg bg-foreground/8 flex items-center justify-center shrink-0 mt-0.5">
          <User size={14} className="text-foreground/50" />
        </div>
      )}
    </div>
  );
}
