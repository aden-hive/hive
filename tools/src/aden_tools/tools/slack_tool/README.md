# Slack Tool

Send messages and interact with Slack workspaces via the Slack Web API.

## Tools

### `slack_send_message`
Send a message to a Slack channel.

**Parameters:**
- `channel` (str) - Channel ID (e.g., 'C0123456789') or name (e.g., '#general')
- `text` (str) - Message text (supports Slack mrkdwn)
- `thread_ts` (str, optional) - Reply in thread

### `slack_list_channels`
List channels in the workspace.

**Parameters:**
- `types` (str) - Channel types: `public_channel,private_channel,mpim,im`
- `limit` (int) - Max results (1-1000, default 100)

### `slack_get_channel_history`
Get recent messages from a channel.

**Parameters:**
- `channel` (str) - Channel ID
- `limit` (int) - Max messages (1-1000, default 20)

### `slack_add_reaction`
Add an emoji reaction to a message.

**Parameters:**
- `channel` (str) - Channel ID
- `timestamp` (str) - Message timestamp (ts)
- `emoji` (str) - Emoji name without colons (e.g., 'thumbsup')

### `slack_get_user_info`
Get information about a Slack user.

**Parameters:**
- `user_id` (str) - User ID (e.g., 'U0123456789')

## Setup

```bash
export SLACK_BOT_TOKEN=xoxb-your-bot-token-here
```

### Required Bot Token Scopes

| Tool | Required Scopes |
|------|----------------|
| `slack_send_message` | `chat:write` |
| `slack_list_channels` | `channels:read`, `groups:read` |
| `slack_get_channel_history` | `channels:history`, `groups:history` |
| `slack_add_reaction` | `reactions:write` |
| `slack_get_user_info` | `users:read` |

## Creating a Slack App

1. Go to https://api.slack.com/apps and click "Create New App"
2. Choose "From scratch", name your app, select workspace
3. Go to "OAuth & Permissions" → "Bot Token Scopes"
4. Add the scopes listed above
5. Click "Install to Workspace"
6. Copy the "Bot User OAuth Token" (starts with `xoxb-`)

## Error Handling

Common errors:
- `invalid_auth` - Invalid or expired token
- `channel_not_found` - Channel doesn't exist or bot not a member
- `not_in_channel` - Bot needs to be invited to the channel
- `missing_scope` - Token lacks required scope
- `ratelimited` - Rate limit exceeded, retry later
