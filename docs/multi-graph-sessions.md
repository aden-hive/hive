# Plan: Multi-Graph Sessions with Guardian Pattern

## Context

The target experience: hive_coder builds an agent (e.g., email automation), loads it into the same runtime session, and acts as its guardian. The email agent runs autonomously while hive_coder watches for failures. On error, hive_coder asks the user for help if they're around, attempts an autonomous fix if they're away, and escalates catastrophic failures for post-mortem.

This requires multiple agent graphs sharing a single `AgentRuntime` session — shared memory and data, but isolated conversations. The existing runtime already has most of the primitives: `ExecutionStream` accepts its own `graph`, `trigger_type="event"` subscribes entry points to the EventBus, and `_get_primary_session_state()` bridges memory across streams.

## Architecture Overview

```
AgentRuntime (shared EventBus, shared state.json, shared data/)
├── hive_coder graph
│   ├── Stream "default"     → coder node (client_facing, manual)
│   └── Stream "guardian"    → guardian node (event-driven, subscribes to EXECUTION_FAILED)
└── email_agent graph
    └── Stream "email_agent::default" → intake node (client_facing, manual)
```

The guardian entry point on hive_coder fires when email_agent emits `EXECUTION_FAILED`. It receives the failure event in its input, reads shared memory for context, and decides: ask user (if present), auto-fix (if away), or escalate (if catastrophic).

## Gap 1: Event Scoping — `graph_id` on Events

**Problem**: EventBus events carry `stream_id` and `node_id` but no `graph_id`. The guardian needs to subscribe to events from a specific graph (email_agent), not a specific stream name.

**Solution**: Add `graph_id: str | None = None` to `AgentEvent` and `filter_graph` to `Subscription`.

### `core/framework/runtime/event_bus.py`
- `AgentEvent` dataclass: add `graph_id: str | None = None` field, include in `to_dict()`
- `Subscription` dataclass: add `filter_graph: str | None = None`
- `subscribe()`: accept `filter_graph` param, pass to `Subscription`
- `_matches()`: check `filter_graph` against `event.graph_id`

### `core/framework/runtime/execution_stream.py`
- `__init__()`: accept `graph_id: str | None = None`, store as `self.graph_id`
- When emitting events via `_event_bus.publish()`: set `event.graph_id = self.graph_id`

## Gap 2: Multi-Graph Runtime — `add_graph()` / `remove_graph()`

**Problem**: `AgentRuntime.__init__` takes a single `GraphSpec`. We need to add/remove graphs dynamically at runtime.

**Solution**: Keep the primary graph on `__init__`. Add methods to register secondary graphs that create their own `ExecutionStream` instances backed by a different graph.

### `core/framework/runtime/agent_runtime.py`

New instance state:
```python
self._graph_id: str = graph_id or "primary"  # ID for the primary graph
self._graphs: dict[str, _GraphRegistration] = {}  # graph_id -> registration
self._active_graph_id: str = self._graph_id  # TUI focus
```

Where `_GraphRegistration` is a simple dataclass:
```python
@dataclass
class _GraphRegistration:
    graph: GraphSpec
    goal: Goal
    entry_points: dict[str, EntryPointSpec]
    streams: dict[str, ExecutionStream]
    storage_subpath: str  # relative to session root, e.g. "graphs/email_agent"
    event_subscriptions: list[str]  # EventBus subscription IDs
    timer_tasks: list[asyncio.Task]
```

New methods:
- `add_graph(graph_id, graph, goal, entry_points, storage_subpath=None)` — creates streams for the graph using graph-scoped storage, sets up event/timer triggers, stamps `graph_id` on all streams. Can be called while running.
- `remove_graph(graph_id)` — stops streams, cancels timers, unsubscribes events, removes registration. Cannot remove primary graph.
- `list_graphs() -> list[str]` — returns all graph IDs
- `active_graph_id` property with setter — TUI uses this to control which graph's events are displayed

Update existing methods:
- `start()`: stamp `self._graph_id` on primary graph streams (via `ExecutionStream.graph_id`)
- `inject_input(node_id, content)`: search active graph's streams first, then all others
- `_get_primary_session_state()`: search across ALL graphs' streams (not just primary's)
- `stop()`: stop all secondary graph streams/timers/subscriptions too

