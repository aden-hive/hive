# Discord Community Digest

**Version**: 1.0.0
**Type**: Multi-node agent

## Overview

Monitor Discord servers, categorize messages by priority, and deliver an actionable summary as a Discord DM. Built for open-source contributors and community managers who need to stay on top of Discord without checking it constantly.

## Architecture

### Execution Flow

```
configure → scan-channels → generate-digest
```

### Nodes

1. **configure** (client-facing) — Captures user preferences: servers, channels, lookback window, keywords, and Discord user ID for DM delivery.
2. **scan-channels** — Pulls messages from target channels, filters by time range, flags mentions/keywords/admin posts. Uses per-channel cursors for incremental fetching.
3. **generate-digest** — Summarizes flagged messages into 4 categories and delivers as a Discord DM.

### Digest Categories

- **Action Needed** — @mentions, direct replies, questions addressed to you
- **Interesting Threads** — active discussions matching keywords or with high engagement
- **Announcements** — admin/moderator posts, roadmap updates, new releases
- **FYI** — everything else worth knowing

## Setup

### 1. Create a Discord Bot

1. Go to https://discord.com/developers/applications
2. Create a new application
3. Go to **Bot** → **Add Bot**
4. Copy the bot token
5. Go to **OAuth2** → **URL Generator**
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Read Message History`, `View Channels`
6. Use the generated URL to invite the bot to your server(s)

### 2. Configure Credentials

```bash
export DISCORD_BOT_TOKEN="your-bot-token-here"
```

Or configure via the Hive credential store.

### 3. Configure Hive LLM

Make sure you have a model configured in `~/.hive/configuration.json` (run `hive quickstart` if you haven't already).

## Usage

### First Run

```bash
cd examples/templates
python -m discord_digest run
```

The agent will ask for your preferences (servers, channels, keywords, user ID) and save them for future runs.

### Subsequent Runs

```bash
python -m discord_digest run
```

Uses saved configuration and cursors — only fetches new messages since the last run.

### Reconfigure

```bash
python -m discord_digest run --reconfigure
```

### Other Commands

```bash
python -m discord_digest info       # Show agent metadata
python -m discord_digest validate   # Check agent structure
python -m discord_digest tui        # Launch TUI dashboard
python -m discord_digest shell      # Interactive CLI session
```

### Scheduling (cron)

```bash
# Run every day at 8 PM
0 20 * * * cd /path/to/hive/examples/templates && DISCORD_BOT_TOKEN="..." python -m discord_digest run -q
```

## Dedup / Incremental Fetching

The agent tracks a per-channel cursor (`cursors.json`) storing the last-processed message ID. On subsequent runs, it uses Discord's `after` parameter to only fetch messages newer than the cursor — no repeated items across runs.

Cursors are stored at `~/.hive/discord_digest/cursors.json`.

## Required Tools

| Tool | Node | Purpose |
|------|------|---------|
| `discord_list_guilds` | scan-channels | Enumerate servers the bot has access to |
| `discord_list_channels` | scan-channels | List text channels in each server |
| `discord_get_messages` | scan-channels | Fetch recent messages with pagination |
| `discord_send_message` | generate-digest | Deliver digest as a DM to the user |
