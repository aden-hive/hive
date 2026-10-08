# Slack Tool

Send messages and interact with Slack workspaces via the Slack Web API.

## Setup

```bash
# Required - Bot token for most operations
export SLACK_BOT_TOKEN=xoxb-your-bot-token-here

# Optional - User token for search.messages API (requires user token)
export SLACK_USER_TOKEN=xoxp-your-user-token-here
```

## All Tools (26 Total)

### Messages (4)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_send_message` | Send message to channel | `chat:write` |
| `slack_update_message` | Edit existing message | `chat:write` |
| `slack_delete_message` | Delete a message | `chat:write` |
| `slack_schedule_message` | Schedule future message | `chat:write` |

### Channels (6)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_list_channels` | List workspace channels | `channels:read`, `groups:read` |
| `slack_get_channel_history` | Read channel messages | `channels:history` |
| `slack_create_channel` | Create new channel | `channels:manage` |
| `slack_archive_channel` | Archive a channel | `channels:manage` |
| `slack_invite_to_channel` | Invite users to channel | `channels:manage` |
| `slack_set_channel_topic` | Set channel topic | `channels:manage` |

### Reactions (2)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_add_reaction` | Add emoji reaction | `reactions:write` |
| `slack_remove_reaction` | Remove emoji reaction | `reactions:write` |

### Users (2)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_get_user_info` | Get user profile | `users:read` |
| `slack_list_users` | List workspace users | `users:read` |

### Files (1)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_upload_file` | Upload text file | `files:write` |

### Search (1)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_search_messages` | Search messages across workspace | `search:read` |

### Threads (1)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_get_thread_replies` | Get all replies in a thread | `channels:history` |

### Pins (3)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_pin_message` | Pin message to channel | `pins:write` |
| `slack_unpin_message` | Unpin message from channel | `pins:write` |
| `slack_list_pins` | List pinned items | `pins:read` |

### Bookmarks (1)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_add_bookmark` | Add bookmark/link to channel | `bookmarks:write` |

### Scheduled Messages (2)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_list_scheduled_messages` | List pending scheduled msgs | `chat:write` |
| `slack_delete_scheduled_message` | Cancel scheduled message | `chat:write` |

### Direct Messages (1)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_send_dm` | Send DM to user | `im:write` |

### Utilities (2)
| Tool | Description | Scope |
|------|-------------|-------|
| `slack_get_permalink` | Get permanent link to message | `chat:write` |
| `slack_send_ephemeral` | Send message visible to one user | `chat:write` |

## Required Scopes

Add these to your Slack app under **OAuth & Permissions**:
- `chat:write`, `channels:read`, `channels:history`, `channels:manage`
- `groups:read`, `reactions:write`, `users:read`, `files:write`
- `search:read`, `pins:read`, `pins:write`, `bookmarks:write`, `im:write`

## Example Usage

```python
# Send message
slack_send_message(channel="C0123456789", text="Hello!")

# Search workspace
slack_search_messages(query="from:@john urgent", count=10)

# Read thread
slack_get_thread_replies(channel="C0123456789", thread_ts="1234567890.123456")

# Send DM
slack_send_dm(user_id="U0123456789", text="Hello privately!")

# Pin a message
slack_pin_message(channel="C0123456789", timestamp="1234567890.123456")

# Add bookmark
slack_add_bookmark(channel="C0123456789", title="Docs", link="https://docs.example.com")
```

## Error Codes

| Error | Meaning |
|-------|---------|
| `invalid_auth` | Token invalid or expired |
| `channel_not_found` | Channel doesn't exist or bot not a member |
| `missing_scope` | Token lacks required scope |
| `ratelimited` | Rate limit hit, retry later |
