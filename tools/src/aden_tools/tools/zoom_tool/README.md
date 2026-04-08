# Zoom Tool

Meeting management, recordings, and user info via the Zoom API v2.

## Tools

| Tool | Description |
|------|-------------|
| `zoom_get_user` | Get Zoom user profile information |
| `zoom_list_meetings` | List scheduled, live, or upcoming meetings for a user |
| `zoom_get_meeting` | Get full details of a specific meeting |
| `zoom_create_meeting` | Create a new instant or scheduled meeting |
| `zoom_update_meeting` | Update topic, time, duration, or agenda of a meeting |
| `zoom_delete_meeting` | Cancel and delete a meeting |
| `zoom_list_recordings` | List cloud recordings within a date range |
| `zoom_list_meeting_participants` | List participants from a past meeting |
| `zoom_list_meeting_registrants` | List registrants for a registration-enabled meeting |

## Setup

Requires a Zoom Server-to-Server OAuth access token:

1. Go to [marketplace.zoom.us](https://marketplace.zoom.us) → **Develop → Build App → Server-to-Server OAuth**
2. Create an app and note the **Account ID**, **Client ID**, and **Client Secret**
3. Generate an access token and set it as an environment variable:

```bash
ZOOM_ACCESS_TOKEN=your-server-to-server-oauth-token
```

> **Token expiry:** Server-to-Server OAuth tokens expire after **1 hour**. You will need to regenerate the token and update `ZOOM_ACCESS_TOKEN` when you see an `"Invalid or expired Zoom access token"` error.

Required OAuth scopes:
- `meeting:read` — list and read meetings
- `meeting:write` — create, update, delete meetings
- `recording:read` — list cloud recordings
- `user:read` — read user profiles

## Usage Examples

### Get authenticated user info

```python
zoom_get_user(user_id="me")
```

### List upcoming meetings

```python
zoom_list_meetings(user_id="me", type="upcoming", page_size=10)
```

### Create a scheduled meeting

```python
zoom_create_meeting(
    topic="Sprint Planning",
    start_time="2025-06-01T10:00:00Z",
    duration=60,
    timezone="America/New_York",
    agenda="Review sprint backlog and assign tasks",
)
```

### Create an instant meeting

```python
zoom_create_meeting(topic="Quick Sync")
```

### Update a meeting

```python
zoom_update_meeting(
    meeting_id="123456789",
    topic="Sprint Planning - Updated",
    duration=90,
)
```

### Delete a meeting

```python
zoom_delete_meeting(meeting_id="123456789")
```

### List cloud recordings for a date range

```python
zoom_list_recordings(
    from_date="2025-05-01",
    to_date="2025-05-31",
    user_id="me",
)
```

### List participants from a past meeting

```python
zoom_list_meeting_participants(meeting_id="123456789")
```

### List approved registrants

```python
zoom_list_meeting_registrants(
    meeting_id="123456789",
    status="approved",
)
```

## Meeting Types

| Type value | Meaning |
|------------|---------|
| `upcoming` | All upcoming meetings |
| `scheduled` | Scheduled meetings only |
| `live` | Currently live meetings |
| `previous_meetings` | Past meetings |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "Zoom credentials not configured", "help": "Set ZOOM_ACCESS_TOKEN environment variable or configure via credential store"}
{"error": "Invalid or expired Zoom access token"}
{"error": "Insufficient Zoom API scopes for this operation"}
{"error": "Zoom rate limit exceeded. Try again later."}
```
