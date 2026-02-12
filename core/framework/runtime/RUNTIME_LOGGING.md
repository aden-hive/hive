# Runtime Logging System

## Overview

The Hive framework uses a **three-level observability system** for tracking agent execution at different granularities:

- **L1 (Summary)**: High-level run outcomes - success/failure, execution quality, attention flags
- **L2 (Details)**: Per-node completion details - retries, verdicts, latency, attention reasons
- **L3 (Tool Logs)**: Step-by-step execution - tool calls, LLM responses, judge feedback

This layered approach enables efficient debugging: start with L1 to identify problematic runs, drill into L2 to find failing nodes, and analyze L3 for root cause details.

---

## Storage Architecture

### Current Structure (Unified Sessions)

**Default since 2026-02-06**

```
~/.hive/agents/{agent_name}/
└── sessions/
    └── session_YYYYMMDD_HHMMSS_{uuid}/
        ├── state.json           # Session state and metadata
        ├── logs/                # Runtime logs (L1/L2/L3)
        │   ├── summary.json     # L1: Run outcome
        │   ├── details.jsonl    # L2: Per-node results
        │   └── tool_logs.jsonl  # L3: Step-by-step execution
        ├── conversations/       # Per-node EventLoop state
        └── data/                # Spillover artifacts
```

**Key characteristics:**
- All session data colocated in one directory
- Consistent ID format: `session_YYYYMMDD_HHMMSS_{short_uuid}`
- Logs written incrementally (JSONL for L2/L3)
- Single source of truth: `state.json`

### Legacy Structure (Deprecated)

**Read-only for backward compatibility**

```
~/.hive/agents/{agent_name}/
├── runtime_logs/
│   └── runs/
│       └── {run_id}/
│           ├── summary.json     # L1
│           ├── details.jsonl    # L2
│           └── tool_logs.jsonl  # L3
├── sessions/
│   └── exec_{stream_id}_{uuid}/
│       ├── conversations/
│       └── data/
├── runs/                        # Deprecated
│   └── run_start_*.json
└── summaries/                   # Deprecated
    └── run_start_*.json
```

**Migration status:**
- ✅ New sessions write to unified structure only
- ✅ Old sessions remain readable
- ❌ No new writes to `runs/`, `summaries/`, `runtime_logs/runs/`
- ⚠️ Deprecation warnings emitted when reading old locations

---

## Components

### RuntimeLogger

**Location:** `core/framework/runtime/runtime_logger.py`

**Responsibilities:**
- Receives execution events from GraphExecutor
- Tracks per-node execution details
- Aggregates attention flags
- Coordinates with RuntimeLogStore

**Key methods:**
```python
def start_run(goal_id: str, session_id: str = "") -> str:
    """Initialize a new run. Uses session_id as run_id if provided."""

def log_step(node_id: str, step_index: int, tool_calls: list, ...):
    """Record one LLM step (L3). Appends to tool_logs.jsonl immediately."""

def log_node_complete(node_id: str, exit_status: str, ...):
    """Record node completion (L2). Appends to details.jsonl immediately."""

async def end_run(status: str):
    """Finalize run, aggregate L2→L1, write summary.json."""
```

**Attention flag triggers:**
```python
# From runtime_logger.py:190-203
needs_attention = any([
    retry_count > 3,
    escalate_count > 2,
    latency_ms > 60000,
    tokens_used > 100000,
    total_steps > 20,
])
```

### RuntimeLogStore

**Location:** `core/framework/runtime/runtime_log_store.py`

**Responsibilities:**
- Manages log file I/O
- Handles both old and new storage paths
- Provides incremental append for L2/L3 (crash-safe)
- Atomic writes for L1

**Storage path resolution:**
```python
def _get_run_dir(run_id: str) -> Path:
    """Determine log directory based on run_id format.

    - session_* → {storage_root}/sessions/{run_id}/logs/
    - Other     → {base_path}/runtime_logs/runs/{run_id}/ (deprecated)
    """
```

