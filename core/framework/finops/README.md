# FinOps / Cost Guardrails for Hive Agents

This module provides comprehensive cost monitoring and control for AI agents, enabling enterprise-ready FinOps capabilities with OpenTelemetry tracing and Prometheus metrics export.

## Features

- **Metrics Collection**: Track tokens, costs, burn rates, and tool usage across runs, nodes, and models
- **OpenTelemetry Integration**: Export traces and metrics to OTLP-compatible backends (Datadog, Grafana, etc.)
- **Prometheus Exporter**: Expose `/metrics` endpoint for Prometheus scraping
- **Budget Policies**: Configure thresholds and actions for cost control (warn, degrade, throttle, kill)
- **Runaway Detection**: Detect and prevent runaway agent loops based on failure patterns and burn rate spikes
- **Cost Estimation**: Real-time cost estimation based on model pricing tables

## Installation

```bash
# Install with FinOps dependencies
pip install framework[finops]

# Or install individual packages
pip install prometheus-client opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

## Quick Start

### Basic Usage

```python
from framework.finops import (
    FinOpsCollector,
    FinOpsConfig,
    get_collector,
)

# Get the global collector
collector = get_collector()

# Start tracking a run
collector.start_run(
    run_id="run-123",
    agent_id="my-agent",
    goal_id="process-documents",
    model="claude-3-5-sonnet-20241022",
)

# Record LLM token usage (automatically calculates cost)
cost = collector.record_llm_tokens(
    run_id="run-123",
    node_id="analyze",
    input_tokens=1000,
    output_tokens=500,
    model="claude-3-5-sonnet-20241022",
)
print(f"Estimated cost: ${cost:.4f}")

# End the run
collector.end_run("run-123", success=True)

# Get aggregated metrics
metrics = collector.get_aggregated_metrics()
print(f"Total runs: {metrics['total_runs']}")
print(f"Total cost: ${metrics['total_estimated_cost_usd']:.2f}")
```

### Enable Prometheus Export

```python
from framework.finops import (
    start_prometheus_server,
    get_collector,
)

# Start Prometheus metrics server on port 9090
start_prometheus_server()

# Or configure via environment variables
# HIVE_PROMETHEUS_ENABLED=true
# HIVE_PROMETHEUS_PORT=9090
# HIVE_PROMETHEUS_HOST=0.0.0.0
```

### Enable OpenTelemetry Export

```python
from framework.finops import init_otel

# Initialize OpenTelemetry
init_otel()  # Uses OTEL_EXPORTER_OTLP_ENDPOINT env var

# Or with explicit config
from framework.finops import FinOpsConfig

config = FinOpsConfig(
    otel_enabled=True,
    otel_endpoint="http://localhost:4317",
    otel_service_name="my-hive-agent",
)
init_otel(config)
```

### Budget Policies

```python
from framework.finops import (
    BudgetPolicyEngine,
    BudgetPolicy,
    BudgetThreshold,
    BudgetAction,
)

# Create policy engine
engine = BudgetPolicyEngine()

# Add a budget policy
engine.add_policy(BudgetPolicy(
    name="agent-cost-limit",
    scope="agent",
    scope_id="my-agent",
    max_cost_usd_per_run=1.00,
    thresholds=[
        BudgetThreshold(threshold=50, action=BudgetAction.WARN, message="50% budget used"),
        BudgetThreshold(threshold=75, action=BudgetAction.DEGRADE, message="Switching to cheaper model"),
        BudgetThreshold(threshold=100, action=BudgetAction.KILL, message="Budget exceeded"),
    ],
))

# Check budget (returns alerts if thresholds exceeded)
alerts = engine.check_run_budget(
    run_id="run-123",
    agent_id="my-agent",
    tokens=5000,
    cost_usd=0.75,
)

for alert in alerts:
    print(f"Alert: {alert.message} - Action: {alert.action}")
```

### Runaway Detection

```python
from framework.finops import get_collector

collector = get_collector()

