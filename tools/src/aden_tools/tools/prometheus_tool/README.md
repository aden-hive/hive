# Prometheus Metrics Query Tool

Provides PromQL-based querying tools for agents to fetch real-time and historical metrics from a Prometheus server.

## Authentication

Authentication is **optional** as most prometheus servers are deployed within private infrastructure. If no credentials are set, requests are sent without auth headers (suitable for open/internal Prometheus instances).

When credentials are present, **Bearer token takes priority** over Basic Auth:

| Priority | Mode         | Environment Variables                         |
| -------- | ------------ | --------------------------------------------- |
| 1        | Bearer Token | `PROMETHEUS_TOKEN`                            |
| 2        | Basic Auth   | `PROMETHEUS_USERNAME` + `PROMETHEUS_PASSWORD` |
| 3        | None         | _(no variables set)_                          |

### Setup

```bash
# Required
export PROMETHEUS_BASE_URL="http://your-prometheus-host:9090"

# Optional — Bearer token (takes priority if set)
export PROMETHEUS_TOKEN="your_token_here"

# Optional — Basic auth
export PROMETHEUS_USERNAME="admin"
export PROMETHEUS_PASSWORD="secret"
```

> \_Note: Base URL can also be configured via the Aden Credential Store under the `prometheus` key.

---

## Tools

| Tool                     | Description                                               |
| ------------------------ | --------------------------------------------------------- |
| `prometheus_query`       | Run an instant PromQL query — returns current value(s)    |
| `prometheus_query_range` | Run a PromQL query over a time range with step resolution |

---

## Tool Reference

### `prometheus_query`

Executes a PromQL expression against `/api/v1/query`. Returns the latest value for matching time series.

**Parameters:**

| Name      | Type | Required | Default | Description                                                       |
| --------- | ---- | -------- | ------- | ----------------------------------------------------------------- |
| `query`   | str  | ✅       | —       | PromQL expression (max 1000 chars)                                |
| `timeout` | int  | ❌       | `5`     | Request timeout in seconds (1–30; out-of-range values reset to 5) |

**Returns:**

```json
{
  "success": true,
  "query": "up",
  "result": [
    {
      "metric": {
        "__name__": "up",
        "job": "prometheus",
        "instance": "localhost:9090"
      },
      "value": [1700000000.0, "1"]
    }
  ],
  "raw": {
    "status": "success",
    "data": {
      "resultType": "vector",
      "result": [
        {
          "metric": {
            "__name__": "up",
            "job": "prometheus",
            "instance": "localhost:9090"
          },
          "value": [1700000000.0, "1"]
        }
      ]
    }
  }
}
```

---

### `prometheus_query_range`

Executes a PromQL expression against `/api/v1/query_range`. Returns a matrix of values over time — useful for graphing, trends, and historical analysis.

**Parameters:**

| Name      | Type | Required | Default | Description                              |
| --------- | ---- | -------- | ------- | ---------------------------------------- |
| `query`   | str  | ✅       | —       | PromQL expression (max 1000 chars)       |
| `start`   | str  | ✅       | —       | Start time — Unix timestamp or RFC3339   |
| `end`     | str  | ✅       | —       | End time — Unix timestamp or RFC3339     |
| `step`    | str  | ❌       | `"60s"` | Resolution step (e.g. `15s`, `5m`, `1h`) |
| `timeout` | int  | ❌       | `5`     | Request timeout in seconds (1–30)        |

**Returns:**

```json
{
  "success": true,
  "query": "rate(http_requests_total[5m])",
  "start": "2024-01-01T00:00:00Z",
  "end": "2024-01-01T01:00:00Z",
  "step": "60s",
  "result": [
    {
      "metric": { "job": "api-server" },
      "values": [
        [1704067200, "3.14"],
        [1704067260, "3.22"]
      ]
    }
  ]
}
```

---

## Error Handling

All tools return structured error dicts on failure.

```json
{ "error": "Request to Prometheus timed out" }
{ "error": "Failed to connect to Prometheus", "help": "Check if Prometheus is running and base_url is correct" }
{ "error": "Prometheus returned status 400", "details": "..." }
{ "error": "Query must be between 1 and 1000 characters" }
{ "error": "start and end time are required" }
{
  "error": "Missing required credential: <description>",
  "help": "<setup instructions>",
  "success": false
}
```

---

## Limits & Safeguards

| Guard             | Value                                                               |
| ----------------- | ------------------------------------------------------------------- |
| Base URL priority | Credential store (`prometheus`) → fallback to `PROMETHEUS_BASE_URL` |
| Timeout handling  | Out-of-range values reset to `5s`                                   |
| Query limit       | Must be 1–1000 characters                                           |
| URL normalization | Trailing `/` removed using `.rstrip('/')`                           |
| Timeout range     | 1–30 seconds (values outside reset defaults to 5s)                  |
