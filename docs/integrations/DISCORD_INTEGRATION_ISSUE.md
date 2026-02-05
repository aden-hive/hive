# [Integration]: Discord Bot API - Complete MCP Tool Implementation

## Differentiation from Issue #1030

**This is NOT a duplicate of #1030.** Issue #1030 proposes a **generic "messaging_tool"** for both Slack and Discord, while this is a **dedicated Discord Bot API integration** with production-ready implementation.

### Key Differences:

| Aspect | Issue #1030 | This Proposal |
|--------|-------------|---------------|
| **Scope** | Generic messaging tool for Slack + Discord | Discord-only Bot API integration |
| **Architecture** | Unified interface with platform abstraction | Direct Discord Bot API implementation |
| **Implementation** | Conceptual with platform/base.py structure | Complete MCP tools with discord.py |
| **Credential Model** | Multiple platform credentials | Single Discord bot token |
| **API Approach** | Abstract messaging interface | Native Discord Bot API features |
| **File Structure** | `messaging_tool/platforms/discord.py` | `discord_tool/discord_tool.py` |
| **Status** | Feature request with ideas | Production-ready specification |
| **Timeline** | No implementation plan | 3-5 day detailed timeline |

### Why Discord-Only is Better:

1. **Native Features**: Direct access to Discord-specific features (embeds, reactions, guild management)
2. **Performance**: No abstraction layer overhead
3. **Maintainability**: Single platform focus, easier to optimize and debug
4. **Discord Bot Ecosystem**: Leverages discord.py library and Discord Bot best practices
5. **Immediate Value**: Can be implemented and deployed independently

**This proposal delivers a complete, Discord-focused integration that follows Hive's established single-platform pattern (like GitHub tools, HubSpot tools).**

## Service

Discord Bot API integration that enables Hive agents to interact with Discord servers for real-time team communication, notifications, and community management. After this integration, developers will be able to create Discord bots that do: community management, DevOps notifications, support automation, and cross-platform integrations.

**Description:** Discord Bot Token for sending messages, reading channels, and managing reactions

## Credential Identity

- **credential_id:** `discord`
- **env_var:** `DISCORD_BOT_TOKEN`
- **credential_key:** `token`

## Tools

Tool function names that require this credential:

- `discord_send_message`
- `discord_read_messages`
- `discord_list_channels`
- `discord_add_reaction`

## Auth Methods

- **Direct API key supported:** Yes
- **Aden OAuth supported:** No

Discord uses Bot Tokens for authentication. No OAuth flow required - users create bots in Discord Developer Portal and use the generated token.

## How to Get the Credential

Link where users obtain the key/token: https://discord.com/developers/applications

Step-by-step instructions:

1. Go to Discord Developer Portal: https://discord.com/developers/applications
2. Create New Application → Enter application name
3. Navigate to "Bot" section → Click "Add Bot"
4. Enable required intents: Message Content Intent
5. Click "Reset Token" and copy the bot token (save securely!)
6. Generate invite URL with permissions: Send Messages, Read Message History, Add Reactions
7. Invite bot to your Discord server using the generated URL

## Health Check

A lightweight API call to validate the credential (no writes, no charges).

- **Endpoint:** `https://discord.com/api/v10/users/@me`
- **Method:** `GET`
- **Auth header:** `Authorization: Bot {token}`
- **Parameters:** None
- **200 means:** Bot token is valid
- **401 means:** Invalid or expired token
- **429 means:** Rate limited but token is valid

## Credential Group

Does this require multiple credentials configured together?

- [x] No, single credential
- [ ] Yes — list the other credential IDs in the group:

## Additional Context

- **API Documentation:** https://discord.com/developers/docs/intro
- **Rate Limits:** 50 messages per channel per second, global rate limit of 50 requests per second
- **Free Tier:** Discord Bot API is free with generous rate limits
- **Library:** Uses discord.py (official Python wrapper)
- **Required Permissions:** View Channels, Send Messages, Read Message History, Add Reactions
- **Privileged Intents:** Message Content Intent required for reading message text

---

## Metadata
**Closes**: #2805  
**Status**: Proposal - Complete Implementation Ready  
**Complexity**: Medium  
**Estimated Implementation Time**: 3-5 days
**Differentiator**: This is a complete MCP tool implementation, not a general feature request like #1030

---

## Problem Statement

Discord has become one of the most popular communication platforms for development teams and communities. While Hive currently has strong integrations for GitHub (12 tools), HubSpot (12 tools), and email (2 tools) among its 44 total MCP tools, it **lacks real-time team communication capabilities**.

Currently, Hive agents cannot directly interact with Discord servers, forcing users to manually:
- Post notifications and alerts to Discord channels
- Monitor messages and events  
- Coordinate team communications
- Trigger workflows based on Discord events

**Strategic Importance**: Hive's own community uses Discord for support (discord.com/invite/MXE49hrKDk). This integration would enable powerful dogfooding opportunities and demonstrate Hive's capabilities to its core developer audience.