# During execution, check for runaway loops
is_runaway, reason = collector.detect_runaway_loop("run-123")
if is_runaway:
    print(f"Runaway detected: {reason}")
    # Take action: kill run, notify, etc.
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HIVE_FINOPS_ENABLED` | `true` | Enable/disable FinOps module |
| `HIVE_PROMETHEUS_ENABLED` | `true` | Enable Prometheus exporter |
| `HIVE_PROMETHEUS_PORT` | `9090` | Prometheus metrics port |
| `HIVE_PROMETHEUS_HOST` | `0.0.0.0` | Prometheus metrics host |
| `HIVE_OTEL_ENABLED` | `false` | Enable OpenTelemetry export |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | - | OTLP endpoint URL |
| `OTEL_SERVICE_NAME` | `hive-agent` | Service name for OTel |
| `HIVE_RUNAWAY_DETECTION_ENABLED` | `true` | Enable runaway detection |
| `HIVE_RUNAWAY_FAILURE_THRESHOLD` | `3` | Consecutive failures for runaway |
| `HIVE_RUNAWAY_BURN_RATE_MULTIPLIER` | `2.0` | Burn rate multiplier for runaway |

## Prometheus Metrics

The following metrics are exposed at the `/metrics` endpoint:

### Run Metrics
- `hive_runs_total` - Total runs by agent and status
- `hive_runs_active` - Currently active runs
- `hive_run_duration_seconds` - Run duration histogram
- `hive_cost_per_run_usd` - Cost per run histogram

### Token Metrics
- `hive_tokens_input_total` - Input tokens by model/node
- `hive_tokens_output_total` - Output tokens by model/node
- `hive_tokens_cache_write_total` - Cache write tokens
- `hive_tokens_cache_read_total` - Cache read tokens

### Cost Metrics
- `hive_estimated_cost_usd_total` - Total estimated cost by model

### Burn Rate & Runaway
- `hive_burn_rate_tokens_per_min` - Current burn rate per run
- `hive_runaway_detected_total` - Runaway loop detections

### Budget Alerts
- `hive_budget_alerts_total` - Budget policy alerts by action
- `hive_budget_threshold_percentage` - Current budget usage percentage

### Node & Tool Metrics
- `hive_nodes_executed_total` - Node executions by type and success
- `hive_node_latency_seconds` - Node execution latency
- `hive_node_retries_total` - Node retry counts
- `hive_tool_calls_total` - Tool call counts by name and error status
- `hive_tool_latency_seconds` - Tool call latency

## Grafana Dashboard

A pre-built Grafana dashboard is available at `dashboards/grafana-hive-finops.json`.

### Import Dashboard

1. Open Grafana → Dashboards → Import
2. Upload the JSON file or paste contents
3. Select your Prometheus data source
4. Click Import

### Dashboard Panels

- **Overview**: Active runs, success/failure rates, total cost, total tokens, runaway detections
- **Token Usage & Costs**: Token rate by model, cost rate by model
- **Burn Rate & Runaway Detection**: Burn rate per run, runaway detection by reason
- **Node & Tool Performance**: Node latency, tool call rates
- **Budget Policies**: Budget usage gauges, budget alerts by action

## Alert Rules (Prometheus)

Example alert rules for common FinOps scenarios:

```yaml
groups:
  - name: hive-finops-alerts
    rules:
      - alert: HighBurnRate
        expr: hive_burn_rate_tokens_per_min > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High token burn rate detected"
          description: "Run {{ $labels.run_id }} has burn rate of {{ $value }} tokens/min"

      - alert: RunawayLoopDetected
        expr: increase(hive_runaway_detected_total[5m]) > 0
        labels:
          severity: critical
        annotations:
          summary: "Runaway loop detected"
          description: "{{ $value }} runaway loops detected in last 5 minutes"

      - alert: BudgetThresholdExceeded
        expr: hive_budget_threshold_percentage > 80
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Budget threshold exceeded"
          description: "Policy {{ $labels.policy_name }} at {{ $value }}%"

      - alert: HighCostPerRun
        expr: histogram_quantile(0.95, hive_cost_per_run_usd) > 1.0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High cost per run"
          description: "95th percentile cost per run is ${{ $value }}"
```

## Supported Models

The pricing table includes the following models (pricing per 1M tokens as of Feb 2026):

### Anthropic
- claude-sonnet-4-20250514
- claude-3-5-sonnet-20241022
- claude-3-5-haiku-20241022
- claude-3-opus-20240229
- claude-3-sonnet-20240229
- claude-3-haiku-20240307

### OpenAI
- gpt-4o, gpt-4o-mini
- gpt-4-turbo, gpt-4
- gpt-3.5-turbo
- o1, o1-mini, o1-preview

### Google
- gemini-2.0-flash
- gemini-1.5-pro, gemini-1.5-flash
- gemini-1.0-pro

### Others
- deepseek-chat, deepseek-reasoner
- cerebras/llama-3.3-70b, cerebras/llama-3.1-8b

## Integration with Hive Runtime

The FinOps module integrates with the Hive runtime through the event bus:

```python
from framework.runtime.event_bus import EventBus, EventType
from framework.finops import get_collector

bus = EventBus()
collector = get_collector()

async def on_execution_started(event):
    collector.start_run(
        run_id=event.execution_id,
        agent_id=event.data.get("agent_id", ""),
    )

async def on_execution_completed(event):
    success = event.data.get("output", {}).get("success", True)
    collector.end_run(event.execution_id, success=success)

bus.subscribe([EventType.EXECUTION_STARTED], on_execution_started)
bus.subscribe([EventType.EXECUTION_COMPLETED], on_execution_completed)
```

## Best Practices

1. **Set Budget Policies Early**: Configure policies before production deployment
2. **Monitor Burn Rate**: Watch for sudden spikes that indicate runaway loops
3. **Use Cache Tokens**: Take advantage of prompt caching to reduce costs
4. **Alert on Budget**: Set up alerting for budget thresholds at 75% and 90%
5. **Review Runaways**: Investigate and fix the root cause of runaway detections
6. **Track by Model**: Monitor costs per model to optimize model selection

## License

MIT License - See LICENSE file for details.
