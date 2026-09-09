# Agent Runtime

> **Scope:** this describes the **standalone agent** execution stack (`AgentLoader` → `AgentHost` → `Orchestrator`), used for single, exportable agents defined with the legacy `nodes`/`edges` format. The **live colony runtime** is different: a session starts a `ColonyRuntime` whose Queen and workers are each an `AgentLoop`, coordinating through the shared [tracker](key_concepts/coordination.md#the-tracker) with no graph traversal. Read the [Architecture Overview](architecture/README.md) for the colony model; read on here for the standalone path.
>
> **Name history:** older revisions of this document (and some code docstrings / log
> strings) call these `AgentRunner`, `AgentRuntime`, `ExecutionStream`, and
> `GraphExecutor`. Those names no longer exist as modules or classes: `AgentRunner`
> is now `AgentLoader`, the runtime class is `AgentHost`, the per-entry-point
> stream is `ExecutionManager`, and graph traversal is `Orchestrator`. The table
> below maps each old name to its current location.

Execution system for standalone Hive agents. A standalone agent — single-entry or multi-entry, headless or TUI — runs through the runtime stack below.

## Topology

```text
                      AgentLoader.load(agent_path)
                               |
                          AgentLoader
                     (loader + public API)
                               |
                            _setup()
                               |
                           AgentHost
                    (lifecycle + orchestration)
                       /       |       \
                Stream A   Stream B   Stream C    ← one per entry point
                   |           |          |
              Orchestrator Orchestrator Orchestrator
                   |           |          |
               Node → Node → Node  (graph traversal)
```

Single-entry agents get a `"default"` entry point automatically (registered from `graph.entry_node` during `AgentLoader._setup()`). There is no separate code path.

## Components

| Component | File | Role |
| --- | --- | --- |
| `AgentLoader` (was `AgentRunner`) | `loader/agent_loader.py` | Load agents, configure tools/LLM, expose high-level API |
| `AgentHost` (was `AgentRuntime`) | `host/agent_host.py` | Lifecycle management, entry point routing, event bus |
| `ExecutionManager` (was `ExecutionStream`) | `host/execution_manager.py` | Per-entry-point execution queue, session persistence |
| `Orchestrator` (was `GraphExecutor`) | `orchestrator/orchestrator.py` | Node traversal, tool dispatch, checkpointing |
| `EventBus` | `host/event_bus.py` | Pub/sub for execution events (streaming, I/O) |
| `SharedBufferManager` | `host/shared_state.py` | Cross-stream state with isolation levels |
| `OutcomeAggregator` | `host/outcome_aggregator.py` | Goal progress tracking across streams |
| `SessionStore` | `storage/session_store.py` | Session state persistence (`sessions/{id}/state.json`) |

Paths are relative to `core/framework/`. `core/framework/runtime/` contains only
`tests/` — there is no `framework.runtime` package, so any `framework.runtime.*`
or `framework.runner.*` import is stale.

## Programming Interface

### AgentLoader (high-level)

```python
from framework.loader.agent_loader import AgentLoader

# Load and run
runner = AgentLoader.load("exports/my_agent", model="anthropic/claude-sonnet-4-20250514")
result = await runner.run({"query": "hello"})

# Resume from paused session
result = await runner.run({"query": "continue"}, session_state=saved_state)

# Lifecycle
await runner.start()                           # Start the runtime
await runner.stop()                            # Stop the runtime
exec_id = await runner.trigger("default", {})  # Non-blocking trigger
entry_points = runner.get_entry_points()       # List entry points

# Context manager
async with AgentLoader.load("exports/my_agent") as runner:
    result = await runner.run({"query": "hello"})

# Cleanup
runner.cleanup()          # Synchronous
await runner.cleanup_async()  # Asynchronous
```

### AgentHost (lower-level)

```python
from pathlib import Path

from framework.host.agent_host import AgentHost
from framework.host.execution_manager import EntryPointSpec

# Create runtime and register entry points
runtime = AgentHost(
    graph=graph,
    goal=goal,
    storage_path=Path("~/.hive/agents/my_agent"),
    llm=llm,
    tools=tools,
    tool_executor=tool_executor,
    checkpoint_config=checkpoint_config,
)
runtime.register_entry_point(
    EntryPointSpec(id="default", name="Default", entry_node="start", trigger_type="manual"),
)

# Lifecycle
await runtime.start()
await runtime.stop()

# Execution
exec_id = await runtime.trigger("default", {"query": "hello"})              # Non-blocking
result = await runtime.trigger_and_wait("default", {"query": "hello"})      # Blocking
result = await runtime.trigger_and_wait("default", {}, session_state=state) # Resume

# Client-facing node I/O
await runtime.inject_input(node_id="chat", content="user response")

# Events
sub_id = runtime.subscribe_to_events(
    event_types=[EventType.CLIENT_OUTPUT_DELTA],
    handler=my_handler,
)
runtime.unsubscribe_from_events(sub_id)

# Inspection
runtime.is_running           # bool
runtime.event_bus            # EventBus
runtime.state_manager        # SharedBufferManager
runtime.get_stats()          # Runtime statistics
```

## Execution Flow

1. `AgentLoader.run()` calls `AgentHost.trigger_and_wait()`
2. `AgentHost` routes to the `ExecutionManager` for the entry point
3. `ExecutionManager` creates an `Orchestrator` and calls `execute()`
4. `Orchestrator` traverses nodes, dispatches tools, manages checkpoints
5. `ExecutionResult` flows back up through the stack
6. `ExecutionManager` writes session state to disk

## Session Resume

All execution paths support session resume:

```python
# First run (agent pauses at a client-facing node)
result = await runner.run({"query": "start task"})
# result.paused_at = "review-node"
# result.session_state = {"memory": {...}, "paused_at": "review-node", ...}

# Resume
result = await runner.run({"input": "approved"}, session_state=result.session_state)
```

Session state flows: `AgentLoader.run()` → `AgentHost.trigger_and_wait()` → `ExecutionManager` execution → `Orchestrator.execute()`.

Checkpoints are saved at node boundaries (`sessions/{id}/checkpoints/`) for crash recovery.

## Event Bus

The `EventBus` provides real-time execution visibility:

| Event | When |
| --- | --- |
| `NODE_STARTED` | Node begins execution |
| `NODE_COMPLETED` | Node finishes |
| `TOOL_CALL_STARTED` | Tool invocation begins |
| `TOOL_CALL_COMPLETED` | Tool invocation finishes |
| `CLIENT_OUTPUT_DELTA` | Agent streams text to user |
| `CLIENT_INPUT_REQUESTED` | Agent needs user input |
| `EXECUTION_COMPLETED` | Full execution finishes |

In headless mode, `AgentLoader` subscribes to `CLIENT_OUTPUT_DELTA` and `CLIENT_INPUT_REQUESTED` to print output and read stdin. In TUI mode, `AdenTUI` subscribes to route events to UI widgets.

## Storage Layout

```
~/.hive/agents/{agent_name}/
  sessions/
    session_YYYYMMDD_HHMMSS_{uuid}/
      state.json              # Session state (status, memory, progress)
      checkpoints/            # Node-boundary snapshots
      logs/
        summary.json          # Execution summary
        details.jsonl         # Detailed event log
        tool_logs.jsonl       # Tool call log
  runtime_logs/               # Cross-session runtime logs
```
