import { memo, useState, useRef, useEffect } from "react";
import { Send, Square, Crown, Cpu, Check, Loader2 } from "lucide-react";
import MarkdownContent from "@/components/MarkdownContent";
import QuestionWidget from "@/components/QuestionWidget";

export interface ChatMessage {
  id: string;
  agent: string;
  agentColor: string;
  content: string;
  timestamp: string;
  type?: "system" | "agent" | "user" | "tool_status" | "worker_input_request";
  role?: "queen" | "worker";
  /** Which worker thread this message belongs to (worker agent name) */
  thread?: string;
  /** Epoch ms when this message was first created — used for ordering queen/worker interleaving */
  createdAt?: number;
}

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (message: string, thread: string) => void;
  isWaiting?: boolean;
  /** When true a worker is thinking (not yet streaming) */
  isWorkerWaiting?: boolean;
  /** When true the queen is busy (typing or streaming) — shows the stop button */
  isBusy?: boolean;
  activeThread: string;
  /** When true, the input is disabled (e.g. during loading) */
  disabled?: boolean;
  /** Called when user clicks the stop button to cancel the queen's current turn */
  onCancel?: () => void;
  /** Pending question from ask_user — replaces textarea when present */
  pendingQuestion?: string | null;
  /** Options for the pending question */
  pendingOptions?: string[] | null;
  /** Called when user submits an answer to the pending question */
  onQuestionSubmit?: (answer: string, isOther: boolean) => void;
  /** Called when user dismisses the pending question without answering */
  onQuestionDismiss?: () => void;
  /** Queen operating phase — shown as a tag on queen messages */
  queenPhase?: "building" | "staging" | "running";
}

const queenColor = "hsl(45,95%,58%)";
const workerColor = "hsl(220,60%,55%)";

function getColor(_agent: string, role?: "queen" | "worker"): string {
  if (role === "queen") return queenColor;
  return workerColor;
}

// Honey-drizzle palette — based on color-hex.com/color-palette/80116
// #8e4200 · #db6f02 · #ff9624 · #ffb825 · #ffd69c + adjacent warm tones
const TOOL_HEX = [
  "#db6f02", // rich orange
  "#ffb825", // golden yellow
  "#ff9624", // bright orange
  "#c48820", // warm bronze
  "#e89530", // honey
  "#d4a040", // goldenrod
  "#cc7a10", // caramel
  "#e5a820", // sunflower
];

function toolHex(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return TOOL_HEX[Math.abs(hash) % TOOL_HEX.length];
}