**Key methods:**
```python
def ensure_run_dir(run_id: str):
    """Create log directory immediately at start_run()."""

def append_step(run_id: str, step: NodeStepLog):
    """Append L3 entry to tool_logs.jsonl. Thread-safe sync write."""

def append_node_detail(run_id: str, detail: NodeDetail):
    """Append L2 entry to details.jsonl. Thread-safe sync write."""

async def save_summary(run_id: str, summary: RunSummaryLog):
    """Write L1 summary.json atomically at end_run()."""
```

**File format:**
- **L1 (summary.json)**: Standard JSON, written once at end
- **L2 (details.jsonl)**: JSONL (one object per line), appended per node
- **L3 (tool_logs.jsonl)**: JSONL (one object per line), appended per step

### Runtime Log Schemas

**Location:** `core/framework/runtime/runtime_log_schemas.py`

**L1: RunSummaryLog**
```python
@dataclass
class RunSummaryLog:
    run_id: str
    goal_id: str
    status: str  # "success", "failure", "degraded", "in_progress"
    started_at: str  # ISO 8601
    ended_at: str | None
    needs_attention: bool
    attention_summary: AttentionSummary
    total_nodes_executed: int
    nodes_with_failures: list[str]
    execution_quality: str  # "clean", "degraded", "failed"
    total_latency_ms: int
    # ... additional metrics
```

**L2: NodeDetail**
```python
@dataclass
class NodeDetail:
    node_id: str
    exit_status: str  # "success", "escalate", "no_valid_edge"
    retry_count: int
    verdict_counts: dict[str, int]  # {ACCEPT: 1, RETRY: 3, ...}
    total_steps: int
    latency_ms: int
    needs_attention: bool
    attention_reasons: list[str]
    # ... tool error tracking, token counts
```

**L3: NodeStepLog**
```python
@dataclass
class NodeStepLog:
    node_id: str
    step_index: int
    tool_calls: list[dict]
    tool_results: list[dict]
    verdict: str  # "ACCEPT", "RETRY", "ESCALATE", "CONTINUE"
    verdict_feedback: str
    llm_response_text: str
    tokens_used: int
    latency_ms: int
    # ... detailed execution state
    # Trace context (OTel-aligned; empty if observability context not set):
    trace_id: str   # From set_trace_context (OTel trace)
    span_id: str    # 16 hex chars per step (OTel span)
    parent_span_id: str  # Optional; for nested span hierarchy
    execution_id: str    # Session/run correlation id
```

L3 entries include `trace_id`, `span_id`, and `execution_id` for correlation and **OpenTelemetry (OTel) compatibility**. When the framework sets trace context (e.g. via `Runtime.start_run()` or `StreamRuntime.start_run()`), these fields are populated automatically so L3 data can be exported to OTel backends without schema changes.

**L2: NodeDetail** also includes `trace_id` and `span_id`; **L1: RunSummaryLog** includes `trace_id` and `execution_id` for the same correlation.

---

## Querying Logs (MCP Tools)

### Tools Location

**MCP Server:** `tools/src/aden_tools/tools/runtime_logs_tool/runtime_logs_tool.py`

Three MCP tools provide access to the logging system:

### L1: query_runtime_logs

**Purpose:** Find problematic runs

```python
query_runtime_logs(
    agent_work_dir: str,        # e.g., "~/.hive/agents/deep_research_agent"
    status: str = "",           # "needs_attention", "success", "failure", "degraded"
    limit: int = 20
) -> dict  # {"runs": [...], "total": int}
```

**Returns:**
```json
{
  "runs": [
    {
      "run_id": "session_20260206_115718_e22339c5",
      "status": "degraded",
      "needs_attention": true,
      "attention_summary": {
        "total_attention_flags": 3,
        "categories": ["missing_outputs", "retry_loops"]
      },
      "started_at": "2026-02-06T11:57:18Z"
    }
  ],
  "total": 1
}
```

**Common queries:**
```python
# Find all problematic runs
query_runtime_logs(agent_work_dir, status="needs_attention")

# Get recent runs regardless of status
query_runtime_logs(agent_work_dir, limit=10)

# Check for failures
query_runtime_logs(agent_work_dir, status="failure")
```

### L2: query_runtime_log_details

**Purpose:** Identify which nodes failed

```python
query_runtime_log_details(
    agent_work_dir: str,
    run_id: str,                    # From L1 query
    needs_attention_only: bool = False,
    node_id: str = ""               # Filter to specific node
) -> dict  # {"run_id": str, "nodes": [...]}
```

