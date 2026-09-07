# Mattermost Tool

Send messages, list channels, react, and manage posts on Mattermost servers via the Mattermost API.

## Setup

### 1. Create a Personal Access Token

1. Log in to your Mattermost server.
2. Go to **Account Settings > Security > Personal Access Tokens**.
3. Click **Create New Token**, enter a description, and click **Save**.
4. Copy the generated token.

### 2. Configure Environment Variables

```bash
export MATTERMOST_ACCESS_TOKEN="your-personal-access-token"
export MATTERMOST_URL="https://mattermost.example.com"
```

- `MATTERMOST_ACCESS_TOKEN` — Personal access token from step 1.
- `MATTERMOST_URL` — Base URL of your Mattermost server (including protocol).

Alternatively, configure via the credential store (`CredentialStoreAdapter`):

- Token: `credentials.get("mattermost")` or `credentials.get_by_alias("mattermost", account)`
- URL: `credentials.get("mattermost_url")`

## Tools (7)

| Tool | Description |
|------|-------------|
| `mattermost_list_teams` | List teams the authenticated user belongs to |
| `mattermost_list_channels` | List public channels for a team |
| `mattermost_get_channel` | Get detailed information about a channel |
| `mattermost_send_message` | Send a message (post) to a channel |
| `mattermost_get_posts` | Get posts from a channel |
| `mattermost_create_reaction` | Add an emoji reaction to a post |
| `mattermost_delete_post` | Delete a post (requires permissions) |

## Usage

### List Teams

```python
result = mattermost_list_teams()
# Returns: {"teams": [...], "success": True}
```

### List Channels

```python
result = mattermost_list_channels(
    team_id="your-team-id",
    per_page=100,
)
# Returns: {"channels": [...], "success": True}
```

### Get Channel Details

```python
result = mattermost_get_channel(
    channel_id="your-channel-id",
)
# Returns: {"channel": {...}, "success": True}
```

### Send a Message

```python
result = mattermost_send_message(
    channel_id="your-channel-id",
    message="Hello from Aden!",
)
# Returns: {"success": True, "post": {...}}
```

### Reply in a Thread

```python
result = mattermost_send_message(
    channel_id="your-channel-id",
    message="This is a reply.",
    root_id="original-post-id",
)
# Returns: {"success": True, "post": {...}}
```

### Get Posts

```python
result = mattermost_get_posts(
    channel_id="your-channel-id",
    per_page=60,
    page=0,
)
# Returns: {"posts": [...], "success": True}
```

### Get Posts with Pagination

```python
result = mattermost_get_posts(
    channel_id="your-channel-id",
    before="post-id-to-get-before",
    after="post-id-to-get-after",
)
# Returns: {"posts": [...], "success": True}
```

### Create a Reaction

```python
result = mattermost_create_reaction(
    post_id="post-id-to-react-to",
    emoji_name="thumbsup",
)
# Returns: {"success": True}
```

### Delete a Post

```python
result = mattermost_delete_post(
    post_id="post-id-to-delete",
)
# Returns: {"success": True, "deleted_post_id": "post-id-to-delete"}
```

## Scope

- Read teams and channels the authenticated user can access
- Send messages and reply in threads
- Retrieve channel posts with pagination
- Add emoji reactions to posts
- Delete posts (requires author or admin permissions)

## Rate Limits

The tool retries up to 2 additional attempts (3 total) on HTTP 429 responses, respecting the `Retry-After` header with a maximum wait of 60 seconds. Subject to your Mattermost server's rate limits.

## API Reference

### mattermost_list_teams

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| account | str | No | Optional account alias for credential store |

### mattermost_list_channels

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| team_id | str | Yes | Team ID (obtain via `mattermost_list_teams`) |
| per_page | int | No | Max channels to return (1‑200, default 100) |
| account | str | No | Optional account alias for credential store |

### mattermost_get_channel

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| channel_id | str | Yes | Channel ID |
| account | str | No | Optional account alias for credential store |

### mattermost_send_message

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| channel_id | str | Yes | Channel ID to post in |
| message | str | Yes | Message text (max 16383 characters, supports Markdown) |
| root_id | str | No | Post ID to reply to (creates a thread) |
| account | str | No | Optional account alias for credential store |

### mattermost_get_posts

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| channel_id | str | Yes | Channel ID |
| per_page | int | No | Max posts to return (1‑200, default 60) |
| page | int | No | Page number for pagination (default 0) |
| before | str | No | Post ID to get posts before |
| after | str | No | Post ID to get posts after |
| account | str | No | Optional account alias for credential store |

### mattermost_create_reaction

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| post_id | str | Yes | ID of the post to react to |
| emoji_name | str | Yes | Emoji name without colons (e.g. "thumbsup", "heart") |
| account | str | No | Optional account alias for credential store |

### mattermost_delete_post

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| post_id | str | Yes | ID of the post to delete |
| account | str | No | Optional account alias for credential store |

### References

- [Mattermost API Documentation](https://api.mattermost.com/)
- [Mattermost Server Docs](https://docs.mattermost.com/)
