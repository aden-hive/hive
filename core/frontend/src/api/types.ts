// --- Session types (primary) ---

export interface LiveSession {
  session_id: string;
  colony_id: string | null;
  has_worker: boolean;
  agent_path: string;
  description: string;
  goal: string;
  node_count: number;
  loaded_at: number;
  uptime_seconds: number;
  intro_message?: string;
  /** Queen operating phase — "independent" (DM) or "colony" (forked into
   *  a colony, workers running or finished). Legacy values "incubating",
   *  "working", and "reviewing" are normalized server-side. */
  queen_phase?: "independent" | "colony";
  /** Whether the queen's LLM supports image content in messages */
  queen_supports_images?: boolean;
  /** Selected queen identity ID (e.g. "queen_technology") */
  queen_id?: string | null;
  /** Selected queen display name (e.g. "Alexandra") */
  queen_name?: string | null;
  /** True after the user has clicked into a colony spawned from this DM —
   *  /chat returns 409 until the user compacts and forks into a new session. */
  colony_spawned?: boolean;
  /** Name of the colony that locked this session (set with colony_spawned). */
  spawned_colony_id?: string | null;
  /** Present in 409 conflict responses when worker is still loading */
  loading?: boolean;
}

export interface LiveSessionDetail extends LiveSession {
  entry_points?: EntryPoint[];
  colonies?: string[];
  /** True when the session exists on disk but is not live (server restarted). */
  cold?: boolean;
}

export interface HistorySession {
  session_id: string;
  cold: boolean;
  live: boolean;
  has_messages: boolean;
  created_at: number;
  last_active_at?: number;
  agent_name?: string | null;
  agent_path?: string | null;
  queen_id?: string | null;
  last_message?: string | null;
  message_count?: number;
}

export interface EntryPoint {
  id: string;
  name: string;
  entry_node: string;
  trigger_type: string;
  trigger_config?: Record<string, unknown>;
  /** Worker task string when this trigger fires autonomously. */
  task?: string;
  /** Seconds until the next timer fire (only present for timer entry points). */
  next_fire_in?: number;
  /** Absolute wall-clock time of the next timer fire (epoch ms). */
  next_fire_at?: number;
  /** Number of times this trigger has fired during the session's lifetime. */
  fire_count?: number;
  /** Wall-clock time of the most recent fire (epoch ms). */
  last_fired_at?: number;
}

export interface WorkerEntry {
  name: string;
  config_path: string;
  description: string;
  tool_count: number;
  task: string;
  spawned_at: string;
  queen_name: string;
  colony_id: string;
}

export interface DiscoverEntry {
  path: string;
  name: string;
  description: string;
  category: string;
  created_at?: string | null;
  session_count: number;
  run_count: number;
  node_count: number;
  tool_count: number;
  tags: string[];
  last_active: string | null;
  is_loaded: boolean;
  icon?: string | null;
  workers: WorkerEntry[];
}

/** Keyed by category name. */
export type DiscoverResult = Record<string, DiscoverEntry[]>;

// --- Execution types ---

export interface TriggerResult {
  execution_id: string;
}

export interface InjectResult {
  delivered: boolean;
}

export interface ChatResult {
  status: "started" | "injected" | "queen";
  execution_id?: string;
  node_id?: string;
  delivered?: boolean;
}

export interface StopResult {
  stopped: boolean;
  execution_id?: string;
  error?: string;
}

export interface GoalProgress {
  progress: number;
  criteria: unknown[];
}

export interface Message {
  seq: number;
  role: string;
  content: string;
  _node_id: string;
  is_transition_marker?: boolean;
  is_client_input?: boolean;
  tool_calls?: unknown[];
  /** Epoch seconds from file mtime — used for cross-conversation ordering */
  created_at?: number;
  [key: string]: unknown;
}

// --- Worker / Node types ---

export interface NodeSpec {
  id: string;
  name: string;
  description: string;
  node_type: string;
  input_keys: string[];
  output_keys: string[];
  nullable_output_keys: string[];
  tools: string[];
  routes: Record<string, string>;
  max_retries: number;
  max_node_visits: number;
  /** Deprecated compatibility field; the queen is interactive by identity now. */
  client_facing: boolean;
  success_criteria: string | null;
  system_prompt: string;
  sub_agents?: string[];
  // Runtime enrichment (when session_id provided)
  visit_count?: number;
  has_failures?: boolean;
  is_current?: boolean;
  in_path?: boolean;
}

export interface EdgeInfo {
  target: string;
  condition: string;
  priority: number;
}

