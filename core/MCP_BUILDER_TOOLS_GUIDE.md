# Agent Builder MCP Tools - MCP Integration Guide

This guide explains how to use the new MCP integration tools in the agent builder MCP server.

## Overview

The agent builder now supports registering external MCP servers as tool sources. This allows you to:

1. Register MCP servers (like tools) during agent building
2. Discover available tools from those servers
3. Use those tools in your agent nodes
4. Automatically generate `mcp_servers.json` configuration on export

## New MCP Tools

### `add_mcp_server`

Register an MCP server as a tool source for your agent.

**Parameters:**

- `name` (string, required): Unique name for the MCP server
- `transport` (string, required): Transport type - "stdio" or "http"
- `command` (string): Command to run (for stdio transport)
- `args` (string): JSON array of command arguments (for stdio)
- `cwd` (string): Working directory (for stdio)
- `env` (string): JSON object of environment variables (for stdio)
- `url` (string): Server URL (for http transport)
- `headers` (string): JSON object of HTTP headers (for http)
- `description` (string): Description of the MCP server

**Example - STDIO:**

```json
{
  "name": "add_mcp_server",
  "arguments": {
    "name": "tools",
    "transport": "stdio",
    "command": "python",
    "args": "[\"mcp_server.py\", \"--stdio\"]",
    "cwd": "../tools",
    "description": "Aden tools for web search and file operations"
  }
}
```

**Example - HTTP:**

```json
{
  "name": "add_mcp_server",
  "arguments": {
    "name": "remote-tools",
    "transport": "http",
    "url": "http://localhost:4001",
    "description": "Remote tool server"
  }
}
```

**Response:**

```json
{
  "success": true,
  "server": {
    "name": "tools",
    "transport": "stdio",
    "command": "python",
    "args": ["mcp_server.py", "--stdio"],
    "cwd": "../tools",
    "description": "Aden tools..."
  },
  "tools_discovered": 6,
  "tools": [
    "web_search",
    "web_scrape",
    "file_read",
    "file_write",
    "pdf_read",
    "example_tool"
  ],
  "total_mcp_servers": 1,
  "note": "MCP server 'tools' registered with 6 tools. These tools can now be used in llm_tool_use nodes."
}
```

### `list_mcp_servers`

List all registered MCP servers.

**Parameters:** None

**Response:**

```json
{
  "mcp_servers": [
    {
      "name": "tools",
      "transport": "stdio",
      "command": "python",
      "args": ["mcp_server.py", "--stdio"],
      "cwd": "../tools",
      "description": "Aden tools..."
    }
  ],
  "total": 1
}
```

### `list_mcp_tools`

List tools available from registered MCP servers.

**Parameters:**

- `server_name` (string, optional): Name of specific server to list tools from. If omitted, lists tools from all servers.

**Example:**

```json
{
  "name": "list_mcp_tools",
  "arguments": {
    "server_name": "tools"
  }
}
```

**Response:**

```json
{
  "success": true,
  "tools_by_server": {
    "tools": [
      {
        "name": "web_search",
        "description": "Search the web for information using Brave Search API...",
        "parameters": ["query", "num_results", "country"]
      },
      {
        "name": "web_scrape",
        "description": "Scrape and extract text content from a webpage...",
        "parameters": ["url", "selector", "include_links", "max_length"]
      }
    ]
  },
  "total_tools": 6,
  "note": "Use these tool names in the 'tools' parameter when adding llm_tool_use nodes"
}
```

### `remove_mcp_server`

Remove a registered MCP server.

**Parameters:**

- `name` (string, required): Name of the MCP server to remove

**Example:**

```json
{
  "name": "remove_mcp_server",
  "arguments": {
    "name": "tools"
  }
}
```

**Response:**

```json
{
  "success": true,
  "removed": "tools",
  "remaining_servers": 0
}
```

## Workflow Example

Here's a complete workflow for building an agent with MCP tools:

### 1. Create Session

```json
{
  "name": "create_session",
  "arguments": {
    "name": "web-research-agent"
  }
}
```

### 2. Register MCP Server

```json
{
  "name": "add_mcp_server",
  "arguments": {
    "name": "tools",
    "transport": "stdio",
    "command": "python",
    "args": "[\"mcp_server.py\", \"--stdio\"]",
    "cwd": "../tools"
  }
}
```

### 3. List Available Tools

```json
{
  "name": "list_mcp_tools",
  "arguments": {
    "server_name": "tools"
  }
}
```

### 4. Set Goal

```json
{
  "name": "set_goal",
  "arguments": {
    "goal_id": "web-research",
    "name": "Web Research Agent",
    "description": "Search the web and summarize findings",
    "success_criteria": "[{\"id\": \"search-success\", \"description\": \"Successfully retrieve search results\", \"metric\": \"results_count\", \"target\": \">= 3\", \"weight\": 1.0}]"
  }
}
```

