import { memo, useState, useRef, useEffect } from "react";
import { Send, Square, Crown, Cpu, Check, ChevronRight, Loader2 } from "lucide-react";
import { formatAgentDisplayName } from "@/lib/chat-helpers";
import MarkdownContent from "@/components/MarkdownContent";

export interface ChatMessage {
  id: string;
  agent: string;
  agentColor: string;
  content: string;
  timestamp: string;
  type?: "system" | "agent" | "user" | "tool_status";
  role?: "queen" | "worker";
  /** Which worker thread this message belongs to (worker agent name) */
  thread?: string;
}

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (message: string, thread: string) => void;
  isWaiting?: boolean;
  activeThread: string;
  /** When true, the agent is waiting for user input — changes placeholder text */
  awaitingInput?: boolean;
  /** When true, the input is disabled (e.g. during loading) */
  disabled?: boolean;
  /** Called when user clicks the stop button to cancel the queen's current turn */
  onCancel?: () => void;
}

const queenColor = "hsl(45,95%,58%)";

function getColor(_agent: string, role?: "queen" | "worker"): string {
  if (role === "queen") return queenColor;
  return "hsl(220,60%,55%)";
}

function ToolActivityRow({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);

  let tools: { name: string; done: boolean }[] = [];
  let allDone = false;
  try {
    const parsed = JSON.parse(content);
    tools = parsed.tools || [];
    allDone = parsed.allDone ?? false;
  } catch {
    // Legacy plain-text fallback
    return (
      <div className="flex gap-3 pl-10">
        <span className="text-[11px] text-muted-foreground bg-muted/40 px-3 py-1 rounded-full border border-border/40">
          {content}
        </span>
      </div>
    );
  }

  if (tools.length === 0) return null;

  const total = tools.length;

  if (allDone && !expanded) {
    return (
      <div className="flex gap-3 pl-10">
        <button
          onClick={() => setExpanded(true)}
          className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronRight className="w-3 h-3" />
          <Check className="w-3 h-3 text-emerald-500" />
          <span>{total} tool{total === 1 ? "" : "s"} used</span>
        </button>
      </div>
    );
  }

  return (
    <div className="flex gap-3 pl-10">
      <div className="flex flex-wrap items-center gap-1.5">
        {allDone && (
          <button onClick={() => setExpanded(false)} className="text-muted-foreground hover:text-foreground transition-colors">
            <ChevronRight className="w-3 h-3 rotate-90" />
          </button>
        )}
        {tools.map((t, i) => (
          <span
            key={i}
            className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${
              t.done
                ? "text-emerald-600 bg-emerald-500/10 border-emerald-500/20"
                : "text-muted-foreground bg-muted/40 border-border/40"
            }`}
          >
            {t.done ? (
              <Check className="w-2.5 h-2.5" />
            ) : (
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
            )}
            {t.name}
          </span>
        ))}
      </div>
    </div>
  );
}

const MessageBubble = memo(function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.type === "user";
  const isQueen = msg.role === "queen";
  const color = getColor(msg.agent, msg.role);

  if (msg.type === "system") {
    return (
      <div className="flex justify-center py-1">
        <span className="text-[11px] text-muted-foreground bg-muted/60 px-3 py-1.5 rounded-full">
          {msg.content}
        </span>
      </div>
    );
  }

  if (msg.type === "tool_status") {
    return <ToolActivityRow content={msg.content} />;
  }

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] bg-primary text-primary-foreground text-sm leading-relaxed rounded-2xl rounded-br-md px-4 py-3">
          <p className="whitespace-pre-wrap break-words">{msg.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div
        className={`flex-shrink-0 ${isQueen ? "w-9 h-9" : "w-7 h-7"} rounded-xl flex items-center justify-center`}
        style={{
          backgroundColor: `${color}18`,
          border: `1.5px solid ${color}35`,
          boxShadow: isQueen ? `0 0 12px ${color}20` : undefined,
        }}
      >
        {isQueen ? (
          <Crown className="w-4 h-4" style={{ color }} />
        ) : (
          <Cpu className="w-3.5 h-3.5" style={{ color }} />
        )}
      </div>
      <div className={`flex-1 min-w-0 ${isQueen ? "max-w-[85%]" : "max-w-[75%]"}`}>
        <div className="flex items-center gap-2 mb-1">
          <span className={`font-medium ${isQueen ? "text-sm" : "text-xs"}`} style={{ color }}>
            {msg.agent}
          </span>
          <span
            className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md ${
              isQueen ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"
            }`}
          >
            {isQueen ? "Queen" : "Worker"}
          </span>
        </div>
        <div
          className={`text-sm leading-relaxed rounded-2xl rounded-tl-md px-4 py-3 ${
            isQueen ? "border border-primary/20 bg-primary/5" : "bg-muted/60"
          }`}
        >
          <MarkdownContent content={msg.content} />
        </div>
      </div>
    </div>
  );
}, (prev, next) => prev.msg.id === next.msg.id && prev.msg.content === next.msg.content);

export default function ChatPanel({ messages, onSend, isWaiting, activeThread, awaitingInput, disabled, onCancel }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [readMap, setReadMap] = useState<Record<string, number>>({});
  const bottomRef = useRef<HTMLDivElement>(null);

  const threadMessages = messages.filter((m) => {
    if (m.type === "system" && !m.thread) return false;
    return m.thread === activeThread;
  });

  // Mark current thread as read
  useEffect(() => {
    const count = messages.filter((m) => m.thread === activeThread).length;
    setReadMap((prev) => ({ ...prev, [activeThread]: count }));
  }, [activeThread, messages]);

  // Suppress unused var
  void readMap;

  const lastMsg = threadMessages[threadMessages.length - 1];
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [threadMessages.length, lastMsg?.content]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    onSend(input.trim(), activeThread);
    setInput("");
  };

  const activeWorkerLabel = formatAgentDisplayName(activeThread);

  return (
    <div className="flex flex-col h-full min-w-0">
      {/* Compact sub-header */}
      <div className="px-5 pt-4 pb-2 flex items-center gap-2">
        <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">Conversation</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto px-5 py-4 space-y-3">
        {threadMessages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        {isWaiting && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-xl bg-muted flex items-center justify-center">
              <Cpu className="w-3.5 h-3.5 text-muted-foreground" />
            </div>
            <div className="bg-muted/60 rounded-2xl rounded-tl-md px-4 py-3">
              <div className="flex gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-border">
        <div className="flex items-center gap-3 bg-muted/40 rounded-xl px-4 py-2.5 border border-border focus-within:border-primary/40 transition-colors">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              disabled
                ? "Connecting to agent..."
                : awaitingInput
                  ? "Agent is waiting for your response..."
                  : `Message ${activeWorkerLabel}...`
            }
            disabled={disabled}
            className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-50 disabled:cursor-not-allowed"
          />
          {isWaiting && onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="p-2 rounded-lg bg-destructive text-destructive-foreground hover:opacity-90 transition-opacity"
            >
              <Square className="w-4 h-4" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim() || disabled}
              className="p-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-30 hover:opacity-90 transition-opacity"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
