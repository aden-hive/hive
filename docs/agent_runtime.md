# Agent Runtime

Unified execution system for all Hive agents. Every agent — single-entry or multi-entry, headless or TUI — runs through the same runtime stack.

## Topology

```
                     AgentRunner.load(agent_path)
                              |
                         AgentRunner
                     (factory + public API)
                              |
                       _setup_agent_runtime()
                              |
                        AgentRuntime
                   (lifecycle + orchestration)
                      /       |       \\
               Stream A   Stream B   Stream C    ← one per entry point
                  |           |          |
            GraphExecutor  GraphExecutor  GraphExecutor
                  |           |          |
              Node → Node → Node  (graph traversal)
```

Single-entry agents get a `"default"` entry point automatically. There is no separate code path.

## Components

| Component | File | Role |
| --- | --- | --- |
| `AgentRunner` | `runner/runner.py` | Load agents, configure tools/LLM, expose high-level API |
| `AgentRuntime` | `runtime/agent_runtime.py` | Lifecycle management, entry point routing, event bus |
| `ExecutionStream` | `runtime/execution_stream.py` | Per-entry-point execution queue, session persistence |
| `GraphExecutor` | `graph/executor.py` | Node traversal, tool dispatch, checkpointing |
| `EventBus` | `runtime/event_bus.py` | Pub/sub for execution events (streaming, I/O) |
| `SharedStateManager` | `runtime/shared_state.py` | Cross-stream state with isolation levels |
| `OutcomeAggregator` | `runtime/outcome_aggregator.py` | Goal progress tracking across streams |
| `SessionStore` | `storage/session_store.py` | Session state persistence (`sessions/{id}/state.json`) |

## Programming Interface

### AgentRunner (high-level)

```python
from framework.runner import AgentRunner

# Load and run
runner = AgentRunner.load("exports/my_agent", model="anthropic/claude-sonnet-4-20250514")
result = await runner.run({"query": "hello"})

# Resume from paused session
result = await runner.run({"query": "continue"}, session_state=saved_state)

# Lifecycle
await runner.start()                           # Start the runtime
await runner.stop()                            # Stop the runtime
exec_id = await runner.trigger("default", {})  # Non-blocking trigger
progress = await runner.get_goal_progress()    # Goal evaluation
entry_points = runner.get_entry_points()       # List entry points

# Context manager
async with AgentRunner.load("exports/my_agent") as runner:
    result = await runner.run({"query": "hello"})

# Cleanup
runner.cleanup()          # Synchronous
await runner.cleanup_async()  # Asynchronous
```

### AgentRuntime (lower-level)

```python
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

# Create runtime with entry points
runtime = create_agent_runtime(
    graph=graph,
    goal=goal,
    storage_path=Path("~/.hive/agents/my_agent"),
    entry_points=[
        EntryPointSpec(id="default", name="Default", entry_node="start", trigger_type="manual"),
    ],
    llm=llm,
    tools=tools,
    tool_executor=tool_executor,
    checkpoint_config=checkpoint_config,
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
runtime.state_manager        # SharedStateManager
runtime.get_stats()          # Runtime statistics
```

## Execution Flow

1. `AgentRunner.run()` calls `AgentRuntime.trigger_and_wait()`
2. `AgentRuntime` routes to the `ExecutionStream` for the entry point
3. `ExecutionStream` creates a `GraphExecutor` and calls `execute()`
4. `GraphExecutor` traverses nodes, dispatches tools, manages checkpoints
5. `ExecutionResult` flows back up through the stack
6. `ExecutionStream` writes session state to disk

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

Session state flows: `AgentRunner.run()` → `AgentRuntime.trigger_and_wait()` → `ExecutionStream.execute()` → `GraphExecutor.execute()`.

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

In headless mode, `AgentRunner` subscribes to `CLIENT_OUTPUT_DELTA` and `CLIENT_INPUT_REQUESTED` to print output and read stdin. In TUI mode, `AdenTUI` subscribes to route events to UI widgets.

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