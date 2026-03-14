"""Node definitions for Discord Community Digest."""

from framework.graph import NodeSpec

# Node 1: Configure digest preferences (client-facing)
configure_node = NodeSpec(
    id="configure",
    name="Configure Digest",
    description="Capture user preferences: servers, channels, lookback window, keywords, and delivery channel.",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=[],
    output_keys=["digest_config"],
    system_prompt="""\
You are a Discord digest configuration assistant.

**STEP 1 — Ask the user for their preferences (text only, NO tool calls):**
Collect these details:
1. Which Discord servers to monitor (server names or "all")
2. How many days to look back (default: 3, range: 1-7)
3. Keywords of interest (default: agent, integration, PR, bug, release)
4. Delivery channel ID — the Discord channel where the digest should be sent
5. Any channels to skip (optional)

**STEP 2 — After the user responds, call set_output:**
set_output("digest_config", {
    "servers": ["all"],
    "lookback_days": 3,
    "keywords": ["agent", "integration", "PR", "bug", "release"],
    "delivery_channel_id": "the_channel_id_user_provided",
    "skip_channels": []
})
""",
    tools=[],
)

# Node 2: Scan Discord channels and collect messages
scan_channels_node = NodeSpec(
    id="scan-channels",
    name="Scan Channels",
    description=(
        "Discover channels, pull messages within the lookback window, "
        "flag mentions, keyword matches, admin posts, and high-engagement threads. "
        "Track per-channel cursor to avoid duplicate messages on reruns."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["digest_config"],
    output_keys=["channel_data"],
    system_prompt="""\
You are a Discord channel scanner. Systematically pull and analyze messages.

STEP-BY-STEP:

1. Load the dedup cursor by calling load_data("discord_digest_cursors").
   If the file doesn't exist, start with an empty dict {{}}.

2. Call discord_list_guilds to get all servers the bot can see.
   Filter to only the servers in digest_config.servers (or all if "all").

3. For each server, call discord_list_channels(guild_id, text_only=True).
   Skip any channels listed in digest_config.skip_channels.

4. For each channel, call discord_get_messages(channel_id, limit=100).
   If the cursor has a last_message_id for this channel, pass it as
   the "after" parameter to skip already-seen messages.

5. Filter messages to only those within the lookback window
   (compare message timestamp against now - lookback_days).

6. For each message, flag it if:
   - It @mentions someone, @everyone, or @here
   - It contains any of digest_config.keywords (case-insensitive)
   - The author has admin/moderator permissions
   - It has high engagement (3+ reactions or 5+ replies)

7. Update the cursor: for each channel, record the newest message ID.
   Call save_data("discord_digest_cursors", updated_cursor_dict).

8. Call set_output("channel_data", {{
       "messages": [...],
       "flagged": [...],
       "channels_scanned": N,
       "messages_found": M
   }})
""",
    tools=[
        "discord_list_guilds",
        "discord_list_channels",
        "discord_get_messages",
        "load_data",
        "save_data",
    ],
)

# Node 3: Generate and deliver the digest
generate_digest_node = NodeSpec(
    id="generate-digest",
    name="Generate Digest",
    description=(
        "Categorize flagged messages into Action Needed / Interesting Threads / "
        "Announcements / FYI, format as a readable digest, and send to the "
        "delivery channel via discord_send_message."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["digest_config", "channel_data"],
    output_keys=["digest_report"],
    system_prompt="""\
You are a digest writer. Take the scanned channel data and produce a clear,
actionable summary.

CATEGORIZE messages into these groups:

1. **Action Needed** — @mentions, direct replies, urgent keyword matches,
   unresolved questions. These need a response.

2. **Interesting Threads** — Active discussions with high engagement
   (3+ reactions, 5+ replies) or matching user keywords. Worth reading.

3. **Announcements** — Posts from admins/moderators, official announcements,
   release notes, roadmap updates.

4. **FYI** — Everything else worth knowing, briefly summarized.

FORMAT the digest using Discord markdown:
- Use ## headers for each category
- Each item: 1-2 line summary with #channel and message link
- Message links: https://discord.com/channels/{guild_id}/{channel_id}/{message_id}
- If a category has no items, omit it entirely
- Keep the total digest concise and scannable

DELIVER the digest:
1. Call discord_send_message(channel_id=digest_config.delivery_channel_id,
   content=formatted_digest)
2. If the digest exceeds 2000 characters, split into multiple messages
   (one per category)
3. If delivery fails, log the error but still set the output

Call set_output("digest_report", full_digest_text)
""",
    tools=["discord_send_message"],
)

__all__ = [
    "configure_node",
    "scan_channels_node",
    "generate_digest_node",
]
