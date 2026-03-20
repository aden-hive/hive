# Core Examples

Runnable examples and the interactive TUI for exploring the Hive agent framework. Run all commands from the **repository root**.

## Navigating Agents in the TUI (Recommended)

The best way to explore agents is through the interactive **TUI dashboard**. It lets you browse, select, and run agents without manual commands.

### 1. Launch the TUI

```bash
./hive tui
```

Or, if `hive` is on your PATH:

```bash
hive tui
```

### 2. Choose how to get started

When the TUI opens, you’ll see the **Hive Agent Launcher** with a **Get Started** tab. You can:

- **Test and run example agents** — Opens the Examples tab so you can try pre-built agents from `examples/templates/`
- **Test and run existing agent** — Opens the Your Agents tab for agents in `exports/`
- **Build or edit agent** — Shows guidance for creating agents via `hive build` or Claude Code `/hive`

Select **Test and run example agents** to explore the framework with ready-made agents.

### 3. Browse and select an agent

The agent picker has tabs:

| Tab | Source | Description |
|-----|--------|-------------|
| **Your Agents** | `exports/` | Agents you’ve created |
| **Framework** | Built-in | Framework agents (e.g. Hive Coder) |
| **Examples** | `examples/templates/` | Pre-built template agents |

Use **Tab** to switch tabs. Use **Enter** to select an agent. Each entry shows name, description, node count, and tool count.

### 4. Run and interact with an agent

After selecting an agent:

- The agent loads and the chat panel becomes active
- Type a message and press **Enter** to send input
- Use **Ctrl+Z** to pause execution
- Use **Ctrl+A** (or type `/agents`) to open the agent picker and switch agents
- Type **`/help`** in the chat for all available commands

### 5. Useful TUI shortcuts

| Shortcut | Action |
|----------|--------|
| **Ctrl+A** | Open agent picker |
| **Ctrl+Z** | Pause execution |
| **Ctrl+L** | Toggle logs |
| **Ctrl+R** | Sessions |
| **Ctrl+E** | Escalate to Hive Coder |
| **Tab** | Focus next panel |

---

## Optional: Command-Line Examples

For developers who want to understand the runtime without the TUI, these scripts run directly from the terminal.

### `manual_agent.py` — Minimal runtime without LLM

Builds and runs an agent using pure Python node logic (no LLM, no API keys).

**What it demonstrates:** Defining nodes with `NodeProtocol`, building a graph (Goal, NodeSpec, EdgeSpec), executing with `GraphExecutor`, and the core runtime loop.

```bash
uv run python core/examples/manual_agent.py
```

**Environment variables:** None required.

---

### `mcp_integration_example.py` — MCP server integration

Shows how to register MCP (Model Context Protocol) servers and use their tools in agents.

**What it demonstrates:** Programmatic registration, HTTP transport, config-file loading, and custom agent workflows with MCP tools.

```bash
uv run python core/examples/mcp_integration_example.py
```

**Environment variables:**

| Variable               | Required | Purpose                       |
|------------------------|----------|-------------------------------|
| `ANTHROPIC_API_KEY`    | Yes      | LLM calls for agent execution |
| `BRAVE_SEARCH_API_KEY` | Yes*     | Web search tool               |

\* Get a free key at [Brave Search API](https://brave.com/search/api/).

**Note:** Example 1 loads `exports/task-planner` (create an agent first via Claude Code `/hive` or use Example 4 to build one). By default only Example 1 runs. Uncomment other examples in `main()` to try HTTP transport, config-file loading, or custom agent building.

---

### `mcp_servers.json` — MCP server configuration template

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

The `cwd` path is resolved relative to the config file's directory. Use `../tools` when the config lives in `exports/my_agent/` (one level below repo root).

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for running scripts
- Dependencies installed: `uv sync` (from `core/` or workspace root)

For MCP examples, ensure the `tools` package is available (workspace dependency).
