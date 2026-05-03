# Langfuse Tool

LLM observability for tracing, scoring, and prompt management using Langfuse.

## Tools

| Tool | Description |
|------|-------------|
| `langfuse_list_traces` | List traces with optional filters |
| `langfuse_get_trace` | Get full details of a specific trace |
| `langfuse_list_scores` | List scores with optional filters |
| `langfuse_create_score` | Create a score for a trace or observation |
| `langfuse_list_prompts` | List prompts from prompt management |
| `langfuse_get_prompt` | Get a specific prompt by name and version |

## Setup

Requires Langfuse public and secret key pair:

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."

# Optional: defaults to US cloud
export LANGFUSE_HOST="https://cloud.langfuse.com"
# EU cloud:
# export LANGFUSE_HOST="https://eu.cloud.langfuse.com"
# Self-hosted:
# export LANGFUSE_HOST="https://your-self-hosted-langfuse.com"
```

> Get your keys from https://cloud.langfuse.com/project/&lt;id&gt;/settings

## Usage Examples

### List recent traces
```python
langfuse_list_traces(user_id="user_123", limit=20)
```

### Get full trace details
```python
langfuse_get_trace(trace_id="trace_abc123")
```

### List scores for a trace
```python
langfuse_list_scores(trace_id="trace_abc123")
```

### Create a score
```python
langfuse_create_score(
    trace_id="trace_abc123",
    name="correctness",
    value=0.95,
    data_type="NUMERIC",
    comment="Output matches expected format perfectly"
)
```

### List production prompts
```python
langfuse_list_prompts(label="production")
```

### Get a specific prompt version
```python
langfuse_get_prompt(
    prompt_name="customer-support-agent",
    label="production"
)
```

## Score Data Types

| Type | Description | Example Value |
|------|-------------|---------------|
| `NUMERIC` | Continuous numeric score | `0.95`, `85.0` |
| `CATEGORICAL` | Category label | `"good"`, `"bad"` |
| `BOOLEAN` | Binary pass/fail | `1.0` (pass), `0.0` (fail) |

## Score Sources

| Source | Description |
|--------|-------------|
| `API` | Score created via API |
| `ANNOTATION` | Human annotation via Langfuse UI |
| `EVAL` | Automated evaluation job |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "Langfuse credentials not configured", "help": "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY environment variables or configure via credential store"}
{"error": "Invalid Langfuse API keys"}
{"error": "Insufficient permissions for this Langfuse resource"}
{"error": "Langfuse resource not found"}
{"error": "Langfuse rate limit exceeded. Try again later."}
{"error": "Request timed out"}
```

## Hive Agent Run Instrumentation

The `tool.py` module provides **three lifecycle functions** that map directly to
a Hive agent run. Together they produce one Langfuse trace per run, with one
child span per node, and an optional quality score at the end.

```
Hive run                         Langfuse UI
─────────────────────────────    ────────────────────────────────────────
start_agent_trace()         →    trace  (session, tags, user_id)
  node 1 executes
  log_node_span()           →      span: node 1  (input, output, latency, tokens)
  node 2 executes
  log_node_span()           →      span: node 2
  node 3 executes
  log_node_span()           →      span: node 3
score_agent_run()           →    score on trace  (name, value 0-1, comment)
                                 lf.flush() sends all buffered data
```

### Import

```python
from aden_tools.tools.langfuse_tool import (
    start_agent_trace,
    log_node_span,
    score_agent_run,
)
```

### Setup — 3 env vars, no code config

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."   # from Langfuse dashboard → Settings
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"   # or self-hosted URL
```

The Langfuse SDK reads these automatically. No config object is passed around.

### `start_agent_trace` — call once at the start

```python
trace_id = start_agent_trace(
    agent_name="research-agent",
    session_id="session-42",
    input_data={"query": "Summarise the Q1 earnings report"},
    user_id="user-99",
    tags=["production", "research"],
)
# Returns: "clx2abc..."  ← keep this for every subsequent call
```

### `log_node_span` — call after every node

```python
span_id = log_node_span(
    trace_id=trace_id,
    node_name="web_search",
    input={"query": "Q1 earnings Tesla"},
    output={"results": ["Tesla Q1 revenue was $21.3B..."]},
    model="gpt-4o",
    latency_ms=843.2,
    tokens={"input": 320, "output": 95, "total": 415},
)
# lf.flush() is called internally — no data is lost between nodes
```

### `score_agent_run` — call once at the very end

```python
score_id = score_agent_run(
    trace_id=trace_id,
    score_name="quality",
    score_value=0.87,          # float in [0, 1]; 1.0 = best
    comment="Output was accurate and well-structured.",
)
# lf.flush() is called internally — score lands even if the process exits next
```

### Why `lf.flush()` matters

Langfuse batches telemetry asynchronously. In fast-running agents the process
can exit before the buffer is drained, silently dropping spans or scores.
`log_node_span` and `score_agent_run` each call `lf.flush()` at the end to
guarantee delivery. `start_agent_trace` does **not** flush — flushing before
the first node runs adds unnecessary latency.