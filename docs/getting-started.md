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

# 2. Run automated Python setup
./scripts/setup-python.sh

# 3. Verify installation
python -c "import framework; import aden_tools; print('✓ Setup complete')"
```

## Building Your First Agent

### Option 1: Using Claude Code Skills (Recommended)

```bash
# Install Claude Code skills (one-time)
./quickstart.sh

# Start Claude Code and build an agent
claude> /building-agents
```

Follow the interactive prompts to:
1. Define your agent's goal
2. Design the workflow (nodes and edges)
3. Generate the agent package
4. Test the agent

### Option 2: From an Example

```bash
# Copy an example agent
cp -r exports/support_ticket_agent exports/my_agent

# Customize the agent
cd exports/my_agent
# Edit agent.json, tools.py, README.md

# Validate the agent
PYTHONPATH=core:exports python -m my_agent validate
```

## Project Structure

```
hive/
├── core/                   # Core Framework
│   ├── framework/          # Agent runtime, graph executor
│   │   ├── runner/         # AgentRunner - loads and runs agents
│   │   ├── executor/       # GraphExecutor - executes node graphs
│   │   ├── protocols/      # Standard protocols (hooks, tracing)
│   │   ├── llm/            # LLM provider integrations
│   │   └── memory/         # Memory systems (STM, LTM/RLM)
│   └── pyproject.toml      # Package metadata
│
├── tools/                  # MCP Tools Package
│   └── src/aden_tools/     # 19 tools for agent capabilities
│       ├── tools/          # Individual tool implementations
│       │   ├── web_search_tool/
│       │   ├── web_scrape_tool/
│       │   └── file_system_toolkits/
│       └── mcp_server.py   # HTTP MCP server
│
├── exports/                # Agent Packages
│   ├── support_ticket_agent/
│   ├── market_research_agent/
│   └── ...                 # Your agents go here
│
├── .claude/                # Claude Code Skills
│   └── skills/
│       ├── building-agents/
│       └── testing-agent/
│
└── docs/                   # Documentation
```

## Running an Agent

```bash
# Validate agent structure
PYTHONPATH=core:exports python -m my_agent validate

# Show agent information
PYTHONPATH=core:exports python -m my_agent info

# Run agent with input
PYTHONPATH=core:exports python -m my_agent run --input '{
  "task": "Your input here"
}'

# Run in mock mode (no LLM calls)
PYTHONPATH=core:exports python -m my_agent run --mock --input '{...}'
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
PYTHONPATH=core:exports python -m my_agent test

# Run with specific test type
PYTHONPATH=core:exports python -m my_agent test --type constraint
PYTHONPATH=core:exports python -m my_agent test --type success
```

## Next Steps

1. **Detailed Setup**: See [ENVIRONMENT_SETUP.md](../ENVIRONMENT_SETUP.md)
2. **Developer Guide**: See [DEVELOPER.md](../DEVELOPER.md)
3. **Agent Patterns**: Explore examples in `/exports`
4. **Custom Tools**: Learn to integrate MCP servers
5. **Join Community**: [Discord](https://discord.com/invite/MXE49hrKDk)

## Troubleshooting

### ModuleNotFoundError: No module named 'framework'

```bash
# Reinstall framework package
cd core
pip install -e .
```

### ModuleNotFoundError: No module named 'aden_tools'

```bash
# Reinstall tools package
cd tools
pip install -e .
```

### LLM API Errors

```bash
# Verify API key is set
echo $ANTHROPIC_API_KEY

# Run in mock mode to test without API
PYTHONPATH=core:exports python -m my_agent run --mock --input '{...}'
```

### Package Installation Issues

```bash
# Remove and reinstall
pip uninstall -y framework aden-tools
./scripts/setup-python.sh
```

## Getting Help

- **Documentation**: Check the `/docs` folder
- **Issues**: [github.com/adenhq/hive/issues](https://github.com/adenhq/hive/issues)
- **Discord**: [discord.com/invite/MXE49hrKDk](https://discord.com/invite/MXE49hrKDk)
- **Examples**: Explore `/exports` for working agents
