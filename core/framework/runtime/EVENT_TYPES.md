# Event Types and Schema Reference

The Hive runtime uses a pub/sub `EventBus` for inter-component communication and observability. Every event is an `AgentEvent` dataclass published through `EventBus.publish()`.

## Event Envelope (`AgentEvent`)

Every event shares a common envelope:

| Field            | Type              | Description                                                  |
| ---------------- | ----------------- | ------------------------------------------------------------ |
| `type`           | `EventType` (str) | Event type identifier (see below)                            |
| `stream_id`      | `str`             | Entry point / pipeline that emitted the event                |
| `node_id`        | `str \| None`     | Graph node that emitted the event                            |
| `execution_id`   | `str \| None`     | Unique execution run ID (UUID, set by `ExecutionStream`)     |
| `graph_id`       | `str \| None`     | Graph that emitted the event (set by `GraphScopedEventBus`)  |
| `data`           | `dict`            | Event-type-specific payload (see individual schemas below)   |
| `timestamp`      | `datetime`        | When the event was created                                   |
| `correlation_id` | `str \| None`     | Optional ID for tracking related events across streams       |

### Identity Fields

The identity tuple `(graph_id, stream_id, node_id, execution_id)` uniquely locates any event:

- **`graph_id`** — Which graph produced the event. Set automatically by `GraphScopedEventBus` (a subclass that stamps `graph_id` on every `publish()` call). Values: `"worker"`, `"judge"`, `"queen"`, or the graph spec ID.
- **`stream_id`** — Which entry point / pipeline. Corresponds to `EntryPointSpec.id` in the graph definition. For single-entry-point graphs, this equals the entry point name (e.g. `"default"`, `"health_check"`, `"ticket_receiver"`).
- **`node_id`** — Which specific node emitted the event. For `EventLoopNode` events, this is the node spec ID.
- **`execution_id`** — UUID identifying a specific execution run. Multiple concurrent executions of the same entry point each get a unique `execution_id`.

---

## Execution Lifecycle

### `execution_started`

A new graph execution has begun.

| Data Field | Type   | Description                     |
| ---------- | ------ | ------------------------------- |
| `input`    | `dict` | Input data passed to the graph  |

**Emitted by:** `ExecutionStream._run_execution()`

---

### `execution_completed`

A graph execution finished successfully.

| Data Field | Type   | Description       |
| ---------- | ------ | ----------------- |
| `output`   | `dict` | Final output data |

**Emitted by:** `ExecutionStream._run_execution()`

---

### `execution_failed`

A graph execution failed with an error.

| Data Field | Type  | Description   |
| ---------- | ----- | ------------- |
| `error`    | `str` | Error message |

**Emitted by:** `ExecutionStream._run_execution()`

---

### `execution_paused`

Execution has been paused (Ctrl+Z or HITL approval).

| Data Field | Type  | Description       |
| ---------- | ----- | ----------------- |
| `reason`   | `str` | Why it was paused |

**Emitted by:** `GraphExecutor.execute()`

---

### `execution_resumed`

Execution has resumed from a paused state.

| Data Field | Type | Description |
| ---------- | ---- | ----------- |
| *(none)*   |      |             |

**Emitted by:** `GraphExecutor.execute()`

---

## Node Event-Loop Lifecycle

These events track the inner loop of `EventLoopNode` — the multi-turn LLM streaming loop that powers most agent nodes.

### `node_loop_started`

An EventLoopNode has begun its execution loop.

| Data Field       | Type       | Description                     |
| ---------------- | ---------- | ------------------------------- |
| `max_iterations` | `int\|null`| Maximum iterations configured   |

**Emitted by:** `EventLoopNode._publish_loop_started()`, `GraphExecutor` (for function nodes in parallel branches)

---

### `node_loop_iteration`

An EventLoopNode has started a new iteration (one LLM turn).

| Data Field  | Type  | Description               |
| ----------- | ----- | ------------------------- |
| `iteration` | `int` | Zero-based iteration index |

**Emitted by:** `EventLoopNode._publish_iteration()`

---

### `node_loop_completed`

An EventLoopNode has finished its execution loop.

| Data Field   | Type  | Description                            |
| ------------ | ----- | -------------------------------------- |
| `iterations` | `int` | Total number of iterations completed   |

