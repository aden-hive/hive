import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Loader2, ArrowRight, Hexagon } from "lucide-react";
import ChatPanel, { type ChatMessage, type ImageContent } from "@/components/ChatPanel";
import { executionApi } from "@/api/execution";
import { sessionsApi } from "@/api/sessions";
import { queensApi } from "@/api/queens";
import { useMultiSSE } from "@/hooks/use-sse";
import type { AgentEvent } from "@/api/types";
import { sseEventToChatMessage } from "@/lib/chat-helpers";
import { useColony } from "@/context/ColonyContext";
import { getQueenForAgent } from "@/lib/colony-registry";

const makeId = () => Math.random().toString(36).slice(2, 9);

export default function QueenDM() {
  const { queenId } = useParams<{ queenId: string }>();
  const navigate = useNavigate();
  const { queens, queenProfiles } = useColony();
  const profileQueen = queenProfiles.find((q) => q.id === queenId);
  const colonyQueen = queens.find((q) => q.id === queenId);
  const queenInfo = getQueenForAgent(queenId || "");
  const queenName = profileQueen?.name ?? colonyQueen?.name ?? queenInfo.name;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [queenReady, setQueenReady] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [pendingOptions, setPendingOptions] = useState<string[] | null>(null);
  const [pendingQuestions, setPendingQuestions] = useState<
    { id: string; prompt: string; options?: string[] }[] | null
  >(null);
  const [awaitingInput, setAwaitingInput] = useState(false);
  const [transitioningToColony, setTransitioningToColony] = useState<string | null>(null);
  const [, setActiveToolCalls] = useState<Record<string, { name: string; done: boolean }>>({});

  const turnCounterRef = useRef(0);
  const queenIterTextRef = useRef<Record<string, Record<number, string>>>({});
  const [queenPhase, setQueenPhase] = useState<"planning" | "building" | "staging" | "running" | "independent">("independent");

  // Switch queen session when queenId changes
  useEffect(() => {
    if (!queenId) return;

    // Immediately reset UI for the new queen
    setSessionId(null);
    setMessages([]);
    setQueenReady(false);
    setLoading(true);
    setIsTyping(false);
    setIsStreaming(false);
    setPendingQuestion(null);
    setPendingOptions(null);
    setPendingQuestions(null);
    setAwaitingInput(false);
    turnCounterRef.current = 0;
    queenIterTextRef.current = {};

    let cancelled = false;

    (async () => {
      try {
        const result = await queensApi.getOrCreateSession(queenId, undefined, "independent");
        if (cancelled) return;

        const sid = result.session_id;
        setSessionId(sid);
        setQueenReady(true);
        // Show typing indicator while the queen initializes (identity hook + first turn)
        setIsTyping(true);

        // Restore messages from history
        if (result.status === "live" || result.status === "resumed") {
          try {
            const { events } = await sessionsApi.eventsHistory(sid);
            if (cancelled) return;
            const restored: ChatMessage[] = [];
            for (const evt of events) {
              const msg = sseEventToChatMessage(evt, "queen-dm", queenName);
              if (!msg) continue;
              if (evt.stream_id === "queen") msg.role = "queen";
              restored.push(msg);
            }
            if (restored.length > 0) {
              restored.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
              if (!cancelled) {
                setMessages(restored);
                setIsTyping(false);
              }
            }
          } catch {
            // No history
          }
        }
      } catch {
        // Session creation failed
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [queenId, queenName]);

  // SSE handler
  const handleSSEEvent = useCallback(
    (_agentType: string, event: AgentEvent) => {
      const isQueen = event.stream_id === "queen";
      if (!isQueen) return;

      switch (event.type) {
        case "execution_started":
          turnCounterRef.current++;
          setIsTyping(true);
          setQueenReady(true);
          setActiveToolCalls({});
          break;

        case "execution_completed": {
          setIsTyping(false);
          setIsStreaming(false);
          // Flush any remaining LLM text
          const executionId = event.execution_id;
          if (executionId) {
            const prefix = `${executionId}:`;
            const matchingKeys = Object.keys(queenIterTextRef.current).filter(k => k.startsWith(prefix));
            
            for (const iterKey of matchingKeys) {
              const parts = queenIterTextRef.current[iterKey];
              const sorted = Object.keys(parts)
                .map(Number)
                .sort((a, b) => a - b);
              const content = sorted.map((k) => parts[k]).join("\n");
              if (content.trim()) {
                const chatMsg: ChatMessage = {
                  id: `queen-stream-${iterKey}-final`,
                  agent: queenName,
                  agentColor: "",
                  content: content,
                  timestamp: "",
                  type: "agent",
                  thread: "queen-dm",
                  createdAt: Date.now(),
                  role: "queen",
                };
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === chatMsg.id);
                  if (idx >= 0) {
                    return prev.map((m, i) => (i === idx ? chatMsg : m));
                  }
                  return [...prev, chatMsg];
                });
              }
              delete queenIterTextRef.current[iterKey];
            }
          }
          setActiveToolCalls({});
          break;
        }

        case "llm_turn_complete":
          turnCounterRef.current++;
          setActiveToolCalls({});
          break;

        case "client_output_delta":
        case "llm_text_delta": {
          const chatMsg = sseEventToChatMessage(event, "queen-dm", queenName, turnCounterRef.current);
          if (chatMsg) {
            if (event.execution_id) {
              const iter = event.data?.iteration ?? 0;
              const inner = (event.data?.inner_turn as number) ?? 0;
              const iterKey = `${event.execution_id}:${iter}`;
              if (!queenIterTextRef.current[iterKey]) {
                queenIterTextRef.current[iterKey] = {};
              }
              const snapshot =
                (event.data?.snapshot as string) || (event.data?.content as string) || "";
              queenIterTextRef.current[iterKey][inner] = snapshot;
              const parts = queenIterTextRef.current[iterKey];
              const sorted = Object.keys(parts)
                .map(Number)
                .sort((a, b) => a - b);
              chatMsg.content = sorted.map((k) => parts[k]).join("\n");
              chatMsg.id = `queen-stream-${event.execution_id}-${iter}`;
            }
            chatMsg.role = "queen";

            setMessages((prev) => {
              const idx = prev.findIndex((m) => m.id === chatMsg.id);
              if (idx >= 0) {
                return prev.map((m, i) => (i === idx ? chatMsg : m));
              }
              return [...prev, chatMsg];
            });
          }
          setIsStreaming(true);
          break;
        }

        case "client_input_requested": {
          const prompt = (event.data?.prompt as string) || "";
          const rawOptions = event.data?.options;
          const options = Array.isArray(rawOptions) ? (rawOptions as string[]) : null;
          const rawQuestions = event.data?.questions;
          const questions = Array.isArray(rawQuestions)
            ? (rawQuestions as { id: string; prompt: string; options?: string[] }[])
            : null;
          setAwaitingInput(true);
          setIsTyping(false);
          setIsStreaming(false);
          setPendingQuestion(prompt || null);
          setPendingOptions(options);
          setPendingQuestions(questions);
          break;
        }

        case "client_input_received": {
          const chatMsg = sseEventToChatMessage(event, "queen-dm", queenName, turnCounterRef.current);
          if (chatMsg) {
            setMessages((prev) => {
              // Reconcile optimistic user message
              if (chatMsg.type === "user" && prev.length > 0) {
                const last = prev[prev.length - 1];
                if (
                  last.type === "user" &&
                  last.content === chatMsg.content &&
                  Math.abs((chatMsg.createdAt ?? 0) - (last.createdAt ?? 0)) <= 15000
                ) {
                  return prev.map((m, i) =>
                    i === prev.length - 1 ? { ...m, id: chatMsg.id } : m,
                  );
                }
              }
              return [...prev, chatMsg];
            });
          }
          break;
        }

        case "queen_phase_changed": {
          const rawPhase = event.data?.phase as string;
          if (rawPhase === "independent" || rawPhase === "planning" || rawPhase === "building" || rawPhase === "staging" || rawPhase === "running") {
            setQueenPhase(rawPhase);
          }
          break;
        }

        case "tool_call_started": {
          // Flush any pending LLM text before showing tool call
          // The ref is keyed by "${execution_id}:${iteration}", find all matching entries
          const executionId = event.execution_id;
          if (executionId) {
            const prefix = `${executionId}:`;
            const matchingKeys = Object.keys(queenIterTextRef.current).filter(k => k.startsWith(prefix));
            
            for (const iterKey of matchingKeys) {
              const parts = queenIterTextRef.current[iterKey];
              const sorted = Object.keys(parts)
                .map(Number)
                .sort((a, b) => a - b);
              const content = sorted.map((k) => parts[k]).join("\n");
              if (content.trim()) {
                const chatMsg: ChatMessage = {
                  id: `queen-stream-${iterKey}-final`,
                  agent: queenName,
                  agentColor: "",
                  content: content,
                  timestamp: "",
                  type: "agent",
                  thread: "queen-dm",
                  createdAt: Date.now(),
                  role: "queen",
                };
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === chatMsg.id);
                  if (idx >= 0) {
                    return prev.map((m, i) => (i === idx ? chatMsg : m));
                  }
                  return [...prev, chatMsg];
                });
              }
              // Clear the ref after flushing
              delete queenIterTextRef.current[iterKey];
            }
          }
          setActiveToolCalls((prev) => ({
            ...prev,
            [event.timestamp || Date.now().toString()]: { name: (event.data?.tool_name as string) || "tool", done: false }
          }));
          break;
        }

        case "tool_call_completed": {
          // Suppress ask_user/ask_user_multiple tool results from appearing in chat
          // They should only show as question modals via client_input_requested
          const toolName = (event.data?.tool_name as string) || "";
          if (toolName === "ask_user" || toolName === "ask_user_multiple") {
            // Don't add to chat - the question modal will handle this
            break;
          }
          // For other tools, show the result
          const result = event.data?.result as string | undefined;
          if (result) {
            try {
              // Try to parse as JSON to see if it's a structured result
              const parsed = JSON.parse(result);
              // If it's a simple success message, show it
              if (parsed.message && typeof parsed.message === "string") {
                const chatMsg: ChatMessage = {
                  id: `tool-result-${event.timestamp || Date.now()}`,
                  agent: queenName,
                  agentColor: "",
                  content: parsed.message,
                  timestamp: "",
                  type: "agent",
                  thread: "queen-dm",
                  createdAt: Date.now(),
                  role: "queen",
                };
                setMessages((prev) => [...prev, chatMsg]);
              }
            } catch {
              // Not JSON, show raw result (truncated)
              const chatMsg: ChatMessage = {
                id: `tool-result-${event.timestamp || Date.now()}`,
                agent: queenName,
                agentColor: "",
                content: result.slice(0, 500),
                timestamp: "",
                type: "agent",
                thread: "queen-dm",
                createdAt: Date.now(),
                role: "queen",
              };
              setMessages((prev) => [...prev, chatMsg]);
            }
          }
          setActiveToolCalls((prev) => {
            const key = Object.keys(prev).find(k => !prev[k].done);
            if (key) {
              return { ...prev, [key]: { ...prev[key], done: true } };
            }
            return prev;
          });
          break;
        }

        case "colony_creation_requested": {
          // Queen in DM mode requested to create a colony for the agent
          const agentPath = event.data?.agent_path as string | undefined;
          const agentName = event.data?.agent_name as string | undefined;
          if (agentPath) {
            // Extract colony ID from agent path (e.g., "founder_twitter_agent" → "founder-twitter-agent")
            const slug = agentPath.replace(/\/$/, "").split("/").pop() || "";
            const colonyId = slug.replace(/_/g, "-");
            
            // Show transition state
            setTransitioningToColony(agentName || colonyId);
            setIsTyping(false);
            
            // Pass the DM session ID so colony can resume from it
            // This preserves conversation history when transitioning to colony
            const dmSessionId = sessionId;
            
            // Delay navigation to let user see the queen's message
            setTimeout(() => {
              navigate(`/colony/${colonyId}`, { 
                state: { queenResumeFrom: dmSessionId } 
              });
            }, 2000);
          }
          break;
        }

        default:
          break;
      }
    },
    [queenName, navigate, sessionId],
  );

  const sseSessions = useMemo((): Record<string, string> => {
    if (sessionId) return { "queen-dm": sessionId };
    return {};
  }, [sessionId]);

  useMultiSSE({ sessions: sseSessions, onEvent: handleSSEEvent });

  // Send handler
  const handleSend = useCallback(
    (text: string, _thread: string, images?: ImageContent[]) => {
      if (awaitingInput) {
        setAwaitingInput(false);
        setPendingQuestion(null);
        setPendingOptions(null);
      }

      const userMsg: ChatMessage = {
        id: makeId(),
        agent: "You",
        agentColor: "",
        content: text,
        timestamp: "",
        type: "user",
        thread: "queen-dm",
        createdAt: Date.now(),
        images,
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsTyping(true);

      if (sessionId) {
        executionApi.chat(sessionId, text, images).catch(() => {
          setIsTyping(false);
          setIsStreaming(false);
        });
      }
    },
    [sessionId, awaitingInput],
  );

  const handleQuestionAnswer = useCallback(
    (answer: string) => {
      setAwaitingInput(false);
      setPendingQuestion(null);
      setPendingOptions(null);
      handleSend(answer, "queen-dm");
    },
    [handleSend],
  );

  const handleMultiQuestionAnswer = useCallback(
    (answers: Record<string, string>) => {
      setAwaitingInput(false);
      setPendingQuestion(null);
      setPendingOptions(null);
      setPendingQuestions(null);
      const formatted = Object.entries(answers)
        .map(([id, val]) => `${id}: ${val}`)
        .join("\n");
      handleSend(formatted, "queen-dm");
    },
    [handleSend],
  );

  const handleCancelQueen = useCallback(async () => {
    if (!sessionId) return;
    try {
      await executionApi.cancelQueen(sessionId);
      setIsTyping(false);
      setIsStreaming(false);
    } catch {
      // ignore
    }
  }, [sessionId]);

  return (
    <div className="flex flex-col h-full">
      {/* Chat */}
      <div className="flex-1 min-h-0 relative">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 backdrop-blur-sm">
            <div className="flex items-center gap-3 text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="text-sm">Connecting to {queenName}...</span>
            </div>
          </div>
        )}

        {transitioningToColony && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/80 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-4 text-foreground">
              <div className="flex items-center gap-3">
                <Hexagon className="w-8 h-8 text-primary animate-pulse" />
                <ArrowRight className="w-5 h-5 text-muted-foreground" />
                <Loader2 className="w-8 h-8 text-primary animate-spin" />
              </div>
              <div className="text-center">
                <p className="text-sm font-medium">
                  Design approved! Moving to colony...
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {transitioningToColony.replace(/_/g, " ")}
                </p>
              </div>
            </div>
          </div>
        )}

        <ChatPanel
          messages={messages}
          onSend={handleSend}
          onCancel={handleCancelQueen}
          activeThread="queen-dm"
          isWaiting={isTyping && !isStreaming}
          isBusy={isTyping}
          disabled={loading || !queenReady || !!transitioningToColony}
          queenPhase={queenPhase}
          pendingQuestion={awaitingInput ? pendingQuestion : null}
          pendingOptions={awaitingInput ? pendingOptions : null}
          pendingQuestions={awaitingInput ? pendingQuestions : null}
          onQuestionSubmit={handleQuestionAnswer}
          onMultiQuestionSubmit={handleMultiQuestionAnswer}
          onQuestionDismiss={() => {
            setAwaitingInput(false);
            setPendingQuestion(null);
            setPendingOptions(null);
          }}
          supportsImages={true}
        />
      </div>
    </div>
  );
}