export interface NodeDetail extends NodeSpec {
  edges: EdgeInfo[];
}

export interface GraphEdge {
  source: string;
  target: string;
  condition: string;
  priority: number;
}

export interface GraphTopology {
  nodes: NodeSpec[];
  edges: GraphEdge[];
  entry_node: string;
  entry_points?: EntryPoint[];
}

export interface NodeCriteria {
  node_id: string;
  success_criteria: string | null;
  output_keys: string[];
  last_execution?: {
    success: boolean;
    error: string | null;
    retry_count: number;
    needs_attention: boolean;
    attention_reasons: string[];
  };
}

// --- Tool info types ---

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

// --- Log types ---

export interface LogEntry {
  [key: string]: unknown;
}

export interface LogNodeDetail {
  node_id: string;
  node_name: string;
  success: boolean;
  error?: string;
  retry_count?: number;
  needs_attention?: boolean;
  attention_reasons?: string[];
  total_steps: number;
}

export interface LogToolStep {
  node_id: string;
  step_index: number;
  llm_text: string;
  [key: string]: unknown;
}

// --- SSE Event types ---

export type EventTypeName =
  | "execution_started"
  | "execution_completed"
  | "execution_failed"
  | "execution_paused"
  | "execution_resumed"
  | "state_changed"
  | "state_conflict"
  | "goal_progress"
  | "goal_achieved"
  | "constraint_violation"
  | "stream_started"
  | "stream_stopped"
  | "node_loop_started"
  | "node_loop_iteration"
  | "node_loop_completed"
  | "node_action_plan"
  | "llm_text_delta"
  | "llm_reasoning_delta"
  | "client_reasoning"
  | "llm_turn_complete"
  | "tool_call_started"
  | "tool_call_completed"
  | "client_output_delta"
  | "client_input_requested"
  | "client_input_received"
  | "client_input_committed"
  | "client_credential_form_requested"
  | "colony_suggestion_requested"
  | "node_internal_output"
  | "node_input_blocked"
  | "node_stalled"
  | "node_tool_doom_loop"
  | "judge_verdict"
  | "node_retry"
  | "context_compaction_started"
  | "context_compacted"
  | "context_usage_updated"
  | "webhook_received"
  | "custom"
  | "escalation_requested"
  | "worker_colony_loaded"
  | "colony_created"
  | "credentials_required"
  | "queen_phase_changed"
  | "colony_fork_marker"
  | "subagent_report"
  | "worker_completed"
  | "worker_failed"
  | "trigger_available"
  | "trigger_activated"
  | "trigger_deactivated"
  | "trigger_fired"
  | "trigger_removed"
  | "trigger_updated"
  | "queen_identity_selected"
  | "task_created"
  | "task_updated"
  | "task_deleted"
  | "task_list_reset"
  | "task_list_reattach_mismatch"
  | "session_snapshot"
  | "credential_provider_connected"
  | "credential_provider_disconnected"
  | "tool_catalog_refreshed"
  | "tools_config_changed"
  | "crm_changed"
  | "session_forked"
  // Stream-health & nudge observability (see core EventType).
  | "stream_ttft_exceeded"
  | "stream_inactive"
  | "stream_nudge_sent"
  | "reminder_injected"
  // The agent loop's authoritative top-level state changed.
  | "loop_state_changed";

export interface AgentEvent {
  type: EventTypeName;
  stream_id: string;
  node_id: string | null;
  execution_id: string | null;
  data: Record<string, unknown>;
  timestamp: string;
  correlation_id: string | null;
  colony_id: string | null;
  run_id?: string | null;
  /** Monotonic publish counter assigned by the EventBus. Synthesised
   * events (e.g. session_snapshot built from the ring buffer) carry
   * seq=0 to mark them as not-from-history. Used by the renderer for
   * dedupe across the disk eventsHistory and live SSE replay paths. */
  seq?: number;
}

/** Shape of the data payload on a session_snapshot event. The SSE
 * handler builds this from the per-session ring buffer at the moment
 * the client subscribes. The renderer uses it to rehydrate
 * isTyping/awaitingInput/in-flight tool pills instantly on revisit. */
export interface SessionSnapshotData {
  snapshot_seq: number;
  is_executing: boolean;
  current_execution_id: string | null;
  current_tool_calls: Array<{
    id: string;
    name: string | null;
    started_at: string;
    execution_id: string | null;
    seq: number;
  }>;
  awaiting_input: boolean;
  queen_busy_reason: "tool" | "llm" | null;
  last_event_at: string | null;
}