**Returns:**
```json
{
  "run_id": "session_20260206_115718_e22339c5",
  "nodes": [
    {
      "node_id": "intake-collector",
      "exit_status": "escalate",
      "retry_count": 5,
      "verdict_counts": {"RETRY": 5, "ESCALATE": 1},
      "attention_reasons": ["high_retry_count", "missing_outputs"],
      "total_steps": 8,
      "latency_ms": 12500,
      "needs_attention": true
    }
  ]
}
```

**Common queries:**
```python
# Get all problematic nodes
query_runtime_log_details(agent_work_dir, run_id, needs_attention_only=True)

# Analyze specific node across run
query_runtime_log_details(agent_work_dir, run_id, node_id="intake-collector")

# Full node breakdown
query_runtime_log_details(agent_work_dir, run_id)
```

### L3: query_runtime_log_raw

**Purpose:** Root cause analysis

```python
query_runtime_log_raw(
    agent_work_dir: str,
    run_id: str,
    step_index: int = -1,           # Specific step or -1 for all
    node_id: str = ""               # Filter to specific node
) -> dict  # {"run_id": str, "steps": [...]}
```

**Returns:**
```json
{
  "run_id": "session_20260206_115718_e22339c5",
  "steps": [
    {
      "node_id": "intake-collector",
      "step_index": 3,
      "tool_calls": [
        {
          "tool": "web_search",
          "args": {"query": "@RomuloNevesOf"}
        }
      ],
      "tool_results": [
        {
          "status": "success",
          "data": "..."
        }
      ],
      "verdict": "RETRY",
      "verdict_feedback": "Missing required output 'twitter_handles'. You found the handle but didn't call set_output.",
      "llm_response_text": "I found the Twitter profile...",
      "tokens_used": 1234,
      "latency_ms": 2500
    }
  ]
}
```

**Common queries:**
```python
# All steps for a problematic node
query_runtime_log_raw(agent_work_dir, run_id, node_id="intake-collector")

# Specific step analysis
query_runtime_log_raw(agent_work_dir, run_id, step_index=5)

# Full execution trace
query_runtime_log_raw(agent_work_dir, run_id)
```

---

## Usage Patterns

### Pattern 1: Top-Down Investigation

**Use case:** Debug a failing agent

```python
# 1. Find problematic runs (L1)
result = query_runtime_logs(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    status="needs_attention"
)
run_id = result["runs"][0]["run_id"]

# 2. Identify failing nodes (L2)
details = query_runtime_log_details(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    run_id=run_id,
    needs_attention_only=True
)
problem_node = details["nodes"][0]["node_id"]

# 3. Analyze root cause (L3)
raw = query_runtime_log_raw(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    run_id=run_id,
    node_id=problem_node
)
# Examine verdict_feedback, tool_results, etc.
```

### Pattern 2: Node-Specific Debugging

**Use case:** Investigate why a specific node keeps failing

```python
# Get recent runs
runs = query_runtime_logs("~/.hive/agents/my_agent", limit=10)

# For each run, check specific node
for run in runs["runs"]:
    node_details = query_runtime_log_details(
        "~/.hive/agents/my_agent",
        run["run_id"],
        node_id="problematic-node"
    )
    # Analyze retry patterns, error types
```

### Pattern 3: Real-Time Monitoring

**Use case:** Watch for issues during development

```python
import time

while True:
    result = query_runtime_logs(
        agent_work_dir="~/.hive/agents/my_agent",
        status="needs_attention",
        limit=1
    )

    if result["total"] > 0:
        new_issue = result["runs"][0]
        print(f"⚠️  New issue detected: {new_issue['run_id']}")
        # Alert or drill into L2/L3

    time.sleep(10)  # Poll every 10 seconds
```

---

## Integration Points

### GraphExecutor → RuntimeLogger

**Location:** `core/framework/graph/executor.py`

```python
# Executor creates logger and passes session_id
logger = RuntimeLogger(store, agent_id)
run_id = logger.start_run(goal_id, session_id=execution_id)

# During execution
logger.log_step(node_id, step_index, tool_calls, ...)
logger.log_node_complete(node_id, exit_status, ...)

# At completion
await logger.end_run(status="success")
```

