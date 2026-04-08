import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import ChatPanel, { type ChatMessage, type ImageContent } from "@/components/ChatPanel";
import { executionApi } from "@/api/execution";
import { sessionsApi } from "@/api/sessions";
import { useMultiSSE } from "@/hooks/use-sse";
import type { LiveSession, AgentEvent } from "@/api/types";
import { sseEventToChatMessage } from "@/lib/chat-helpers";
import { useColony } from "@/context/ColonyContext";
import { getQueenForAgent } from "@/lib/colony-registry";

const makeId = () => Math.random().toString(36).slice(2, 9);

export default function QueenDM() {
  const { queenId } = useParams<{ queenId: string }>();
  const { queens } = useColony();
  const queen = queens.find((q) => q.id === queenId);
  const queenInfo = getQueenForAgent(queenId || "");
  const queenName = queen?.name || queenInfo.name;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [queenReady, setQueenReady] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [pendingOptions, setPendingOptions] = useState<string[] | null>(null);
  const [awaitingInput, setAwaitingInput] = useState(false);

  const turnCounterRef = useRef(0);
  const queenIterTextRef = useRef<Record<string, Record<number, string>>>({});
  const loadingRef = useRef(false);

  // Create queen-only session
  useEffect(() => {
    if (!queenId || loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    setMessages([]);
    setSessionId(null);
    setQueenReady(false);

    (async () => {
      try {
        // Check for existing queen-only sessions
        const { sessions: allLive } = await sessionsApi.list();
        let session: LiveSession | undefined = allLive.find(
          (s) => !s.has_worker && !s.agent_path,
        );

        if (!session) {
          session = await sessionsApi.create(undefined, undefined, undefined, undefined, undefined);
        }

        setSessionId(session.session_id);
        setLoading(false);
        setQueenReady(true);

        // Restore messages
        try {
          const { events } = await sessionsApi.eventsHistory(session.session_id);
          const restored: ChatMessage[] = [];
          for (const evt of events) {
            const msg = sseEventToChatMessage(evt, "queen-dm", queenName);
            if (!msg) continue;
            if (evt.stream_id === "queen") msg.role = "queen";
            restored.push(msg);
          }
          if (restored.length > 0) {
            restored.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
            setMessages(restored);
          }
        } catch {
          // No history
        }
      } catch (err) {
        setLoading(false);
      } finally {
        loadingRef.current = false;
      }
    })();
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
          break;

        case "execution_completed":
          setIsTyping(false);
          setIsStreaming(false);
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
          setAwaitingInput(true);
          setIsTyping(false);
          setIsStreaming(false);
          setPendingQuestion(prompt || null);
          setPendingOptions(options);
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

        default:
          break;
      }
    },
    [queenName],
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

        <ChatPanel
          messages={messages}
          onSend={handleSend}
          onCancel={handleCancelQueen}
          activeThread="queen-dm"
          isWaiting={isTyping && !isStreaming}
          isBusy={isTyping}
          disabled={loading || !queenReady}
          queenPhase="planning"
          pendingQuestion={awaitingInput ? pendingQuestion : null}
          pendingOptions={awaitingInput ? pendingOptions : null}
          onQuestionSubmit={handleQuestionAnswer}
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
