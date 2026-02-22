// --- Agent types ---

export interface Agent {
  id: string;
  agent_path: string;
  name: string;
  description: string;
  goal: string;
  node_count: number;
  loaded_at: number;
  uptime_seconds: number;
}

export interface EntryPoint {
  id: string;
  name: string;
  entry_node: string;
  trigger_type: string;
}

export interface AgentDetail extends Agent {
  entry_points: EntryPoint[];
  graphs: string[];
}

export interface DiscoverEntry {
  path: string;
  name: string;
  description: string;
  category: string;
  session_count: number;
  node_count: number;
  tool_count: number;
  tags: string[];
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
  status: "started" | "injected";
  execution_id?: string;
  node_id?: string;
  delivered?: boolean;
}

export interface StopResult {
  stopped: boolean;
  execution_id?: string;
  error?: string;
}

export interface ResumeResult {
  execution_id: string;
  resumed_from: string;
  checkpoint_id: string | null;
}

export interface ReplayResult {
  execution_id: string;
  replayed_from: string;
  checkpoint_id: string;
}

export interface GoalProgress {
  progress: number;
  criteria: unknown[];
}

// --- Session types ---

export interface SessionSummary {
  session_id: string;
  status?: string;
  started_at?: string | null;
  completed_at?: string | null;
  steps?: number;
  paused_at?: string | null;
  checkpoint_count: number;
}

export interface SessionDetail {
  status: string;
  started_at: string;
  completed_at: string | null;
  input_data: Record<string, unknown>;
  memory: Record<string, unknown>;
  progress: {
    current_node: string | null;
    paused_at: string | null;
    steps_executed: number;
    path: string[];
    node_visit_counts: Record<string, number>;
    nodes_with_failures: string[];
    resume_from?: string;
  };
}

export interface Checkpoint {
  checkpoint_id: string;
  current_node: string | null;
  next_node: string | null;
  is_clean: boolean;
  timestamp: string | null;
  error?: string;
}

export interface Message {
  seq: number;
  role: string;
  content: string;
  _node_id: string;
  [key: string]: unknown;
}

// --- Graph / Node types ---

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
  client_facing: boolean;
  success_criteria: string | null;
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
  | "llm_text_delta"
  | "llm_reasoning_delta"
  | "tool_call_started"
  | "tool_call_completed"
  | "client_output_delta"
  | "client_input_requested"
  | "node_internal_output"
  | "node_input_blocked"
  | "node_stalled"
  | "node_tool_doom_loop"
  | "judge_verdict"
  | "output_key_set"
  | "node_retry"
  | "edge_traversed"
  | "context_compacted"
  | "webhook_received"
  | "custom"
  | "escalation_requested";

export interface AgentEvent {
  type: EventTypeName;
  stream_id: string;
  node_id: string | null;
  execution_id: string | null;
  data: Record<string, unknown>;
  timestamp: string;
  correlation_id: string | null;
  graph_id: string | null;
}