**Emitted by:** `EventLoopNode._publish_loop_completed()`, `GraphExecutor` (for function nodes in parallel branches)

---

## LLM Streaming

### `llm_text_delta`

Incremental text output from the LLM (non-client-facing nodes only).

| Data Field | Type  | Description                              |
| ---------- | ----- | ---------------------------------------- |
| `content`  | `str` | New text chunk (delta)                   |
| `snapshot` | `str` | Full accumulated text so far             |

**Emitted by:** `EventLoopNode._publish_text_delta()` when `client_facing=False`

---

### `llm_reasoning_delta`

Incremental reasoning/thinking output from the LLM.

| Data Field | Type  | Description         |
| ---------- | ----- | ------------------- |
| `content`  | `str` | New reasoning chunk |

**Emitted by:** Not currently wired in `EventLoopNode` (reserved for extended thinking models).

---

## Tool Lifecycle

### `tool_call_started`

The LLM has requested a tool call and execution is about to begin.

| Data Field   | Type   | Description                          |
| ------------ | ------ | ------------------------------------ |
| `tool_use_id`| `str`  | Unique ID for this tool invocation   |
| `tool_name`  | `str`  | Name of the tool being called        |
| `tool_input` | `dict` | Arguments passed to the tool         |

**Emitted by:** `EventLoopNode._publish_tool_started()`

---

### `tool_call_completed`

A tool call has finished executing.

| Data Field   | Type   | Description                            |
| ------------ | ------ | -------------------------------------- |
| `tool_use_id`| `str`  | Same ID from `tool_call_started`       |
| `tool_name`  | `str`  | Name of the tool                       |
| `result`     | `str`  | Tool execution result (may be truncated)|
| `is_error`   | `bool` | Whether the tool returned an error     |

**Emitted by:** `EventLoopNode._publish_tool_completed()`

---

## Client I/O

These events are emitted only by nodes with `client_facing=True`. They drive the TUI's chat interface.

### `client_output_delta`

Incremental text output meant for the human operator.

| Data Field | Type  | Description                  |
| ---------- | ----- | ---------------------------- |
| `content`  | `str` | New text chunk (delta)       |
| `snapshot` | `str` | Full accumulated text so far |

**Emitted by:** `EventLoopNode._publish_text_delta()` when `client_facing=True`

---

### `client_input_requested`

The node is waiting for human input (via `ask_user` tool or auto-block on text-only turns).

| Data Field | Type  | Description                                       |
| ---------- | ----- | ------------------------------------------------- |
| `prompt`   | `str` | Optional prompt/question shown to the user        |

**Emitted by:** `EventLoopNode._await_user_input()`, doom loop handler

The TUI subscribes to this event to show the input prompt and focus the chat input. After the user types, `inject_event()` is called on the node to unblock it.

---

## Internal Node Observability

### `node_internal_output`

Output from a non-client-facing node (for debugging/monitoring).

| Data Field | Type  | Description      |
| ---------- | ----- | ---------------- |
| `content`  | `str` | Output text      |

**Emitted by:** Available via `emit_node_internal_output()` — not currently wired in the default `EventLoopNode`.

---

### `node_input_blocked`

A non-client-facing node is blocked waiting for input.

| Data Field | Type  | Description     |
| ---------- | ----- | --------------- |
| `prompt`   | `str` | Block reason    |

**Emitted by:** Available via `emit_node_input_blocked()` — reserved for future use.

---

### `node_stalled`

The node's LLM has produced identical responses for several consecutive turns (stall detection).

| Data Field | Type  | Description                                       |
| ---------- | ----- | ------------------------------------------------- |
| `reason`   | `str` | Always `"Consecutive identical responses detected"`|

**Emitted by:** `EventLoopNode._publish_stalled()`

---

### `node_tool_doom_loop`

The LLM is calling the same tool(s) with identical arguments repeatedly (doom loop detection).

| Data Field    | Type  | Description                          |
| ------------- | ----- | ------------------------------------ |
| `description` | `str` | Human-readable doom loop description |

**Emitted by:** `EventLoopNode` doom loop handler

---

## Judge Decisions

### `judge_verdict`

The judge (custom or implicit) has evaluated the current iteration.

