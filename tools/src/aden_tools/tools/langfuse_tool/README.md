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