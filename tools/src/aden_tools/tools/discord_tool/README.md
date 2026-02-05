# Discord Bot API Integration

Complete Discord Bot API integration for Aden Hive framework providing 4 MCP tools for Discord automation and communication.

## Overview

The Discord tool enables AI agents to interact with Discord servers through bot functionality including:
- Send messages to channels with rich embeds
- Read message history and metadata
- List and filter server channels
- Add emoji reactions to messages

## Setup

### 1. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create new application and bot
3. Copy bot token
4. Invite bot to your server with required permissions

### 2. Configure Credentials

Set your Discord bot token:

```bash
export DISCORD_BOT_TOKEN="your_bot_token_here"
```

### 3. Bot Permissions

Required bot permissions:
- `Send Messages` - Send messages to channels
- `Read Message History` - Read channel message history  
- `Add Reactions` - Add emoji reactions
- `View Channels` - List and access channels

## Tools

### discord_send_message

Send messages to Discord channels with optional rich embeds.

```python
await discord_send_message(
    channel_id="123456789",
    content="Hello Discord!",
    embed_title="Status Update",
    embed_description="Agent task completed successfully",
    embed_color=0x00FF00
)
```

**Parameters:**
- `channel_id` (str): Discord channel ID
- `content` (str): Message text content
- `embed_title` (str, optional): Embed title
- `embed_description` (str, optional): Embed description
- `embed_color` (int, optional): Embed color as integer

**Returns:**
```json
{
  "success": true,
  "message_id": "987654321",
  "channel_id": "123456789"
}
```

### discord_read_messages

Fetch recent messages from Discord channels with metadata.

```python
await discord_read_messages(
    channel_id="123456789",
    limit=20
)
```

**Parameters:**
- `channel_id` (str): Discord channel ID
- `limit` (int): Number of messages to fetch (max 100)

**Returns:**
```json
{
  "success": true,
  "messages": [
    {
      "id": "987654321",
      "content": "Hello world!",
      "author": "Username#1234",
      "channel_id": "123456789",
      "timestamp": "2024-01-01T12:00:00",
      "reactions": ["👍", "❤️"]
    }
  ],
  "count": 1,
  "channel_id": "123456789"
}
```

### discord_list_channels

List accessible channels in Discord servers with filtering.

```python
await discord_list_channels(
    guild_id="123456789",
    channel_type="text"
)
```

**Parameters:**
- `guild_id` (str, optional): Filter by specific server
- `channel_type` (str, optional): Filter by channel type (text, voice, category)

**Returns:**
```json
{
  "success": true,
  "channels": [
    {
      "id": "123456789",
      "name": "general",
      "type": "text",
      "guild_id": "987654321"
    }
  ],
  "count": 1,
  "guild_id": "987654321"
}
```

### discord_add_reaction

Add emoji reactions to Discord messages.

```python
await discord_add_reaction(
    channel_id="123456789",
    message_id="987654321",
    emoji="👍"
)
```

**Parameters:**
- `channel_id` (str): Discord channel ID
- `message_id` (str): Discord message ID
- `emoji` (str): Unicode emoji or custom emoji name

**Returns:**
```json
{
  "success": true,
  "channel_id": "123456789",
  "message_id": "987654321",
  "emoji": "👍"
}
```

## Error Handling

All tools return structured error responses:

```json
{
  "success": false,
  "error": "Channel 123456789 not found"
}
```

Common errors:
- Invalid channel/message IDs
- Missing bot permissions
- Network connectivity issues
- Invalid bot token

## Rate Limiting

Discord API rate limiting is handled automatically by discord.py library:
- Message sending: ~5 requests/5 seconds per channel
- Message reading: ~50 requests/second
- Reactions: ~1 request/0.25 seconds per channel

## Usage Examples

### Customer Support Bot

```python
# Monitor support channel and respond
messages = await discord_read_messages("support-channel-id", 10)
for msg in messages["messages"]:
    if "help" in msg["content"].lower():
        await discord_send_message(
            msg["channel_id"],
            f"Hi {msg['author']}, I'll help you with that!",
            embed_title="Support Request Received",
            embed_color=0x0099FF
        )
        await discord_add_reaction(msg["channel_id"], msg["id"], "✅")
```

### Status Updates

```python
# Send deployment status to team channel
await discord_send_message(
    "team-channel-id",
    "Deployment completed successfully!",
    embed_title="🚀 Production Deploy",
    embed_description="Version 2.1.0 is now live",
    embed_color=0x00FF00
)
```

### Channel Management

```python
# List all text channels in server
channels = await discord_list_channels("server-id", "text")
for channel in channels["channels"]:
    print(f"Channel: #{channel['name']} (ID: {channel['id']})")
```

## Dependencies

- `discord.py>=2.4.0` - Discord API client library
- `aiohttp>=3.9.0` - Async HTTP client (discord.py dependency)

## Health Check

The credential spec includes health check endpoint:
- **URL**: `https://discord.com/api/v10/users/@me`
- **Method**: GET with bot token authentication
- **Purpose**: Validate bot token and API connectivity