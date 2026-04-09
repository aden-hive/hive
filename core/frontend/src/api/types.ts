// --- Session types (primary) ---

export interface LiveSession {
  session_id: string;
  colony_id: string | null;
  colony_name: string | null;
  has_worker: boolean;
  agent_path: string;
  description: string;
  goal: string;
  node_count: number;
  loaded_at: number;
  uptime_seconds: number;
  intro_message?: string;
  /** Queen operating phase — "planning", "building", "staging", or "running" */
  queen_phase?: "planning" | "building" | "staging" | "running" | "independent";
  /** Whether the queen's LLM supports image content in messages */
  queen_supports_images?: boolean;
  /** Selected queen identity ID (e.g. "queen_technology") */
  queen_id?: string | null;
  /** Selected queen display name (e.g. "Alexandra") */
  queen_name?: string | null;
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
}

export interface DiscoverEntry {
  path: string;
  name: string;
  description: string;
  category: string;
  session_count: number;
  run_count: number;
  node_count: number;
  tool_count: number;
  tags: string[];
  last_active: string | null;
  is_loaded: boolean;
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

// --- Draft graph types (planning phase) ---

export interface DraftNode {
  id: string;
  name: string;
  description: string;
  node_type: string;
  tools: string[];
  input_keys: string[];
  output_keys: string[];
  success_criteria: string;
  sub_agents: string[];
  /** For decision nodes: the yes/no question evaluated during dissolution. */
  decision_clause?: string;
  flowchart_type: string;
  flowchart_shape: string;
  flowchart_color: string;
}

export interface DraftEdge {
  id: string;
  source: string;
  target: string;
  condition: string;
  description: string;
  /** Short label shown on the flowchart edge (e.g. "Yes", "No"). */
  label?: string;
}

export interface DraftGraph {
  agent_name: string;
  goal: string;
  description: string;
  success_criteria: string[];
  constraints: string[];
  nodes: DraftNode[];
  edges: DraftEdge[];
  entry_node: string;
  terminal_nodes: string[];
  flowchart_legend: Record<string, { shape: string; color: string }>;
}

/** Mapping from runtime graph nodes → original flowchart draft nodes. */
export interface FlowchartMap {
  /** runtime_node_id → list of original draft node IDs it absorbed. */
  map: Record<string, string[]> | null;
  /** Original draft graph preserved before planning-node dissolution (decision + subagent). */
  original_draft: DraftGraph | null;
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
  | "llm_turn_complete"
  | "tool_call_started"
  | "tool_call_completed"
  | "client_output_delta"
  | "client_input_requested"
  | "client_input_received"
  | "node_internal_output"
  | "node_input_blocked"
  | "node_stalled"
  | "node_tool_doom_loop"
  | "judge_verdict"
  | "node_retry"
  | "context_compacted"
  | "context_usage_updated"
  | "webhook_received"
  | "custom"
  | "escalation_requested"
  | "worker_colony_loaded"
  | "credentials_required"
  | "queen_phase_changed"
  | "subagent_report"
  | "trigger_available"
  | "trigger_activated"
  | "trigger_deactivated"
  | "trigger_fired"
  | "trigger_removed"
  | "trigger_updated"
  | "queen_identity_selected";

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
}