| Data Field   | Type  | Description                                          |
| ------------ | ----- | ---------------------------------------------------- |
| `action`     | `str` | `"ACCEPT"`, `"RETRY"`, `"ESCALATE"`, or `"CONTINUE"` |
| `feedback`   | `str` | Judge feedback (empty for ACCEPT/CONTINUE)           |
| `judge_type` | `str` | `"custom"` (explicit JudgeProtocol) or `"implicit"` (stop-reason heuristic) |
| `iteration`  | `int` | Which iteration this verdict applies to              |

**Emitted by:** `EventLoopNode._publish_judge_verdict()`

**Verdict meanings:**
- **ACCEPT** — Output meets requirements; node exits successfully.
- **RETRY** — Output needs improvement; loop continues with feedback injected.
- **ESCALATE** — Problem cannot be solved at this level; triggers escalation.
- **CONTINUE** — Implicit verdict: LLM called tools, so it's making progress — let it keep going.

---

## Output Tracking

### `output_key_set`

A node has set an output key via the `set_output` synthetic tool.

| Data Field | Type  | Description       |
| ---------- | ----- | ----------------- |
| `key`      | `str` | Output key name   |

**Emitted by:** `EventLoopNode._publish_output_key_set()`

---

## Retry & Edge Tracking

### `node_retry`

A transient error occurred during an LLM call and the node is retrying.

| Data Field    | Type  | Description                        |
| ------------- | ----- | ---------------------------------- |
| `retry_count` | `int` | Current retry attempt number       |
| `max_retries` | `int` | Maximum retries configured         |
| `error`       | `str` | Error message (truncated to 500ch) |

**Emitted by:** `EventLoopNode` (stream retry handler), `GraphExecutor` (node-level retry)

---

### `edge_traversed`

The executor has traversed an edge from one node to another.

| Data Field       | Type  | Description                                    |
| ---------------- | ----- | ---------------------------------------------- |
| `source_node`    | `str` | Node ID the edge starts from                   |
| `target_node`    | `str` | Node ID the edge goes to                       |
| `edge_condition` | `str` | Edge condition: `"router"`, `"on_success"`, etc. |

**Emitted by:** `GraphExecutor.execute()` — after router decisions, condition-based edges, and fallback edges.

---

## Context Management

### `context_compacted`

Not currently emitted — reserved for future use when `NodeConversation` compacts history.

---

## State Changes

### `state_changed`

A shared memory key has been modified.

| Data Field  | Type  | Description                        |
| ----------- | ----- | ---------------------------------- |
| `key`       | `str` | Memory key that changed            |
| `old_value` | `Any` | Previous value                     |
| `new_value` | `Any` | New value                          |
| `scope`     | `str` | Scope of the change                |

**Emitted by:** Available via `emit_state_changed()` — not currently wired in default execution.

---

### `state_conflict`

Not currently emitted — reserved for concurrent write conflict detection.

---

## Goal Tracking

### `goal_progress`

Goal completion progress update.

| Data Field        | Type    | Description                          |
| ----------------- | ------- | ------------------------------------ |
| `progress`        | `float` | 0.0–1.0 completion fraction         |
| `criteria_status` | `dict`  | Per-criterion status                 |

**Emitted by:** Available via `emit_goal_progress()` — not currently wired in default execution.

---

### `goal_achieved`

Not currently emitted — reserved for explicit goal completion signals.

---

### `constraint_violation`

A goal constraint has been violated.

| Data Field      | Type  | Description              |
| --------------- | ----- | ------------------------ |
| `constraint_id` | `str` | Which constraint failed  |
| `description`   | `str` | What went wrong          |

**Emitted by:** Available via `emit_constraint_violation()`.

---

## Stream Lifecycle

### `stream_started` / `stream_stopped`

Not currently emitted — reserved for `ExecutionStream` lifecycle tracking.

---

## External Triggers

### `webhook_received`

An external webhook has been received.

| Data Field     | Type   | Description                  |
| -------------- | ------ | ---------------------------- |
| `path`         | `str`  | Webhook URL path             |
| `method`       | `str`  | HTTP method                  |
| `headers`      | `dict` | HTTP headers                 |
| `payload`      | `dict` | Request body                 |
| `query_params` | `dict` | URL query parameters         |

**Emitted by:** Webhook server integration.

Note: `node_id` is not set on this event; `stream_id` is the webhook source ID.

