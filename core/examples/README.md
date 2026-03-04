# Core Examples

Runnable examples demonstrating the Hive agent framework. Run all commands from the **repository root**.

## Examples

### 1. `manual_agent.py` — Minimal runtime without LLM

Builds and runs an agent using pure Python node logic (no LLM, no API keys).

**What it demonstrates:**

- Defining nodes with `NodeProtocol`
- Building a graph (Goal, NodeSpec, EdgeSpec)
- Executing the graph with `GraphExecutor`
- The core runtime loop: Setup → Graph definition → Execution → Result

**Run:**

```bash
uv run python core/examples/manual_agent.py
```

**Environment variables:** None required.

**Expected output:**

```
Setting up Manual Agent...
Executing agent with input: name='Alice'...

Success!
Path taken: greeter -> uppercaser
Final output: HELLO, ALICE!
```

---

### 2. `mcp_integration_example.py` — MCP server integration

Shows how to register MCP (Model Context Protocol) servers and use their tools in agents.

**What it demonstrates:**

1. **Programmatic registration** — Register the tools MCP server via STDIO and run an agent that uses `web_search`
2. **HTTP transport** — Connect to an MCP server over HTTP (for Docker deployments)
3. **Config file** — Load MCP servers from `mcp_servers.json`
4. **Custom agent** — Build a custom agent workflow that uses MCP tools

**Run:**

```bash
uv run python core/examples/mcp_integration_example.py
```

**Environment variables:**

| Variable              | Required | Purpose                                      |
|-----------------------|----------|----------------------------------------------|
| `ANTHROPIC_API_KEY`   | Yes      | LLM calls for agent execution                |
| `BRAVE_SEARCH_API_KEY`| Yes*     | Web search tool (Example 1 uses `web_search`)|

\* Get a free key at [Brave Search API](https://brave.com/search/api/).

**Expected output (Example 1):**

```
============================================================
MCP Integration Examples
============================================================

=== Example 1: Programmatic MCP Server Registration ===

Registered N tools from tools MCP server

Available tools: ['web_search', 'web_scrape', ...]

Agent result: {...}
```

**Note:** Example 1 loads `exports/task-planner` (create an agent first via Claude Code `/hive` or use Example 4 to build one). By default only Example 1 runs. Uncomment other examples in `main()` to try HTTP transport, config-file loading, or custom agent building.

---

### 3. `mcp_servers.json` — MCP server configuration template

Reference configuration for MCP servers. Copy into your agent folder (e.g. `exports/my_agent/mcp_servers.json`) to auto-load tools at agent startup.

**Formats supported:**

- **List format:** `{"servers": [{"name": "...", "transport": "stdio", ...}]}`
- **Dict format:** `{"server-name": {"transport": "stdio", ...}}`

**Example (STDIO):**

```json
{
  "servers": [
    {
      "name": "tools",
      "transport": "stdio",
      "command": "uv",
      "args": ["run", "python", "mcp_server.py", "--stdio"],
      "cwd": "../tools",
      "env": {
        "BRAVE_SEARCH_API_KEY": "${BRAVE_SEARCH_API_KEY}"
      }
    }
  ]
}
```

The `cwd` path is resolved relative to the config file’s directory. Use `../tools` when the config lives in `exports/my_agent/` (one level below repo root).

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for running scripts
- Dependencies installed: `uv sync` (from `core/` or workspace root)

For MCP examples, ensure the `tools` package is available (workspace dependency).
