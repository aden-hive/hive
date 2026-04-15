# Datadog Tool

Monitor and observe your infrastructure with the Datadog MCP tool. Supports metrics querying, monitor management, event listing, and log search via the Datadog API v1/v2.

## Credentials

| Environment Variable | Required | Description |
|---|---|---|
| `DATADOG_API_KEY` | Yes | Datadog API key |
| `DATADOG_APP_KEY` | Yes (most tools) | Datadog Application key |
| `DATADOG_SITE` | No | Datadog site (default: `datadoghq.com`; EU: `datadoghq.eu`) |

Get your API and Application keys from **Organization Settings → API Keys / Application Keys** in the Datadog UI.

## Tools

### `datadog_query_metrics`
Query Datadog metrics time series data.

**Parameters:**
- `query` (str, required) — Datadog metrics query string, e.g. `avg:system.cpu.user{host:web-01}`
- `from_time` (int, required) — Start of query window as UNIX timestamp (seconds)
- `to_time` (int, required) — End of query window as UNIX timestamp (seconds)

**Example:**
```
query: avg:system.cpu.user{*}
from_time: 1700000000
to_time: 1700003600
```

---

### `datadog_list_monitors`
List Datadog monitors with optional filters.

**Parameters:**
- `name` (str) — Filter by monitor name substring
- `tags` (str) — Comma-separated scope tags, e.g. `env:prod,service:web`
- `monitor_tags` (str) — Comma-separated monitor-level tags
- `with_downtimes` (bool) — Include active downtime objects
- `limit` (int) — Max monitors to return (default 50, max 1000)

---

### `datadog_get_monitor`
Get full details of a specific Datadog monitor by its numeric ID.

**Parameters:**
- `monitor_id` (int, required) — Numeric monitor ID

---

### `datadog_mute_monitor`
Mute a Datadog monitor to suppress alert notifications.

**Parameters:**
- `monitor_id` (int, required) — Numeric monitor ID
- `scope` (str) — Scope to mute, e.g. `host:web-01` (omit for all)
- `end` (int) — UNIX timestamp when mute expires (0 = indefinite)

---

### `datadog_list_events`
List Datadog events within a time range. Only requires `DATADOG_API_KEY`.

**Parameters:**
- `start` (int, required) — Start of time range as UNIX timestamp
- `end` (int, required) — End of time range as UNIX timestamp
- `tags` (str) — Comma-separated tags to filter by
- `sources` (str) — Comma-separated event sources
- `priority` (str) — `normal` or `low`
- `unaggregated` (bool) — Return unaggregated events
- `limit` (int) — Max events to return (default 50, max 1000)

---

### `datadog_search_logs`
Search Datadog logs using the Logs Search API (v2).

**Parameters:**
- `query` (str) — Log search query, e.g. `service:web status:error`
- `from_time` (str) — Start time: ISO 8601 or relative like `now-1h` (default `now-15m`)
- `to_time` (str) — End time (default `now`)
- `limit` (int) — Max log events to return (default 50, max 1000)
- `sort` (str) — `timestamp` (ascending) or `-timestamp` (descending)

## Notes

- All tools return `{"error": "..."}` on failure with a descriptive message.
- The `DATADOG_SITE` variable supports any [Datadog site](https://docs.datadoghq.com/getting_started/site/) (e.g. `us3.datadoghq.com`, `datadoghq.eu`).
- `datadog_list_events` only requires `DATADOG_API_KEY` (no application key needed).
