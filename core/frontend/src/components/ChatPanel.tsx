import { memo, useState, useRef, useEffect, useMemo } from "react";
import { Send, Square, Crown, Cpu, Check, Loader2 } from "lucide-react";

export interface ContextUsageEntry {
  usagePct: number;
  messageCount: number;
  estimatedTokens: number;
  maxTokens: number;
}
import MarkdownContent from "@/components/MarkdownContent";
import QuestionWidget from "@/components/QuestionWidget";
import MultiQuestionWidget from "@/components/MultiQuestionWidget";
import ParallelSubagentBubble, { type SubagentGroup } from "@/components/ParallelSubagentBubble";

export interface ChatMessage {
  id: string;
  agent: string;
  agentColor: string;
  content: string;
  timestamp: string;
  type?: "system" | "agent" | "user" | "tool_status" | "worker_input_request" | "run_divider";
  role?: "queen" | "worker";
  /** Which worker thread this message belongs to (worker agent name) */
  thread?: string;
  /** Epoch ms when this message was first created — used for ordering queen/worker interleaving */
  createdAt?: number;
  /** Queen phase active when this message was created */
  phase?: "planning" | "building" | "staging" | "running";
  /** Backend node_id that produced this message — used for subagent grouping */
  nodeId?: string;
  /** Backend execution_id for this message */
  executionId?: string;
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
  /** Multiple questions from ask_user_multiple */
  pendingQuestions?: { id: string; prompt: string; options?: string[] }[] | null;
  /** Called when user submits an answer to the pending question */
  onQuestionSubmit?: (answer: string, isOther: boolean) => void;
  /** Called when user submits answers to multiple questions */
  onMultiQuestionSubmit?: (answers: Record<string, string>) => void;
  /** Called when user dismisses the pending question without answering */
  onQuestionDismiss?: () => void;
  /** Queen operating phase — shown as a tag on queen messages */
  queenPhase?: "planning" | "building" | "staging" | "running";
  /** Context window usage for queen and workers */
  contextUsage?: Record<string, ContextUsageEntry>;
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

const MessageBubble = memo(function MessageBubble({ msg, queenPhase }: { msg: ChatMessage; queenPhase?: "planning" | "building" | "staging" | "running" }) {
  const isUser = msg.type === "user";
  const isQueen = msg.role === "queen";
  const color = getColor(msg.agent, msg.role);

  if (msg.type === "run_divider") {
    return (
      <div className="flex items-center gap-3 py-2 my-1">
        <div className="flex-1 h-px bg-border/60" />
        <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider">
          {msg.content}
        </span>
        <div className="flex-1 h-px bg-border/60" />
      </div>
    );
  }

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
              ? ((msg.phase ?? queenPhase) === "running"
                ? "running"
                : (msg.phase ?? queenPhase) === "staging"
                  ? "staging"
                  : (msg.phase ?? queenPhase) === "planning"
                    ? "planning"
                    : "building")
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
}, (prev, next) => prev.msg.id === next.msg.id && prev.msg.content === next.msg.content && prev.msg.phase === next.msg.phase && prev.queenPhase === next.queenPhase);

export default function ChatPanel({ messages, onSend, isWaiting, isWorkerWaiting, isBusy, activeThread, disabled, onCancel, pendingQuestion, pendingOptions, pendingQuestions, onQuestionSubmit, onMultiQuestionSubmit, onQuestionDismiss, queenPhase, contextUsage }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [readMap, setReadMap] = useState<Record<string, number>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const threadMessages = messages.filter((m) => {
    if (m.type === "system" && !m.thread) return false;
    if (m.thread !== activeThread) return false;
    // Hide queen messages whose content is whitespace-only — these are
    // tool-use-only turns that have no visible text.  During live operation
    // tool pills provide context, but on resume the pills are gone so
    // the empty bubble is meaningless.
    if (m.role === "queen" && !m.type && (!m.content || !m.content.trim())) return false;
    return true;
  });

  // Group consecutive subagent messages into parallel bubbles.
  // A message is a "subagent message" if its nodeId contains ":subagent:".
  // Consecutive runs of subagent messages with 2+ distinct nodeIds become
  // a ParallelSubagentBubble; runs with only 1 nodeId render normally.
  type RenderItem =
    | { kind: "message"; msg: ChatMessage }
    | { kind: "parallel"; groupId: string; groups: SubagentGroup[] };

  const renderItems = useMemo<RenderItem[]>(() => {
    const items: RenderItem[] = [];
    let i = 0;
    while (i < threadMessages.length) {
      const msg = threadMessages[i];
      const isSubagent = msg.nodeId?.includes(":subagent:");
      if (!isSubagent) {
        items.push({ kind: "message", msg });
        i++;
        continue;
      }
      // Start collecting a consecutive subagent run
      const runStart = i;
      while (
        i < threadMessages.length &&
        threadMessages[i].nodeId?.includes(":subagent:")
      ) {
        i++;
      }
      const runMsgs = threadMessages.slice(runStart, i);
      // Group by nodeId. With the backend fix, each subagent instance
      // gets a unique nodeId (e.g. "node:subagent:agent:2" for instance 2).
      const byNode = new Map<string, ChatMessage[]>();
      for (const m of runMsgs) {
        const nid = m.nodeId!;
        if (!byNode.has(nid)) byNode.set(nid, []);
        byNode.get(nid)!.push(m);
      }
      // Always fold subagent messages into a consolidated bubble —
      // even a single subagent gets the folded view with one square.
      const groups: SubagentGroup[] = [];
      for (const [nodeId, msgs] of byNode) {
        groups.push({
          nodeId,
          messages: msgs,
          contextUsage: contextUsage?.[nodeId],
        });
      }
      const groupId = `par-${runMsgs[0].id}`;
      items.push({ kind: "parallel", groupId, groups });
    }
    return items;
  }, [threadMessages, contextUsage]);

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
        {renderItems.map((item) =>
          item.kind === "parallel" ? (
            <div key={item.groupId}>
              <ParallelSubagentBubble groupId={item.groupId} groups={item.groups} />
            </div>
          ) : (
            <div key={item.msg.id}>
              <MessageBubble msg={item.msg} queenPhase={queenPhase} />
            </div>
          )
        )}

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

      {/* Context window usage bar — sits between messages and input */}
      {(() => {
        if (!contextUsage) return null;
        const queenUsage = contextUsage["__queen__"];
        const workerEntries = Object.entries(contextUsage).filter(([k]) => k !== "__queen__");
        const workerUsage = workerEntries.length > 0
          ? workerEntries.reduce((best, [, v]) => (v.usagePct > best.usagePct ? v : best), workerEntries[0][1])
          : undefined;
        if (!queenUsage && !workerUsage) return null;
        return (
          <div className="flex items-center gap-3 mx-4 px-3 py-1 rounded-lg bg-muted/30 border border-border/20 group/ctx flex-shrink-0">
            {queenUsage && (
              <div className="flex items-center gap-2 flex-1 min-w-0" title={`Queen: ${(queenUsage.estimatedTokens / 1000).toFixed(1)}k / ${(queenUsage.maxTokens / 1000).toFixed(0)}k tokens \u00b7 ${queenUsage.messageCount} messages`}>
                <Crown className="w-3 h-3 flex-shrink-0" style={{ color: "hsl(45,95%,58%)" }} />
                <div className="flex-1 h-1.5 rounded-full bg-muted/50 overflow-hidden min-w-[60px]">
                  <div
                    className="h-full rounded-full transition-all duration-500 ease-out"
                    style={{
                      width: `${Math.min(queenUsage.usagePct, 100)}%`,
                      backgroundColor: queenUsage.usagePct >= 90 ? "hsl(0,65%,55%)" : queenUsage.usagePct >= 70 ? "hsl(35,90%,55%)" : "hsl(45,95%,58%)",
                    }}
                  />
                </div>
                <span className="text-[10px] text-muted-foreground/70 flex-shrink-0 tabular-nums">
                  <span className="group-hover/ctx:hidden">{queenUsage.usagePct}%</span>
                  <span className="hidden group-hover/ctx:inline">{(queenUsage.estimatedTokens / 1000).toFixed(1)}k / {(queenUsage.maxTokens / 1000).toFixed(0)}k</span>
                </span>
              </div>
            )}
            {workerUsage && (
              <div className="flex items-center gap-2 flex-1 min-w-0" title={`Worker: ${(workerUsage.estimatedTokens / 1000).toFixed(1)}k / ${(workerUsage.maxTokens / 1000).toFixed(0)}k tokens \u00b7 ${workerUsage.messageCount} messages`}>
                <Cpu className="w-3 h-3 flex-shrink-0" style={{ color: "hsl(220,60%,55%)" }} />
                <div className="flex-1 h-1.5 rounded-full bg-muted/50 overflow-hidden min-w-[60px]">
                  <div
                    className="h-full rounded-full transition-all duration-500 ease-out"
                    style={{
                      width: `${Math.min(workerUsage.usagePct, 100)}%`,
                      backgroundColor: workerUsage.usagePct >= 90 ? "hsl(0,65%,55%)" : workerUsage.usagePct >= 70 ? "hsl(35,90%,55%)" : "hsl(220,60%,55%)",
                    }}
                  />
                </div>
                <span className="text-[10px] text-muted-foreground/70 flex-shrink-0 tabular-nums">
                  <span className="group-hover/ctx:hidden">{workerUsage.usagePct}%</span>
                  <span className="hidden group-hover/ctx:inline">{(workerUsage.estimatedTokens / 1000).toFixed(1)}k / {(workerUsage.maxTokens / 1000).toFixed(0)}k</span>
                </span>
              </div>
            )}
          </div>
        );
      })()}

      {/* Input area — question widget replaces textarea when a question is pending */}
      {pendingQuestions && pendingQuestions.length >= 2 && onMultiQuestionSubmit ? (
        <MultiQuestionWidget
          questions={pendingQuestions}
          onSubmit={onMultiQuestionSubmit}
          onDismiss={onQuestionDismiss}
        />
      ) : pendingQuestion && pendingOptions && onQuestionSubmit ? (
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
