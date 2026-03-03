# Observability - Structured Logging

## Configuration via Environment Variables

Control logging format using environment variables:

```bash
# JSON logging (production) - Machine-parseable, one line per log
export LOG_FORMAT=json
python -m my_agent run

# Human-readable (development) - Color-coded, easy to read
# Default if LOG_FORMAT is not set
python -m my_agent run
```

**Alternative:** Set `ENV=production` to automatically use JSON format:

```bash
export ENV=production
python -m my_agent run
```

---

## Overview

The Hive framework provides automatic structured logging with trace context propagation. Logs include correlation IDs (`trace_id`, `execution_id`) that automatically follow your agent execution flow.

**Features:**
- **Zero developer friction**: Standard `logger.info()` calls automatically get trace context
- **ContextVar-based propagation**: Thread-safe and async-safe for concurrent executions
- **Dual output modes**: JSON for production, human-readable for development
- **Automatic correlation**: `trace_id` and `execution_id` propagate through all logs

## Quick Start

Logging is automatically configured when you use `AgentRunner`. No setup required:

```python
from framework.runner import AgentRunner

runner = AgentRunner(graph=my_graph, goal=my_goal)
result = await runner.run({"input": "data"})
# Logs automatically include trace_id, execution_id, agent_id, etc.
```

## Programmatic Configuration

Configure logging explicitly in your code:

```python
from framework.observability import configure_logging

# Human-readable (development)
configure_logging(level="DEBUG", format="human")

# JSON (production)
configure_logging(level="INFO", format="json")

# Auto-detect from environment
configure_logging(level="INFO", format="auto")
```

### Configuration Options

- **level**: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`, `"CRITICAL"`
- **format**: 
  - `"json"` - Machine-parseable JSON (one line per log entry)
  - `"human"` - Human-readable with colors
  - `"auto"` - Detects from `LOG_FORMAT` env var or `ENV=production`

## Log Format Examples

### JSON Format (Machine-parseable)

```json
{"timestamp": "2026-01-28T15:01:02.671126+00:00", "level": "info", "logger": "framework.runtime", "message": "Starting agent execution", "trace_id": "54e80d7b5bd6409dbc3217e5cd16a4fd", "execution_id": "b4c348ec54e80d7b5bd6409dbc3217e50", "agent_id": "sales-agent", "goal_id": "qualify-leads"}
```

**Features:**
- `trace_id` and `execution_id` are 32 hex chars (W3C/OTel-aligned, no prefixes)
- Compact single-line format (easy to stream/parse)
- All trace context fields included automatically

### Human-Readable Format (Development)

```
[INFO    ] [trace:12345678 | exec:a1b2c3d4 | agent:sales-agent] Starting agent execution
[INFO    ] [trace:12345678 | exec:a1b2c3d4 | agent:sales-agent] Processing input data [node_id:input-processor]
[INFO    ] [trace:12345678 | exec:a1b2c3d4 | agent:sales-agent] LLM call completed [latency_ms:1250] [tokens_used:450]
```

**Features:**
- Color-coded log levels
- Shortened IDs for readability (first 8 chars)
- Context prefix shows trace correlation

## Trace Context Fields

When the framework sets trace context, these fields are included in all logs. IDs are 32 hex (W3C/OTel-aligned, no prefixes).

- **trace_id**: Trace identifier
- **execution_id**: Run/session correlation
- **agent_id**: Agent/graph identifier
- **goal_id**: Goal being pursued
- **node_id**: Current node (when set)

## Custom Log Fields

Add custom fields using the `extra` parameter:

```python
import logging

logger = logging.getLogger("my_module")

# Add custom fields
logger.info("LLM call completed", extra={
    "latency_ms": 1250,
    "tokens_used": 450,
    "model": "claude-3-5-sonnet-20241022",
    "node_id": "web-search"
})
```

These fields appear in both JSON and human-readable formats.

## Usage in Your Code

### Standard Logging (Recommended)

Just use Python's standard logging - context is automatic:

```python
import logging

logger = logging.getLogger(__name__)

def my_function():
    # This log automatically includes trace_id, execution_id, etc.
    logger.info("Processing data")
    
    try:
        result = do_work()
        logger.info("Work completed", extra={"result_count": len(result)})
    except Exception as e:
        logger.error("Work failed", exc_info=True)
```

### Framework-Managed Context

The framework automatically sets trace context at key points:

- **Runtime.start_run()**: Sets `trace_id`, `execution_id`, `goal_id`
- **GraphExecutor.execute()**: Adds `agent_id`
- **Node execution**: Adds `node_id`

Propagation is automatic via ContextVar.

## Advanced Usage

### Manual Context Management

If you need to set trace context manually (rare):

```python
from framework.observability import set_trace_context, get_trace_context

# Set context (32-hex, no prefixes)
set_trace_context(
    trace_id="54e80d7b5bd6409dbc3217e5cd16a4fd",
    execution_id="b4c348ec54e80d7b5bd6409dbc3217e50",
    agent_id="my-agent"
)

# Get current context
context = get_trace_context()
print(context["execution_id"])

# Clear context (usually not needed)
from framework.observability import clear_trace_context
clear_trace_context()
```

### Testing

For tests, you may want to configure logging explicitly:

```python
import pytest
from framework.observability import configure_logging

@pytest.fixture(autouse=True)
def setup_logging():
    configure_logging(level="DEBUG", format="human")
```

## Best Practices

1. **Production**: Use JSON format (`LOG_FORMAT=json` or `ENV=production`)
2. **Development**: Use human-readable format (default)
3. **Don't manually set context**: Let the framework manage it
4. **Use standard logging**: No special APIs needed - just `logger.info()`
5. **Add custom fields**: Use `extra` dict for additional metadata

## Troubleshooting

### Logs missing trace context

Ensure `configure_logging()` has been called (usually automatic via `AgentRunner._setup()`).

### JSON logs not appearing

Check environment variables:
```bash
echo $LOG_FORMAT
echo $ENV
```

Or explicitly set:
```python
configure_logging(format="json")
```

### Context not propagating

ContextVar automatically propagates through async calls. If context seems lost, check:
- Are you in the same async execution context?
- Has `set_trace_context()` been called for this execution?

## See Also

- [Logging Implementation](../observability/logging.py) - Source code
- [AgentRunner](../runner/runner.py) - Where logging is configured
- [Runtime Core](../runtime/core.py) - Where trace context is set