### EventLoopNode → RuntimeLogger

**Location:** `core/framework/graph/event_loop_node.py`

```python
# EventLoopNode logs each step
self._logger.log_step(
    node_id=self.id,
    step_index=step_count,
    tool_calls=current_tool_calls,
    tool_results=current_tool_results,
    verdict=verdict,
    verdict_feedback=feedback,
    ...
)
```

### AgentRuntime → RuntimeLogger

**Location:** `core/framework/runtime/agent_runtime.py`

```python
# Runtime initializes logger with storage path
log_store = RuntimeLogStore(base_path / "runtime_logs")
logger = RuntimeLogger(log_store, agent_id)

# Passes session_id from ExecutionStream
logger.start_run(goal_id, session_id=execution_id)
```

---

## File Format Details

### L1: summary.json

**Written:** Once at end_run()
**Format:** Standard JSON

```json
{
  "run_id": "session_20260206_115718_e22339c5",
  "goal_id": "deep-research",
  "status": "degraded",
  "started_at": "2026-02-06T11:57:18.593081",
  "ended_at": "2026-02-06T11:58:45.123456",
  "needs_attention": true,
  "attention_summary": {
    "total_attention_flags": 3,
    "categories": ["missing_outputs", "retry_loops"],
    "nodes_with_attention": ["intake-collector"]
  },
  "total_nodes_executed": 4,
  "nodes_with_failures": ["intake-collector"],
  "execution_quality": "degraded",
  "total_latency_ms": 86530,
  "total_retries": 5
}
```

### L2: details.jsonl

**Written:** Incrementally (append per node completion)
**Format:** JSONL (one JSON object per line)

```jsonl
{"node_id":"intake-collector","exit_status":"escalate","retry_count":5,"verdict_counts":{"RETRY":5,"ESCALATE":1},"total_steps":8,"latency_ms":12500,"needs_attention":true,"attention_reasons":["high_retry_count","missing_outputs"],"tool_error_count":0,"tokens_used":9876}
{"node_id":"profile-analyzer","exit_status":"success","retry_count":0,"verdict_counts":{"ACCEPT":1},"total_steps":2,"latency_ms":5432,"needs_attention":false,"attention_reasons":[],"tool_error_count":0,"tokens_used":3456}
```

### L3: tool_logs.jsonl

**Written:** Incrementally (append per step)
**Format:** JSONL (one JSON object per line)

Each line includes **trace context** when the framework has set it (via the observability module): `trace_id`, `span_id`, `parent_span_id` (optional), and `execution_id`. These align with OpenTelemetry/W3C TraceContext so L3 data can be exported to OTel backends without schema changes.

```jsonl
{"node_id":"intake-collector","step_index":3,"trace_id":"54e80d7b5bd6409dbc3217e5cd16a4fd","span_id":"a1b2c3d4e5f67890","execution_id":"b4c348ec54e80d7b5bd6409dbc3217e50","tool_calls":[...],"verdict":"RETRY",...}
```

**Why JSONL?**
- Incremental append during execution (crash-safe)
- No need to parse entire file to add one line
- Data persisted immediately, not buffered
- Easy to stream/process line-by-line

---

## Attention Flags System

### Automatic Detection

The runtime logger automatically flags issues based on execution metrics:

| Trigger | Threshold | Attention Reason | Category |
|---------|-----------|------------------|----------|
| High retries | `retry_count > 3` | `high_retry_count` | Retry Loops |
| Escalations | `escalate_count > 2` | `escalation_pattern` | Guard Failures |
| High latency | `latency_ms > 60000` | `high_latency` | High Latency |
| Token usage | `tokens_used > 100000` | `high_token_usage` | Memory/Context |
| Stalled steps | `total_steps > 20` | `excessive_steps` | Stalled Execution |
| Tool errors | `tool_error_count > 0` | `tool_failures` | Tool Errors |
| Missing outputs | `exit_status != "success"` | `missing_outputs` | Missing Outputs |

### Attention Categories

Used by `/hive-debugger` skill for issue categorization:

