# Discord Tool

Send messages and interact with Discord servers via the Discord API.

## Supported Actions

- **discord_list_guilds** – List guilds (servers) the bot is a member of
- **discord_list_channels** – List channels for a guild (optional `text_only` filter)
- **discord_send_message** – Send a message to a channel (validates 2000-char limit)
- **discord_get_messages** – Get recent messages from a channel

## Limits & Validation

- **Message length**: Max 2000 characters (validated before sending)
- **Rate limits**: Automatically retries up to 2 times on 429 using Discord's `retry_after`; returns clear error when exhausted
- **Channel filtering**: `discord_list_channels` defaults to text channels only; use `text_only=False` for all types

## Setup

1. Create a Discord application at [Discord Developer Portal](https://discord.com/developers/applications).

2. Create a bot:
   - Go to **Bot** section
   - Add a bot and copy the token

3. Invite the bot to your server:
   - Go to **OAuth2** → **URL Generator**
   - Scopes: `bot`
   - Bot permissions: `Send Messages`, `Read Message History`, `View Channels`, `Read Messages/View Channels`
   - Use the generated URL to invite the bot

4. Set the environment variable:
   ```bash
   export DISCORD_BOT_TOKEN=your_bot_token_here
   ```

## Getting IDs

Enable **Developer Mode** in Discord (User Settings → Advanced → Developer Mode).
Then right-click a server or channel to **Copy ID**.

## Use Case

Example: "When a production incident is resolved, post a short summary to our #incidents Discord channel."
