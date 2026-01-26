# Execution Trace Inspector

A comprehensive debugging and observability tool for analyzing agent executions.

## Overview

The `TraceInspector` provides detailed inspection of agent executions including:
- **Decision Timeline**: Chronological view of all decisions made during execution
- **State Inspection**: Capture and inspect state at any point in execution
- **Cost Analysis**: Detailed breakdown of LLM costs and token usage
- **Performance Profiling**: Identify bottlenecks and slow operations
- **Problem Detection**: Automatic detection of issues and failures
- **Export/Import**: Save traces for offline analysis

## Usage

### Basic Usage

```python
from framework.runtime.trace_inspector import TraceInspector

# Create inspector
inspector = TraceInspector(storage_path="./traces")

# Start tracking an execution
trace = inspector.start_trace(
    execution_id="exec_123",
    stream_id="webhook",
    goal_id="goal_1",
    input_data={"ticket_id": "123"},
)

# During execution, add events
trace.add_decision(decision)
trace.record_outcome(decision_id, outcome)
trace.add_event("llm_call", data={"tokens": 1000, "cost_usd": 0.01})
trace.capture_state_snapshot("checkpoint_1", current_state)

# Complete the trace
trace.complete("completed", output_data={"result": "success"})

# Analyze the trace
analysis = inspector.analyze(trace)
print(analysis["summary"])
print(analysis["recommendations"])
```

### CLI Usage

```bash
# Step 1: List available traces (to find execution_id)
python3 -m framework trace-inspect --list --agent-path ./exports/my_agent

# Step 2: Inspect a specific trace
python3 -m framework trace-inspect <execution_id> --agent-path ./exports/my_agent

# Example with actual execution_id:
python3 -m framework trace-inspect exec_main_fb04a5c8 --agent-path ./exports/test_agent

# Show detailed timeline
python3 -m framework trace-inspect <execution_id> --agent-path ./exports/my_agent --timeline

# Inspect a trace from JSON file (if exported)
python3 -m framework trace-inspect <execution_id> --trace-file trace.json

# Export analysis to JSON
python3 -m framework trace-inspect <execution_id> --agent-path ./exports/my_agent --export analysis.json

# Output as JSON
python3 -m framework trace-inspect <execution_id> --agent-path ./exports/my_agent --json
```

**Quick Start:**
1. Run an agent to generate traces:
   ```bash
   python3 -m framework run ./exports/my_agent --input '{"query": "test"}'
   ```

2. List available traces:
   ```bash
   python3 -m framework trace-inspect --list --agent-path ./exports/my_agent
   ```

3. Inspect a trace (use execution_id from step 2):
   ```bash
   python3 -m framework trace-inspect <execution_id> --agent-path ./exports/my_agent
   ```

## Architecture

The trace collection system integrates seamlessly with both execution architectures:

### Execution Paths

The framework supports two execution paths, both with trace collection:

#### 1. Multi-Entry-Point Agents (AgentRuntime)

For agents with `async_entry_points`, trace collection flows through:

```
AgentRuntime
  └─> TraceInspector (initialized at runtime creation)
      └─> ExecutionStream (per entry point)
          └─> _run_execution()
              ├─> TraceInspector.start_trace()  # Start trace
              ├─> StreamRuntimeAdapter (with trace reference)
              │   ├─> decide() → trace.add_decision()
              │   └─> record_outcome() → trace.record_outcome()
              └─> TraceInspector.complete_trace()  # Auto-save on completion
```

**Key Components:**
- `AgentRuntime`: Initializes `TraceInspector` and passes it to `ExecutionStream`
- `ExecutionStream`: Creates traces at execution start, stores in `ExecutionContext`
- `StreamRuntimeAdapter`: Intercepts `decide()` and `record_outcome()` calls to populate trace
- Auto-save: Traces saved to `{storage_path}/traces/{execution_id}.json` on completion

#### 2. Single-Entry-Point Agents (GraphExecutor)

For legacy single-entry-point agents, trace collection uses a wrapper pattern:

```
AgentRunner
  └─> TraceInspector (initialized at runner creation)
      └─> _run_with_executor()
          ├─> TraceInspector.start_trace()  # Start trace
          ├─> TracedRuntime (wrapper around Runtime)
          │   └─> end_run() hook
          │       └─> Collects all decisions/outcomes before Runtime clears them
          └─> TraceInspector.complete_trace()  # Auto-save on completion
```

**Key Components:**
- `AgentRunner`: Initializes `TraceInspector` and manages trace lifecycle
- `TracedRuntime`: Wrapper class that intercepts `Runtime.end_run()` to extract trace data
  - **Why needed**: `Runtime` clears run data in `end_run()`, so we must capture it first
  - **How it works**: `__getattr__` forwards all calls to base `Runtime`, except `end_run()` which collects trace data first
