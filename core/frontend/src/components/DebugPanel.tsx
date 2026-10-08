import { useEffect, useRef, useState } from "react";
import { useDebugState } from "@/components/DebugStateContext";
import { useLiveSessions } from "@/hooks/use-live-sessions";
import { deriveColonyStatus, STATUS_LABEL } from "@/lib/colony-status";
import { useGlobalEvents } from "@/hooks/use-sse";
import { api, ApiError } from "@/api/client";
import { credentialsApi, type OAuthStatusResponse } from "@/api/credentials";
import type { AgentEvent } from "@/api/types";

type Section =
  | "conn" | "queen" | "tools" | "oauth" | "snapshot" | "liveness" | "replay" | "reminders" | "events" | "global";

type LiveToolEntry = { name: string; description: string; kind: "mcp" | "lifecycle" | "synthetic" };
type ToolStatus = "callable" | "searchable" | "unregistered";
type ExpectedToolEntry = LiveToolEntry & { status: ToolStatus };
type LiveToolsResponse = {
  session_id: string;
  phase: string | null;
  phase_state_ready?: boolean;
  // `tools` is a back-compat alias of `actual_tools` (older runtimes only send it).
  tools: LiveToolEntry[];
  actual_tools?: LiveToolEntry[];
  expected_tools?: ExpectedToolEntry[];
  framework_added: LiveToolEntry[];
  connected_providers: string[];
  mcp_tool_count_registered: number;
};