1. **Missing Outputs**: Node didn't set required output keys
2. **Tool Errors**: Tool calls failed (API errors, timeouts)
3. **Retry Loops**: Judge repeatedly rejecting outputs
4. **Guard Failures**: Output validation failed
5. **Stalled Execution**: EventLoopNode not making progress
6. **High Latency**: Slow tool calls or LLM responses
7. **Client-Facing Issues**: Premature set_output before user input
8. **Edge Routing Errors**: No edges match current state
9. **Memory/Context Issues**: Conversation history too long
10. **Constraint Violations**: Agent violated goal-level rules

---

## Migration Guide

### Reading Old Logs

The system automatically handles both old and new formats:

```python
# MCP tools check both locations automatically
result = query_runtime_logs("~/.hive/agents/old_agent")
# Returns logs from both:
# - ~/.hive/agents/old_agent/runtime_logs/runs/*/
# - ~/.hive/agents/old_agent/sessions/session_*/logs/
```

### Deprecation Warnings

When reading from old locations, deprecation warnings are emitted:

```
DeprecationWarning: Reading logs from deprecated location for run_id=20260101T120000_abc12345.
New sessions use unified storage at sessions/session_*/logs/
```

### Migration Script (Optional)

For migrating existing old logs to new format, see:
- `EXECUTION_STORAGE_REDESIGN.md` - Migration strategy
- Future: `scripts/migrate_to_unified_sessions.py`

---

## Performance Characteristics

### Write Performance

- **L3 append**: ~1-2ms per step (sync I/O, thread-safe)
- **L2 append**: ~1-2ms per node (sync I/O, thread-safe)
- **L1 write**: ~5-10ms at end_run (atomic, async)

**Overhead:** < 5% of total execution time for typical agents

### Read Performance

- **L1 summary**: ~1-5ms (single JSON file)
- **L2 details**: ~10-50ms (JSONL, depends on node count)
- **L3 raw logs**: ~50-500ms (JSONL, depends on step count)

**Optimization:** Use filters (node_id, step_index) to reduce data read

### Storage Size

Typical session with 5 nodes, 20 steps:

- **L1 (summary.json)**: ~2-5 KB
- **L2 (details.jsonl)**: ~5-10 KB (1-2 KB per node)
- **L3 (tool_logs.jsonl)**: ~50-200 KB (2-10 KB per step)

**Total per session:** ~60-215 KB

**Compression:** Consider archiving old sessions after 90 days

---

## Troubleshooting

### Issue: Logs not appearing

**Symptom:** MCP tools return empty results

**Check:**
1. Verify storage path exists: `~/.hive/agents/{agent_name}/`
2. Check session directories: `ls ~/.hive/agents/{agent_name}/sessions/`
3. Verify logs directory exists: `ls ~/.hive/agents/{agent_name}/sessions/session_*/logs/`
4. Check file permissions

### Issue: Corrupt JSONL files

**Symptom:** Partial data or JSON decode errors

**Cause:** Process crash during write (rare, but possible)

**Recovery:**
```python
# MCP tools skip corrupt lines automatically
query_runtime_log_details(agent_work_dir, run_id)
# Logs warning but continues with valid lines
```

### Issue: High disk usage

**Symptom:** Storage growing too large

**Solution:**
```bash
# Archive old sessions
cd ~/.hive/agents/{agent_name}/sessions/
find . -name "session_2025*" -type d -exec tar -czf archive.tar.gz {} +
rm -rf session_2025*

# Or set up automatic cleanup (future feature)
```

---

## References

**Implementation:**
- `core/framework/runtime/runtime_logger.py` - Logger implementation
- `core/framework/runtime/runtime_log_store.py` - Storage layer
- `core/framework/runtime/runtime_log_schemas.py` - Data schemas
- `tools/src/aden_tools/tools/runtime_logs_tool/runtime_logs_tool.py` - MCP query tools

**Documentation:**
- `EXECUTION_STORAGE_REDESIGN.md` - Unified session storage design
- `/.claude/skills/hive-debugger/SKILL.md` - Interactive debugging skill

**Related:**
- `core/framework/schemas/session_state.py` - Session state schema
- `core/framework/storage/session_store.py` - Session state storage
- `core/framework/graph/executor.py` - GraphExecutor integration
