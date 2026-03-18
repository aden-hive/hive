import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Paperclip, Loader2, PanelLeft, PanelRightOpen, Sparkles, FileSpreadsheet, Layers } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { ChatBubble } from "@/components/nexus/ChatBubble";
import { StreamingBubble } from "@/components/nexus/StreamingBubble";
import { useChatMessages } from "@/hooks/useChatMessages";
import { MOCK_MESSAGES } from "@/data/mock-data";
import type { AgentTemplate } from "@/data/mock-data";

const DEFAULT_QUICK_ACTIONS = ["Summarize", "Analyze Data", "Generate Report", "Review Code"];

interface ExecutionCallbacks {
  startExecution: () => void;
  onStreamStart: () => void;
  onStreamDelta: (chunkLen: number) => void;
  onStreamDone: () => void;
  onStreamError: () => void;
}

interface ChatViewProps {
  sessionId: string | null;
  onCreateSession: (title?: string) => Promise<string | null>;
  onUpdateTitle: (sessionId: string, title: string) => Promise<void>;
  onToggleSidebar: () => void;
  onToggleExecution: () => void;
  executionHook?: ExecutionCallbacks;
  activeTemplate?: AgentTemplate | null;
}

export function ChatView({
  sessionId,
  onCreateSession,
  onUpdateTitle,
  onToggleSidebar,
  onToggleExecution,
  executionHook,
  activeTemplate,
}: ChatViewProps) {
  const { messages, streamedText, phase, loadMessages, sendMessage } = useChatMessages(sessionId, executionHook);
  const [inputValue, setInputValue] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const isDemo = !sessionId && messages.length === 0 && phase === "idle";
  const displayMessages = isDemo
    ? (activeTemplate?.sampleMessages || MOCK_MESSAGES)
    : messages;
  const quickActions = activeTemplate?.quickActions || DEFAULT_QUICK_ACTIONS;

  useEffect(() => {
    if (sessionId) loadMessages(sessionId);
  }, [sessionId, loadMessages]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamedText, phase]);

  const handleSend = useCallback(async () => {
    const text = inputValue.trim();
    if (!text || phase !== "idle") return;

    let sid = sessionId;
    if (!sid) {
      sid = await onCreateSession(text.length > 50 ? text.slice(0, 47) + "..." : text);
      if (!sid) return;
    }

    setInputValue("");
    sendMessage(text, (title) => onUpdateTitle(sid!, title));
  }, [inputValue, phase, sessionId, onCreateSession, onUpdateTitle, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleQuickAction = (action: string) => {
    if (phase !== "idle") return;
    setInputValue(action);
    setTimeout(() => {
      setInputValue("");
      (async () => {
        let sid = sessionId;
        if (!sid) {
          sid = await onCreateSession(action);
          if (!sid) return;
        }
        sendMessage(action, (title) => onUpdateTitle(sid!, title));
      })();
    }, 100);
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-background">
      {/* Header */}
      <header className="h-12 border-b border-border bg-card/80 backdrop-blur-sm flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-2.5">
          <button onClick={onToggleSidebar} className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-all lg:hidden">
            <PanelLeft size={15} />
          </button>
          <div className="flex items-center gap-2">
            <div className={`w-1.5 h-1.5 rounded-full transition-colors ${phase !== "idle" ? "bg-primary animate-pulse" : "bg-success"}`} />
            <h2 className="text-[13px] font-semibold text-foreground font-display">
              {activeTemplate ? activeTemplate.title : "Nexus AI"}
            </h2>
          </div>
          {activeTemplate && (
            <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-primary/8 text-primary uppercase tracking-wide hidden sm:inline-flex items-center gap-1">
              <Layers size={9} /> Template
            </span>
          )}
          <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full transition-colors hidden sm:inline-flex items-center gap-1 uppercase tracking-wide ${
            phase === "thinking" ? "bg-primary/10 text-primary" :
            phase === "streaming" ? "bg-success/10 text-success" :
            "bg-muted text-muted-foreground/60"
          }`}>
            {phase === "thinking" ? "Thinking" : phase === "streaming" ? "Streaming" : "Ready"}
          </span>
        </div>
        <button onClick={onToggleExecution} className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-all lg:hidden">
          <PanelRightOpen size={15} />
        </button>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[720px] mx-auto px-4 md:px-6 py-6 space-y-4">
          {isDemo && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mb-3">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-muted/50 border border-border/40 w-fit mx-auto text-[9px] font-semibold text-muted-foreground/60 uppercase tracking-wider">
                <Sparkles size={10} className="text-primary/60" />
                {activeTemplate ? `${activeTemplate.title} — Sample conversation` : "Sample conversation"}
              </div>
            </motion.div>
          )}

          {displayMessages.map((msg, i) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.15, delay: isDemo ? i * 0.06 : 0 }}
            >
              {msg.file && (
                <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} mb-2`}>
                  <div className="flex items-center gap-2.5 px-3 py-2 bg-card border border-border rounded-xl shadow-card max-w-[240px]">
                    <div className="w-8 h-8 bg-success/10 rounded-lg flex items-center justify-center shrink-0">
                      <FileSpreadsheet size={14} className="text-success" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-[11px] font-medium text-foreground truncate">{msg.file.name}</p>
                      <p className="text-[9px] text-muted-foreground/50">{msg.file.size}</p>
                    </div>
                  </div>
                </div>
              )}
              <ChatBubble
                message={{
                  ...msg,
                  timestamp: msg.timestamp || new Date(msg.created_at || "").toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" }),
                }}
              />
            </motion.div>
          ))}

          <AnimatePresence>
            {phase === "thinking" && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} className="flex justify-start pl-10">
                <div className="bg-card border border-border rounded-2xl px-4 py-2.5 flex items-center gap-2.5 shadow-card">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                  <span className="text-[11px] text-muted-foreground/60 font-medium">Thinking…</span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {phase === "streaming" && streamedText && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
                <StreamingBubble content={streamedText} />
              </motion.div>
            )}
          </AnimatePresence>

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border bg-card/80 backdrop-blur-sm px-4 py-3">
        <div className="max-w-[720px] mx-auto">
          <div className="flex gap-1.5 mb-2.5 overflow-x-auto pb-0.5 no-scrollbar">
            {quickActions.map((chip) => (
              <button
                key={chip}
                onClick={() => handleQuickAction(chip)}
                disabled={phase !== "idle"}
                className="whitespace-nowrap px-2.5 py-1 rounded-full border border-border text-[10px] font-semibold text-muted-foreground/60 hover:border-primary/30 hover:text-primary hover:bg-primary/5 transition-colors disabled:opacity-30 disabled:pointer-events-none"
              >
                {chip}
              </button>
            ))}
          </div>

          <div className="relative">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={activeTemplate ? `Ask ${activeTemplate.title} anything…` : "Ask Nexus AI anything…"}
              disabled={phase !== "idle"}
              rows={1}
              className="w-full bg-muted/50 border border-border rounded-xl px-4 py-2.5 pr-24 text-[13px] focus:outline-none focus:ring-2 focus:ring-primary/15 focus:border-primary/30 transition-all resize-none min-h-[44px] max-h-[120px] text-foreground placeholder:text-muted-foreground/40 disabled:opacity-50"
            />
            <div className="absolute right-1.5 bottom-1 flex gap-0.5">
              <button className="p-2 text-muted-foreground/30 hover:text-muted-foreground transition-all rounded-md">
                <Paperclip size={15} />
              </button>
              <button
                onClick={handleSend}
                disabled={!inputValue.trim() || phase !== "idle"}
                className="p-2 bg-primary text-primary-foreground rounded-lg hover:opacity-90 transition-all disabled:opacity-20 disabled:pointer-events-none"
              >
                {phase !== "idle" ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