### Storage Layout
```
~/.hive/agents/hive_coder/sessions/{session_id}/
    state.json                  ← SHARED across all graphs
    data/                       ← SHARED data directory
    conversations/coder/        ← hive_coder conversations
    graphs/
        email_agent/            ← secondary graph storage root
            conversations/
                intake/
            checkpoints/
```

Secondary graph executors get `storage_path = {session_root}/graphs/{graph_id}/` while `state.json` and `data/` remain at the session root. The `resume_session_id` mechanism in `_get_primary_session_state()` already handles this — secondary executions find the primary session's `state.json`.

**Concurrent state.json writes**: For the guardian pattern (sequential: email_agent fails → guardian triggers), no file lock needed. But since both could technically write concurrently, add a simple `fcntl.flock()` wrapper around `_write_progress()` in the executor. Small, defensive change.

## Gap 3: Guardian Pattern — User Presence + Autonomous Recovery

**Problem**: When email_agent fails, hive_coder's guardian entry point must decide: ask user or auto-fix.

**Solution**: User presence is a runtime-level signal. The guardian's system prompt and event data give it enough context to decide.

### User Presence Tracking
Add to `AgentRuntime`:
```python
self._last_user_input_time: float = 0.0  # monotonic timestamp
```

Updated in `inject_input()` (called whenever user types in TUI). Exposed as:
```python
@property
def user_idle_seconds(self) -> float:
    if self._last_user_input_time == 0:
        return float('inf')
    return time.monotonic() - self._last_user_input_time
```

The guardian node's system prompt instructs the LLM: "If user_idle_seconds < 120, ask the user for guidance via the client-facing interaction. If user is away, attempt an autonomous fix."

This is NOT framework logic — it's prompt-driven. The guardian node is a regular `event_loop` node with `client_facing=True` and tools for code editing + agent lifecycle. The LLM decides the strategy based on presence info injected as context.

### Escalation Model
Escalation = save a structured log entry. No special framework support needed. The guardian node uses `save_data("escalation_log.jsonl", ...)` via the existing data tools. The LLM writes:
```json
{"timestamp": "...", "severity": "catastrophic", "agent": "email_agent", "error": "...", "attempted_fixes": [...], "recommended_action": "..."}
```

Post-mortem: user opens `/data escalation_log.jsonl` or the TUI shows a notification linking to it.

## Gap 4: Graph Lifecycle Tools — Stop/Reload/Restart

**Problem**: hive_coder needs to programmatically stop a broken agent, fix its code, reload it, and restart it.

**Solution**: MCP tools accessible to the active agent. Uses `ContextVar` to access the runtime (same pattern as `data_dir`).

### `core/framework/tools/session_graph_tools.py` (NEW)

```python
async def load_agent(agent_path: str) -> str:
    """Load an agent graph into the running session."""

async def unload_agent(graph_id: str) -> str:
    """Stop and remove an agent graph from the session."""

async def start_agent(graph_id: str, entry_point: str = "default", input_data: str = "{}") -> str:
    """Trigger an entry point on a loaded agent graph."""

async def restart_agent(graph_id: str) -> str:
    """Unload and re-load an agent (picks up code changes)."""

async def list_agents() -> str:
    """List all agent graphs in the current session with their status."""

async def get_user_presence() -> str:
    """Return user idle time and presence status."""
```

These tools call `runtime.add_graph()`, `runtime.remove_graph()`, `runtime.trigger()`, etc.

### Registration
These tools are registered via `ToolRegistry` with `CONTEXT_PARAM` for `runtime` (injected by the executor, same as `data_dir`). Only available when the runtime is multi-graph capable (set by `cmd_code()`).

## Gap 5: TUI Integration — Graph Switching + Background Notifications

### `core/framework/tui/app.py`
- `_route_event()`: check `event.graph_id` against `runtime.active_graph_id`
  - Events from active graph: route normally (streaming, chat, etc.)
  - `CLIENT_INPUT_REQUESTED` from background graph: show notification bar
  - `EXECUTION_FAILED` from background graph: show error notification
  - `EXECUTION_COMPLETED` from background: show brief completion notice
  - Other background events: silent (visible in logs)