---

## Proposed Solution

Add **4 new MCP tools** for Discord integration, bringing Hive's total from 44 to **48 tools**.

**Developer Experience**: After implementation, developers will only need to create a Discord bot, set credentials, and immediately build powerful Discord agents using Claude Code skills - including community management bots, DevOps notification systems, support automation, and cross-platform integrations - no additional setup or integration work required.

### Core Tools (MVP)

1. **`discord_send_message`**
   - Send text messages to specific channels
   - Support for embeds (rich message formatting)
   - Support for file attachments
   - Message threading support

2. **`discord_read_messages`**
   - Fetch recent messages from a channel
   - Filter by time range, author, or content
   - Retrieve message metadata (author, timestamp, reactions)

3. **`discord_list_channels`**
   - List all accessible channels in a guild (server)
   - Filter by channel type (text, voice, announcement, etc.)
   - Get channel metadata and permissions

4. **`discord_add_reaction`**
   - Add emoji reactions to messages
   - Support for both Unicode and custom emojis

---

## Use Cases & Agent Examples

### 1. Community Management Agent
```json
{
  "node_id": "moderate_community",
  "node_type": "llm_generate",
  "tools": ["discord_read_messages", "discord_add_reaction", "discord_send_message"],
  "system_prompt": "Monitor for spam and policy violations. React and warn as needed.",
  "parameters": {
    "channels": ["general", "help", "off-topic"],
    "check_interval": 300
  }
}
```

### 2. DevOps Notification Agent
- **Scenario**: CI/CD agent monitors build pipelines and posts deployment status
- **Tools Used**: `discord_send_message` with embeds
- **Example**: "🚀 Build #245 deployed to production successfully ✅"

### 3. Support Bot Agent
- **Scenario**: Monitor #support channel and provide automated responses
- **Tools Used**: `discord_read_messages`, `discord_send_message`, `web_search`
- **Workflow**: Scan for questions → Search docs → Respond with help

### 4. Cross-Platform Integration
- **GitHub + Discord**: Post issue notifications to Discord channels
- **HubSpot + Discord**: Alert team when new deals are created
- **Analytics + Discord**: Send weekly reports to #data-insights

---

## Technical Implementation

### Architecture
Following existing MCP tool patterns (GitHub, HubSpot, Email):

```python
# tools/src/aden_tools/tools/discord_tool/discord_tool.py
from mcp.types import Tool
from framework.credentials import CredentialStoreAdapter
import discord

@mcp_tool()
async def discord_send_message(
    channel_id: str,
    content: str,
    embed: Optional[Dict[str, Any]] = None,
    credentials: CredentialStoreAdapter = None
) -> Dict[str, Any]:
    """Send a message to a Discord channel."""
    # Implementation using discord.py
```

### Credential Management
```python
# tools/src/aden_tools/credentials/discord.py
DISCORD_CREDENTIALS = CredentialSpec(
    name="discord",
    description="Discord Bot authentication",
    fields={
        "DISCORD_BOT_TOKEN": {
            "type": "string",
            "required": True,
            "description": "Discord Bot Token from Discord Developer Portal",
            "sensitive": True
        }
    }
)
```

### Dependencies
- `discord.py>=2.4.0` - Official Discord API wrapper
- `aiohttp>=3.9.0` - Async HTTP client (discord.py dependency)

---

## Files to Create

### Core Implementation
```
tools/src/aden_tools/tools/discord_tool/
├── __init__.py                 # Package initialization
├── discord_tool.py             # Main tool implementation with MCP decorators
├── README.md                   # Usage documentation and setup guide
└── types.py                    # Type definitions (optional)
```

### Credentials
```
tools/src/aden_tools/credentials/discord.py
```

### Tests
```
tools/tests/tools/test_discord_tool.py  # 20+ comprehensive unit tests
```

---

## Files to Modify

1. **`tools/src/aden_tools/tools/__init__.py`** - Register Discord tools
2. **`tools/src/aden_tools/credentials/__init__.py`** - Add Discord credentials
3. **`tools/pyproject.toml`** - Add discord.py dependency
4. **`.claude/skills/building-agents-construction/SKILL.md`** - Update tool count (44→48)

---

## Environment Setup

### Required Environment Variables
```bash
DISCORD_BOT_TOKEN=your_bot_token_here
```

### Bot Setup Process (Per Developer)
**Each developer creates their own Discord bot:**

1. Go to Discord Developer Portal: https://discord.com/developers/applications
2. Create New Application → Create Bot
3. Copy bot token (save securely!)
4. Enable required intents: Message Content Intent
5. Generate invite URL with permissions: Send Messages, Read Message History, Add Reactions
6. Invite bot to **your own** Discord server

**Result**: Your bot only works in servers you invite it to - complete control and isolation.

