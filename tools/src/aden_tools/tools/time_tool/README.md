# Time Tool

Get current date and time with timezone support. Useful for agents in long-running sessions where the injected system prompt time goes stale.

## Setup

No credentials required. Uses Python's built-in `zoneinfo` module.

## Tools (1)

| Tool | Description |
|------|-------------|
| `get_current_time` | Get current date/time for any IANA timezone |

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timezone` | `str` | `"UTC"` | IANA timezone name |

## Response Fields

| Field | Format | Example |
|-------|--------|---------|
| `datetime` | ISO 8601 | `2026-02-07T14:30:00+00:00` |
| `date` | `YYYY-MM-DD` | `2026-02-07` |
| `time` | `HH:MM:SS` | `14:30:00` |
| `timezone` | IANA name | `UTC` |
| `day_of_week` | Full name | `Saturday` |
| `unix_timestamp` | Seconds since epoch | `1770554400` |

## Example Usage

```python
# Default (UTC)
get_current_time()

# US Eastern
get_current_time(timezone="America/New_York")

# India
get_current_time(timezone="Asia/Kolkata")

# Invalid timezone returns error
get_current_time(timezone="Invalid/Zone")
# {"error": "Failed to get time: 'No time zone found with key Invalid/Zone'"}
```
