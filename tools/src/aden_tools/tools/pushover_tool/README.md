# Pushover Tool

Send push notifications to mobile devices via the [Pushover API](https://pushover.net/api).

## Setup

1. Create an account at [pushover.net](https://pushover.net)
2. Create an application at [pushover.net/apps/build](https://pushover.net/apps/build)
3. Copy your **API Token** and **User Key**

## Authentication

Set the following environment variables:
```bash
export PUSHOVER_API_TOKEN=your_api_token
export PUSHOVER_USER_KEY=your_user_key
```

## Available Tools

### `pushover_send_notification`
Send a push notification to your device.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| message | str | Yes | Notification body |
| title | str | No | Notification title |
| priority | int | No | -2 to 2 (default 0) |
| sound | str | No | Sound name |
| device | str | No | Target device name |

### `pushover_send_notification_with_url`
Send a notification with a URL attachment.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| message | str | Yes | Notification body |
| url | str | Yes | URL to attach |
| url_title | str | No | Title for the URL |
| title | str | No | Notification title |
| priority | int | No | -2 to 2 (default 0) |

### `pushover_get_sounds`
Get list of available notification sounds.

### `pushover_validate_user`
Validate credentials and list registered devices.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| device | str | No | Device name to validate |

## Priority Levels

| Value | Description |
|-------|-------------|
| -2 | Lowest – no sound or vibration |
| -1 | Low – no sound or vibration |
| 0 | Normal (default) |
| 1 | High – bypasses quiet hours |
| 2 | Emergency – repeats until acknowledged |

## Example Usage
```python
# Send a simple notification
pushover_send_notification(
    message="Agent task completed successfully!",
    title="Hive Agent",
    priority=0,
)

# Send with a URL
pushover_send_notification_with_url(
    message="Your report is ready",
    url="https://example.com/report",
    url_title="View Report",
    title="Hive Agent",
)
```
