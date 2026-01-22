# MCP Integration Guide

This guide explains how to integrate Model Context Protocol (MCP) servers with the Hive Core Framework, enabling agents to use tools from external MCP servers.

## Overview

The framework provides built-in support for MCP servers, allowing you to:

- **Register MCP servers** via STDIO or HTTP transport
- **Auto-discover tools** from registered servers
- **Use MCP tools** seamlessly in your agents
- **Manage multiple MCP servers** simultaneously

## Quick Start

### 1. Register an MCP Server Programmatically

```python
from framework.runner.runner import AgentRunner

# Load your agent
runner = AgentRunner.load("exports/my-agent")

# Register tools MCP server
runner.register_mcp_server(
    name="tools",
    transport="stdio",
    command="python",
    args=["-m", "aden_tools.mcp_server", "--stdio"],
    cwd="/path/to/tools"
)

# Tools are now available to your agent
result = await runner.run({"input": "data"})
```

### 2. Use Configuration File

Create `mcp_servers.json` in your agent folder:

```json
{
  "servers": [
    {
      "name": "tools",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "aden_tools.mcp_server", "--stdio"],
      "cwd": "../tools"
    }
  ]
}
```

The framework will automatically load and register these servers when you load the agent:

```python
runner = AgentRunner.load("exports/my-agent")  # MCP servers auto-loaded
```

## Transport Types

### STDIO Transport

Best for local MCP servers running as subprocesses:

```python
runner.register_mcp_server(
    name="local-tools",
    transport="stdio",
    command="python",
    args=["-m", "my_tools.server", "--stdio"],
    cwd="/path/to/my-tools",
    env={
        "API_KEY": "your-key-here"
    }
)
```

**Configuration:**

- `command`: Executable to run (e.g., "python", "node")
- `args`: List of command-line arguments
- `cwd`: Working directory for the process
- `env`: Environment variables (optional)

### HTTP Transport

Best for remote MCP servers or containerized deployments:

```python
runner.register_mcp_server(
    name="remote-tools",
    transport="http",
    url="http://localhost:4001",
    headers={
        "Authorization": "Bearer token"
    }
)
```

**Configuration:**

- `url`: Base URL of the MCP server
- `headers`: HTTP headers to include (optional)

## Using MCP Tools in Agents

Once registered, MCP tools are available just like any other tool:

### In Node Specifications

```python
from framework.builder.workflow import WorkflowBuilder

builder = WorkflowBuilder()

# Add a node that uses MCP tools
builder.add_node(
    node_id="researcher",
    name="Web Researcher",
    node_type="llm_tool_use",
    system_prompt="Research the topic using web_search",
    tools=["web_search"],  # Tool from tools MCP server
    input_keys=["topic"],
    output_keys=["findings"]
)
```

### In Agent.json

Tools from MCP servers can be referenced in your agent.json just like built-in tools:

```json
{
  "nodes": [
    {
      "id": "searcher",
      "name": "Web Searcher",
      "node_type": "llm_tool_use",
      "system_prompt": "Search for information about {topic}",
      "tools": ["web_search", "web_scrape"],
      "input_keys": ["topic"],
      "output_keys": ["results"]
    }
  ]
}
```

## Available Tools from tools

When you register the `tools` MCP server, the following tools become available:

- **web_search**: Search the web using Brave Search API
- **web_scrape**: Scrape content from a URL
- **file_read**: Read file contents
- **file_write**: Write content to a file
- **pdf_read**: Extract text from PDF files

## Environment Variables

Some MCP tools require environment variables. You can pass them in the configuration:

### Via Programmatic Registration

```python
runner.register_mcp_server(
    name="tools",
    transport="stdio",
    command="python",
    args=["-m", "aden_tools.mcp_server", "--stdio"],
    cwd="../tools",
    env={
        "BRAVE_SEARCH_API_KEY": os.environ["BRAVE_SEARCH_API_KEY"]
    }
)
```

