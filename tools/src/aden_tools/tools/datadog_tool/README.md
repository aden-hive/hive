# Datadog Observability Tool

This tool provides agents with **read-only** access to Datadog observability data. It enables agents to reason about system health, investigate failures, and monitor performance metrics without requiring write access or configuration capabilities.

## Features

- **Query Logs**: Search logs with full filter support (service, status, tags) and time ranges.
- **Fetch Metrics**: Retrieve time-series metrics for latency, error rates, and resource usage.
- **Check Monitors**: Verify the status of system alerts (Alert/Warn states).

## Prerequisites

To use this tool, you must provide Datadog API credentials via environment variables:

- `DATADOG_API_KEY`: Your Datadog API Key.
- `DATADOG_APP_KEY`: Your Datadog Application Key (required for reading logs/metrics).
- `DATADOG_SITE` (Optional): Datadog site parameter (e.g., `datadoghq.eu` for EU). Defaults to `datadoghq.com`.

## Tools

### 1. `datadog_list_logs`
Search for logs matching a query string.

**Parameters:**
- `query`: Search query (e.g., `service:backend status:error`).
- `time_from`: Start time (ISO 8601 or relative `now-15m`). Default: `now-15m`.
- `time_to`: End time. Default: `now`.
- `limit`: Max logs to return (max 100). Default: 20.

**Example Usage:**
```python
# Find recent errors in the payment service
logs = datadog_list_logs(query="service:payment-service status:error", time_from="now-1h")
```

### 2. `datadog_get_metrics`
Fetch time-series metric points.

**Parameters:**
- `query`: Metric query (e.g., `avg:system.cpu.idle{env:prod}`).
- `from_seconds_ago`: Start seconds ago. Default: 3600 (1 hour).
- `to_seconds_ago`: End seconds ago. Default: 0.

**Example Usage:**
```python
# Check CPU usage for the last hour
metrics = datadog_get_metrics(query="avg:system.cpu.idle{host:web-01}")
```

### 3. `datadog_get_monitor_status`
Check the status of monitors (alerts).

**Parameters:**
- `monitor_tags`: Tags to filter monitors (e.g., `service:backend`).
- `group_states`: States to include (default: `Alert,Warn`).

**Example Usage:**
```python
# Check if any production backend monitors are alerting
alerts = datadog_get_monitor_status(monitor_tags="service:backend,env:prod")
```

## Security & Scoping
This integration is strictly **read-only**. The tool functions only wrap the Datadog `GET` (and search `POST`) endpoints and do not expose any capabilities to modify dashboards, monitors, or logs.