function ToolActivityRow({ content }: { content: string }) {
  let tools: { name: string; done: boolean }[] = [];
  try {
    const parsed = JSON.parse(content);
    tools = parsed.tools || [];
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

  // Group by tool name → count done vs running
  const grouped = new Map<string, { done: number; running: number }>();
  for (const t of tools) {
    const entry = grouped.get(t.name) || { done: 0, running: 0 };
    if (t.done) entry.done++;
    else entry.running++;
    grouped.set(t.name, entry);
  }

  // Build pill list: running first, then done
  const runningPills: { name: string; count: number }[] = [];
  const donePills: { name: string; count: number }[] = [];
  for (const [name, counts] of grouped) {
    if (counts.running > 0) runningPills.push({ name, count: counts.running });
    if (counts.done > 0) donePills.push({ name, count: counts.done });
  }

  return (
    <div className="flex gap-3 pl-10">
      <div className="flex flex-wrap items-center gap-1.5">
        {runningPills.map((p) => {
          const hex = toolHex(p.name);
          return (
            <span
              key={`run-${p.name}`}
              className="inline-flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full"
              style={{ color: hex, backgroundColor: `${hex}18`, border: `1px solid ${hex}35` }}
            >
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
              {p.name}
              {p.count > 1 && (
                <span className="text-[10px] font-medium opacity-70">×{p.count}</span>
              )}
            </span>
          );
        })}
        {donePills.map((p) => {
          const hex = toolHex(p.name);
          return (
            <span
              key={`done-${p.name}`}
              className="inline-flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full"
              style={{ color: hex, backgroundColor: `${hex}18`, border: `1px solid ${hex}35` }}
            >
              <Check className="w-2.5 h-2.5" />
              {p.name}
              {p.count > 1 && (
                <span className="text-[10px] opacity-80">×{p.count}</span>
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
}

const MessageBubble = memo(function MessageBubble({ msg, queenPhase }: { msg: ChatMessage; queenPhase?: "building" | "staging" | "running" }) {
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
            {isQueen
              ? queenPhase === "running"
                ? "running phase"
                : queenPhase === "staging"
                  ? "staging phase"
                  : "building phase"
              : "Worker"}
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
}, (prev, next) => prev.msg.id === next.msg.id && prev.msg.content === next.msg.content && prev.queenPhase === next.queenPhase);

export default function ChatPanel({ messages, onSend, isWaiting, isWorkerWaiting, isBusy, activeThread, disabled, onCancel, pendingQuestion, pendingOptions, onQuestionSubmit, onQuestionDismiss, queenPhase }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [readMap, setReadMap] = useState<Record<string, number>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  // Autoscroll: only when user is already near the bottom
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = distFromBottom < 80;
  };

  useEffect(() => {
    if (stickToBottom.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [threadMessages, pendingQuestion, isWaiting, isWorkerWaiting]);

  // Always start pinned to bottom when switching threads
  useEffect(() => {
    stickToBottom.current = true;
  }, [activeThread]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    onSend(input.trim(), activeThread);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  return (
    <div className="flex flex-col h-full min-w-0">
      {/* Compact sub-header */}
      <div className="px-5 pt-4 pb-2 flex items-center gap-2">
        <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">Conversation</p>
      </div>

      {/* Messages */}
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-auto px-5 py-4 space-y-3">
        {threadMessages.map((msg) => (
          <div key={msg.id}>
            <MessageBubble msg={msg} queenPhase={queenPhase} />
          </div>
        ))}

        {/* Show typing indicator while waiting for first queen response (disabled + empty chat) */}
        {(isWaiting || (disabled && threadMessages.length === 0)) && (
          <div className="flex gap-3">
            <div
              className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center"
              style={{
                backgroundColor: `${queenColor}18`,
                border: `1.5px solid ${queenColor}35`,
                boxShadow: `0 0 12px ${queenColor}20`,
              }}
            >
              <Crown className="w-4 h-4" style={{ color: queenColor }} />
            </div>
            <div className="border border-primary/20 bg-primary/5 rounded-2xl rounded-tl-md px-4 py-3">
              <div className="flex gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        {isWorkerWaiting && !isWaiting && (
          <div className="flex gap-3">
            <div
              className="flex-shrink-0 w-7 h-7 rounded-xl flex items-center justify-center"
              style={{
                backgroundColor: `${workerColor}18`,
                border: `1.5px solid ${workerColor}35`,
              }}
            >
              <Cpu className="w-3.5 h-3.5" style={{ color: workerColor }} />
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

      {/* Input area — question widget replaces textarea when a question is pending */}
      {pendingQuestion && pendingOptions && onQuestionSubmit ? (
        <QuestionWidget
          question={pendingQuestion}
          options={pendingOptions}
          onSubmit={onQuestionSubmit}
          onDismiss={onQuestionDismiss}
        />
      ) : (
        <form onSubmit={handleSubmit} className="p-4">
          <div className="flex items-center gap-3 bg-muted/40 rounded-xl px-4 py-2.5 border border-border focus-within:border-primary/40 transition-colors">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                const ta = e.target;
                ta.style.height = "auto";
                ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder={disabled ? "Connecting to agent..." : "Message Queen Bee..."}
              disabled={disabled}
              className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-50 disabled:cursor-not-allowed resize-none overflow-y-auto"
            />
            {isBusy && onCancel ? (
              <button
                type="button"
                onClick={onCancel}
                className="p-2 rounded-lg bg-amber-500/15 text-amber-400 border border-amber-500/40 hover:bg-amber-500/25 transition-colors"
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
      )}
    </div>
  );
}
