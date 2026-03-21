# Google Calendar Tool

A tool for managing Google Calendar events, checking availability, and coordinating schedules.

## Features

- **Events**: Create, read, update, and delete calendar events
- **Calendars**: List and access user's calendars
- **Availability**: Check free/busy times for smart scheduling
- **Attendees**: Add participants and send meeting invites

## Setup

### Option A: Aden OAuth (Recommended)

Use Aden's managed OAuth flow for automatic token refresh:

1. Set `aden_provider_name="google-calendar"` in your agent's credential spec
2. Aden handles the OAuth flow and token refresh automatically

### Option B: Direct Token (Testing)

For quick testing, get a token from the [Google OAuth Playground](https://developers.google.com/oauthplayground/):

1. Go to OAuth Playground
2. Select "Google Calendar API v3" scopes
3. Authorize and get an access token
4. Set the environment variable:

```bash
export GOOGLE_ACCESS_TOKEN="your-access-token"
```

**Note:** Access tokens from OAuth Playground expire after ~1 hour. For production, use Aden OAuth.

## Authentication

This tool uses OAuth 2.0 for authentication with Google Calendar API.

**Default scope:**
- `https://www.googleapis.com/auth/calendar` - Full read/write access to calendars and events

**Alternative (read-only):**
- `https://www.googleapis.com/auth/calendar.readonly` - Read-only access

## Tools

### calendar_list_events

List upcoming calendar events.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| calendar_id | str | No | "primary" | Calendar ID or "primary" for main calendar |
| time_min | str | No | now | Start time (ISO 8601 format) |
| time_max | str | No | None | End time (ISO 8601 format) |
| max_results | int | No | 10 | Maximum events to return (1-2500) |
| query | str | No | None | Free text search terms |

**Example:**
```python
calendar_list_events(
    calendar_id="primary",
    time_min="2024-01-15T00:00:00Z",
    time_max="2024-01-22T00:00:00Z",
    max_results=20
)
```

### calendar_get_event

Get details of a specific event.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| event_id | str | Yes | - | The event ID |
| calendar_id | str | No | "primary" | Calendar ID |

### calendar_create_event

Create a new calendar event.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| summary | str | Yes | - | Event title |
| start_time | str | Yes | - | Start time (ISO 8601). For all-day events: "YYYY-MM-DD" |
| end_time | str | Yes | - | End time (ISO 8601). For all-day events: "YYYY-MM-DD" (exclusive) |
| calendar_id | str | No | "primary" | Calendar ID |
| description | str | No | None | Event description |
| location | str | No | None | Event location |
| attendees | list[str] | No | None | List of attendee emails |
| send_notifications | bool | No | True | Send invite emails to attendees |
| timezone | str | No | None | IANA timezone (e.g., "America/New_York"). Ignored for all-day events. |
| all_day | bool | No | False | Create an all-day event (uses date-only start/end) |

**Note:** When attendees are provided, a Google Meet link is automatically generated.

**Example (timed event):**
```python
calendar_create_event(
    summary="Team Standup",
    start_time="2024-01-15T09:00:00",
    end_time="2024-01-15T09:30:00",
    timezone="America/New_York",
    attendees=["alice@example.com", "bob@example.com"],
    description="Daily sync meeting"
)
```

**Example (all-day event):**
```python
calendar_create_event(
    summary="Company Holiday",
    start_time="2024-12-25",
    end_time="2024-12-26",  # end date is exclusive
    all_day=True
)
```

### calendar_update_event

Update an existing event. Only provided fields are changed (uses PATCH).

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| event_id | str | Yes | - | The event ID to update |
| calendar_id | str | No | "primary" | Calendar ID |
| summary | str | No | None | New event title |
| start_time | str | No | None | New start time. For all-day: "YYYY-MM-DD" |
| end_time | str | No | None | New end time. For all-day: "YYYY-MM-DD" |
| description | str | No | None | New description |
| location | str | No | None | New location |
| attendees | list[str] | No | None | Updated attendee list |
| send_notifications | bool | No | True | Send update emails |
| timezone | str | No | None | IANA timezone (e.g., "America/New_York"). Ignored for all-day. |
| all_day | bool | No | False | Convert to all-day event (requires start_time + end_time) |
| add_meet_link | bool | No | False | Add a Google Meet link to the event |

### calendar_delete_event

Delete a calendar event.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| event_id | str | Yes | - | The event ID to delete |
| calendar_id | str | No | "primary" | Calendar ID |
| send_notifications | bool | No | True | Send cancellation emails |

### calendar_list_calendars

List all calendars accessible to the user.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| max_results | int | No | 100 | Maximum calendars to return |

### calendar_get_calendar

Get details of a specific calendar.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| calendar_id | str | Yes | - | The calendar ID |

### calendar_check_availability

Check free/busy status for scheduling.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| time_min | str | Yes | - | Start of time range (ISO 8601) |
| time_max | str | Yes | - | End of time range (ISO 8601) |
| calendars | list[str] | No | ["primary"] | Calendar IDs to check |
| timezone | str | No | "UTC" | Timezone for the query |

**Example:**
```python
calendar_check_availability(
    time_min="2024-01-15T00:00:00Z",
    time_max="2024-01-16T00:00:00Z",
    calendars=["primary", "team-calendar@group.calendar.google.com"]
)
```

**Response:**
```json
{
    "time_min": "2024-01-15T00:00:00Z",
    "time_max": "2024-01-16T00:00:00Z",
    "calendars": {
        "primary": {
            "busy": [
                {"start": "2024-01-15T09:00:00Z", "end": "2024-01-15T10:00:00Z"},
                {"start": "2024-01-15T14:00:00Z", "end": "2024-01-15T15:00:00Z"}
            ]
        }
    }
}
```

## Error Handling

All tools return a dict with either success data or an error:

**Success:**
```json
{
    "id": "event123",
    "summary": "Team Meeting",
    "start": {"dateTime": "2024-01-15T09:00:00Z"},
    "end": {"dateTime": "2024-01-15T10:00:00Z"}
}
```

**Error:**
```json
{
    "error": "Calendar credentials not configured",
    "help": "Set GOOGLE_ACCESS_TOKEN environment variable"
}
```

## Common Use Cases

### Schedule a meeting with availability check
```python
# 1. Check when everyone is free
availability = calendar_check_availability(
    time_min="2024-01-15T00:00:00Z",
    time_max="2024-01-19T00:00:00Z"
)

# 2. Create the meeting at a free slot
event = calendar_create_event(
    summary="Project Review",
    start_time="2024-01-16T14:00:00Z",
    end_time="2024-01-16T15:00:00Z",
    attendees=["team@example.com"]
)
```

### Get today's agenda
```python
from datetime import datetime, timedelta

today = datetime.now().replace(hour=0, minute=0, second=0)
tomorrow = today + timedelta(days=1)

events = calendar_list_events(
    time_min=today.isoformat() + "Z",
    time_max=tomorrow.isoformat() + "Z"
)
```

## API Reference

This tool uses the [Google Calendar API v3](https://developers.google.com/calendar/api/v3/reference).