### 5. Add Node with MCP Tool

```json
{
  "name": "add_node",
  "arguments": {
    "node_id": "web-searcher",
    "name": "Web Search",
    "description": "Search the web for information",
    "node_type": "llm_tool_use",
    "input_keys": "[\"query\"]",
    "output_keys": "[\"search_results\"]",
    "system_prompt": "Search for {query} using the web_search tool",
    "tools": "[\"web_search\"]"
  }
}
```

Note: `web_search` is now available because we registered the tools MCP server!

### 6. Export Agent

```json
{
  "name": "export_graph",
  "arguments": {}
}
```

The export will create:

- `exports/web-research-agent/agent.json` - Agent specification
- `exports/web-research-agent/README.md` - Documentation
- `exports/web-research-agent/mcp_servers.json` - **MCP server configuration** ✨

## MCP Configuration File

When you export an agent with registered MCP servers, an `mcp_servers.json` file is automatically created:

```json
{
  "servers": [
    {
      "name": "tools",
      "transport": "stdio",
      "command": "python",
      "args": ["mcp_server.py", "--stdio"],
      "cwd": "../tools",
      "description": "Aden tools for web search and file operations"
    }
  ]
}
```

This file is automatically loaded by the AgentRunner when the agent is executed, making the MCP tools available at runtime.

## Using the Exported Agent

Once exported, load and run the agent normally:

```python
from framework.runner.runner import AgentRunner

# Load agent - MCP servers auto-load from mcp_servers.json
runner = AgentRunner.load("exports/web-research-agent")

# Run with input
result = await runner.run({"query": "latest AI breakthroughs"})

# The web_search tool from tools is automatically available!
```

## Benefits

1. **Discoverable Tools**: See what tools are available before using them
2. **Validation**: Connection is tested when registering the server
3. **Automatic Configuration**: No manual file editing required
4. **Documentation**: README includes MCP server information
5. **Runtime Ready**: Exported agents work immediately with configured tools

## Common MCP Servers

### tools

Provides:

- `web_search` - Brave Search API integration
- `web_scrape` - Web page content extraction
- `file_read` / `file_write` - File operations
- `pdf_read` - PDF text extraction

### Custom MCP Servers

You can register any MCP server that follows the Model Context Protocol specification.

## Troubleshooting

### "Failed to connect to MCP server"

- Verify the `command` and `args` are correct
- Check that the server is accessible at the specified path/URL
- Ensure any required environment variables are set
- For STDIO: verify the command can be executed from the `cwd`
- For HTTP: verify the server is running and accessible

### Tools not appearing

- Use `list_mcp_tools` to verify tools were discovered
- Check the tool names match exactly (case-sensitive)
- Ensure the MCP server is still registered (`list_mcp_servers`)

### Export doesn't include mcp_servers.json

- Verify you registered at least one MCP server
- Check `get_session_status` to see `mcp_servers_count > 0`
- Re-export the agent after registering servers

## Credential Validation

When adding nodes with tools that require API keys (like `web_search`), the agent builder automatically validates that the required credentials are available.

### How It Works

When you call `add_node` or `update_node` with a `tools` parameter, the agent builder:

1. Checks which tools require credentials (e.g., `web_search` requires `BRAVE_SEARCH_API_KEY`)
2. Validates those credentials are set in the environment or `.env` file
3. Returns an error if any credentials are missing

### Missing Credentials Error

If credentials are missing, you'll receive a response like:

```json
{
  "valid": false,
  "errors": ["Missing credentials for tools: ['BRAVE_SEARCH_API_KEY']"],
  "missing_credentials": [
    {
      "credential": "brave_search",
      "env_var": "BRAVE_SEARCH_API_KEY",
      "tools_affected": ["web_search"],
      "help_url": "https://brave.com/search/api/",
      "description": "API key for Brave Search"
    }
  ],
  "action_required": "Add the credentials to your .env file and retry",
  "example": "Add to .env:\nBRAVE_SEARCH_API_KEY=your_key_here",
  "message": "Cannot add node: missing API credentials. Add them to .env and retry this command."
}
```

### Fixing Credential Errors

1. Get the required API key from the URL in `help_url`
2. Add it to your environment:

   ```bash
   # Option 1: Export directly
   export BRAVE_SEARCH_API_KEY=your-key-here

   # Option 2: Add to tools/.env
   echo "BRAVE_SEARCH_API_KEY=your-key-here" >> tools/.env
   ```

3. Retry the `add_node` command

### Required Credentials by Tool

| Tool         | Credential             | Get Key                                               |
| ------------ | ---------------------- | ----------------------------------------------------- |
| `web_search` | `BRAVE_SEARCH_API_KEY` | [brave.com/search/api](https://brave.com/search/api/) |

Note: The MCP server itself requires `ANTHROPIC_API_KEY` at startup for LLM operations.
