# Calendly Tool

Check availability, create booking links, and optionally cancel events via the Calendly API v2.

## Setup

```bash
# Required - Personal Access Token
export CALENDLY_API_TOKEN=your-calendly-api-token
```

**Get your token:**
1. Go to https://calendly.com/integrations/api_webhooks
2. Click "Create Token" or "Generate new token"
3. Give it a name and copy the token
4. Set `CALENDLY_API_TOKEN` environment variable

Alternatively, configure via the credential store (`CredentialStoreAdapter`).

## Tools (4)

| Tool | Description |
|------|-------------|
| `calendly_list_event_types` | List all event types with names, URIs, and scheduling URLs |
| `calendly_get_availability` | Get available booking times for an event type |
| `calendly_get_booking_link` | Get the scheduling URL for a single event type by URI |
| `calendly_cancel_event` | Cancel a scheduled event (optional) |

## Usage

### List event types

```python
# Returns event_types with uri, name, scheduling_url, duration
result = calendly_list_event_types()
```

### Get availability

```python
# event_type_uri from calendly_list_event_types
result = calendly_get_availability(
    event_type_uri="https://api.calendly.com/event_types/XXXXX",
    start_time="2026-02-01T00:00:00Z",
    end_time="2026-02-07T23:59:59Z"
)
# Returns available_times (max 7-day range)
```

### Get booking link

```python
# Use when you have event type URI and need the shareable link
result = calendly_get_booking_link(
    event_type_uri="https://api.calendly.com/event_types/XXXXX"
)
# Returns scheduling_url for inclusion in emails or messages
```

### Cancel event

```python
# event_uri from webhook or scheduled event list
result = calendly_cancel_event(
    event_uri="https://api.calendly.com/scheduled_events/XXXXX",
    reason="Meeting rescheduled"  # optional
)
```

## Scope (MVP)

- List event types
- Get availability for an event type (max 7-day range)
- Create booking/scheduling link
- Cancel scheduled event (optional)

## API Reference

- [Calendly API Docs](https://developer.calendly.com/api-docs)
