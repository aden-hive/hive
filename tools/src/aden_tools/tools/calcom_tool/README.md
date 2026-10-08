# Cal.com Tool

MCP tool integration for [Cal.com](https://cal.com) - open source scheduling infrastructure.

## Overview

This tool provides 9 MCP-registered functions for interacting with the Cal.com API:

| Tool | Description |
|------|-------------|
| `calcom_list_bookings` | List bookings with optional filters (status, event type, date range) |
| `calcom_get_booking` | Get detailed information about a specific booking |
| `calcom_create_booking` | Create a new booking for an event type |
| `calcom_cancel_booking` | Cancel an existing booking |
| `calcom_get_availability` | Get available time slots for booking |
| `calcom_update_schedule` | Update a user's availability schedule |
| `calcom_list_schedules` | List all availability schedules for the authenticated user |
| `calcom_list_event_types` | List all configured event types |
| `calcom_get_event_type` | Get detailed information about an event type |

## Configuration

### Environment Variable

```bash
export CALCOM_API_KEY="cal_live_..."
```

### Getting an API Key

1. Log in to [Cal.com](https://cal.com)
2. Go to **Settings → Developer → API Keys**
3. Click **"Create new API key"**
4. Give it a name and set expiration
5. Copy the key (shown only once)

## Usage Examples

### List Upcoming Bookings

```python
calcom_list_bookings(status="upcoming", limit=10)
```

### Create a Booking

```python
calcom_create_booking(
    event_type_id=123,
    start="2024-01-20T14:00:00Z",
    name="John Doe",
    email="john@example.com",
    timezone="America/New_York",
    notes="Discuss Q1 planning"
)
```

### Check Availability

```python
calcom_get_availability(
    event_type_id=123,
    start_time="2024-01-20T00:00:00Z",
    end_time="2024-01-27T00:00:00Z",
    timezone="America/New_York"
)
```

### Cancel a Booking

```python
calcom_cancel_booking(
    booking_id=456,
    reason="Schedule conflict"
)
```

## API Reference

- **Base URL:** `https://api.cal.com/v1`
- **Authentication:** Bearer token
- **Documentation:** [Cal.com API Reference](https://cal.com/docs/api-reference/v1)

## Error Handling

All tools return a dict with either:
- Success: API response data
- Error: `{"error": "description", "help": "guidance"}`

Common error scenarios:
- `401`: Invalid or expired API key
- `403`: Insufficient permissions
- `404`: Resource not found
- `429`: Rate limit exceeded
