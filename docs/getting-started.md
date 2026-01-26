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

### Option 2: Create Agent Manually

> **Note:** The `exports/` directory is where your agents are created. It is not included in the repository (gitignored) because agents are user-generated via Claude Code skills or created manually.

```bash
# Create exports directory if it doesn't exist
mkdir -p exports/my_agent

# Create your agent structure
cd exports/my_agent
# Create agent.json, tools.py, README.md (see DEVELOPER.md for structure)

# Validate the agent
PYTHONPATH=core:exports python -m my_agent validate
```

### Option 3: Manual Code-First (Minimal Example)

If you prefer to start with code rather than CLI wizards, check out the manual agent example:

```bash
# View the minimal example
cat core/examples/manual_agent.py

# Run it (no API keys required)
PYTHONPATH=core python core/examples/manual_agent.py
```

This demonstrates the core runtime loop using pure Python functions, skipping the complexity of LLM setup and file-based configuration.

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
3. **Build Agents**: Use `/building-agents` skill in Claude Code
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
pip uninstall -y framework tools
./scripts/setup-python.sh
```

## Getting Help

- **Documentation**: Check the `/docs` folder
- **Issues**: [github.com/adenhq/hive/issues](https://github.com/adenhq/hive/issues)
- **Discord**: [discord.com/invite/MXE49hrKDk](https://discord.com/invite/MXE49hrKDk)
- **Build Agents**: Use `/building-agents` skill to create agents

## Common Use Cases & Examples

### 1. Building a Web Research Agent

**Goal**: Create an agent that researches topics and summarizes findings

```bash
# Start Claude Code
claude> /building-agents

# Define goal:
# "Research a given topic and return a comprehensive summary with sources"

# The agent will:
# 1. Accept a topic as input
# 2. Use web_search_tool to find relevant sources
# 3. Use web_scrape_tool to extract content
# 4. Process and summarize findings
# 5. Return results with sources

# Once generated, run with:
PYTHONPATH=core:exports python -m web_research_agent run --input '{
  "topic": "Climate change impacts on agriculture",
  "max_sources": 5
}'
```

### 2. Building an E-commerce Order Processing Agent

**Goal**: Automate order validation and processing

```bash
# Create agent to:
# 1. Validate order data
# 2. Check inventory
# 3. Calculate shipping
# 4. Process payment
# 5. Generate confirmation

# Uses file_system_tools to manage inventory
# Uses variables to track order state
```

### 3. Building a Customer Support Agent

**Goal**: Automate customer inquiry responses

```bash
# Agent handles:
# 1. Customer question parsing
# 2. Knowledge base search
# 3. Issue categorization
# 4. Response generation
# 5. Escalation if needed

# Uses memory to track conversation history
```

## Running Agents in Production

### Mock Mode (Testing)

```bash
# Test agent logic without LLM calls
PYTHONPATH=core:exports python -m my_agent run \
  --mock \
  --input '{"query": "test"}'

# Useful for:
# - Testing workflow logic
# - Developing agent without API costs
# - Debugging node execution
```

### Production Mode

```bash
# Run with real LLM calls
export ANTHROPIC_API_KEY="your-key"
PYTHONPATH=core:exports python -m my_agent run \
  --input '{"query": "production-query"}' \
  --verbose

# Monitor execution:
# - Check logs for decisions and outcomes
# - Review tokens used
# - Monitor error handling
```

## Performance Optimization

### Memory Management

```python
# In your agent's tools.py
def configure_memory():
    # Short-term memory for current session
    stm_size = 10  # Keep last 10 decisions
    
    # Long-term memory for learning
    ltm_enabled = True
    ltm_retention = "7d"  # Retain 7 days
```

### Token Optimization

```bash
# Use appropriate model sizes
# claude-3-5-sonnet: Better cost/performance
# claude-3-opus: Better reasoning for complex tasks

# Run with token tracking
PYTHONPATH=core:exports python -m my_agent run \
  --input '...' \
  --track-tokens
```

## Extending the Framework

### Adding Custom Tools

```bash
# Implement MCP servers following:
# tools/README.md - Tool development guide

# Once implemented, register in agent:
# 1. Update agent.json with tool config
# 2. Add tool imports in tools.py
# 3. Test with /testing-agent skill
```

### Custom Decision Logic

```python
# In your agent's nodes, implement custom decision logic
runtime.decide(
    intent="Evaluate customer sentiment",
    options=[
        {"id": "positive", "description": "Positive sentiment"},
        {"id": "negative", "description": "Negative sentiment"},
        {"id": "neutral", "description": "Neutral sentiment"},
    ],
    chosen="positive",  # Your logic determines this
    reasoning="High confidence keywords detected"
)
```

## Real-World Patterns

### Pattern 1: Multi-Stage Decision Making

```
Input → Analyze → Plan → Execute → Validate → Output
         (decision) (decision) (decision)
```

### Pattern 2: Error Recovery

```
Try Operation → Failed? → Apply Fix → Retry → Success/Escalate
```

### Pattern 3: Human in the Loop

```
Autonomous Action → Requires Approval? → Wait for Human → Continue
```

## Debugging Agents

### View Agent Decisions

```bash
# Enable verbose logging
PYTHONPATH=core:exports python -m my_agent run \
  --input '...' \
  --verbose \
  --log-level debug
```

### Test Individual Nodes

```bash
# Use mock mode to test specific nodes
claude> /testing-agent

# Generate constraint tests for:
# 1. Data validation nodes
# 2. Decision logic nodes
# 3. Tool invocation nodes
```

### Performance Profiling

```bash
# Track execution time and token usage
PYTHONPATH=core:exports python -m my_agent run \
  --input '...' \
  --profile \
  --metrics
```

## Advanced Topics

### Multi-Agent Coordination

The framework supports:
- Agents calling other agents
- Shared memory between agents
- Orchestrated workflows

### Real-time Monitoring

```bash
# Integration with observability platforms:
# - LangSmith
# - Arize
# - Custom dashboards
```

### Continuous Learning

Agents can:
- Learn from execution outcomes
- Update decision strategies
- Improve over time

---

**Need help?** Check the [Troubleshooting Guide](troubleshooting.md) or visit [Discord](https://discord.com/invite/MXE49hrKDk)
