# Slack Tool

Send messages and interact with Slack workspaces via the Slack Web API.

## Setup

```bash
export SLACK_BOT_TOKEN=xoxb-your-bot-token-here
```

## All Tools (15 Total)

### Messages
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_send_message` | Send message to channel | `chat:write` |
| `slack_update_message` | Edit existing message | `chat:write` |
| `slack_delete_message` | Delete a message | `chat:write` |
| `slack_schedule_message` | Schedule future message | `chat:write` |

### Channels
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_list_channels` | List workspace channels | `channels:read`, `groups:read` |
| `slack_get_channel_history` | Read channel messages | `channels:history` |
| `slack_create_channel` | Create new channel | `channels:manage` |
| `slack_archive_channel` | Archive a channel | `channels:manage` |
| `slack_invite_to_channel` | Invite users to channel | `channels:manage` |
| `slack_set_channel_topic` | Set channel topic | `channels:manage` |

### Reactions
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_add_reaction` | Add emoji reaction | `reactions:write` |
| `slack_remove_reaction` | Remove emoji reaction | `reactions:write` |

### Users
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_get_user_info` | Get user profile | `users:read` |
| `slack_list_users` | List workspace users | `users:read` |

### Files
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_upload_file` | Upload text file | `files:write` |

## Creating a Slack App

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. Go to **OAuth & Permissions** → Add scopes from table above
3. Click **Install to Workspace**
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

## Example Usage

```python
# Send message
slack_send_message(channel="C0123456789", text="Hello!")

# Schedule message (Unix timestamp)
import time
future = int(time.time()) + 3600  # 1 hour from now
slack_schedule_message(channel="C0123456789", text="Reminder!", post_at=future)

# Create channel and invite users
result = slack_create_channel(name="my-new-channel")
slack_invite_to_channel(channel=result["channel"]["id"], user_ids="U001,U002")

# Upload file
slack_upload_file(channel="C0123456789", content="name,value\na,1\nb,2", filename="data.csv")
```

## Error Codes

| Error | Meaning |
|-------|---------|
| `invalid_auth` | Token invalid or expired |
| `channel_not_found` | Channel doesn't exist or bot not a member |
| `not_in_channel` | Bot needs to be invited |
| `missing_scope` | Token lacks required scope |
| `ratelimited` | Rate limit hit, retry later |
