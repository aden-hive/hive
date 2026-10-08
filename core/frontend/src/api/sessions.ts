import { api } from "./client";
import type {
  AgentEvent,
  HistorySession,
  LiveSession,
  LiveSessionDetail,
} from "./types";

/** One backward page of a session's persisted event log. */
export interface EventsHistoryPage {
  events: AgentEvent[];
  session_id: string;
  /** Total events in the file; -1 on cursor pages (not recomputed there). */
  total: number;
  returned: number;
  /** Legacy field, kept for back-compat; superseded by `has_more_older`. */
  truncated: boolean;
  limit: number;
  /** Absolute 1-based line-index of the first returned event — pass as
   *  `beforeIndex` for the next older page. */
  start_index: number;
  /** Byte offset of the first returned line — pass as `beforeOffset` for the
   *  next older page. */
  start_offset: number;
  /** True while older events remain (i.e. `start_offset > 0`). */
  has_more_older: boolean;
}

export const sessionsApi = {
  // --- Session lifecycle ---

  /** Create a session.
   *
   *  - ``colonyId`` + colony dir exists  → opens the existing colony.
   *  - ``colonyId`` + dir missing + ``sourceSessionId`` → "Create Colony
   *    popup" path: the backend forks the source independent queen
   *    session into the new colony, compacts the source conversation into
   *    the colony queen seed, and locks the source session.
   *  - ``colonyId`` + dir missing                        → bootstraps a
   *    fresh minimal colony with the queen in colony phase.
   *  - no ``colonyId``                                   → queen-only DM. */
  create: (opts?: {
    colonyId?: string;
    model?: string;
    /** First-user-message brief for the new session. For colony-creation
     *  flows this is the colony's goal; for fresh queen-only chats it's
     *  whatever opening prompt the user typed. Sent to the backend as
     *  ``initial_prompt`` either way. */
    colonyGoal?: string;
    queenResumeFrom?: string;
    initialPhase?: string;
    queenName?: string;
    sourceSessionId?: string;
  }) => {
    // Creating/opening a colony is NOT LLM work — the queen parks until the
    // first /chat — so free users are allowed here. The LLM is gated where it
    // actually runs: a chat send (api/execution.ts) and the initial_prompt
    // below.
    return api.post<LiveSession>("/sessions", {
      colony_id: opts?.colonyId,
      model: opts?.model,
      initial_prompt: opts?.colonyGoal,
      queen_resume_from: opts?.queenResumeFrom || undefined,
      initial_phase: opts?.initialPhase || undefined,
      queen_name: opts?.queenName || undefined,
      source_session_id: opts?.sourceSessionId || undefined,
    });
  },

  /** List all active sessions. */
  list: () => api.get<{ sessions: LiveSession[] }>("/sessions"),

  /** Get session detail (includes entry_points — the session's triggers). */
  get: (sessionId: string) =>
    api.get<LiveSessionDetail>(`/sessions/${sessionId}`),

  /** Authoritative trigger list for a colony session — the durable triggers
   *  (from the colony's triggers.json) plus live status (enabled / next-fire /
   *  fire stats). The colony page seeds its trigger cards from this on load so
   *  they don't depend on SSE events surviving the bounded event ring buffer
   *  (which on a busy colony evicts older triggers — the "only one / none show
   *  up" bug). SSE trigger_* events then layer live deltas on top. */
  listTriggers: (sessionId: string) =>
    api.get<{
      triggers: Array<{
        trigger_id: string;
        trigger_type: string;
        trigger_config: Record<string, unknown>;
        name: string;
        task: string;
        enabled: boolean;
        last_fired_at?: string | null;
        next_due_at?: string | null;
      }>;
    }>(`/sessions/${sessionId}/triggers`),

  /** Stop a session entirely. */
  stop: (sessionId: string) =>
    api.delete<{ session_id: string; stopped: boolean }>(
      `/sessions/${sessionId}`,
    ),

  // --- Session info ---

  stats: (sessionId: string) =>
    api.get<Record<string, unknown>>(`/sessions/${sessionId}/stats`),

  /** Create a new timer trigger from the desktop UI and activate it
   *  immediately. The runtime slugifies `name` into a trigger_id, stores
   *  `name` as the trigger's description, and starts the timer — emitting a
   *  TRIGGER_ACTIVATED SSE event the colony page turns into a trigger card.
   *  `trigger_config` carries the UTC `cron` (built by lib/schedule.ts) or a
   *  plain `interval_minutes`. */
  createTrigger: (
    sessionId: string,
    opts: {
      name: string;
      task: string;
      trigger_config: Record<string, unknown>;
      trigger_type?: "timer";
    },
  ) =>
    api.post<{
      trigger_id: string;
      name: string;
      trigger_type: string;
      trigger_config: Record<string, unknown>;
    }>(`/sessions/${sessionId}/triggers`, {
      trigger_type: "timer",
      ...opts,
    }),

  updateTrigger: (
    sessionId: string,
    triggerId: string,
    patch: { task?: string; trigger_config?: Record<string, unknown> },
  ) =>
    api.patch<{ trigger_id: string; task: string; trigger_config: Record<string, unknown> }>(
      `/sessions/${sessionId}/triggers/${triggerId}`,
      patch,
    ),

  activateTrigger: (sessionId: string, triggerId: string) =>
    api.post<{ status: string; trigger_id: string }>(
      `/sessions/${sessionId}/triggers/${triggerId}/activate`,
    ),

  deactivateTrigger: (sessionId: string, triggerId: string) =>
    api.post<{ status: string; trigger_id: string }>(
      `/sessions/${sessionId}/triggers/${triggerId}/deactivate`,
    ),

  runTrigger: (sessionId: string, triggerId: string) =>
    api.post<{ status: string; trigger_id: string }>(
      `/sessions/${sessionId}/triggers/${triggerId}/run`,
    ),

  /** Get a backward page of the persisted eventbus log for a session
   *  (works for cold sessions — used for full UI replay).
   *
   *  Omit the cursor (`beforeOffset`/`beforeIndex`) to fetch the most recent
   *  `limit` events (default 500, server clamps to [1, 10000]). To page older,
   *  pass the previous response's `start_offset` as `beforeOffset` and its
   *  `start_index` as `beforeIndex`; the response then holds the `limit` events
   *  immediately preceding that cursor. `has_more_older` is true while older
   *  events remain; `start_offset` / `start_index` are the next cursor.
   */
  eventsHistory: (
    sessionId: string,
    opts?: { limit?: number; beforeOffset?: number; beforeIndex?: number },
  ) => {
    const qs = new URLSearchParams();
    if (opts?.limit != null) qs.set("limit", String(opts.limit));
    if (opts?.beforeOffset != null)
      qs.set("before_offset", String(opts.beforeOffset));
    if (opts?.beforeIndex != null)
      qs.set("before_index", String(opts.beforeIndex));
    const q = qs.toString();
    return api.get<EventsHistoryPage>(
      `/sessions/${sessionId}/events/history${q ? `?${q}` : ""}`,
    );
  },

  /** Dismiss the "Create Colony" popup opened by a colony-phase queen's
   *  ``task_create(new_colony=true)`` pivot.
   *
   *  Distinct from the DM ``suggest_colony`` dismissal (which works via
   *  a regular chat message) because the colony-pivot path parks the
   *  queen on ``_input_ready`` after a synthetic intercept — only the
   *  backend's ``inject_event`` can wake her. Returns
   *  ``{dismissed: false, reason: "no_pending_pivot"}`` on a benign
   *  race (popup already resolved); the UI can ignore that quietly. */
  dismissColonyPivot: (sessionId: string) =>
    api.post<{ dismissed: boolean; reason?: string }>(
      `/sessions/${sessionId}/dismiss-colony-pivot`,
    ),

  /** Open the session's data folder in the OS file manager. */
  revealFolder: (sessionId: string) =>
    api.post<{ path: string }>(`/sessions/${sessionId}/reveal`),

  /** List all queen sessions on disk — live + cold (post-restart). */
  history: () =>
    api.get<{ sessions: HistorySession[] }>("/sessions/history"),

  /** Permanently delete a history session (stops live session + removes disk files). */
  deleteHistory: (sessionId: string) =>
    api.delete<{ deleted: string }>(`/sessions/history/${sessionId}`),
};

/** Per-colony overseer history. Lives on a separate endpoint from
 *  ``sessionsApi.history()`` (queen DM history) because a sidebar click
 *  on a colony should resume that colony's ongoing chat — not surface
 *  unrelated queen DMs that happen to share an ``agent_path`` slug. */
export const colonySessionsApi = {
  /** All overseer sessions for ``colonyName``, newest first. The list
   *  is empty when the colony has no prior chat yet. */
  list: (colonyName: string) =>
    api.get<{ sessions: HistorySession[] }>(
      `/colonies/${encodeURIComponent(colonyName)}/sessions`,
    ),

  /** Most-recently-active overseer session for ``colonyName`` that has
   *  messages. Returns ``{ session: null }`` when nothing qualifies. */
  active: (colonyName: string) =>
    api.get<{ session: HistorySession | null }>(
      `/colonies/${encodeURIComponent(colonyName)}/active-session`,
    ),
};