### Via Configuration File

```json
{
  "servers": [
    {
      "name": "tools",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "aden_tools.mcp_server", "--stdio"],
      "cwd": "../tools",
      "env": {
        "BRAVE_SEARCH_API_KEY": "${BRAVE_SEARCH_API_KEY}"
      }
    }
  ]
}
```

The framework will substitute `${VAR_NAME}` with values from the environment.

## Multiple MCP Servers

You can register multiple MCP servers to access different sets of tools:

```json
{
  "servers": [
    {
      "name": "tools",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "aden_tools.mcp_server", "--stdio"],
      "cwd": "../tools"
    },
    {
      "name": "database-tools",
      "transport": "http",
      "url": "http://localhost:5001"
    },
    {
      "name": "analytics-tools",
      "transport": "http",
      "url": "http://analytics-server:6001"
    }
  ]
}
```

All tools from all servers will be available to your agent.

## Best Practices

### 1. Use STDIO for Development

STDIO transport is easier to debug and doesn't require managing server processes:

```python
runner.register_mcp_server(
    name="dev-tools",
    transport="stdio",
    command="python",
    args=["-m", "my_tools.server", "--stdio"]
)
```

### 2. Use HTTP for Production

HTTP transport is better for:

- Containerized deployments
- Shared tools across multiple agents
- Remote tool execution

```python
runner.register_mcp_server(
    name="prod-tools",
    transport="http",
    url="http://tools-service:8000"
)
```

### 3. Handle Cleanup

Always clean up MCP connections when done:

```python
try:
    runner = AgentRunner.load("exports/my-agent")
    runner.register_mcp_server(...)
    result = await runner.run(input_data)
finally:
    runner.cleanup()  # Disconnects all MCP servers
```

Or use context manager:

```python
async with AgentRunner.load("exports/my-agent") as runner:
    runner.register_mcp_server(...)
    result = await runner.run(input_data)
    # Automatic cleanup
```

### 4. Tool Name Conflicts

If multiple MCP servers provide tools with the same name, the last registered server wins. To avoid conflicts:

- Use unique tool names in your MCP servers
- Register servers in priority order (most important last)
- Use separate agents for different tool sets

## Troubleshooting

### Connection Errors

If you get connection errors with STDIO transport:

1. Check that the command and path are correct
2. Verify the MCP server starts successfully standalone
3. Check environment variables are set correctly
4. Look at stderr output for error messages

### Tool Not Found

If a tool is registered but not found:

1. Verify the server registered successfully (check logs)
2. List available tools: `runner._tool_registry.get_registered_names()`
3. Check tool name spelling in your node configuration

### HTTP Server Not Responding

If HTTP transport fails:

1. Verify the server is running: `curl http://localhost:4001/health`
2. Check firewall settings
3. Verify the URL and port are correct

## Example: Full Agent with MCP Tools

Here's a complete example of an agent that uses MCP tools:

```python
import asyncio
from pathlib import Path
from framework.runner.runner import AgentRunner

async def main():
    # Create agent path
    agent_path = Path("exports/web-research-agent")

    # Load agent
    runner = AgentRunner.load(agent_path)

    # Register MCP server
    runner.register_mcp_server(
        name="tools",
        transport="stdio",
        command="python",
        args=["-m", "aden_tools.mcp_server", "--stdio"],
        cwd="../tools",
        env={
            "BRAVE_SEARCH_API_KEY": "your-api-key"
        }
    )

    # Run agent
    result = await runner.run({
        "query": "latest developments in quantum computing"
    })

    print(f"Research complete: {result}")

    # Cleanup
    runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
```

## See Also

- [MCP_SERVER_GUIDE.md](MCP_SERVER_GUIDE.md) - Building your own MCP servers
- [examples/mcp_integration_example.py](examples/mcp_integration_example.py) - More examples
- [examples/mcp_servers.json](examples/mcp_servers.json) - Example configuration
