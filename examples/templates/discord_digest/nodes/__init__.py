"""Node definitions for Discord Community Digest."""

from framework.graph import NodeSpec

# ---------------------------------------------------------------------------
# Node 1: Configure digest preferences (client-facing)
# ---------------------------------------------------------------------------
configure_node = NodeSpec(
    id="configure",
    name="Configure Digest",
    description=(
        "Capture user preferences: servers, channels, lookback window, "
        "keywords, and Discord user ID for DM delivery."
    ),
    node_type="event_loop",
    client_facing=True,
    input_keys=[],
    output_keys=["digest_config"],
    system_prompt="""\
You are a Discord digest assistant helping the user set up their preferences.

**STEP 1 — Greet and ask the user:**
Ask the user for:
1. Which Discord servers to monitor (default: all servers the bot can see)
2. Which channels to focus on, or "all" for all text channels (default: all)
3. How many days to look back (default: 3)
4. Keywords or topics of interest (default: agent, integration, PR, bug, release)
5. Their Discord user ID — so the bot can DM them the digest
   (they can find it by enabling Developer Mode in Discord settings,
   then right-clicking their name and selecting "Copy User ID")

Keep it brief and friendly. If the user already provided preferences in their \
initial message, acknowledge them.

After your greeting, call ask_user() to wait for the user's response.

**STEP 2 — After the user responds, call set_output:**
set_output("digest_config", <JSON string>) with this structure:
{
  "servers": ["all"],
  "channels": ["all"],
  "lookback_days": 3,
  "keywords": ["agent", "integration", "PR", "bug", "release"],
  "user_id": "<their Discord user ID>"
}

If they didn't provide a user ID, ask again — it's required for DM delivery.
""",
    tools=[],
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 2: Scan Discord channels and collect messages
# ---------------------------------------------------------------------------
scan_channels_node = NodeSpec(
    id="scan-channels",
    name="Scan Channels",
    description=(
        "Pull messages from target Discord channels, "
        "filter by time range, and flag important messages."
    ),
    node_type="event_loop",
    input_keys=["digest_config"],
    output_keys=["channel_data"],
    system_prompt="""\
You are a Discord channel scanner. Your job is to systematically pull messages \
from Discord and identify what matters.

Using the digest_config provided, do the following steps IN ORDER:

1. Call discord_list_guilds to get all available servers.
2. For each target server (or all if "all"), call discord_list_channels to get \
text channels.
3. For each channel, call discord_get_messages to fetch recent messages.
   IMPORTANT: If the digest_config contains a "cursors" object, use the cursor \
value for each channel as the "after" parameter in discord_get_messages. This \
ensures you only fetch NEW messages since the last digest run. Example:
   - cursors: {"123456": "999888777"} means call \
discord_get_messages(channel_id="123456", after="999888777")
   - If a channel has no cursor, fetch without the "after" parameter.
4. Filter messages to only those within the lookback window (lookback_days from config).
5. For each channel scanned, track the HIGHEST (newest) message ID you see. \
You will include these as "new_cursors" in your output so the next run picks up \
where this one left off.
6. Flag messages that:
   - @mention the user (check for <@USER_ID> where USER_ID is from config)
   - Are replies to the user's previous messages
   - Come from server admins or moderators (check for admin/moderator roles)
   - Contain any of the configured keywords
   - Have high engagement (many replies or reactions)

Compile all flagged messages with their channel name, author, content, \
timestamp, and why they were flagged.

Output the results using set_output("channel_data", <JSON string>) with:
{
  "channels_scanned": <number>,
  "messages": [
    {
      "channel": "<channel name>",
      "channel_id": "<channel id>",
      "author": "<username>",
      "content": "<message text>",
      "timestamp": "<ISO timestamp>",
      "message_id": "<message id>",
      "flags": ["mention", "keyword:agent", "admin_post", ...]
    }
  ],
  "new_cursors": {
    "<channel_id>": "<highest message ID seen>"
  }
}
""",
    tools=[
        "discord_list_guilds",
        "discord_list_channels",
        "discord_get_messages",
    ],
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 3: Generate and deliver the digest
# ---------------------------------------------------------------------------
generate_digest_node = NodeSpec(
    id="generate-digest",
    name="Generate Digest",
    description="Summarize scanned messages into an actionable digest and deliver as a Discord DM.",
    node_type="event_loop",
    input_keys=["digest_config", "channel_data"],
    output_keys=["digest_report"],
    system_prompt="""\
You are a digest writer. Take the scanned channel data and produce a clear, \
actionable summary organized into these categories:

1. **Action Needed** — Messages where someone @mentioned the user, replied to \
their message, or asked them a direct question. These need a response.

2. **Interesting Threads** — Active discussions matching the user's keywords \
or with high engagement. Worth reading but no response required.

3. **Announcements** — Posts from admins/moderators, roadmap updates, new \
releases, or official announcements.

4. **FYI** — Everything else worth knowing, briefly summarized.

Format the digest as a readable message. Keep it concise — each item should \
be 1-2 lines with the channel name and a brief summary.

If a category has no items, omit it entirely.

**Delivery:**
1. First, get the user's Discord user ID from digest_config.
2. Call discord_send_message to DM the user. To DM a user, send to the DM \
channel. The bot needs to create a DM channel first — but since \
discord_send_message can send to any channel ID, you should note the user_id \
for delivery.
3. If the digest is longer than 2000 characters (Discord's limit), split it \
into multiple messages — send one per category.

After sending, store the full digest text using:
set_output("digest_report", "<the full digest text>")
""",
    tools=["discord_send_message"],
    max_retries=2,
)

# All nodes for easy import
all_nodes = [
    configure_node,
    scan_channels_node,
    generate_digest_node,
]

__all__ = [
    "configure_node",
    "scan_channels_node",
    "generate_digest_node",
    "all_nodes",
]