- `action_switch_graph(graph_id)`: update `runtime.active_graph_id`, refresh graph view, show header

### `core/framework/tui/widgets/chat_repl.py`
- Track `_input_graph_id: str | None` alongside `_input_node_id`
- `handle_input_requested(node_id, graph_id)`: if background graph, show notification instead of enabling input
- `_submit_input()`: pass `graph_id` to help `inject_input()` route correctly
- New TUI commands:
  - `/graphs` — list loaded graphs and their status
  - `/graph <id>` — switch active graph focus
  - `/load <path>` — load an agent graph into the session
  - `/unload <id>` — remove a graph from the session
- On graph switch: flush streaming state, render graph header separator

### `core/framework/tui/widgets/graph_view.py`
- `switch_graph(graph_id)` — re-render the graph visualization for the new active graph
- When multi-graph active: show tab-like header listing all loaded graphs

## Gap 6: CLI + Runner Integration

### `core/framework/runner/cli.py`
- `cmd_code()` creates the hive_coder runtime with `graph_id="hive_coder"`
- Registers `session_graph_tools` with the tool config so hive_coder's LLM can call them
- Sets `runtime._multi_graph_capable = True` flag

### `core/framework/runner/runner.py`
- New method: `setup_as_secondary(runtime, graph_id)` — configures this runner to join an existing `AgentRuntime` as a secondary graph. Uses the existing `AgentRunner.load()` to parse agent.json, then calls `runtime.add_graph()` with the parsed graph/goal/entry_points.

## Gap 7: Reliable Mid-Node Resume

**Problem**: When an EventLoopNode is interrupted (crash, Ctrl+Z, context switch), resume doesn't restore to exactly where execution stopped. Several pieces of in-node state are lost, which changes behavior post-resume. In multi-graph sessions with parallel execution and frequent context switching, these gaps compound.

### What's already restored correctly
- **Conversation history**: All messages persisted to disk immediately via `FileConversationStore._persist()` — one file per message in `parts/NNNNNNNNNN.json`
- **OutputAccumulator values**: Write-through to `cursor.json` on every `accumulator.set()` call
- **Iteration counter**: Written to `cursor.json` at the end of each iteration (step 6g)
- **Orphaned tool calls**: `_repair_orphaned_tool_calls()` patches in-flight tool calls with error messages so the LLM knows to retry

### What's lost — and fixes

#### 1. `user_interaction_count` (CRITICAL)
Resets to 0 on resume. This controls client-facing blocking semantics: before the first interaction, `set_output`-only turns don't prevent blocking (the LLM must present to the user first). After resume, a node that had 3 user interactions behaves as if the user never interacted.

**Fix**: Persist `user_interaction_count` to `cursor.json` alongside `iteration` and `outputs`. Write it in `_write_cursor()` (step 6g), restore in `_restore()`.

**Files**: `core/framework/graph/event_loop_node.py`

#### 2. Accumulator outputs not in SharedMemory
The `OutputAccumulator` writes to `cursor.json` (durable) but only writes to `SharedMemory` when the judge ACCEPTs. On crash, the CancelledError handler captures `memory.read_all()` — which doesn't include the accumulator's WIP values. On resume, edge conditions checking those memory keys see `None`.

**Fix**: In the executor's `CancelledError` handler, read the interrupted node's `cursor.json` and write any accumulator outputs to `memory` before building `session_state_out`. This ensures resume memory includes WIP output values.

**Files**: `core/framework/graph/executor.py` (CancelledError handler, ~line 1289)

#### 3. Stall/doom-loop detection counters
`recent_responses` and `recent_tool_fingerprints` reset to empty lists. A previously near-stalled node gets a fresh detection budget.

**Fix**: Persist these to `cursor.json`. They're small (last N strings). Write in `_write_cursor()`, restore in `_restore()`.

**Files**: `core/framework/graph/event_loop_node.py`

#### 4. `continuous_conversation` at executor level
In continuous mode, the executor's `continuous_conversation` variable is `None` on resume. The node's `_restore()` recovers messages from disk, but the executor doesn't pre-populate this variable until the node returns.

