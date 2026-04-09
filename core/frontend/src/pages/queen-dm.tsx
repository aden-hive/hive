import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import ChatPanel, { type ChatMessage, type ImageContent } from "@/components/ChatPanel";
import QueenSessionSwitcher from "@/components/QueenSessionSwitcher";
import { executionApi } from "@/api/execution";
import { sessionsApi } from "@/api/sessions";
import { queensApi } from "@/api/queens";
import { useMultiSSE } from "@/hooks/use-sse";
import type { AgentEvent, HistorySession } from "@/api/types";
import { sseEventToChatMessage } from "@/lib/chat-helpers";
import { useColony } from "@/context/ColonyContext";
import { useHeaderActions } from "@/context/HeaderActionsContext";
import { getQueenForAgent } from "@/lib/colony-registry";

const makeId = () => Math.random().toString(36).slice(2, 9);

export default function QueenDM() {
  const { queenId } = useParams<{ queenId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { queens, queenProfiles, refresh } = useColony();
  const { setActions } = useHeaderActions();
  const profileQueen = queenProfiles.find((q) => q.id === queenId);
  const colonyQueen = queens.find((q) => q.id === queenId);
  const queenInfo = getQueenForAgent(queenId || "");
  const queenName = profileQueen?.name ?? colonyQueen?.name ?? queenInfo.name;
  const selectedSessionParam = searchParams.get("session");

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
  const [, setActiveToolCalls] = useState<Record<string, { name: string; done: boolean }>>({});
  const [historySessions, setHistorySessions] = useState<HistorySession[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [switchingSessionId, setSwitchingSessionId] = useState<string | null>(null);
  const [creatingNewSession, setCreatingNewSession] = useState(false);

  const turnCounterRef = useRef(0);
  const queenIterTextRef = useRef<Record<string, Record<number, string>>>({});
  const [queenPhase, setQueenPhase] = useState<"planning" | "building" | "staging" | "running" | "independent">("independent");

  const resetViewState = useCallback(() => {
    setSessionId(null);
    setMessages([]);
    setQueenReady(false);
    setIsTyping(false);
    setIsStreaming(false);
    setPendingQuestion(null);
    setPendingOptions(null);
    setPendingQuestions(null);
    setAwaitingInput(false);
    setActiveToolCalls({});
    setQueenPhase("independent");
    turnCounterRef.current = 0;
    queenIterTextRef.current = {};
  }, []);

  const restoreMessages = useCallback(
    async (sid: string, cancelled: () => boolean) => {
      try {
        const { events } = await sessionsApi.eventsHistory(sid);
        if (cancelled()) return;
        const restored: ChatMessage[] = [];
        for (const evt of events) {
          const msg = sseEventToChatMessage(evt, "queen-dm", queenName);
          if (!msg) continue;
          if (evt.stream_id === "queen") msg.role = "queen";
          restored.push(msg);
        }
        if (restored.length > 0 && !cancelled()) {
          restored.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
          setMessages(restored);
          setIsTyping(false);
        }
      } catch {
        // No history
      }
    },
    [queenName],
  );

  useEffect(() => {
    if (!queenId) return;

    resetViewState();
    setLoading(true);

    let cancelled = false;

    (async () => {
      try {
        const result = selectedSessionParam
          ? await queensApi.selectSession(queenId, selectedSessionParam)
          : await queensApi.getOrCreateSession(queenId, undefined, "independent");
        if (cancelled) return;

        const sid = result.session_id;
        setSessionId(sid);
        setQueenReady(true);
        // Show typing indicator while the queen initializes (identity hook + first turn)
        setIsTyping(true);

        if (selectedSessionParam && selectedSessionParam !== sid) {
          setSearchParams({ session: sid }, { replace: true });
        }
        await restoreMessages(sid, () => cancelled);
        refresh();
      } catch {
        // Session creation failed
      } finally {
        if (!cancelled) {
          setLoading(false);
          setSwitchingSessionId(null);
          setCreatingNewSession(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [queenId, selectedSessionParam, restoreMessages, refresh, resetViewState, setSearchParams]);

  useEffect(() => {
    if (!queenId) return;
    let cancelled = false;
    setHistoryLoading(true);

    sessionsApi
      .history()
      .then(({ sessions }) => {
        if (cancelled) return;
        const filtered = sessions
          .filter((session) => session.queen_id === queenId)
          .sort((a, b) => b.created_at - a.created_at);
        setHistorySessions(filtered);
      })
      .catch(() => {
        if (!cancelled) setHistorySessions([]);
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [queenId, sessionId]);

  const handleSelectHistoricalSession = useCallback(
    (nextSessionId: string) => {
      if (!nextSessionId || nextSessionId === sessionId) return;
      setSwitchingSessionId(nextSessionId);
      setSearchParams({ session: nextSessionId });
    },
    [sessionId, setSearchParams],
  );

  const handleCreateNewSession = useCallback(() => {
    if (!queenId) return;
    setCreatingNewSession(true);
    const request = queensApi.createNewSession(queenId, undefined, "independent");
    request
      .then((result) => {
        setSearchParams({ session: result.session_id });
      })
      .catch(() => {
        setCreatingNewSession(false);
      });
  }, [queenId, setSearchParams]);

  useEffect(() => {
    if (!queenId) return;
    setActions(
      <QueenSessionSwitcher
        sessions={historySessions}
        currentSessionId={sessionId}
        loading={historyLoading}
        switchingSessionId={switchingSessionId}
        creatingNew={creatingNewSession}
        onSelect={handleSelectHistoricalSession}
        onCreateNew={handleCreateNewSession}
      />
    );
    return () => setActions(null);
  }, [
    creatingNewSession,
    handleCreateNewSession,
    handleSelectHistoricalSession,
    historyLoading,
    historySessions,
    queenId,
    sessionId,
    setActions,
    switchingSessionId,
  ]);

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

        case "execution_completed":
          setIsTyping(false);
          setIsStreaming(false);
          break;

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
          const toolName = (event.data?.tool_name as string) || "unknown";
          const toolUseId = (event.data?.tool_use_id as string) || "";
          const sid = event.stream_id;
          const execId = event.execution_id || "exec";

          setActiveToolCalls((prev) => {
            const newActive = { ...prev, [toolUseId]: { name: toolName, done: false } };
            const tools = Object.entries(newActive).map(([, t]) => ({ name: t.name, done: t.done }));
            const allDone = tools.length > 0 && tools.every((t) => t.done);
            const msgId = `tool-pill-${sid}-${execId}-${turnCounterRef.current}`;
            const toolMsg: ChatMessage = {
              id: msgId,
              agent: queenName,
              agentColor: "",
              content: JSON.stringify({ tools, allDone }),
              timestamp: "",
              type: "tool_status",
              role: "queen",
              thread: "queen-dm",
              createdAt: Date.now(),
              nodeId: event.node_id || undefined,
              executionId: event.execution_id || undefined,
            };
            setMessages((prevMsgs) => {
              const idx = prevMsgs.findIndex((m) => m.id === msgId);
              if (idx >= 0) {
                return prevMsgs.map((m, i) => (i === idx ? toolMsg : m));
              }
              return [...prevMsgs, toolMsg];
            });
            return newActive;
          });
          break;
        }

        case "tool_call_completed": {
          const toolUseId = (event.data?.tool_use_id as string) || "";
          const sid = event.stream_id;
          const execId = event.execution_id || "exec";

          setActiveToolCalls((prev) => {
            const updated = { ...prev };
            if (updated[toolUseId]) {
              updated[toolUseId] = { ...updated[toolUseId], done: true };
            }
            const tools = Object.entries(updated).map(([, t]) => ({ name: t.name, done: t.done }));
            const allDone = tools.length > 0 && tools.every((t) => t.done);
            const msgId = `tool-pill-${sid}-${execId}-${turnCounterRef.current}`;
            const toolMsg: ChatMessage = {
              id: msgId,
              agent: queenName,
              agentColor: "",
              content: JSON.stringify({ tools, allDone }),
              timestamp: "",
              type: "tool_status",
              role: "queen",
              thread: "queen-dm",
              createdAt: Date.now(),
              nodeId: event.node_id || undefined,
              executionId: event.execution_id || undefined,
            };
            setMessages((prevMsgs) => {
              const idx = prevMsgs.findIndex((m) => m.id === msgId);
              if (idx >= 0) {
                return prevMsgs.map((m, i) => (i === idx ? toolMsg : m));
              }
              return [...prevMsgs, toolMsg];
            });
            return updated;
          });
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

        <ChatPanel
          messages={messages}
          onSend={handleSend}
          onCancel={handleCancelQueen}
          activeThread="queen-dm"
          isWaiting={isTyping && !isStreaming}
          isBusy={isTyping}
          disabled={loading || !queenReady}
          queenPhase={queenPhase}
          showQueenPhaseBadge={false}
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
