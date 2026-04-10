# Configuration Guide

Aden Hive is a Python-based agent framework. Configuration is handled through environment variables and agent-level config files. There is no centralized `config.yaml` or Docker Compose setup.

## Configuration Overview

```
~/.hive/configuration.json  (global defaults: provider, model, max_tokens)
Environment variables        (API keys, runtime flags)
Agent config.py              (per-agent settings: model, tools, storage)
pyproject.toml               (package metadata and dependencies)
.mcp.json                    (MCP server connections)
```

## Global Configuration (~/.hive/configuration.json)

The `quickstart.sh` script creates this file during setup. It stores the default LLM provider, model, and max_tokens used by all agents unless overridden in an agent's own `config.py`.

```json
{
  "llm": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 8192,
    "api_key_env_var": "ANTHROPIC_API_KEY"
  },
  "created_at": "2026-01-15T12:00:00+00:00"
}
```

The default `max_tokens` value (8192) is defined as `DEFAULT_MAX_TOKENS` in `framework.orchestrator.edge` and re-exported from `framework.orchestrator`. Each agent's `RuntimeConfig` reads from this file at startup. To change defaults, either re-run `quickstart.sh` or edit the file directly.

## Environment Variables

### LLM Providers (at least one required for real execution)

```bash
# Anthropic (primary provider)
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI (optional, for GPT models via LiteLLM)
export OPENAI_API_KEY="sk-..."

# OpenRouter (optional, for OpenRouter-hosted models)
export OPENROUTER_API_KEY="..."

# Hive LLM (optional, for Hive-managed models)
export HIVE_API_KEY="..."

# Cerebras (optional, used by output cleaner and some nodes)
export CEREBRAS_API_KEY="..."

# Groq (optional, fast inference)
export GROQ_API_KEY="..."
```

The framework supports 100+ LLM providers through [LiteLLM](https://docs.litellm.ai/docs/providers). Set the corresponding environment variable for your provider.

### Provider Examples

Native Supported Providers (DeepSeek, Mistral, Together AI, xAI, Perplexity):

```json
{
  "llm": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "max_tokens": 8192,
    "api_key_env_var": "DEEPSEEK_API_KEY"
  }
}
```

Notes:

- Set `provider` to `deepseek` (or `mistral`, `together`, `xai`, `perplexity`)
- Use the standard model name in `model`, for example `deepseek-chat`
- **No `api_base` is required** for these natively supported providers

OpenRouter:

```json
{
  "llm": {
    "provider": "openrouter",
    "model": "x-ai/grok-4.20-beta",
    "max_tokens": 8192,
    "api_key_env_var": "OPENROUTER_API_KEY",
    "api_base": "https://openrouter.ai/api/v1"
  }
}
```

Notes:

- Set `provider` to `openrouter`
- Use the raw OpenRouter model ID in `model`, for example `x-ai/grok-4.20-beta`
- `api_base` should be `https://openrouter.ai/api/v1`
- If you paste a model that already starts with `openrouter/`, Hive tolerates and normalizes it

Hive LLM:

```json
{
  "llm": {
    "provider": "hive",
    "model": "queen",
    "max_tokens": 32768,
    "api_key_env_var": "HIVE_API_KEY",
    "api_base": "https://api.adenhq.com"
  }
}
```

Notes:

- Set `provider` to `hive`
- Common Hive model values are `queen`, `kimi-2.5`, and `GLM-5`
- Hive LLM requests use the Hive endpoint at `https://api.adenhq.com`

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

# Fernet encryption key for credential store at ~/.hive/credentials
export HIVE_CREDENTIAL_KEY="your-fernet-key"

# Custom agent storage path (default: ~/.hive/agents/{agent_name}/)
export AGENT_STORAGE_PATH="/custom/storage"
```

## Agent Configuration

Each agent package in `exports/` contains its own `config.py`:

```python
# exports/my_agent/config.py
CONFIG = {
    "model": "anthropic/claude-sonnet-4-5-20250929",  # Default LLM model
    "max_tokens": 8192,  # default: DEFAULT_MAX_TOKENS from framework.orchestrator
    "temperature": 0.7,
    "tools": ["web_search", "pdf_read"],   # MCP tools to enable
    "storage_path": "~/.hive/agents/my_agent/",  # Runtime data location (default)
}
```

If `model` or `max_tokens` are omitted, the agent loads defaults from `~/.hive/configuration.json`.

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
    "coder-tools": {
      "command": "uv",
      "args": ["run", "coder_tools_server.py", "--stdio"],
      "cwd": "tools"
    },
    "tools": {
      "command": "uv",
      "args": ["run", "mcp_server.py", "--stdio"],
      "cwd": "tools"
    }
  }
}
```

The `coder-tools` server provides agent scaffolding via `initialize_and_build_agent` and related tools. The `tools` MCP server exposes tools including web search, PDF reading, CSV processing, and file system operations.

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
2. **If you use a local `.env` file, keep it private** - This repository does not include a root `.env.example`; use your own local `.env` file or shell environment variables for secrets
3. **Use real provider keys in non-production environments** - validate configuration with low-risk inputs before production rollout
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
echo $ANTHROPIC_API_KEY  # Or echo $OPENROUTER_API_KEY / echo $HIVE_API_KEY
```

On Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# Or:
$env:OPENROUTER_API_KEY = "your-openrouter-key"
$env:HIVE_API_KEY = "your-hive-key"
```

### Agent not found

Run from the project root with PYTHONPATH:

```bash
PYTHONPATH=exports uv run python -m my_agent validate
```

See [Environment Setup](./environment-setup.md) for detailed installation instructions.
