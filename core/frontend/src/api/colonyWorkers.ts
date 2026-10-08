import { api } from "./client";

export interface WorkerResult {
  status: string;
  summary: string;
  error: string | null;
  tokens_used: number;
  duration_seconds: number;
}

export interface TaskSummary {
  total: number;
  completed: number;
  in_progress: number;
  pending: number;
}

export interface WorkerSummary {
  worker_id: string;
  task: string;
  /** Queen-authored one-sentence description of what this worker is doing,
   *  in end-user language — the preferred human title for the worker.
   *  Seeded at spawn into the worker's task-list meta; null for workers
   *  spawned before the feature or dispatched without one. */
  goal?: string | null;
  status: string;
  started_at: number;
  result: WorkerResult | null;
  /** Per-worker task progress counts. Null when the worker has no task
   *  list or is not active (historical/stopped workers). */
  task_summary?: TaskSummary | null;
  /** Batch coordinates for workers spawned as part of a parallel batch.
   *  Optional because the runtime may not yet populate it on the list
   *  endpoint, and because solo workers (queen-spawned one-offs) have
   *  no batch. When present, ``batch_size > 0`` and ``batch_index`` is
   *  1-based within the batch. */
  batch?: WorkerBatch | null;
}

/** Coordinates of a worker spawned as part of a parallel batch.
 *  ``batch_index`` is 1-based (1..batch_size); ``0`` means the worker
 *  was not spawned as part of a batch. */
export interface WorkerBatch {
  batch_id: string;
  batch_index: number;
  batch_size: number;
  /** Run-scoped dispatch ordinal for playbook workers. Playbook dispatches
   *  are size-1 batches that all share one batch_id, so batch_index is always
   *  1 and can't disambiguate peers; when ``worker_seq > 0`` it is the stable
   *  per-worker ordinal to render instead. ``0`` for ordinary fan-out, which
   *  uses ``batch_index``. */
  worker_seq?: number;
}

/** Full per-worker record from GET /sessions/{id}/workers/{worker_id}.
 *  Superset of WorkerSummary: adds the worker's profile name, batch
 *  coordinates, and its full task list. Unlike the list endpoint,
 *  this reads result.json from disk for terminated workers, so
 *  ``result`` is populated even for historical workers. */
export interface WorkerDetailData extends WorkerSummary {
  profile_name: string;
  batch: WorkerBatch;
  tasks: unknown[];
}

/** One tool invocation inside an assistant transcript message. */
export interface WorkerToolCall {
  name: string;
  /** Raw argument payload — usually a JSON string. */
  arguments: string;
}

/** One message in a worker's conversation transcript. */
export interface WorkerMessage {
  seq: number;
  /** "user" | "assistant" | "tool". */
  role: string;
  content: string;
  /** Present on assistant messages that invoked tools. */
  tool_calls?: WorkerToolCall[];
  /** Present on tool-result messages — links back to the call. */
  tool_use_id?: string;
}

/** Response of GET /sessions/{id}/workers/{worker_id}/conversation. */
export interface WorkerConversation {
  worker_id: string;
  messages: WorkerMessage[];
  /** Total parts on disk; may exceed messages.length when truncated. */
  total: number;
  truncated: boolean;
}

export interface ColonySkill {
  name: string;
  description: string;
  location: string;
  base_dir: string;
  source_scope: string;
}

export interface ColonyTool {
  name: string;
  description: string;
  /** Canonical credential/provider key (e.g. "hubspot", "gmail") for
   *  tools bound to an Aden credential. ``null`` for framework/core
   *  tools that don't require a provider credential. */
  provider: string | null;
}

export const colonyWorkersApi = {
  /** List spawned workers (live + completed) for a colony session. */
  list: (sessionId: string) =>
    api.get<{ workers: WorkerSummary[] }>(`/sessions/${sessionId}/workers`),

  /** Inspect a single worker. Served from live runtime state when the
   *  worker is still in memory, otherwise from its on-disk run dir. */
  get: (sessionId: string, workerId: string) =>
    api.get<{ worker: WorkerDetailData }>(
      `/sessions/${sessionId}/workers/${workerId}`,
    ),

  /** Fetch a worker's full message transcript (conversations/parts). */
  getConversation: (sessionId: string, workerId: string) =>
    api.get<WorkerConversation>(
      `/sessions/${sessionId}/workers/${workerId}/conversation`,
    ),

  /** List the colony's shared skills catalog. */
  listSkills: (sessionId: string) =>
    api.get<{ skills: ColonySkill[] }>(`/sessions/${sessionId}/colony/skills`),

  /** List the colony's default tools. */
  listTools: (sessionId: string) =>
    api.get<{ tools: ColonyTool[] }>(`/sessions/${sessionId}/colony/tools`),
};
