# Mattermost Tool

Interact with Mattermost servers for team collaboration and messaging.

## Description

The Mattermost tool allows agents to list teams and channels, send messages, retrieve posts, and manage reactions on a Mattermost server. It supports both cloud and self-hosted instances.

## Tools

### mattermost_list_teams
List all teams the authenticated user belongs to.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `account` | str | No | `""` | Optional account alias for multi-account setups |

### mattermost_list_channels
List public channels for a specific team.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `team_id` | str | Yes | - | ID of the team |
| `per_page`| int | No | `100` | Max channels to return (1-200) |
| `account` | str | No | `""` | Optional account alias |

### mattermost_get_channel
Get detailed information about a channel.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `channel_id` | str | Yes | - | ID of the channel |
| `account`    | str | No | `""` | Optional account alias |

### mattermost_send_message
Send a message (post) to a channel. Supports Markdown.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `channel_id` | str | Yes | - | ID of the channel to post in |
| `message`    | str | Yes | - | Message text (max 16383 chars) |
| `root_id`    | str | No | `""` | ID of the parent post for threading |
| `account`    | str | No | `""` | Optional account alias |

### mattermost_get_posts
Retrieve posts from a channel with pagination support.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `channel_id` | str | Yes | - | ID of the channel |
| `per_page`   | int | No | `60` | Max posts to return (1-200) |
| `page`       | int | No | `0`  | Page number for pagination |
| `before`     | str | No | `""` | Post ID to get posts before |
| `after`      | str | No | `""` | Post ID to get posts after |
| `account`    | str | No | `""` | Optional account alias |

### mattermost_create_reaction
Add an emoji reaction to a specific post.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `post_id`    | str | Yes | - | ID of the post to react to |
| `emoji_name` | str | Yes | - | Emoji name (e.g., "thumbsup", "heart") |
| `account`    | str | No | `""` | Optional account alias |

### mattermost_delete_post
Delete an existing post.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `post_id` | str | Yes | - | ID of the post to delete |
| `account` | str | No | `""` | Optional account alias |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MATTERMOST_URL` | Yes | Base URL of your Mattermost server (e.g. `https://mattermost.example.com`) |
| `MATTERMOST_ACCESS_TOKEN` | Yes | Personal access token from your Mattermost profile |

## Example Usage

```python
# List teams to get team_id
teams = mattermost_list_teams()

# List channels for a team
channels = mattermost_list_channels(team_id="your-team-id")

# Send a message to a channel
mattermost_send_message(channel_id="your-channel-id", message="Hello from Aden Hive! 🚀")

# Reply to a thread
mattermost_send_message(channel_id="your-channel-id", message="Replying to this thread.", root_id="parent-post-id")
```

## Error Handling

Returns error dicts for common issues:
- `Mattermost credentials not configured` - Missing access token or URL
- `HTTP 401: Unauthorized` - Invalid access token
- `HTTP 404: Not Found` - Invalid team or channel ID
- `Message exceeds 16383 character limit` - Provided message is too long
- `Mattermost rate limit exceeded` - Too many requests (429)
