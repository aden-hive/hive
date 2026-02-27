# Execution Intelligence

Execution Intelligence introduces structured runtime tracing for agent executions.

## Phase 1 Overview

Phase 1 adds a lightweight `ExecutionTrace` system that records:

- Graph execution spans
- Per-node execution spans
- LLM call spans (provider-agnostic)
- Tool execution spans

Each span includes:

- `id` (uuid)
- `parent_id` (optional)
- `name`
- `start_time`
- `end_time`
- `metadata`
- `status` (`running`, `success`, `error`)

Traces are persisted to:

- `sessions/<execution_id>/execution_trace.json`

This artifact is deterministic and replay-ready (Phase 2 stub).

## Configuration

Execution tracing is opt-in and disabled by default:

```python
from framework.runtime.agent_runtime import AgentRuntimeConfig

config = AgentRuntimeConfig(
    enable_execution_trace=True,
)
```

When `enable_execution_trace=False`, runtime behavior remains unchanged and does not allocate trace wrappers.

## Runtime Integration

Tracing is integrated at runtime boundaries without changing public APIs:

- `framework.runtime.execution_stream.ExecutionStream`
  - Creates per-execution trace instances
  - Wraps LLM providers and tool executors only when enabled
  - Persists trace artifacts at execution completion

- `framework.graph.executor.GraphExecutor`
  - Records node execution spans for each node step

## Design Notes

- No global trace state is used.
- Trace nesting relies on `contextvars` and works in async execution.
- Serialization uses deterministic insertion ordering for stable replay input.
- Replay entrypoint is present (`ExecutionTrace.replay`) and intentionally deferred to Phase 2.
