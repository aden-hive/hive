import { useState, useRef, useEffect } from "react";
import { Send, Crown, Cpu } from "lucide-react";

export interface ChatMessage {
  id: string;
  agent: string;
  agentColor: string;
  content: string;
  timestamp: string;
  type?: "system" | "agent" | "user";
  role?: "queen" | "worker";
  /** Which worker thread this message belongs to (worker agent name) */
  thread?: string;
}

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (message: string, thread: string) => void;
  isWaiting?: boolean;
  activeThread: string;
}

const queenColor = "hsl(45,95%,58%)";
const workerColorMap: Record<string, string> = {
  "inbox-management": "hsl(38,80%,55%)",
  "job-hunter": "hsl(30,85%,58%)",
  "fitness-coach": "hsl(25,75%,55%)",
  "vuln-assessment": "hsl(15,70%,52%)",
};

function getColor(_agent: string, role?: "queen" | "worker"): string {
  if (role === "queen") return queenColor;
  return workerColorMap[_agent] || "hsl(220,60%,55%)";
}

export const workerList = [
  { id: "inbox-management", label: "Inbox Management" },
  { id: "job-hunter", label: "Job Hunter" },
  { id: "fitness-coach", label: "Fitness Coach" },
  { id: "vuln-assessment", label: "Vuln Assessment" },
  { id: "content-writer", label: "Content Writer" },
  { id: "new-agent", label: "New Agent" },
];

function MessageBubble({ msg }: { msg: ChatMessage }) {
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

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] bg-primary text-primary-foreground text-sm leading-relaxed rounded-2xl rounded-br-md px-4 py-3">
          <p className="whitespace-pre-wrap">{msg.content}</p>
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
          <p className="whitespace-pre-wrap text-foreground">{msg.content}</p>
        </div>
      </div>
    </div>
  );
}

export default function ChatPanel({ messages, onSend, isWaiting, activeThread }: ChatPanelProps) {
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [threadMessages.length]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    onSend(input.trim(), activeThread);
    setInput("");
  };

  const activeWorker = workerList.find((w) => w.id === activeThread);

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
            placeholder={`Message ${activeWorker?.label}...`}
            className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
          <button
            type="submit"
            disabled={!input.trim()}
            className="p-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-30 hover:opacity-90 transition-opacity"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </form>
    </div>
  );
}
