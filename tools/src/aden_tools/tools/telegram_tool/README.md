# Telegram Bot Tool

Send messages and documents to Telegram chats using the Bot API.

## Features

- **telegram_send_message** - Send text messages to users, groups, or channels
- **telegram_send_document** - Send documents/files to chats

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Choose a name and username for your bot
4. Copy the API token provided (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Configure the Token

Set the environment variable:

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token-here"
```

Or configure via the Hive credential store.

### 3. Get Your Chat ID

To send messages, you need the chat ID:

1. Start a conversation with your bot
2. Send any message to the bot
3. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find the `chat.id` in the response

For groups: Add the bot to the group, then check getUpdates.

## Usage Examples

### Send a Message

```python
telegram_send_message(
    chat_id="123456789",
    text="Hello from Hive! 🚀",
    parse_mode="HTML"
)
```

### Send with Formatting

```python
# HTML formatting
telegram_send_message(
    chat_id="123456789",
    text="<b>Alert:</b> Task completed successfully!",
    parse_mode="HTML"
)

# Markdown formatting
telegram_send_message(
    chat_id="123456789",
    text="*Bold* and _italic_ text",
    parse_mode="Markdown"
)
```

### Send a Document

```python
telegram_send_document(
    chat_id="123456789",
    document="https://example.com/report.pdf",
    caption="Weekly Report"
)
```

### Silent Notification

```python
telegram_send_message(
    chat_id="123456789",
    text="Background update completed",
    disable_notification=True
)
```

## API Reference

### telegram_send_message

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| chat_id | str | Yes | Target chat ID or @username |
| text | str | Yes | Message text (1-4096 chars) |
| parse_mode | str | No | "HTML" or "Markdown" |
| disable_notification | bool | No | Send silently |

### telegram_send_document

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| chat_id | str | Yes | Target chat ID or @username |
| document | str | Yes | URL or file_id of document |
| caption | str | No | Caption (0-1024 chars) |
| parse_mode | str | No | Format for caption |

## Error Handling

The tools return error dictionaries on failure:

```python
{"error": "Invalid Telegram bot token"}
{"error": "Chat not found"}
{"error": "Bot was blocked by the user or lacks permissions"}
{"error": "Rate limit exceeded. Try again later."}
```

## References

- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [BotFather](https://t.me/BotFather)
