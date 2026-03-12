# Tools

Hive agents interact with external services through **tools** — functions exposed via MCP (Model Context Protocol) servers. The main tool server lives at `tools/mcp_server.py` and registers integrations from the `aden_tools` package.

## Verified vs Unverified

Tools are split into two tiers:

| Tier | Description | Default |
|------|-------------|---------|
| **Verified** | Stable integrations tested on main. Always loaded. | On |
| **Unverified** | New or community integrations pending full review. | Off |

Verified tools include core capabilities like web search, GitHub, email, file system operations, and security scanners. Unverified tools cover newer integrations like Jira, Notion, Salesforce, Snowflake, and others that are functional but haven't completed the full review process.

## Enabling Unverified Tools

Set the `INCLUDE_UNVERIFIED_TOOLS` environment variable to opt in:

```bash
# Shell
INCLUDE_UNVERIFIED_TOOLS=true uv run python tools/mcp_server.py --stdio
```

### In `mcp_servers.json`

When configuring an agent's MCP server, pass the env var in the server config:

```json
{
  "servers": [
    {
      "name": "tools",
      "transport": "stdio",
      "command": "uv",
      "args": ["run", "python", "tools/mcp_server.py", "--stdio"],
      "env": {
        "INCLUDE_UNVERIFIED_TOOLS": "true"
      }
    }
  ]
}
```

### In Docker

```bash
docker run -e INCLUDE_UNVERIFIED_TOOLS=true ...
```

### In Python

If calling `register_all_tools` directly (e.g., in a custom server):

```python
from aden_tools.tools import register_all_tools

register_all_tools(mcp, credentials=credentials, include_unverified=True)
```

Accepted values: `true`, `1`, `yes` (case-insensitive). Any other value or unset means off.

## Listing Available Tools

The MCP server logs registered tools at startup (HTTP mode):

```bash
uv run python tools/mcp_server.py
# [MCP] Registered 47 tools: [...]
```

In STDIO mode, logs go to stderr to keep stdout clean for JSON-RPC.

## Adding a New Tool

New tool integrations are added to `tools/src/aden_tools/tools/` and registered in `_register_unverified()` in `tools/src/aden_tools/tools/__init__.py`. Once reviewed and stabilized, they graduate to `_register_verified()`.

See the [developer guide](developer-guide.md) for the full contribution workflow.