export default function DebugPanel() {
  const { events, replay, setActive } = useDebugState();
  // Tell the provider the panel is visible: the shared context only
  // re-renders on SSE events while a panel instance is mounted.
  useEffect(() => {
    setActive(true);
    return () => setActive(false);
  }, [setActive]);
  const { rows, byQueen, byColony, connected: liveConnected } = useLiveSessions();
  const [globalEvents, setGlobalEvents] = useState<AgentEvent[]>([]);
  const [expanded, setExpanded] = useState<Record<Section, boolean>>({
    conn: true, queen: true, tools: false, oauth: true, snapshot: true, liveness: false,
    replay: true, reminders: true, events: true, global: false,
  });

  // Agent-loop state is dumped to window.__hive_debug_state by the page
  // components (queen-dm.tsx / colony-chat.tsx).
  const [queenState, setQueenState] = useState<Record<string, unknown>>({});
  useEffect(() => {
    const iv = setInterval(() => {
      const s = (window as unknown as Record<string, unknown>).__hive_debug_state;
      if (s && typeof s === "object") setQueenState(s as Record<string, unknown>);
    }, 500);
    return () => clearInterval(iv);
  }, []);

  // Re-render every second so age-based readouts (idle, last-event) keep
  // ticking even while no SSE events arrive — an idle gap is exactly when
  // we want those counters to keep moving.
  const [, setTick] = useState(0);
  useEffect(() => {
    const iv = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(iv);
  }, []);

  // Live tools — what the LLM actually owns *right now*. Source of truth for
  // diagnosing "agent claims no tool access after OAuth": this calls
  // phase_state.get_current_tools() on the runtime, which is what
  // dynamic_tools_provider hands the agent loop on its next iteration.
  // Fetched only while the section is expanded — refreshes every 3s so
  // newly-authorized providers appear without a manual reload.
  const sessionIdForTools = typeof queenState.sessionId === "string" ? queenState.sessionId : null;
  const toolsOpen = expanded.tools;
  const [liveTools, setLiveTools] = useState<LiveToolsResponse | null>(null);
  const [liveToolsError, setLiveToolsError] = useState<string | null>(null);
  const [liveToolsAt, setLiveToolsAt] = useState<number | null>(null);
  useEffect(() => {
    if (!toolsOpen || !sessionIdForTools) {
      return;
    }
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const data = await api.get<LiveToolsResponse>(
          `/sessions/${encodeURIComponent(sessionIdForTools)}/live_tools`,
        );
        if (cancelled) return;
        setLiveTools(data);
        setLiveToolsError(null);
        setLiveToolsAt(Date.now());
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof ApiError ? `${e.status} ${e.message}` : String(e);
        setLiveToolsError(msg);
      }
    };
    fetchOnce();
    const iv = setInterval(fetchOnce, 3000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [toolsOpen, sessionIdForTools]);

  // Live OAuth connections — the runtime's view of the credential store
  // (CredentialStoreAdapter.default → get_all_account_info). Polled every
  // 5s while the section is open so a disconnect on hive.adenhq.com (or a
  // newly-authorized account) shows up here without a page reload.
  const oauthOpen = expanded.oauth;
  const [oauthStatus, setOauthStatus] = useState<OAuthStatusResponse | null>(null);
  const [oauthError, setOauthError] = useState<string | null>(null);
  const [oauthFetchedAt, setOauthFetchedAt] = useState<number | null>(null);
  useEffect(() => {
    if (!oauthOpen) return;
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const data = await credentialsApi.oauthStatus();
        if (cancelled) return;
        setOauthStatus(data);
        setOauthError(null);
        setOauthFetchedAt(Date.now());
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof ApiError ? `${e.status} ${e.message}` : String(e);
        setOauthError(msg);
      }
    };
    fetchOnce();
    const iv = setInterval(fetchOnce, 5000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [oauthOpen]);

  // Global events
  useGlobalEvents({
    onEvent: (e) => setGlobalEvents((p) => [e, ...p].slice(0, 20)),
  });

  const logEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const toggle = (s: Section) =>
    setExpanded((p) => ({ ...p, [s]: !p[s] }));

  const now = Date.now();
  const lastEventAge = typeof queenState.lastEventAt === "number"
    ? Math.round((now - (queenState.lastEventAt as number)) / 1000) + "s"
    : "?";

  return (
    <div className="fixed right-0 top-0 bottom-0 w-[400px] z-[9999] bg-black/90 text-[11px] text-green-400 font-mono overflow-y-auto border-l border-white/10 shadow-2xl">
      <div className="sticky top-0 bg-black/95 border-b border-white/10 px-3 py-2 flex items-center justify-between z-10">
        <span className="text-xs font-bold text-white tracking-wider">DEBUG</span>
        <span className="text-[10px] text-white/40">Ctrl+Shift+D to toggle</span>
      </div>

      {/* Connection */}
      <Section header="Connection" section="conn" expanded={expanded} onToggle={toggle}>
        <Row label="SSE state" value={String(queenState.sseState ?? "?")} />
        <Row label="Online" value={String(navigator.onLine)} ok={navigator.onLine} />
        <Row label="Live feed" value={String(liveConnected)} ok={liveConnected} />
        <Row label="Last event" value={lastEventAge} />
        <Row label="Session ID" value={String(queenState.sessionId ?? "none").slice(0, 36)} />
      </Section>

      {/* Agent Loop State */}
      <Section header="Agent Loop State" section="queen" expanded={expanded} onToggle={toggle}>
        <Row label="active" value={String(!!queenState.active)} ok={!queenState.active} />
        <Row label="isStreaming" value={String(!!queenState.isStreaming)} ok={!queenState.isStreaming} />
        <Row label="awaitingInput" value={String(!!queenState.awaitingInput)} warn={!!queenState.awaitingInput} />
        {/* parkReason: WHY the loop is parked — meaningful whenever the
            backend carries it (AWAITING_USER OR INTERRUPTED parks both
            do). Render the field's own value directly; do NOT gate on
            awaitingInput, and do NOT let interruptCause borrow it.
            A broken reason (llm_error / doom_loop / empty_responses) is
            an unhealthy park, flagged red. */}
        <Row
          label="parkReason"
          value={formatParkReason(queenState.parkReason)}
          ok={isBrokenPark(queenState.parkReason) ? false : undefined}
        />
        {/* interrupted: the loop is not moving and it is NOT a deliberate
            end-of-turn (broken park, stream stall, crash). Mutually
            exclusive with awaitingInput — a true here is always red. */}
        <Row
          label="interrupted"
          value={String(!!queenState.interrupted)}
          ok={queenState.interrupted ? false : undefined}
        />
        {/* interruptCause: a NON-park cause (stream_stall / crashed / stale).
            Park-reason interrupts (user_stopped, llm_error, doom_loop, …) live
            in parkReason above — keep these two fields strictly disjoint. */}
        <Row
          label="interruptCause"
          value={queenState.interruptCause ? String(queenState.interruptCause) : "—"}
          ok={queenState.interruptCause ? false : undefined}
        />
        <Row label="pendingQuestions" value={formatPendingQuestions(queenState.pendingQuestions)} />
        <Row label="tasks" value={formatTasks(queenState.tasks)} />
        <Row label="isCompacting" value={String(!!queenState.isCompacting)} warn={!!queenState.isCompacting} />
        <Row label="lastCompaction" value={formatLastCompaction(queenState.lastCompaction)} />
        <Row label="currentTool" value={String(queenState.currentToolName ?? "—")} />
        <Row label="queenPhase" value={String(queenState.queenPhase ?? "?")} />
        <Row label="messages.count" value={String(queenState.messageCount ?? "?")} />
        {/* Real-time context-window readout, refreshed after every tool call. */}
        <Row label="context.usage" value={formatContextUsage(queenState.contextUsage)} warn={contextUsageWarn(queenState.contextUsage)} />
        <Row label="context.tokens" value={formatContextTokens(queenState.contextUsage)} />
        <Row label="context.breakdown" value={formatContextBreakdown(queenState.contextUsage)} />
        <Row label="context.trigger" value={formatContextTrigger(queenState.contextUsage)} />
      </Section>

      {/* Tools (live) — what the LLM actually owns this iteration. Hits the
          runtime's GET /api/sessions/{id}/live_tools, which calls
          phase_state.get_current_tools() under the hood. Use this to verify
          newly-OAuthed MCP tools surfaced; if a provider shows up under
          ``connected`` but the tool isn't in the list, the agent loop's
          tool snapshot is stale (refresh on next phase-state rebuild). */}
      <Section header="Tools (live)" section="tools" expanded={expanded} onToggle={toggle}>
        {!sessionIdForTools && (
          <div className="text-white/30 px-3 py-1">No active session</div>
        )}
        {sessionIdForTools && (
          <>
            {liveToolsError && (
              <div className="text-red-400 px-3 py-1">err: {liveToolsError}</div>
            )}
            {liveTools && (() => {
              // ACTUAL = what the loop can literally call now (eager + ask_user).
              // EXPECTED = the configured/allowed surface, status-tagged. Older
              // runtimes only send `tools`; fall back to it for the actual list.
              const actual = liveTools.actual_tools ?? liveTools.tools;
              const expected = liveTools.expected_tools ?? [];
              const actualNames = new Set(actual.map((t) => t.name));
              const statusColor: Record<ToolStatus, string> = {
                callable: "text-green-400",
                searchable: "text-amber-400",
                unregistered: "text-red-400",
              };
              return (
                <>
                  <Row label="phase" value={String(liveTools.phase ?? "—")} />
                  <Row label="actual.count" value={String(actual.length)} />
                  <Row label="expected.count" value={String(expected.length)} />
                  <Row label="mcp.registered" value={String(liveTools.mcp_tool_count_registered)} />
                  {liveTools.phase_state_ready === false && (
                    <Row label="phase_state" value="not ready — live set unavailable" ok={false} />
                  )}
                  <Row
                    label="connected"
                    value={
                      liveTools.connected_providers.length
                        ? liveTools.connected_providers.join(", ")
                        : "none"
                    }
                    warn={liveTools.connected_providers.length === 0}
                  />
                  <Row
                    label="fetched"
                    value={
                      liveToolsAt
                        ? `${Math.max(0, Math.round((Date.now() - liveToolsAt) / 1000))}s ago`
                        : "—"
                    }
                  />
                  {/* Side by side: callable-now vs allowed. A tool in EXPECTED
                      but not ACTUAL (amber=searchable, red=no server) is allowed
                      yet not callable this turn — the divergence to hunt. */}
                  <div className="flex gap-2 px-2 pt-1">
                    <div className="flex-1 min-w-0">
                      <div className="text-[10px] uppercase tracking-wider text-white/40 pb-0.5">
                        actual · callable ({actual.length})
                      </div>
                      {actual.length === 0 && <div className="text-white/30 py-0.5">none</div>}
                      {actual.map((t) => (
                        <div
                          key={`a:${t.name}`}
                          className="py-0.5 border-b border-white/5 text-cyan-300 truncate"
                          title={`${t.kind} — ${t.description}`}
                        >
                          {t.name}
                        </div>
                      ))}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[10px] uppercase tracking-wider text-white/40 pb-0.5">
                        expected · allowed ({expected.length})
                      </div>
                      {expected.length === 0 && <div className="text-white/30 py-0.5">none</div>}
                      {expected.map((t) => (
                        <div
                          key={`e:${t.name}`}
                          className={`py-0.5 border-b border-white/5 truncate ${statusColor[t.status] ?? "text-white/50"}`}
                          title={`${t.kind} — ${t.status}${actualNames.has(t.name) ? "" : " (not callable yet)"} — ${t.description}`}
                        >
                          {t.name}
                          {t.status !== "callable" && (
                            <span className="text-white/30"> · {t.status === "searchable" ? "search" : "no srv"}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              );
            })()}
            {!liveTools && !liveToolsError && (
              <div className="text-white/30 px-3 py-1">loading…</div>
            )}
          </>
        )}
      </Section>

      {/* OAuth Connections (live) — what the runtime's credential store
          currently holds. Hits GET /api/credentials/oauth-status which
          reads the memoized CredentialStoreAdapter (no sync_all on each
          poll). Use this to verify a disconnect on hive.adenhq.com
          actually propagated to the runtime, or that a fresh authorize
          landed. */}
      <Section header="OAuth Connections (live)" section="oauth" expanded={expanded} onToggle={toggle}>
        {oauthError && (
          <div className="text-red-400 px-3 py-1">err: {oauthError}</div>
        )}
        {!oauthError && !oauthStatus && (
          <div className="text-white/30 px-3 py-1">loading…</div>
        )}
        {oauthStatus && (
          <>
            <Row
              label="aden_api_key"
              value={oauthStatus.has_aden_key ? "set" : "missing"}
              ok={oauthStatus.has_aden_key}
            />
            <Row
              label="providers"
              value={String(Object.keys(oauthStatus.accounts_by_provider).length)}
              warn={Object.keys(oauthStatus.accounts_by_provider).length === 0}
            />
            <Row
              label="accounts"
              value={String(
                Object.values(oauthStatus.accounts_by_provider).reduce(
                  (sum, list) => sum + list.length,
                  0,
                ),
              )}
            />
            <Row
              label="fetched"
              value={
                oauthFetchedAt
                  ? `${Math.max(0, Math.round((Date.now() - oauthFetchedAt) / 1000))}s ago`
                  : "—"
              }
            />
            <div className="max-h-[260px] overflow-y-auto">
              {Object.keys(oauthStatus.accounts_by_provider).length === 0 && (
                <div className="text-white/30 px-3 py-1">No connected providers</div>
              )}
              {Object.entries(oauthStatus.accounts_by_provider)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([provider, accounts]) => (
                  <div key={provider} className="pl-3 pt-1 pb-0.5">
                    <div className="text-[10px] uppercase tracking-wider text-white/40 pb-0.5">
                      {provider} ({accounts.length})
                    </div>
                    {accounts.map((acct) => {
                      const email = acct.identity?.email || "";
                      const label = email || acct.alias || acct.credential_id;
                      return (
                        <div
                          key={`${provider}:${acct.alias}:${acct.credential_id}`}
                          className="px-2 py-0.5 border-b border-white/5 text-cyan-300"
                          title={`source=${acct.source} id=${acct.credential_id}`}
                        >
                          {label}
                          {acct.source && acct.source !== "aden" && (
                            <span className="text-white/30"> ({acct.source})</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))}
            </div>
          </>
        )}
      </Section>

      {/* Session Snapshot — fields mirrored from snapStateRef (queen-dm.tsx);
          colony routes omit them and the rows fall back to defaults. */}
      <Section header="Session Snapshot (latest)" section="snapshot" expanded={expanded} onToggle={toggle}>
        {/* activity: the loop's authoritative 3-state — executing /
            awaiting_user / interrupted. The three booleans below derive
            from it and are mutually exclusive. */}
        <Row label="activity" value={String(queenState.activity ?? "—")} ok={queenState.activity === "interrupted" ? false : undefined} />
        <Row label="is_executing" value={String(!!queenState.is_executing)} ok={!queenState.is_executing} />
        <Row label="awaiting_input" value={String(!!queenState.awaiting_input)} warn={!!queenState.awaiting_input} />
        <Row label="interrupted" value={String(!!queenState.interrupted)} ok={queenState.interrupted ? false : undefined} />
        <Row label="interrupt_cause" value={queenState.interrupted ? String(queenState.interrupt_cause ?? "?") : "—"} ok={queenState.interrupted ? false : undefined} />
        {/* park_reason: WHY the loop is parked — a broken reason (llm_error,
            doom_loop, empty_responses) is an unhealthy park, flagged red. */}
        <Row
          label="park_reason"
          value={formatParkReason(queenState.park_reason)}
          ok={isBrokenPark(queenState.park_reason) ? false : undefined}
          warn={isBrokenPark(queenState.park_reason)}
        />
        <Row label="snapshot_seq" value={String(queenState.snapshot_seq ?? "?")} />
        <Row label="busy_reason" value={String(queenState.busy_reason ?? "—")} />
        <Row label="open_tools" value={String(queenState.open_tools ?? "0")} />
      </Section>

      {/* Sidebar Liveness */}
      <Section header="Sidebar Liveness (live feed)" section="liveness" expanded={expanded} onToggle={toggle}>
        <Row label="Rows" value={String(rows.length)} />
        {Array.from(byQueen.entries()).map(([qid, l]) => (
          <div key={qid} className="pl-3 py-0.5 border-b border-white/5">
            <div className="text-[10px] text-white/60">{qid}</div>
            <Row label="  exec" value={String(l.is_executing)} ok={!l.is_executing} />
            <Row label="  await" value={String(l.awaiting_input)} warn={l.awaiting_input} />
            <Row label="  tool" value={l.current_tool_name ?? "—"} />
            {/* workers: in-flight (queued/pending/running) colony workers. The
                overseer parks its own loop while it waits on these, so exec
                goes false mid-fan-out — this is what keeps the colony "active". */}
            <Row label="  workers" value={String(l.active_worker_count)} />
          </div>
        ))}
        {/* Per-colony: exactly what drives the sidebar / org-chart dot, so a
            "why is this Parked?" question is answerable straight from here. */}
        {byColony.size > 0 && (
          <div className="mt-1 pt-1 border-t border-white/10">
            <div className="text-[10px] text-white/40 pb-0.5">by colony (dot source)</div>
            {Array.from(byColony.entries()).map(([cid, l]) => (
              <div key={cid} className="pl-3 py-0.5 border-b border-white/5">
                <div className="text-[10px] text-white/60">{cid}</div>
                <Row label="  exec" value={String(l.is_executing)} ok={!l.is_executing} />
                <Row label="  workers" value={String(l.active_worker_count)} />
                <Row
                  label="  status"
                  value={STATUS_LABEL[deriveColonyStatus(true, l)]}
                />
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Replay State */}
      <Section header="Replay State" section="replay" expanded={expanded} onToggle={toggle}>
        <Row label="turnCounters" value={replay ? JSON.stringify(replay.turnCounters) : "—"} />
        <Row label="toolTrackers" value={String(replay?.toolTrackers ?? "—")} />
        <Row label="seenSeqs" value={String(replay?.seenSeqsSize ?? "—")} />
        <Row label="snapshotSeq" value={String(replay?.snapshotSeq ?? "—")} />
      </Section>

      {/* Reminder Hub */}
      <Section header="Reminder Hub" section="reminders" expanded={expanded} onToggle={toggle}>
        {(() => {
          const list = reminderList(queenState);
          const idleSec = idleSinceEventSec(queenState, now);
          const idleNudge = latestIdleNudge(list);
          return (
            <>
              <Row
                label="idle"
                value={idleSec === null ? "?" : `${idleSec}s`}
                warn={idleSec !== null && idleSec >= 60}
              />
              <Row
                label="idle-nudges"
                value={idleNudge}
                warn={idleNudge !== "0/?" && idleNudge !== "—"}
              />
              <div className="max-h-[260px] overflow-y-auto">
                {list.length === 0 && (
                  <div className="text-white/30 px-3 py-1">No reminders yet</div>
                )}
                {list.map((r, i) => {
                  const ts = new Date(r.at).toTimeString().slice(0, 8);
                  return (
                    <div
                      key={i}
                      className="px-2 py-0.5 border-b border-white/5 text-pink-300"
                    >
                      <span className="text-white/20">{ts}</span>{" "}
                      <span className="font-bold">{r.source}</span>
                      {r.detail ? <span className="text-white/40"> {r.detail}</span> : null}
                    </div>
                  );
                })}
              </div>
            </>
          );
        })()}
      </Section>

      {/* Event Log */}
      <Section header={`Event Log (${events.length})`} section="events" expanded={expanded} onToggle={toggle}>
        <div className="max-h-[400px] overflow-y-auto">
          {events.length === 0 && <div className="text-white/30 px-3 py-1">No events yet</div>}
          {events.map((e, i) => {
            const seq = e.seq ?? 0;
            const ts = ((e.timestamp as string) ?? "").slice(11, 19) || "";
            const color =
              e.type === "tool_call_started" ? "text-cyan-400" :
              e.type === "tool_call_completed" ? "text-cyan-300" :
              e.type === "client_output_delta" ? "text-white/70" :
              e.type === "execution_started" ? "text-yellow-400" :
              e.type === "execution_completed" ? "text-yellow-300" :
              e.type === "client_input_requested" ? "text-amber-400" :
              e.type === "client_input_received" ? "text-amber-300" :
              e.type === "session_snapshot" ? "text-purple-400" :
              e.type === "context_compaction_started" ? "text-orange-400 font-bold" :
              e.type === "context_compacted" ? "text-orange-300" :
              e.type === "reminder_injected" ? "text-pink-400 font-bold" :
              e.type === "stream_nudge_sent" ? "text-pink-300" :
              e.type === "stream_inactive" || e.type === "stream_ttft_exceeded" ? "text-red-400" :
              e.type.includes("llm_turn") ? "text-green-400" :
              "text-white/40";
            return (
              <div key={i} className={`px-2 py-0.5 border-b border-white/5 hover:bg-white/5 ${color}`}>
                <span className="text-white/30">{String(seq).padStart(4)}</span>{" "}
                <span className="text-white/20">{ts}</span>{" "}
                {e.type}
              </div>
            );
          })}
          <div ref={logEndRef} />
        </div>
      </Section>

      {/* Global Events */}
      <Section header={`Global Events (${globalEvents.length})`} section="global" expanded={expanded} onToggle={toggle}>
        {globalEvents.map((e, i) => (
          <div key={i} className="px-2 py-0.5 text-purple-300 border-b border-white/5">
            {e.type} — {JSON.stringify(e.data ?? {}).slice(0, 80)}
          </div>
        ))}
      </Section>

      <div className="h-8" />
    </div>
  );
}

function Section({
  header, section, expanded, onToggle, children,
}: {
  header: string; section: Section;
  expanded: Record<Section, boolean>;
  onToggle: (s: Section) => void;
  children: React.ReactNode;
}) {
  const open = expanded[section];
  return (
    <div className="border-b border-white/10">
      <button
        onClick={() => onToggle(section)}
        className="w-full text-left px-3 py-1.5 hover:bg-white/5 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-white/60"
      >
        <span className="text-[8px]">{open ? "▼" : "▶"}</span>
        {header}
      </button>
      {open && <div className="pb-1">{children}</div>}
    </div>
  );
}

// Pending ask_user questions for the current park. "none" — combined with
// awaitingInput=true — is the invalid-park state the idle nudge re-engages.
function formatPendingQuestions(v: unknown): string {
  if (!Array.isArray(v) || v.length === 0) return "none";
  const first = v[0] as { prompt?: string } | undefined;
  const prompt = typeof first?.prompt === "string" ? first.prompt.trim() : "";
  const head = prompt ? `: ${prompt.slice(0, 48)}` : "";
  return `${v.length}${head}`;
}

// Broken park reasons — the loop parked after a failure, not by design.
// Mirrors ParkReason.is_broken on the backend.
function isBrokenPark(v: unknown): boolean {
  return v === "llm_error" || v === "empty_responses" || v === "doom_loop";
}

// ParkReason value for the current park: a healthy reason (ask_user,
// turn_done, …) reads plainly; a broken one is tagged so it stands out.
function formatParkReason(v: unknown): string {
  if (typeof v !== "string" || !v) return "—";
  return isBrokenPark(v) ? `${v} ⚠ broken` : v;
}

// The agent's task list — total plus a per-status breakdown.
function formatTasks(v: unknown): string {
  if (!Array.isArray(v) || v.length === 0) return "none";
  const counts: Record<string, number> = {};
  for (const t of v) {
    const s = (t as { status?: string } | undefined)?.status ?? "?";
    counts[s] = (counts[s] ?? 0) + 1;
  }
  const parts = ["pending", "in_progress", "completed", "abandoned"]
    .filter((s) => counts[s])
    .map((s) => `${counts[s]} ${s}`);
  return parts.length ? `${v.length} · ${parts.join(" / ")}` : String(v.length);
}

function formatLastCompaction(v: unknown): string {
  if (!v || typeof v !== "object") return "—";
  const r = v as { before?: number; after?: number; at?: number };
  if (typeof r.before !== "number" || typeof r.after !== "number") return "—";
  const ageSec = typeof r.at === "number"
    ? Math.max(0, Math.round((Date.now() - r.at) / 1000))
    : null;
  const ago = ageSec === null ? "" : ` (${ageSec}s ago)`;
  return `${r.before}% → ${r.after}%${ago}`;
}

// Reminder Hub readout. ``reminders`` is the recent-injection log mirrored
// from queen-dm.tsx (a reminder_injected event handler); ``lastEventAt`` is
// the wall-clock of the most recent SSE event — the live idle proxy.
type RecentReminder = {
  source: string;
  detail: string;
  nudgeCount: number | null;
  cap: number | null;
  at: number;
};

function idleSinceEventSec(queenState: Record<string, unknown>, now: number): number | null {
  return typeof queenState.lastEventAt === "number"
    ? Math.max(0, Math.round((now - (queenState.lastEventAt as number)) / 1000))
    : null;
}

function reminderList(queenState: Record<string, unknown>): RecentReminder[] {
  const v = queenState.reminders;
  return Array.isArray(v) ? (v as RecentReminder[]) : [];
}

// "<count>/<cap>" from the most recent idle_nudge reminder (the list is
// newest-first); "0/?" before any idle nudge has fired.
function latestIdleNudge(list: RecentReminder[]): string {
  const r = list.find((x) => x.source === "idle_nudge");
  if (!r) return "0/?";
  const count = typeof r.nudgeCount === "number" ? r.nudgeCount : 0;
  const cap = typeof r.cap === "number" ? String(r.cap) : "?";
  return `${count}/${cap}`;
}

function Row({ label, value, ok, warn }: { label: string; value: string; ok?: boolean; warn?: boolean }) {
  const color = warn ? "text-amber-400" : ok === false ? "text-red-400" : ok === true ? "text-green-400" : "text-white/50";
  return (
    <div className="flex justify-between px-3 py-0.5 hover:bg-white/[0.02]">
      <span className="text-white/40">{label}</span>
      <span className={color}>{value}</span>
    </div>
  );
}

// Real-time context-usage helpers. The shape comes from the
// CONTEXT_USAGE_UPDATED event published by event_publishing.py — see
// queen-dm.tsx for the case handler that fills `__hive_debug_state.contextUsage`.
type ContextUsageState = {
  usagePct?: number;
  estimatedTokens?: number;
  maxContextTokens?: number;
  messageCount?: number;
  trigger?: string;
  conversationChars?: number;
  systemChars?: number;
  toolDefsChars?: number;
  imageBlocks?: number;
  at?: number;
};

function asUsage(v: unknown): ContextUsageState | null {
  if (!v || typeof v !== "object") return null;
  return v as ContextUsageState;
}

function formatContextUsage(v: unknown): string {
  const u = asUsage(v);
  if (!u || typeof u.usagePct !== "number") return "—";
  const ageSec = typeof u.at === "number"
    ? Math.max(0, Math.round((Date.now() - u.at) / 1000))
    : null;
  const ago = ageSec === null ? "" : ` (${ageSec}s ago)`;
  return `${u.usagePct}%${ago}`;
}

function contextUsageWarn(v: unknown): boolean {
  const u = asUsage(v);
  return !!u && typeof u.usagePct === "number" && u.usagePct >= 70;
}

function formatContextTokens(v: unknown): string {
  const u = asUsage(v);
  if (!u || typeof u.estimatedTokens !== "number") return "—";
  const max = u.maxContextTokens && u.maxContextTokens > 0 ? `/${u.maxContextTokens.toLocaleString()}` : "";
  return `${u.estimatedTokens.toLocaleString()}${max}`;
}

function formatContextBreakdown(v: unknown): string {
  const u = asUsage(v);
  if (!u) return "—";
  // chars-per-token heuristic matches the backend (chars * 4 / 12 = chars/3)
  const t = (c?: number) => (typeof c === "number" ? Math.floor((c * 4) / 12).toLocaleString() : "?");
  const conv = t(u.conversationChars);
  const sys = t(u.systemChars);
  const tools = t(u.toolDefsChars);
  const imgs = typeof u.imageBlocks === "number" ? u.imageBlocks : 0;
  const imgTok = imgs > 0 ? ` img=${(imgs * 2000).toLocaleString()}` : "";
  return `conv=${conv} sys=${sys} tools=${tools}${imgTok}`;
}

function formatContextTrigger(v: unknown): string {
  const u = asUsage(v);
  if (!u) return "—";
  const msgs = typeof u.messageCount === "number" ? ` msgs=${u.messageCount}` : "";
  return `${u.trigger || "?"}${msgs}`;
}
