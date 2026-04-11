# Getting Started

This guide will help you set up the Aden Agent Framework and build your first agent.

## Prerequisites

- **Python 3.11+** ([Download](https://www.python.org/downloads/)) - Python 3.12 or 3.13 recommended
- **pip** - Package installer for Python (comes with Python)
- **git** - Version control
- **Claude Code** ([Install](https://docs.anthropic.com/claude/docs/claude-code)) - Optional, for using building skills

## Quick Start

The fastest way to get started:

**Linux / macOS:**

```bash
# 1. Clone the repository
git clone https://github.com/aden-hive/hive.git
cd hive

# 2. Run automated setup
./quickstart.sh

# 3. Verify installation (optional, quickstart.sh already verifies)
uv run python -c "import framework; import aden_tools; print('✓ Setup complete')"
```

**Windows (PowerShell):**

```powershell
# 1. Clone the repository
git clone https://github.com/aden-hive/hive.git
cd hive

# 2. Run automated setup
.\quickstart.ps1

# 3. Verify installation (optional, quickstart.ps1 already verifies)
uv run python -c "import framework; import aden_tools; print('Setup complete')"
```

> **Note:** On Windows, running `.\quickstart.ps1` requires PowerShell 5.1+. If you see a "running scripts is disabled" error, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first. Alternatively, use WSL — see [environment-setup.md](./environment-setup.md) for details.

## Building Your First Agent

Agents are not included by default in a fresh clone.

Agents are created using Claude Code or by manual creation in the
exports/ directory. Until an agent exists, agent validation and run
commands will fail.

### Option 1: Using Claude Code Skills (Recommended)

This is the recommended way to create your first agent.

**Requirements**

- Anthropic (Claude) API access
- Claude Code CLI installed
- Unix-based shell (macOS, Linux, or Windows via WSL)

```bash
# Setup already done via quickstart.sh above

# Start Claude Code and build an agent
Use the coder-tools initialize_and_build_agent tool
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
│   │   ├── testing/        # Testing utilities
│   │   └── tui/            # Terminal UI dashboard
│   └── pyproject.toml      # Package metadata
│
├── tools/                  # MCP Tools Package
│   ├── mcp_server.py       # MCP server entry point
│   └── src/aden_tools/     # Tools for agent capabilities
│       └── tools/          # Individual tool implementations
│           ├── web_search_tool/
│           ├── web_scrape_tool/
│           └── file_system_toolkits/
│
├── exports/                # Agent Packages (user-generated, not in repo)
│   └── your_agent/         # Your agents created via coder-tools workflow
│
├── examples/
│   └── templates/          # Pre-built template agents
│
└── docs/                   # Documentation
```

## Running an Agent

```bash
# Launch the web dashboard in your browser
hive open

# Run a specific agent
hive run exports/my_agent --input '{"task": "Your input here"}'

```

## API Keys Setup

For running agents with real LLMs:

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"        # Optional
export OPENROUTER_API_KEY="your-key-here"    # Optional, for OpenRouter models
export HIVE_API_KEY="your-key-here"          # Optional, for Hive LLM
export BRAVE_SEARCH_API_KEY="your-key-here"  # Optional, for web search
```

Get your API keys:

- **Anthropic**: [console.anthropic.com](https://console.anthropic.com/)
- **OpenAI**: [platform.openai.com](https://platform.openai.com/)
- **OpenRouter**: [openrouter.ai/keys](https://openrouter.ai/keys)
- **Hive LLM**: [Hive Discord](https://discord.com/invite/hQdU7QDkgR)
- **Brave Search**: [brave.com/search/api](https://brave.com/search/api/)

Quickstart can configure OpenRouter and Hive LLM for you interactively. See [configuration.md](./configuration.md) for the full configuration examples.

## Testing Your Agent

```bash
# Run tests
PYTHONPATH=exports uv run python -m my_agent test

# Run with specific test type
PYTHONPATH=exports uv run python -m my_agent test --type constraint
PYTHONPATH=exports uv run python -m my_agent test --type success
```

## Next Steps

1. **Dashboard**: Run `hive open` to launch the web dashboard
2. **Detailed Setup**: See [environment-setup.md](./environment-setup.md)
3. **Developer Guide**: See [developer-guide.md](./developer-guide.md)
4. **Build Agents**: Use the coder-tools `initialize_and_build_agent` tool in Claude Code
5. **Custom Tools**: Learn to integrate MCP servers
6. **Join Community**: [Discord](https://discord.com/invite/MXE49hrKDk)

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
echo $OPENROUTER_API_KEY
echo $HIVE_API_KEY

```

### Package Installation Issues

```bash
# Remove and reinstall
uv pip uninstall -y framework tools
./quickstart.sh
```

## Getting Help

- **Documentation**: Check the `/docs` folder
- **Issues**: [github.com/adenhq/hive/issues](https://github.com/aden-hive/hive/issues)
- **Discord**: [discord.com/invite/MXE49hrKDk](https://discord.com/invite/MXE49hrKDk)
- **Build Agents**: Use the coder-tools workflow to create agents
