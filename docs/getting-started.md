# Getting Started

This guide will help you set up the Aden Agent Framework and build your first agent.

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
claude> /building-agents-construction
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
# Create agent.json, tools.py, README.md (see DEVELOPER.md for structure)

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
├── core/                   # Core Framework
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
│   │   └── testing/        # Testing utilities
│   └── pyproject.toml      # Package metadata
│
├── tools/                  # MCP Tools Package
│   └── src/aden_tools/     # Tools for agent capabilities
│       ├── tools/          # Individual tool implementations
│       │   ├── web_search_tool/
│       │   ├── web_scrape_tool/
│       │   └── file_system_toolkits/
│       └── mcp_server.py   # HTTP MCP server
│
├── exports/                # Agent Packages (user-generated, not in repo)
│   └── your_agent/         # Your agents created via /building-agents
│
├── .claude/                # Claude Code Skills
│   └── skills/
│       ├── agent-workflow/
│       ├── building-agents-construction/
│       ├── building-agents-core/
│       ├── building-agents-patterns/
│       └── testing-agent/
│
└── docs/                   # Documentation
```

## Running an Agent

```bash
# Validate agent structure
PYTHONPATH=exports uv run python -m my_agent validate

# Show agent information
PYTHONPATH=exports uv run python -m my_agent info

# Run agent with input
PYTHONPATH=exports uv run python -m my_agent run --input '{
  "task": "Your input here"
}'

# Run in mock mode (no LLM calls)
PYTHONPATH=exports uv run python -m my_agent run --mock --input '{...}'
```

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
claude> /testing-agent

# Or manually
PYTHONPATH=exports uv run python -m my_agent test

# Run with specific test type
PYTHONPATH=exports uv run python -m my_agent test --type constraint
PYTHONPATH=exports uv run python -m my_agent test --type success
```

## Next Steps

1. **Detailed Setup**: See [ENVIRONMENT_SETUP.md](../ENVIRONMENT_SETUP.md)
2. **Developer Guide**: See [DEVELOPER.md](../DEVELOPER.md)
3. **Build Agents**: Use `/building-agents` skill in Claude Code
4. **Custom Tools**: Learn to integrate MCP servers
5. **Join Community**: [Discord](https://discord.com/invite/MXE49hrKDk)

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

# Run in mock mode to test without API
PYTHONPATH=exports uv run python -m my_agent run --mock --input '{...}'
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
- **Build Agents**: Use `/building-agents` skill to create agents
