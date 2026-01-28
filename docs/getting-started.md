# Getting Started

This guide walks you through the complete setup needed to build, validate, and run goal-driven AI agents using the Aden Hive Agent Framework.

## Prerequisites

-Make sure you have the following installed:
-Python 3.11+ (Python 3.12 / 3.13 recommended)
-pip – Python package installer (included with Python)
-git – Version control
-Claude Code (optional) – Required for using the /building-agents and /testing-agent skills

## Quick Start

The fastest way to get started:

```bash
1. Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

2. Run the automated Python setup
./scripts/setup-python.sh

3. Verify installation
python -c "import framework; import aden_tools; print('✓ Setup complete')"
```

## Building Your First Agent
You can build agents using Claude Code skills, by manually creating files, or by starting from a minimal Python example.

### Option 1: Using Claude Code Skills (Recommended)

```bash
Install the skills (one-time setup):
./quickstart.sh

Start Claude Code:
claude> /building-agents-construction
```

Follow the guided prompts to:
1. Define your agent’s goal
2. Design the workflow (nodes & edges)
3. Generate an agent package
4. Test the agent
5. Run the agent

### Option 2: Create Agent Manually
The exports/ directory is gitignored because agents are user-generated.

```bash
Create the directory:
mkdir -p exports/my_agent
cd exports/my_agent

Create your agent files:
-agent.json
-tools.py
-README.md

(Refer to DEVELOPER.md for structure and examples.)

Validate the agent:
PYTHONPATH=core:exports python -m my_agent validate
```

### Option 3: Manual Code-First (Minimal Example)

Hive includes a simple example that demonstrates the core runtime loop.

```bash
View it:
cat core/examples/manual_agent.py

Run it:
PYTHONPATH=core python core/examples/manual_agent.py

This example does not require API keys.
```

This demonstrates the core runtime loop using pure Python functions, skipping the complexity of LLM setup and file-based configuration.

## Project Structure

```
hive/
├── core/                     # Core Framework
│   ├── framework/            # Runtime, graph executor, protocols
│   │   ├── runner/           # AgentRunner
│   │   ├── executor/         # GraphExecutor
│   │   ├── protocols/        # Hooks & event protocols
│   │   ├── llm/              # LLM integrations
│   │   └── memory/           # STM / LTM systems
│   └── pyproject.toml
│
├── tools/                    # MCP Tools Package
│   └── src/aden_tools/
│       ├── tools/            # Web search, scraping, filesystem toolkits, etc.
│       └── mcp_server.py
│
├── exports/                  # Agent packages (user-created)
│   └── your_agent/
│
├── .claude/                  # Claude Code Skills
│   └── skills/
│       ├── agent-workflow/
│       ├── building-agents-construction/
│       ├── building-agents-core/
│       ├── building-agents-patterns/
│       └── testing-agent/
│
└── docs/                     # Documentation

```

## Running an Agent

```bash
Validate the agent:
PYTHONPATH=core:exports python -m my_agent validate

Show agent information:
PYTHONPATH=core:exports python -m my_agent info

Run with input:
PYTHONPATH=core:exports python -m my_agent run --input '{
  "task": "Your input here"
}'

Mock mode (no LLM calls):
PYTHONPATH=core:exports python -m my_agent run --mock --input '{...}'
```

## API Keys Setup

If you want to use real LLMs:
Add to ~/.bashrc, ~/.zshrc, or equivalent:

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"        # Optional
export BRAVE_SEARCH_API_KEY="your-key-here"  # Optional, for web search
```

Get your API keys:
-Anthropic → https://console.anthropic.com
-OpenAI → https://platform.openai.com
-Brave Search → https://brave.com/search/api


## Testing Your Agent

```bash
Using Claude Code:
claude> /testing-agent

Or manually:
PYTHONPATH=core:exports python -m my_agent test

Test specific types:
PYTHONPATH=core:exports python -m my_agent test --type constraint
PYTHONPATH=core:exports python -m my_agent test --type success
```

## Next Steps

1. Environment Setup: ENVIRONMENT_SETUP.md
2. Developer Guide: DEVELOPER.md
3. Build Agents: Use /building-agents in Claude Code
4. Implement Tools: Learn MCP servers
5. Join the Community: Discord

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
#Reinstall packages:
pip uninstall -y framework tools
./scripts/setup-python.sh
```
## Getting Help

-Documentation → /docs
-Issues → https://github.com/adenhq/hive/issues
-Discord → https://discord.com/invite/MXE49hrKDk
-Agent Builder → /building-agents in Claude Code