**Fix**: After a resumed node completes, set `continuous_conversation = result.conversation` (this already happens in the normal path at line 1155 — verify it also runs on the resume path).

**Files**: `core/framework/graph/executor.py`

### Multi-graph specific: independent resume per graph
Each graph in a multi-graph session has its own storage subdirectory (`graphs/{graph_id}/`) with its own `conversations/`, `checkpoints/`, and `cursor.json` files. Resume is already per-executor, so each graph resumes independently. The shared `state.json` at the session root captures the union of all graphs' memory — the `fcntl.flock()` wrapper on `_write_progress()` (Gap 2) ensures concurrent writes don't corrupt it.

### Implementation
These fixes are prerequisite to multi-graph and should be done as **Phase 0** before the EventBus changes:
1. Persist `user_interaction_count` + stall/doom counters to `cursor.json`
2. Restore them in `_restore()`
3. Flush accumulator outputs to SharedMemory in executor's CancelledError handler
4. Verify continuous_conversation is set on resume path

## Implementation Phases

### Phase 0: Reliable Mid-Node Resume (prerequisite)
1. `event_loop_node.py` — persist `user_interaction_count`, `recent_responses`, `recent_tool_fingerprints` to `cursor.json` via `_write_cursor()`; restore in `_restore()`
2. `executor.py` — in CancelledError handler, read interrupted node's `cursor.json` accumulator outputs and write to `memory` before building `session_state_out`
3. `executor.py` — verify `continuous_conversation` is populated on resume path

### Phase 1: EventBus Foundation
1. `event_bus.py` — `graph_id` on `AgentEvent`, `filter_graph` on `Subscription` + `_matches()`
2. `execution_stream.py` — accept and stamp `graph_id` on emitted events

### Phase 2: Multi-Graph Runtime
3. `agent_runtime.py` — `_GraphRegistration` dataclass, `add_graph()`, `remove_graph()`, `list_graphs()`, `active_graph_id` property
4. `agent_runtime.py` — update `inject_input()`, `_get_primary_session_state()`, `stop()` for multi-graph
5. `agent_runtime.py` — user presence tracking (`_last_user_input_time`, `user_idle_seconds`)
6. Storage path logic: secondary graphs get `{session_root}/graphs/{graph_id}/`

### Phase 3: Graph Lifecycle Tools
7. `core/framework/tools/session_graph_tools.py` — `load_agent`, `unload_agent`, `start_agent`, `restart_agent`, `list_agents`, `get_user_presence`
8. `runner.py` — `setup_as_secondary()` method

### Phase 4: TUI Integration
9. `app.py` — `graph_id` event filtering, background notifications, `action_switch_graph`
10. `chat_repl.py` — `/graphs`, `/graph`, `/load`, `/unload` commands, graph_id tracking
11. `graph_view.py` — multi-graph header, `switch_graph()`

### Phase 5: hive_coder Integration
12. `cli.py` — `cmd_code()` sets up multi-graph capable runtime, registers graph tools
13. hive_coder's agent config — add guardian entry point with `trigger_type="event"` subscribing to `EXECUTION_FAILED`
14. Guardian node system prompt — presence-aware triage logic (ask user / auto-fix / escalate)

## Backward Compatibility
- Single-graph `hive run exports/my_agent` unchanged: `graph_id` defaults to `None`, no secondary graphs loaded, events carry `graph_id=None`, TUI shows no graph switching UI
- All new fields are optional with `None` defaults
- `_get_primary_session_state()` existing behavior preserved when no secondary graphs exist

## Verification
1. **Unit**: `add_graph()` creates streams with correct `graph_id`, events carry `graph_id`, `filter_graph` works in subscriptions, `inject_input()` routes to correct graph
2. **Integration**: Load hive_coder + email_agent, email_agent fails → guardian fires → reads shared memory → decides action
3. **TUI**: `/graphs` shows both, `/graph` switches, background failure notification appears, input routing works across graphs
4. **Backward compat**: `hive run exports/deep_research_agent --tui` works unchanged
5. **Lifecycle**: `restart_agent` picks up code changes, `unload_agent` cleans up streams and subscriptions
