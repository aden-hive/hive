# Configuration Guide

Aden Hive is a Python-based agent framework. Configuration is handled through environment variables and agent-level config files. There is no centralized `config.yaml` or Docker Compose setup.

## Configuration Overview

```
Environment variables     (API keys, runtime flags)
Agent config.py           (per-agent settings: model, tools, storage)
pyproject.toml            (package metadata and dependencies)
.mcp.json                 (MCP server connections)
```

## Environment Variables

### LLM Providers (at least one required for real execution)

```bash
# Anthropic (primary provider)
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI (optional, for GPT models via LiteLLM)
export OPENAI_API_KEY="sk-..."

# Cerebras (optional, used by output cleaner and some nodes)
export CEREBRAS_API_KEY="..."

# Groq (optional, fast inference)
export GROQ_API_KEY="..."
```

The framework supports 100+ LLM providers through [LiteLLM](https://docs.litellm.ai/docs/providers). Set the corresponding environment variable for your provider.

### Search & Tools (optional)

```bash
# Web search for agents (Brave Search)
export BRAVE_SEARCH_API_KEY="..."

# Exa Search (alternative web search)
export EXA_API_KEY="..."
```

### Runtime Flags

```bash
# Run agents without LLM calls (structure-only validation)
export MOCK_MODE=1

# Custom credentials storage path (default: ~/.aden/credentials)
export ADEN_CREDENTIALS_PATH="/custom/path"

# Custom agent storage path (default: /tmp)
export AGENT_STORAGE_PATH="/custom/storage"
```

## Agent Configuration

Each agent package in `exports/` contains its own `config.py`:

```python
# exports/my_agent/config.py
CONFIG = {
    "model": "claude-haiku-4-5-20251001",  # Default LLM model
    "max_tokens": 4096,
    "temperature": 0.7,
    "tools": ["web_search", "pdf_read"],   # MCP tools to enable
    "storage_path": "/tmp/my_agent",       # Runtime data location
}
```

### Agent Graph Specification

Agent behavior is defined in `agent.json` (or constructed in `agent.py`):

```json
{
  "id": "my_agent",
  "name": "My Agent",
  "goal": {
    "success_criteria": [...],
    "constraints": [...]
  },
  "nodes": [...],
  "edges": [...]
}
```

See the [Getting Started Guide](getting-started.md) for building agents.

## MCP Server Configuration

MCP (Model Context Protocol) servers are configured in `.mcp.json` at the project root:

```json
{
  "mcpServers": {
    "agent-builder": {
      "command": "core/.venv/bin/python",
      "args": ["-m", "framework.mcp.agent_builder_server"],
      "cwd": "."
    },
    "tools": {
      "command": "tools/.venv/bin/python",
      "args": ["-m", "aden_tools.mcp_server", "--stdio"],
      "cwd": "."
    }
  }
}
```

The tools MCP server exposes tools including web search, PDF reading, CSV processing, and file system operations.

## Storage

Aden Hive uses **file-based persistence** (no database required):

```
{storage_path}/
  runs/{run_id}.json          # Complete execution traces
  indexes/
    by_goal/{goal_id}.json    # Runs indexed by goal
    by_status/{status}.json   # Runs indexed by status
    by_node/{node_id}.json    # Runs indexed by node
  summaries/{run_id}.json     # Quick-load run summaries
```

Storage is managed by `framework.storage.FileStorage`. No external database setup is needed.

## IDE Setup

### VS Code

Add to `.vscode/settings.json`:

```json
{
  "python.analysis.extraPaths": [
    "${workspaceFolder}/core",
    "${workspaceFolder}/exports"
  ]
}
```

### PyCharm

1. Open Project Settings > Project Structure
2. Mark `core` as Sources Root
3. Mark `exports` as Sources Root

## Security Best Practices

1. **Never commit API keys** - Use environment variables or `.env` files
2. **`.env` is git-ignored** - Copy `.env.example` to `.env` at the project root and fill in your values
3. **Mock mode for testing** - Set `MOCK_MODE=1` to avoid LLM calls during development
4. **Credential isolation** - Each tool validates its own credentials at runtime

## Troubleshooting

### "ModuleNotFoundError: No module named 'framework'"

Install the core package:

```bash
cd core && uv pip install -e .
```

### API key not found

Ensure the environment variable is set in your current shell session:

```bash
echo $ANTHROPIC_API_KEY  # Should print your key
```

On Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

### Agent not found

Run from the project root with PYTHONPATH:

```bash
PYTHONPATH=exports uv run python -m my_agent validate
```

See [Environment Setup](../ENVIRONMENT_SETUP.md) for detailed installation instructions.
