# Mattermost Tool

Interact with Mattermost servers — send messages, manage channels, react to posts, and more — within the Aden agent framework.

## Installation

The Mattermost tool uses `httpx` which is already included in the base dependencies. No additional installation required.

## Setup

You need a Mattermost **Personal Access Token** and the **URL** of your Mattermost server.

### Getting a Personal Access Token

1. Log into your Mattermost instance
2. Go to **Profile → Security → Personal Access Tokens**
3. Click **Create Token**, give it a description (e.g., "Hive Agent")
4. Copy the token (shown only once)

> **Note:** Personal Access Tokens must be enabled by your Mattermost admin under **System Console → Integrations → Integration Management**.

### Configuration

Set the following environment variables:

```bash
export MATTERMOST_ACCESS_TOKEN="your-token-here"
export MATTERMOST_URL="https://your-mattermost.example.com"
```

Or configure via the Hive credential store:

```bash
hive credentials set mattermost
```

## Available Tools

| Tool | Description |
|---|---|
| `mattermost_list_teams` | List all teams the bot belongs to |
| `mattermost_list_channels` | List public channels for a team |
| `mattermost_get_channel` | Get info about a specific channel |
| `mattermost_send_message` | Send a message to a channel |
| `mattermost_get_posts` | Fetch posts (messages) from a channel |
| `mattermost_create_reaction` | Add an emoji reaction to a post |
| `mattermost_delete_post` | Delete a post |
| `mattermost_update_post` | Edit an existing post |
| `mattermost_search_posts` | Search for posts across the server |
| `mattermost_get_user` | Get information about a user |
| `mattermost_create_direct_channel` | Open a direct message channel with a user |
| `mattermost_upload_file` | Upload a file to a channel |

## Example Usage

### Send a message

```python
result = mattermost_send_message(
    channel_id="abc123",
    message="Hello from Hive! :wave:"
)
```

### Reply in a thread

```python
result = mattermost_send_message(
    channel_id="abc123",
    message="This is a thread reply",
    root_id="parent_post_id_here"
)
```

### Search for posts

```python
result = mattermost_search_posts(
    team_id="team123",
    terms="deployment failed",
    is_or_search=False
)
```

### Send a direct message

```python
# First open a DM channel
dm = mattermost_create_direct_channel(user_id="user123")
channel_id = dm["channel"]["id"]

# Then send
mattermost_send_message(channel_id=channel_id, message="Hey, quick question...")
```

## Required Permissions

The token needs the following Mattermost permissions:

- `read_channel` — to list and read channels
- `post_all` — to send messages in any channel
- `create_post` — to create posts
- `delete_post` — to delete posts (own posts, or admin for others)
- `edit_post` — to edit posts
- `create_direct_channel` — to open DMs
- `upload_file` — to attach files

For most use cases, a standard user token with default permissions is sufficient.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MATTERMOST_ACCESS_TOKEN` | Yes | Personal Access Token |
| `MATTERMOST_URL` | Yes | Full URL of your Mattermost server (e.g., `https://chat.example.com`) |

## Notes

- The Mattermost API base path (`/api/v4`) is appended automatically — do not include it in `MATTERMOST_URL`
- Message length is capped at **16,383 characters** (Mattermost API limit)
- Rate-limited requests (HTTP 429) are automatically retried up to 2 times with backoff
- Self-hosted and Mattermost Cloud instances are both supported

## API Reference

[https://api.mattermost.com/](https://api.mattermost.com/)

## Contributed by


