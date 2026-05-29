# Slack MCP Server Setup

## ✅ What We've Accomplished

1. **Created a proper MCP server** (`tools/slack_mcp_server.py`) using FastMCP
2. **Configured the agent** to use the MCP server via `mcp_servers.json`
3. **Set up environment variables** in `.env` file with Slack credentials
4. **Fixed agent architecture** - separated nodes.py from agent.py properly

## 📁 Files Created/Modified

### New Files:
- `tools/slack_mcp_server.py` - FastMCP-based Slack integration server

### Modified Files:
- `mcp_servers.json` - Updated to use the new MCP server
- `nodes.py` - Fixed imports and node types
- `agent.py` - Fixed graph structure and imports
- `.env` - Added Slack and Gemini API credentials

## 🔧 MCP Server Features

The Slack MCP server provides two tools:

### 1. `slack_post_message`
Posts a message to a Slack channel with optional Block Kit formatting.

**Parameters:**
- `channel` (required): Channel ID or name (#general)
- `text` (required): Plain text message
- `blocks` (optional): Slack Block Kit blocks array
- `username` (optional): Bot display name override
- `icon_emoji` (optional): Bot icon emoji (e.g., ':bee:')

### 2. `slack_list_channels`
Lists public Slack channels the bot has access to.

**Parameters:**
- `limit` (optional): Max channels to return (default: 100)
- `cursor` (optional): Pagination cursor

## 🚀 How to Run the Agent with Slack

```powershell
.\hive.ps1 run examples/templates/meeting_notes_agent --input '{
  "transcript": "Meeting: Q1 Planning. Sarah: We need to launch by March 31st. Marcus: I will have the API done by Friday. Tom: Approved.",
  "meeting_name": "Q1 Planning",
  "meeting_date": "2026-02-23",
  "slack_channel": "CHANNEL_ID_HERE"
}'
```

**Note:** Use the Slack channel ID (e.g., `C012AB3CD`) instead of the channel name for reliable delivery. You can find channel IDs in Slack by right-clicking a channel → View channel details → Copy channel ID.

## 📋 Prerequisites

1. **Slack Bot Token** - Set in `.env`:
   ```
   SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
   ```
   
   Get your token from: https://api.slack.com/apps → Your App → OAuth & Permissions

2. **Slack App Scopes** - Your Slack app needs:
   - `chat:write` - Post messages
   - `chat:write.public` - Post to channels without joining

3. **LLM API Key** - Set in `.env`:
   ```
   GEMINI_API_KEY=your-key-here
   ```
   (Or use ANTHROPIC_API_KEY for Claude)

## 🔍 Testing the MCP Server

The MCP server is running correctly when you see:
```
INFO:slack-mcp-server:Starting Slack MCP Server...
INFO:slack-mcp-server:Slack token found: xoxb-xxxxx...
```

The server waits for MCP protocol messages from the Hive framework.

## 📊 Agent Flow with Slack

1. **validate_input** - Validates transcript and parameters
2. **extract_meeting_data** - Uses LLM to extract structured data
3. **parse_and_validate** - Validates against Pydantic schema
4. **format_slack_message** - Creates Slack Block Kit payload
5. **post_to_slack** - Calls MCP tool to post message
6. **compile_final_output** - Returns final result

## ⚠️ Known Limitations

1. **Gemini API Rate Limit** - Free tier: 5 requests/minute
   - Solution: Wait 1 minute between runs or use paid API key

2. **MCP Server Registration** - May show "Failed to register MCP server: 'transport'" warning
   - This is non-fatal; the server still works when called

## 🎯 Next Steps

1. **Test with a real Slack channel** - Once Gemini rate limit resets
2. **Add more Slack features** - Thread replies, reactions, file uploads
3. **Optimize LLM calls** - Reduce number of calls to avoid rate limits
4. **Add error recovery** - Better handling of Slack API errors

## 📚 Resources

- [Slack API Documentation](https://api.slack.com/)
- [Slack Block Kit Builder](https://app.slack.com/block-kit-builder)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Hive Framework Docs](https://docs.adenhq.com/)
