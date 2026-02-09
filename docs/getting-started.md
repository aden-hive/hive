# Getting Started

This guide helps you go from **cloned repo → first agent running**.

If you want a high‑level mental model first, read **[First 15 Minutes with Hive](articles/first-15-minutes-with-hive.md)**, then come back here for commands.

## Prerequisites

- **Python 3.11+** ([Download](https://www.python.org/downloads/)) - Python 3.12 or 3.13 recommended
- **pip** - Package installer for Python (comes with Python)
- **git** - Version control
- **Claude Code** ([Install](https://docs.anthropic.com/claude/docs/claude-code)) - Optional, for using building skills

## Quick Start

The fastest way to get started:

```bash
# 1. Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# 2. Run automated setup
./quickstart.sh

# 3. Verify installation (optional, quickstart.sh already verifies)
uv run python -c "import framework; import aden_tools; print('✓ Setup complete')"
```

## Building Your First Agent

### Option 1: Using Claude Code Skills (Recommended)

```bash
# Setup already done via quickstart.sh above

# Start Claude Code and build an agent
claude> /hive
```

Follow the interactive prompts to:

1. Define your agent's goal
2. Design the workflow (nodes and edges)
3. Generate the agent package
4. Test the agent

### Option 2: Create Agent Manually

> **Note:** The `exports/` directory is where your agents are created. It is not included in the repository (gitignored) because agents are user-generated via Claude Code skills or created manually.

```bash
# Create exports directory if it doesn't exist
mkdir -p exports/my_agent

# Create your agent structure
cd exports/my_agent
# Create agent.json, tools.py, README.md (see developer-guide.md for structure)

# Validate the agent
PYTHONPATH=exports uv run python -m my_agent validate
```

### Option 3: Manual Code-First (Minimal Example)

If you prefer to start with code rather than CLI wizards, check out the manual agent example:

```bash
# View the minimal example
cat core/examples/manual_agent.py

# Run it (no API keys required)
uv run python core/examples/manual_agent.py
```

This demonstrates the core runtime loop using pure Python functions, skipping the complexity of LLM setup and file-based configuration.

## Project Structure

```
hive/
├── core/                   # Core framework package (Python)
│   ├── framework/          # Agent runtime, graph executor
│   │   ├── builder/        # Agent builder utilities
│   │   ├── credentials/    # Credential management
│   │   ├── graph/          # GraphExecutor - executes node graphs
│   │   ├── llm/            # LLM provider integrations
│   │   ├── mcp/            # MCP server integration
│   │   ├── runner/         # AgentRunner - loads and runs agents
│   │   ├── runtime/        # Runtime environment
│   │   ├── schemas/        # Data schemas
│   │   ├── storage/        # File-based persistence
│   │   ├── testing/        # Testing utilities
│   │   └── tui/            # Terminal UI dashboard
│   └── pyproject.toml      # Package metadata
│
├── tools/                  # MCP tools project (separate Python package)
│   ├── mcp_server.py       # MCP server entry point
│   └── src/aden_tools/     # Tools for agent capabilities
│       └── tools/          # Individual MCP tool implementations
│           ├── web_search_tool/
│           ├── web_scrape_tool/
│           └── file_system_toolkits/
│
├── exports/                # Agent Packages (user-generated, not in repo)
│   └── your_agent/         # Your agents created via /hive
│
├── examples/
│   └── templates/          # Pre-built template agents
│
├── .claude/                # Claude Code Skills
│   └── skills/
│       ├── hive/
│       ├── hive-create/
│       ├── hive-concepts/
│       ├── hive-patterns/
│       └── hive-test/
│
└── docs/                   # Documentation
```

**Why does `tools/src/aden_tools/tools` look duplicated?**

- `tools/` is the **project root** for the tools package (like a typical Python package layout).
- `src/aden_tools/` is the **importable package** (`import aden_tools`).
- `src/aden_tools/tools/` holds **individual MCP tools** that agents can call (file system, web search, etc.).

## Running an Agent

```bash
# Browse and run agents interactively (Recommended)
hive tui

# Run a specific agent
hive run exports/my_agent --input '{"task": "Your input here"}'

# Run with TUI dashboard
hive run exports/my_agent --tui

```

You can also run agents purely via Python modules if you prefer:

```bash
# Equivalent to `hive run` using Python directly
PYTHONPATH=exports uv run python -m my_agent run --input '{
  "task": "Your input here"
}'
```

- **`PYTHONPATH=core:exports`** makes the `framework` package and your `exports/` agents importable.
- **`hive`** is a thin CLI wrapper around the same runtime (see `core/framework/cli.py`); the TUI (`hive tui`) sits on top of the same runner.

## API Keys Setup

For running agents with real LLMs:

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"        # Optional
export BRAVE_SEARCH_API_KEY="your-key-here"  # Optional, for web search
```

Get your API keys:

- **Anthropic**: [console.anthropic.com](https://console.anthropic.com/)
- **OpenAI**: [platform.openai.com](https://platform.openai.com/)
- **Brave Search**: [brave.com/search/api](https://brave.com/search/api/)

## Testing Your Agent

```bash
# Using Claude Code
claude> /hive-test

# Or manually
PYTHONPATH=exports uv run python -m my_agent test

# Run with specific test type
PYTHONPATH=exports uv run python -m my_agent test --type constraint
PYTHONPATH=exports uv run python -m my_agent test --type success
```

## Next Steps

1. **TUI Dashboard**: Run `hive tui` to explore agents interactively
2. **Detailed Setup**: See [environment-setup.md](./environment-setup.md)
3. **Developer Guide**: See [developer-guide.md](./developer-guide.md)
4. **Build Agents**: Use `/hive` skill in Claude Code
5. **Custom Tools**: Learn to integrate MCP servers
6. **Join Community**: [Discord](https://discord.com/invite/MXE49hrKDk)

## Key Concepts (Glossary)

- **Hive framework (`core/`)**: Python runtime that executes agent graphs, manages state, and talks to LLMs.
- **Tools package (`tools/` / `aden_tools`)**: Collection of MCP tools (file system, web, data, etc.) that agents can call.
- **Agent package (`exports/my_agent/`)**: Your generated agent, including `agent.json`, `tools.py`, tests, and code.
- **MCP server**: A process that exposes tools over the Model Context Protocol so coding agents (Claude, Cursor) can call them safely.
- **Claude Code / Cursor skills**: Pre-built workflows (like `/building-agents-construction`, `/testing-agent`) that orchestrate Hive and MCP tools for you.
- **TUI (coming soon)**: Text‑based UI for inspecting agents and runs; will sit on top of the same CLI and runtime you use here.

## Troubleshooting

### ModuleNotFoundError: No module named 'framework'

```bash
# Reinstall framework package
cd core
uv pip install -e .
```

### ModuleNotFoundError: No module named 'aden_tools'

```bash
# Reinstall tools package
cd tools
uv pip install -e .
```

### LLM API Errors

```bash
# Verify API key is set
echo $ANTHROPIC_API_KEY

```

### Package Installation Issues

```bash
# Remove and reinstall
pip uninstall -y framework tools
./quickstart.sh
```

## Getting Help

- **Documentation**: Check the `/docs` folder
- **Issues**: [github.com/adenhq/hive/issues](https://github.com/adenhq/hive/issues)
- **Discord**: [discord.com/invite/MXE49hrKDk](https://discord.com/invite/MXE49hrKDk)
- **Build Agents**: Use `/hive` skill to create agents