---

## Escalation

### `escalation_requested`

An agent has requested handoff to the Hive Coder (via the `escalate_to_coder` synthetic tool).

| Data Field | Type  | Description                     |
| ---------- | ----- | ------------------------------- |
| `reason`   | `str` | Why escalation is needed        |
| `context`  | `str` | Additional context for the coder|

**Emitted by:** `EventLoopNode` when the LLM calls `escalate_to_coder`.

---

## Worker Health Monitoring

These events form the **judge → queen → operator** escalation pipeline.

### `worker_escalation_ticket`

The Worker Health Judge has detected a degradation pattern and is escalating to the Queen.

| Data Field | Type   | Description                          |
| ---------- | ------ | ------------------------------------ |
| `ticket`   | `dict` | Full `EscalationTicket` (see below)  |

**Emitted by:** `emit_escalation_ticket` tool (in `worker_monitoring_tools.py`)

#### EscalationTicket Schema

| Field                     | Type               | Description                                              |
| ------------------------- | ------------------ | -------------------------------------------------------- |
| `ticket_id`               | `str`              | Auto-generated UUID                                      |
| `created_at`              | `str`              | ISO timestamp                                            |
| `worker_agent_id`         | `str`              | Which worker agent                                       |
| `worker_session_id`       | `str`              | Which session                                            |
| `worker_node_id`          | `str`              | Which node is struggling                                 |
| `worker_graph_id`         | `str`              | Which graph                                              |
| `severity`                | `str`              | `"low"`, `"medium"`, `"high"`, or `"critical"`           |
| `cause`                   | `str`              | Human-readable problem description                       |
| `judge_reasoning`         | `str`              | Judge's deliberation chain                               |
| `suggested_action`        | `str`              | e.g. `"Restart node"`, `"Human review"`, `"Kill session"`|
| `recent_verdicts`         | `list[str]`        | e.g. `["RETRY", "RETRY", "CONTINUE", "RETRY"]`          |
| `total_steps_checked`     | `int`              | Steps the judge inspected                                |
| `steps_since_last_accept` | `int`              | Consecutive non-ACCEPT steps                             |
| `stall_minutes`           | `float \| null`    | Minutes since last activity (null if active)             |
| `evidence_snippet`        | `str`              | Excerpt from recent LLM output                           |

---

### `queen_intervention_requested`

The Queen has triaged an escalation ticket and decided the human operator should be involved.

| Data Field        | Type  | Description                                          |
| ----------------- | ----- | ---------------------------------------------------- |
| `ticket_id`       | `str` | From the original `EscalationTicket`                 |
| `analysis`        | `str` | Queen's 2–3 sentence analysis                        |
| `severity`        | `str` | `"low"`, `"medium"`, `"high"`, or `"critical"`       |
| `queen_graph_id`  | `str` | Queen's graph ID (for TUI navigation)                |
| `queen_stream_id` | `str` | Queen's stream ID                                    |

**Emitted by:** `notify_operator` tool (in `worker_monitoring_tools.py`)

The TUI subscribes to this event and shows a non-disruptive notification. The worker continues running.

---

## Custom Events

### `custom`

User-defined events with arbitrary payloads. No schema enforced.

---

## Subscription & Filtering

Events can be filtered when subscribing:

```python
bus.subscribe(
    event_types=[EventType.TOOL_CALL_STARTED, EventType.TOOL_CALL_COMPLETED],
    handler=my_handler,
    filter_stream="default",       # Only events from this stream
    filter_node="planner",         # Only events from this node
    filter_execution="exec-uuid",  # Only events from this execution
    filter_graph="worker",         # Only events from this graph
)
```

## Debug Event Logging

Set `HIVE_DEBUG_EVENTS=1` to write every published event to a JSONL file at `~/.hive/event_logs/<timestamp>.jsonl`. Each line is the full JSON serialization of an `AgentEvent`:

```json
{
  "type": "tool_call_started",
  "stream_id": "default",
  "node_id": "planner",
  "execution_id": "a1b2c3d4-...",
  "graph_id": "worker",
  "data": {"tool_use_id": "tu_1", "tool_name": "web_search", "tool_input": {"query": "..."}},
  "timestamp": "2026-02-24T12:00:00.000000",
  "correlation_id": null
}
```
