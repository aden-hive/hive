import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Loader2, Users } from "lucide-react";
import ChatPanel, {
  type ChatMessage,
  type ImageContent,
} from "@/components/ChatPanel";
import QueenSessionSwitcher from "@/components/QueenSessionSwitcher";
import { executionApi } from "@/api/execution";
import { sessionsApi } from "@/api/sessions";
import { queensApi } from "@/api/queens";
import { useMultiSSE } from "@/hooks/use-sse";
import type { AgentEvent, HistorySession } from "@/api/types";
import { sseEventToChatMessage } from "@/lib/chat-helpers";
import { useColony } from "@/context/ColonyContext";
import { useHeaderActions } from "@/context/HeaderActionsContext";
import { getQueenForAgent, slugToColonyId } from "@/lib/colony-registry";

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
  const newSessionFlag = searchParams.get("new");

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
  const [, setActiveToolCalls] = useState<
    Record<string, { name: string; done: boolean }>
  >({});
  const [historySessions, setHistorySessions] = useState<HistorySession[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [switchingSessionId, setSwitchingSessionId] = useState<string | null>(
    null,
  );
  const [creatingNewSession, setCreatingNewSession] = useState(false);
  const [spawning, setSpawning] = useState(false);
  const [initialDraft, setInitialDraft] = useState<string | null>(null);
  const [cloneDialogOpen, setCloneDialogOpen] = useState(false);
  const [cloneColonyName, setCloneColonyName] = useState("");
  const [cloneTask, setCloneTask] = useState("");

  const turnCounterRef = useRef(0);
  // Maps tool_use_id → the pill message ID and tool name that was created for it.
  // Survives turn counter resets so deferred completions (e.g. ask_user) can
  // find and update the correct pill even after llm_turn_complete bumps the counter.
  const toolUseToPillRef = useRef<
    Record<string, { msgId: string; name: string }>
  >({});
  const queenIterTextRef = useRef<Record<string, Record<number, string>>>({});
  const [queenPhase, setQueenPhase] = useState<
    "planning" | "building" | "staging" | "running" | "independent"
  >("independent");

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
    setInitialDraft(null);
    turnCounterRef.current = 0;
    toolUseToPillRef.current = {};
    queenIterTextRef.current = {};
  }, []);

  const restoreMessages = useCallback(
    async (sid: string, cancelled: () => boolean) => {
      try {
        const { events, truncated, total, returned } =
          await sessionsApi.eventsHistory(sid);
        if (cancelled()) return;
        const restored: ChatMessage[] = [];
        for (const evt of events) {
          const msg = sseEventToChatMessage(evt, "queen-dm", queenName);
          if (!msg) continue;
          if (evt.stream_id === "queen") msg.role = "queen";
          restored.push(msg);
        }
        // Show a banner if the server truncated older events.
        const droppedCount = Math.max(0, total - returned);
        if (truncated && droppedCount > 0) {
          const firstTs = events[0]?.timestamp;
          const bannerCreatedAt = firstTs
            ? new Date(firstTs).getTime() - 1
            : 0;
          restored.unshift({
            id: `restore-truncated-${sid}`,
            agent: "System",
            agentColor: "",
            type: "run_divider",
            content: `${droppedCount.toLocaleString()} older event${droppedCount === 1 ? "" : "s"} not shown (showing last ${returned.toLocaleString()})`,
            timestamp: firstTs ?? new Date().toISOString(),
            thread: "queen-dm",
            createdAt: bannerCreatedAt,
          });
        }
        if (restored.length > 0 && !cancelled()) {
          restored.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
          setMessages(restored);
          // Only clear typing if the history contains a completed execution;
          // during bootstrap the queen is still processing.
          const hasCompleted = events.some(
            (e: AgentEvent) => e.type === "execution_completed",
          );
          if (hasCompleted) {
            setIsTyping(false);
          }
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
    const isBootstrap = newSessionFlag === "1";
    // Consume the pending first message up-front so this bootstrap is one-shot:
    // a re-run after URL rewrite or a browser refresh won't re-fill the composer.
    const pendingFirstMessage = isBootstrap
      ? sessionStorage.getItem(`queenFirstMessage:${queenId}`)
      : null;
    if (isBootstrap && pendingFirstMessage !== null) {
      sessionStorage.removeItem(`queenFirstMessage:${queenId}`);
    }

    (async () => {
      try {
        if (isBootstrap) {
          // Pass the pending message as initial_prompt so the queen
          // processes it immediately (no phantom "Hello" greeting).
          await queensApi.createNewSession(
            queenId,
            pendingFirstMessage ?? undefined,
            "independent",
          );
        } else if (selectedSessionParam) {
          await queensApi.selectSession(queenId, selectedSessionParam);
        } else {
          await queensApi.getOrCreateSession(queenId, undefined, "independent");
        }
        if (cancelled) return;
        let sid: string;

        // Fast path: if we have a session_id in URL from home screen (just created),
        // use it directly without an extra API call. The session is already live.
        // This eliminates the 10-13s delay from the unnecessary selectSession API call.
        if (
          selectedSessionParam &&
          selectedSessionParam.startsWith("session_")
        ) {
          sid = selectedSessionParam;
          setSessionId(sid);
          setQueenReady(true);
          setIsTyping(true);
          setLoading(false); // Hide loading immediately - SSE will connect now
          // Don't await restoreMessages - let it happen in background
          restoreMessages(sid, () => cancelled).then(() => refresh());
          return;
        }

        if (selectedSessionParam) {
          // Resume historical session - need to verify ownership via API
          const result = await queensApi.selectSession(
            queenId,
            selectedSessionParam,
          );
          if (cancelled) return;
          sid = result.session_id;
          setSessionId(sid);
          setQueenReady(true);
          setIsTyping(true);

          if (selectedSessionParam !== sid) {
            setSearchParams({ session: sid }, { replace: true });
          }
        } else {
          // No session specified - get or create one
          const result = await queensApi.getOrCreateSession(
            queenId,
            undefined,
            "independent",
          );
          if (cancelled) return;
          sid = result.session_id;
          setSessionId(sid);
          setQueenReady(true);

          if (isBootstrap) {
            // Swap ?new=1 for ?session={sid} so a browser refresh rehydrates
            // this session instead of creating another new one.
            setSearchParams({ session: sid }, { replace: true });

            // Message was passed as initial_prompt so the queen is already
            // processing it. Show the user bubble and typing indicator.
            if (pendingFirstMessage && !cancelled) {
              const userMsg: ChatMessage = {
                id: makeId(),
                agent: "You",
                agentColor: "",
                content: pendingFirstMessage,
                timestamp: "",
                type: "user",
                thread: "queen-dm",
                createdAt: Date.now(),
              };
              setMessages((prev) => [...prev, userMsg]);
              setIsTyping(true);
            }
          } else {
            setIsTyping(true);
          }

          if (!isBootstrap && selectedSessionParam && selectedSessionParam !== sid) {
            setSearchParams({ session: sid }, { replace: true });
          }
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
  }, [
    queenId,
    selectedSessionParam,
    newSessionFlag,
    restoreMessages,
    refresh,
    resetViewState,
    setSearchParams,
  ]);

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

  const handleColonySpawn = useCallback(async () => {
    if (!sessionId || spawning) return;
    const colony = cloneColonyName.trim();
    if (!colony) return;
    setSpawning(true);
    try {
      const result = await executionApi.colonySpawn(
        sessionId,
        colony,
        cloneTask.trim() || undefined,
      );
      const msg: ChatMessage = {
        id: makeId(),
        agent: "System",
        agentColor: "",
        content: `Forked to colony "${result.colony_name}"${result.is_new ? " (new)" : ""} — session ${result.queen_session_id}`,
        timestamp: "",
        type: "system",
        thread: "queen-dm",
        createdAt: Date.now(),
      };
      setMessages((prev) => [...prev, msg]);
      setCloneDialogOpen(false);
      setCloneColonyName("");
      setCloneTask("");
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      const msg: ChatMessage = {
        id: makeId(),
        agent: "System",
        agentColor: "",
        content: `Clone failed: ${errMsg}`,
        timestamp: "",
        type: "system",
        thread: "queen-dm",
        createdAt: Date.now(),
      };
      setMessages((prev) => [...prev, msg]);
    } finally {
      setSpawning(false);
    }
  }, [sessionId, spawning, cloneColonyName, cloneTask]);

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
    const request = queensApi.createNewSession(
      queenId,
      undefined,
      "independent",
    );
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
      <>
        <button
          onClick={() => setCloneDialogOpen(true)}
          disabled={!sessionId}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0 disabled:opacity-50"
          title="Clone queen to a colony"
        >
          <Users className="w-3.5 h-3.5" />
          Clone Colony
        </button>
        <QueenSessionSwitcher
          sessions={historySessions}
          currentSessionId={sessionId}
          loading={historyLoading}
          switchingSessionId={switchingSessionId}
          creatingNew={creatingNewSession}
          onSelect={handleSelectHistoricalSession}
          onCreateNew={handleCreateNewSession}
        />
      </>,
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
          toolUseToPillRef.current = {};
          // Clear queued flag on all user messages now that the queen is processing
          setMessages((prev) => {
            if (!prev.some((m) => m.queued)) return prev;
            return prev.map((m) => (m.queued ? { ...m, queued: undefined } : m));
          });
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
          const chatMsg = sseEventToChatMessage(
            event,
            "queen-dm",
            queenName,
            turnCounterRef.current,
          );
          if (chatMsg) {
            if (event.execution_id) {
              const iter = event.data?.iteration ?? 0;
              const inner = (event.data?.inner_turn as number) ?? 0;
              const iterKey = `${event.execution_id}:${iter}`;
              if (!queenIterTextRef.current[iterKey]) {
                queenIterTextRef.current[iterKey] = {};
              }
              const snapshot =
                (event.data?.snapshot as string) ||
                (event.data?.content as string) ||
                "";
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
          const options = Array.isArray(rawOptions)
            ? (rawOptions as string[])
            : null;
          const rawQuestions = event.data?.questions;
          const questions = Array.isArray(rawQuestions)
            ? (rawQuestions as {
                id: string;
                prompt: string;
                options?: string[];
              }[])
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
          const chatMsg = sseEventToChatMessage(
            event,
            "queen-dm",
            queenName,
            turnCounterRef.current,
          );
          if (chatMsg) {
            setMessages((prev) => {
              // Reconcile optimistic user message
              if (chatMsg.type === "user" && prev.length > 0) {
                const last = prev[prev.length - 1];
                if (
                  last.type === "user" &&
                  last.content === chatMsg.content &&
                  Math.abs((chatMsg.createdAt ?? 0) - (last.createdAt ?? 0)) <=
                    15000
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
          if (
            rawPhase === "independent" ||
            rawPhase === "planning" ||
            rawPhase === "building" ||
            rawPhase === "staging" ||
            rawPhase === "running"
          ) {
            setQueenPhase(rawPhase);
          }
          break;
        }

        case "colony_created": {
          // Queen called create_colony() — surface a clickable system
          // message linking to /colony/{colony_name} so the user can
          // navigate to the new colony immediately.
          const colonyName = (event.data?.colony_name as string) || "";
          const isNew = (event.data?.is_new as boolean) ?? true;
          const skillName = (event.data?.skill_name as string) || "";
          if (!colonyName) break;
          // ColonyContext keys colonies by slugToColonyId(slug), not by the
          // raw snake_case directory name. Apply the same transform so the
          // /colony/:colonyId route lookup in colony-chat.tsx resolves.
          const routeId = slugToColonyId(colonyName);
          const msg: ChatMessage = {
            id: makeId(),
            agent: "System",
            agentColor: "",
            content: JSON.stringify({
              kind: "colony_created",
              colony_name: colonyName,
              is_new: isNew,
              skill_name: skillName,
              href: `/colony/${routeId}`,
            }),
            timestamp: "",
            type: "colony_link",
            thread: "queen-dm",
            createdAt: Date.now(),
          };
          setMessages((prev) => [...prev, msg]);
          // Refresh the sidebar's colony list so the new colony shows up
          // under "Colonies" immediately (without requiring a page
          // reload or the 30s status poll).
          refresh();
          break;
        }

        case "tool_call_started": {
          const toolName = (event.data?.tool_name as string) || "unknown";
          const toolUseId = (event.data?.tool_use_id as string) || "";
          const sid = event.stream_id;
          const execId = event.execution_id || "exec";
          const eventCreatedAt = event.timestamp
            ? new Date(event.timestamp).getTime()
            : Date.now();

          // Track which pill message this tool belongs to so deferred
          // completions (ask_user) can find it after the turn counter changes.
          const msgId = `tool-pill-${sid}-${execId}-${turnCounterRef.current}`;
          toolUseToPillRef.current[toolUseId] = { msgId, name: toolName };

          setActiveToolCalls((prev) => {
            const newActive = {
              ...prev,
              [toolUseId]: { name: toolName, done: false },
            };
            const tools = Object.entries(newActive).map(([, t]) => ({
              name: t.name,
              done: t.done,
            }));
            const allDone = tools.length > 0 && tools.every((t) => t.done);
            const toolMsg: ChatMessage = {
              id: msgId,
              agent: queenName,
              agentColor: "",
              content: JSON.stringify({ tools, allDone }),
              timestamp: "",
              type: "tool_status",
              role: "queen",
              thread: "queen-dm",
              createdAt: eventCreatedAt,
              nodeId: event.node_id || undefined,
              executionId: event.execution_id || undefined,
            };
            setMessages((prevMsgs) => {
              const idx = prevMsgs.findIndex((m) => m.id === msgId);
              if (idx >= 0) {
                return prevMsgs.map((m, i) =>
                  i === idx ? { ...toolMsg, createdAt: m.createdAt ?? toolMsg.createdAt } : m,
                );
              }
              // Insert in sorted position by createdAt
              const ts = toolMsg.createdAt ?? Date.now();
              let insertIdx = prevMsgs.length - 1;
              while (insertIdx >= 0 && (prevMsgs[insertIdx].createdAt ?? 0) > ts) {
                insertIdx--;
              }
              if (insertIdx === -1 || insertIdx === prevMsgs.length - 1) {
                return [...prevMsgs, toolMsg];
              }
              const next = [...prevMsgs];
              next.splice(insertIdx + 1, 0, toolMsg);
              return next;
            });
            return newActive;
          });
          break;
        }

        case "tool_call_completed": {
          const toolUseId = (event.data?.tool_use_id as string) || "";

          // Look up the original pill message this tool belongs to.
          // For deferred completions (ask_user), the turn counter and
          // activeToolCalls have already been reset by llm_turn_complete,
          // so we rely on the ref recorded during tool_call_started.
          const tracked = toolUseToPillRef.current[toolUseId];
          delete toolUseToPillRef.current[toolUseId];

          // Mark done in activeToolCalls if still present (normal case)
          setActiveToolCalls((prev) => {
            if (!prev[toolUseId]) return prev;
            return {
              ...prev,
              [toolUseId]: { ...prev[toolUseId], done: true },
            };
          });

          // Determine the correct pill message ID
          const sid = event.stream_id;
          const execId = event.execution_id || "exec";
          const pillMsgId =
            tracked?.msgId ??
            `tool-pill-${sid}-${execId}-${turnCounterRef.current}`;
          const toolName = tracked?.name;

          // Update the pill message content directly
          setMessages((prevMsgs) => {
            const idx = prevMsgs.findIndex((m) => m.id === pillMsgId);
            if (idx < 0) return prevMsgs;

            try {
              const parsed = JSON.parse(prevMsgs[idx].content);
              const tools: { name: string; done: boolean }[] =
                parsed.tools || [];

              if (toolName) {
                let marked = false;
                for (let i = 0; i < tools.length; i++) {
                  if (
                    tools[i].name === toolName &&
                    !tools[i].done &&
                    !marked
                  ) {
                    tools[i] = { ...tools[i], done: true };
                    marked = true;
                  }
                }
              }

              const allDone =
                tools.length > 0 && tools.every((t) => t.done);
              return prevMsgs.map((m, i) =>
                i === idx
                  ? {
                      ...m,
                      content: JSON.stringify({ tools, allDone }),
                    }
                  : m,
              );
            } catch {
              return prevMsgs;
            }
          });
          break;
        }

        default:
          break;
      }
    },
    [queenName, refresh],
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

      const isQueenBusy = isTyping;
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
        queued: isQueenBusy || undefined,
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
    [sessionId, awaitingInput, isTyping],
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
      setActiveToolCalls({});
      toolUseToPillRef.current = {};
      // Clear queued flags since the queen is now idle
      setMessages((prev) => {
        if (!prev.some((m) => m.queued)) return prev;
        return prev.map((m) => (m.queued ? { ...m, queued: undefined } : m));
      });
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
              <span className="text-sm">
                {selectedSessionParam?.startsWith("session_")
                  ? "Connecting to session..."
                  : `Connecting to ${queenName}...`}
              </span>
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
          initialDraft={initialDraft}
        />
      </div>

      {cloneDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => !spawning && setCloneDialogOpen(false)}
          />
          <div className="relative bg-card border border-border/60 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-sm font-semibold text-foreground">
              Fork to Colony
            </h2>
            <p className="text-[11px] text-muted-foreground">
              Forks the queen's full session into a new colony. Multiple
              sessions can run against it in parallel.
            </p>
            <div className="space-y-3">
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                  Colony name
                </label>
                <input
                  type="text"
                  value={cloneColonyName}
                  onChange={(e) =>
                    setCloneColonyName(
                      e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""),
                    )
                  }
                  placeholder="e.g. research_team"
                  className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                  Task{" "}
                  <span className="text-muted-foreground/40">(optional)</span>
                </label>
                <input
                  type="text"
                  value={cloneTask}
                  onChange={(e) => setCloneTask(e.target.value)}
                  placeholder="Continue the work from the queen's session"
                  className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => {
                  setCloneDialogOpen(false);
                  setCloneColonyName("");
                  setCloneTask("");
                }}
                disabled={spawning}
                className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleColonySpawn}
                disabled={spawning || !cloneColonyName.trim()}
                className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {spawning ? "Forking..." : "Fork"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