- Auto-save: Same as multi-entry-point path

### Trace Data Flow

```
Execution Start
  ↓
TraceInspector.start_trace()
  → Creates ExecutionTrace object
  → Stores in memory (_traces dict)
  ↓
During Execution
  ├─> Decisions: trace.add_decision(decision)
  ├─> Outcomes: trace.record_outcome(decision_id, outcome)
  ├─> Events: trace.add_event(event_type, data)
  └─> State: trace.capture_state_snapshot(checkpoint, state)
  ↓
Execution Complete
  ↓
TraceInspector.complete_trace()
  → trace.complete(status, output_data)
  → _save_trace(trace)  # Auto-save to disk
  → JSON file: {storage_path}/traces/{execution_id}.json
```

### Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| `TraceInspector` | Central trace manager, storage, analysis |
| `ExecutionTrace` | In-memory trace data structure |
| `StreamRuntimeAdapter` | Captures decisions/outcomes for multi-entry-point agents |
| `TracedRuntime` | Captures decisions/outcomes for single-entry-point agents |
| `ExecutionStream` | Orchestrates trace lifecycle for concurrent executions |
| `AgentRunner` | Orchestrates trace lifecycle for single executions |

### Thread Safety

- `TraceInspector`: Thread-safe (uses in-memory dict, file I/O is atomic)
- `ExecutionTrace`: Not thread-safe (one trace per execution, single-threaded execution context)
- Multiple executions can run concurrently, each with its own trace

### Storage

Traces are stored as JSON files:
- **Location**: `{storage_path}/traces/{execution_id}.json`
- **Format**: JSON with ISO datetime strings
- **Auto-save**: On trace completion (success, failure, or pause)
- **Persistence**: Survives runtime restarts

## Integration with Runtime

The `TraceInspector` is automatically available in both execution paths:

### AgentRuntime (Multi-Entry-Point)

```python
from framework.runtime import AgentRuntime

runtime = AgentRuntime(...)
await runtime.start()

# Access trace inspector
inspector = runtime.trace_inspector

# Traces are automatically saved to storage/traces/ when executions complete
```

### AgentRunner (Single-Entry-Point)

```python
from framework.runner import AgentRunner

runner = AgentRunner.load("exports/my_agent")
result = await runner.run({"input": "data"})

# Access trace inspector
inspector = runner.trace_inspector

# Traces are automatically saved to ~/.hive/storage/{agent_name}/traces/
```

## Analysis Output

The analysis includes:

- **Summary**: High-level execution summary
- **Timeline**: Chronological event timeline
- **Decisions**: Decision analysis with success rates
- **Performance**: Latency metrics and bottlenecks
- **Cost**: Cost breakdown per decision/token
- **Problems**: Detected issues (failures, slow execution, high cost)
- **Recommendations**: Suggested improvements

## Export/Import

Traces can be exported to JSON for offline analysis:

```python
# Export
inspector.export_trace(trace, "trace.json")

# Import later
trace = inspector.import_trace("trace.json")
analysis = inspector.analyze(trace)
```

## Example Analysis Output

```
Execution Trace Analysis
============================================================

Execution ID: exec_123
Status: completed
Duration: 5234ms

Summary:
  ✓ Execution completed | Duration: 5234ms | Decisions: 5 | LLM calls: 3 | Tool calls: 2 | Cost: $0.0234 | Success rate: 80.0%

Decisions:
  Total: 5
  Successful: 4
  Failed: 1
  Success Rate: 80.0%

Failed Decisions:
  - [node_3] Search for user data
    Error: API timeout

Performance:
  Total Duration: 5234ms
  Avg Decision Latency: 1046ms
  Max Decision Latency: 2500ms
  Nodes Executed: 5
  Insights:
    - 1 decisions took >5s

Cost:
  Total: $0.0234
  Per Decision: $0.004680
  Per Token: $0.000023
  Total Tokens: 1,020

Problems Detected:
  ⚠️ [warning] Execution took 5234ms
  🔴 [error] 1 decisions failed

Recommendations:
  • Consider improving decision logic - success rate is low
  • High decision latency - consider caching or optimization
```

## Features

### Automatic Metrics Collection

The inspector automatically tracks:
- Decision counts and success rates
- LLM call counts and token usage
- Tool call frequencies
- Latency metrics (avg, max per decision)
- Cost calculations

### Problem Detection

Automatically detects:
- Failed decisions
- Slow executions (>1 minute)
- High costs (>$1.00)
- Excessive LLM calls (>50)

### Recommendations

Provides actionable recommendations:
- Low success rates
- High retry counts
- Cost inefficiencies
- Performance bottlenecks

## Storage

Traces are automatically saved to `{storage_path}/traces/{execution_id}.json` when:
- An execution completes
- A trace is explicitly completed

This allows for persistent trace storage and later analysis.