### Required Bot Permissions
- ✅ View Channels
- ✅ Send Messages  
- ✅ Read Message History
- ✅ Add Reactions
- ✅ Use External Emojis

---

## Testing Strategy

### Unit Tests (20+ tests)
- Message sending validation (content length, channel ID format)
- Credential resolution (token retrieval, env var fallback)
- Rate limiting handling
- Permission error handling
- Message fetching with filters
- Embed formatting validation
- Reaction addition (unicode and custom emojis)
- Error handling for invalid tokens/channels

### Integration Tests
- Real Discord API testing with test server
- Rate limiting behavior verification
- End-to-end agent testing

### Manual Testing
```bash
# Test tools directly
cd tools
python -c "
import asyncio
from aden_tools.tools.discord_tool import discord_send_message
from aden_tools.credentials import CredentialStoreAdapter

async def test():
    credentials = CredentialStoreAdapter()
    result = await discord_send_message(
        channel_id='YOUR_TEST_CHANNEL_ID',
        content='Test message from Hive! 🚀',
        credentials=credentials
    )
    print(f'Success: {result}')

asyncio.run(test())
"
```

---

## How Developers Use Discord Integration

### **Individual Bot Setup** (Each Developer Creates Their Own)
**Important**: Each developer creates their own Discord bot - no shared infrastructure.

```bash
# Step 1: Developer creates Discord bot (one-time setup)
# - Go to Discord Developer Portal
# - Create application → Create bot → Copy token
# - Invite bot to their Discord server

# Step 2: Configure credentials
export DISCORD_BOT_TOKEN="your_unique_bot_token"

# Step 3: Build Discord agents
claude> /building-agents-construction
# Goal: "Monitor my Discord server for support requests"

# Step 4: Run agents in your server
PYTHONPATH=core:exports python -m support_bot run --input '{
  "guild_id": "your_server_id",
  "monitor_channels": ["support", "general"]
}'
```

### **Available Terminal Commands**
```bash
# Build Discord agents
claude> /building-agents-construction

# Run Discord agents
PYTHONPATH=core:exports python -m agent_name run --input '{...}'

# Test agents
PYTHONPATH=core:exports python -m agent_name test

# List all tools (including Discord)
cd tools && python mcp_server.py --help

# Test Discord tools directly
python -c "from aden_tools.tools.discord_tool import discord_send_message; ..."
```

### **Privacy & Security**
- ✅ Each user controls their own bot and servers
- ✅ No shared credentials or cross-contamination
- ✅ Complete isolation between organizations
- ✅ Follows same pattern as GitHub/HubSpot integrations

---

## Implementation Timeline

### Phase 1: Core Implementation (3-5 days)

**Day 1**: Project setup & credential management
- Create tool directory structure
- Implement CredentialSpec for Discord
- Set up development environment

**Day 2**: Core tools implementation
- Implement `discord_send_message` and `discord_read_messages`
- Add discord.py dependency
- Basic error handling

**Day 3**: Complete tool set
- Implement `discord_list_channels` and `discord_add_reaction`
- Add comprehensive error handling and rate limiting
- Multi-provider pattern setup

**Day 4**: Testing & documentation
- Write 20+ unit tests
- Create comprehensive README
- Integration testing

**Day 5**: Integration & PR
- Register tools in MCP server
- Update skill documentation
- Build test agent using Claude Code
- Submit PR

---

## Success Metrics

- [ ] All 4 MVP tools implemented and tested
- [ ] Tests achieve >90% code coverage
- [ ] Documentation is comprehensive and clear
- [ ] Integration works with example agents
- [ ] MCP server registers all tools correctly
- [ ] No critical bugs in first week after merge

---

## Security Considerations

1. **Token Security**: Use encrypted credential storage, never hardcode tokens
2. **Rate Limiting**: Respect Discord's limits (50 messages/channel/second)
3. **Permission Validation**: Check bot permissions before operations
4. **Data Privacy**: Handle user data according to Discord's ToS

---

## Future Enhancements (Phase 2+)

- Voice channel integration
- Webhook support for event-driven workflows
- Slash commands for bot interactions
- Message editing and deletion
- Thread management
- Role management tools

---

## Contributor

**@RodrigoMvs123** - Ready to implement this integration following Hive's patterns and standards.

---

**This integration addresses issue #2805 and will add Discord as Hive's first real-time chat platform, complementing existing GitHub, HubSpot, and email integrations.**ead management
- Role management tools

---

## References

- **Discord Bot Documentation**: https://discord.com/developers/docs/intro
- **discord.py Library**: https://discordpy.readthedocs.io/
- **Hive Email Tool Reference**: Existing email integration pattern
- **MCP Discord Examples**: Community implementations for reference

---

## Contributor

**@RodrigoMvs123** - Ready to implement this integration following Hive's patterns and standards.

---

**This integration addresses issue #2805 and will add Discord as Hive's first real-time chat platform, complementing existing GitHub, HubSpot, and email integrations.**