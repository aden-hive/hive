import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Loader2, Plus } from "lucide-react";
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
import {
  newReplayState,
  replayEvent,
  replayEventsToMessages,
} from "@/lib/chat-helpers";
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
  const [pendingQuestions, setPendingQuestions] = useState<
    { id: string; prompt: string; options?: string[] }[] | null
  >(null);
  const [awaitingInput, setAwaitingInput] = useState(false);
  const [tokenUsage, setTokenUsage] = useState({ input: 0, output: 0 });
  const [historySessions, setHistorySessions] = useState<HistorySession[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [switchingSessionId, setSwitchingSessionId] = useState<string | null>(
    null,
  );
  const [creatingNewSession, setCreatingNewSession] = useState(false);
  const [initialDraft, setInitialDraft] = useState<string | null>(null);
  const [cloneDialogOpen, setCloneDialogOpen] = useState(false);
  const [cloneColonyName, setCloneColonyName] = useState("");
  const [cloneTask, setCloneTask] = useState("");
  // Colony-spawned lock state. Once a colony has been spawned from this DM
  // and the user clicked into it, /chat is rejected server-side and the
  // composer is replaced with a "compact + new session" button. Hydrated
  // from the session detail and updated optimistically on click.
  const [colonySpawned, setColonySpawned] = useState(false);
  const [spawnedColonyName, setSpawnedColonyName] = useState<string | null>(
    null,
  );
  const [compactingAndForking, setCompactingAndForking] = useState(false);

  const replayStateRef = useRef(newReplayState());
  const [queenPhase, setQueenPhase] = useState<
    "independent" | "incubating" | "working" | "reviewing"
  >("independent");

  const resetViewState = useCallback(() => {
    setSessionId(null);
    setMessages([]);
    setQueenReady(false);
    setIsTyping(false);
    setIsStreaming(false);
    setPendingQuestions(null);
    setAwaitingInput(false);
    setQueenPhase("independent");
    setTokenUsage({ input: 0, output: 0 });
    setInitialDraft(null);
    setColonySpawned(false);
    setSpawnedColonyName(null);
    setCompactingAndForking(false);
    replayStateRef.current = newReplayState();
  }, []);

  const upsertMessage = useCallback(
    (chatMsg: ChatMessage, options?: { reconcileOptimisticUser?: boolean }) => {
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === chatMsg.id);
        if (idx >= 0) {
          return prev.map((m, i) =>
            i === idx ? { ...chatMsg, createdAt: m.createdAt ?? chatMsg.createdAt } : m,
          );
        }
        if (options?.reconcileOptimisticUser && chatMsg.type === "user") {
          const incomingTs = chatMsg.createdAt ?? Date.now();
          const matchIdx = prev.findIndex(
            (m) =>
              m.type === "user" &&
              m.content === chatMsg.content &&
              Math.abs(incomingTs - (m.createdAt ?? incomingTs)) <= 15000,
          );
          if (matchIdx !== -1) {
            return prev.map((m, i) =>
              i === matchIdx ? { ...m, id: chatMsg.id, queued: undefined } : m,
            );
          }
        }

        const ts = chatMsg.createdAt ?? Date.now();
        let insertIdx = prev.length - 1;
        while (insertIdx >= 0 && (prev[insertIdx].createdAt ?? 0) > ts) {
          insertIdx--;
        }
        if (insertIdx === -1 || insertIdx === prev.length - 1) {
          return [...prev, chatMsg];
        }
        const next = [...prev];
        next.splice(insertIdx + 1, 0, chatMsg);
        return next;
      });
    },
    [],
  );

  const restoreMessages = useCallback(
    async (sid: string, cancelled: () => boolean) => {
      try {
        const { events, truncated, total, returned } =
          await sessionsApi.eventsHistory(sid);
        if (cancelled()) return;

        // Use the stateful replay so tool_status pills are synthesized
        // the same way the live SSE handler does — without this the
        // refreshed queen DM shows zero tool activity.
        const replayState = newReplayState();
        const restored = replayEventsToMessages(
          events,
          "queen-dm",
          queenName,
          undefined,
          replayState,
        );
        replayStateRef.current = replayState;

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
        let bootstrapSessionId: string | null = null;
        if (isBootstrap) {
          // Pass the pending message as initial_prompt so the queen
          // processes it immediately (no phantom "Hello" greeting).
          const bootstrapResult = await queensApi.createNewSession(
            queenId,
            pendingFirstMessage ?? undefined,
            "independent",
          );
          bootstrapSessionId = bootstrapResult.session_id;
        } else if (selectedSessionParam) {
          await queensApi.selectSession(queenId, selectedSessionParam);
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
          // Bootstrap uses the session id from createNewSession directly so a
          // stale live session for this queen can't steal the flow. Otherwise
          // fall back to get-or-create.
          if (bootstrapSessionId) {
            sid = bootstrapSessionId;
          } else {
            const result = await queensApi.getOrCreateSession(
              queenId,
              undefined,
              "independent",
            );
            if (cancelled) return;
            sid = result.session_id;
          }
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

  // Hydrate the colony-spawned lock + queen phase from the session detail
  // whenever the session ID changes. /sessions/{id} carries both flags
  // (and the cold-info path returns colony_spawned after a server restart),
  // so this single fetch covers live, page-reload, and post-restart states.
  // Without seeding queen_phase here the badge starts at the useState
  // default ("independent") and only updates when a fresh
  // QUEEN_PHASE_CHANGED SSE event fires — a reload mid-incubation would
  // briefly mis-render.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    sessionsApi
      .get(sessionId)
      .then((data) => {
        if (cancelled) return;
        const detail = data as {
          colony_spawned?: boolean;
          spawned_colony_name?: string | null;
          queen_phase?: "independent" | "incubating" | "working" | "reviewing";
        };
        setColonySpawned(Boolean(detail.colony_spawned));
        setSpawnedColonyName(detail.spawned_colony_name ?? null);
        if (
          detail.queen_phase === "independent" ||
          detail.queen_phase === "incubating" ||
          detail.queen_phase === "working" ||
          detail.queen_phase === "reviewing"
        ) {
          setQueenPhase(detail.queen_phase);
        }
      })
      .catch(() => {
        // Non-fatal — lock + phase simply won't activate until a fresh
        // SSE event arrives.
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const handleColonyLinkClick = useCallback(
    (colonyName: string) => {
      if (!sessionId || !colonyName) return;
      // Optimistically lock so the textarea swaps to the button before the
      // user navigates back. Backend persists the same flag in meta.json so
      // a refresh would re-hydrate the locked state anyway.
      setColonySpawned(true);
      setSpawnedColonyName(colonyName);
      executionApi.markColonySpawned(sessionId, colonyName).catch(() => {
        // Revert on failure so the user isn't stranded with no composer.
        setColonySpawned(false);
        setSpawnedColonyName(null);
      });
    },
    [sessionId],
  );

  const handleCompactAndFork = useCallback(async () => {
    if (!sessionId || compactingAndForking || !queenId) return;
    setCompactingAndForking(true);
    try {
      const result = await executionApi.compactAndFork(sessionId);
      // Navigate to the freshly-forked session for the same queen. Replacing
      // the URL keeps the back button on the home/history page rather than
      // bouncing back to the now-locked DM.
      setSearchParams({ session: result.new_session_id }, { replace: true });
    } catch {
      setCompactingAndForking(false);
    }
  }, [sessionId, compactingAndForking, queenId, setSearchParams]);

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
      const emittedMessages = replayEvent(
        replayStateRef.current,
        event,
        "queen-dm",
        queenName,
      );

      switch (event.type) {
        case "execution_started":
          setIsTyping(true);
          setQueenReady(true);
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
          if (event.data) {
            const inp = (event.data.input_tokens as number) || 0;
            const out = (event.data.output_tokens as number) || 0;
            setTokenUsage((prev) => ({ input: prev.input + inp, output: prev.output + out }));
          }
          break;

        case "client_output_delta":
        case "llm_text_delta": {
          for (const msg of emittedMessages) upsertMessage(msg);
          setIsStreaming(true);
          break;
        }

        case "client_input_requested": {
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
          setPendingQuestions(questions);
          break;
        }

        case "client_input_received": {
          for (const msg of emittedMessages) {
            upsertMessage(msg, { reconcileOptimisticUser: true });
          }
          break;
        }

        case "queen_phase_changed": {
          const rawPhase = event.data?.phase as string;
          if (
            rawPhase === "independent" ||
            rawPhase === "incubating" ||
            rawPhase === "working" ||
            rawPhase === "reviewing"
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
          for (const msg of emittedMessages) upsertMessage(msg);
          break;
        }

        case "tool_call_completed": {
          for (const msg of emittedMessages) upsertMessage(msg);
          break;
        }

        default:
          break;
      }
    },
    [queenName, refresh, upsertMessage],
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
        setPendingQuestions(null);
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

  const handleColonySpawn = useCallback(() => {
    const colony = cloneColonyName.trim();
    if (!colony) return;
    const task = cloneTask.trim();
    const message = task
      ? `Create a colony named \`${colony}\` for the following task:\n\n${task}`
      : `Create a colony named \`${colony}\` from this session.`;
    handleSend(message, "queen-dm");
    setCloneDialogOpen(false);
    setCloneColonyName("");
    setCloneTask("");
  }, [cloneColonyName, cloneTask, handleSend]);

  const handleQuestionAnswer = useCallback(
    (answers: Record<string, string>) => {
      setAwaitingInput(false);
      setPendingQuestions(null);
      // For a single question, send just the answer text. For a batch,
      // send "id: answer" lines so the agent can map replies back.
      const entries = Object.entries(answers);
      const formatted =
        entries.length === 1
          ? entries[0][1]
          : entries.map(([id, val]) => `${id}: ${val}`).join("\n");
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
      replayStateRef.current = newReplayState();
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
          showQueenPhaseBadge
          pendingQuestions={awaitingInput ? pendingQuestions : null}
          onQuestionSubmit={handleQuestionAnswer}
          onQuestionDismiss={() => {
            setAwaitingInput(false);
            setPendingQuestions(null);
          }}
          supportsImages={true}
          initialDraft={initialDraft}
          queenProfileId={queenId ?? null}
          queenId={queenId}
          onColonyLinkClick={handleColonyLinkClick}
          colonySpawned={colonySpawned}
          spawnedColonyName={spawnedColonyName}
          queenDisplayName={queenName}
          onCompactAndFork={handleCompactAndFork}
          compactingAndForking={compactingAndForking}
          onStartNewSession={handleCreateNewSession}
          startingNewSession={creatingNewSession}
          tokenUsage={tokenUsage}
          headerAction={
            <button
              onClick={() => setCloneDialogOpen(true)}
              disabled={!sessionId}
              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium text-primary hover:bg-primary/10 transition-colors disabled:opacity-40"
            >
              <Plus className="w-3 h-3" />
              Create a Colony
            </button>
          }
        />
      </div>

      {cloneDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setCloneDialogOpen(false)}
          />
          <div className="relative bg-card border border-border/60 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-sm font-semibold text-foreground">
              Create a Colony
            </h2>
            <p className="text-[11px] text-muted-foreground">
              Create a new colony from this queen's session. The colony inherits
              the queen's tools, context, and conversation history.
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
                className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleColonySpawn}
                disabled={!cloneColonyName.trim()}
                className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
