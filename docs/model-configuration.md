# LLM Model Configuration Guide

This guide covers the new interactive model configuration system for Hive, which makes it easy to switch between LLM providers and models.

## Quick Start

### Interactive TUI (Recommended for New Users)

Launch the interactive model selector:

```bash
hive config models
```

This opens a full-screen TUI where you can:
- Browse all supported providers
- See which providers have configured API keys (✓)
- Select a model with detailed specs
- Save and validate your configuration

**Navigation:**
- Use arrow keys or Tab to navigate
- Press Enter to select
- Press Escape or Cancel button to exit

### CLI Mode (For Scripting & Power Users)

List all available providers and models:

```bash
hive config models --list
```

Set provider and model directly:

```bash
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"
hive config models --provider anthropic --model "claude-sonnet-4-20250514"
```

View current configuration:

```bash
hive config show
hive config show --json  # For scripting
```

## Problem This Solves

### Before: Manual JSON Editing (Error-Prone)

```bash
# Had to manually edit ~/.hive/configuration.json
# Risk of JSON syntax errors
# No validation until runtime
# Easy to misconfigure (e.g., Moonshot AI model with Groq credentials)
```

### After: Interactive & Validated

```bash
# Interactive TUI with validation
hive config models

# Or quick CLI for scripting
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"

# Validation prevents misconfigurations:
# ✗ Error: Model 'gpt-4o' is not compatible with provider 'groq'
```

## Supported Providers

### Anthropic (Claude)
```bash
# Recommended: Claude Sonnet 4
hive config models --provider anthropic --model "claude-sonnet-4-20250514"

# Other models:
# - claude-opus-4-20250514 (most capable)
# - claude-haiku-4-5-20251001 (fastest)
# - claude-3-5-sonnet-20241022 (previous gen)
```

**API Key:** Get from https://console.anthropic.com/settings/keys
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Groq (Ultra-Fast Inference)
```bash
# Recommended: Llama 3.3 70B
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"

# Other models:
# - groq/llama3-70b-8192 (previous gen, very fast)
# - groq/llama3-8b-8192 (fastest)
# - groq/mixtral-8x7b-32768 (32K context)
```

**API Key:** Get from https://console.groq.com/keys
```bash
export GROQ_API_KEY="gsk_..."
```

### OpenAI (GPT)
```bash
# Recommended: GPT-4o or GPT-4o Mini
hive config models --provider openai --model "gpt-4o-mini"

# Other models:
# - gpt-4o (latest multimodal)
# - gpt-4-turbo (previous gen)
# - gpt-3.5-turbo (legacy, very fast)
```

**API Key:** Get from https://platform.openai.com/api-keys
```bash
export OPENAI_API_KEY="sk-..."
```

### Google (Gemini)
```bash
# Recommended: Gemini 2.0 Flash
hive config models --provider google --model "gemini/gemini-2.0-flash-exp"

# Other models:
# - gemini/gemini-1.5-pro (2M context!)
# - gemini/gemini-1.5-flash (1M context, fast)
```

**API Key:** Get from https://makersuite.google.com/app/apikey
```bash
export GEMINI_API_KEY="..."
```

### Cerebras (Ultra-Fast Hardware)
```bash
# Recommended: Llama 3.3 70B on Cerebras
hive config models --provider cerebras --model "cerebras/llama-3.3-70b"

# Other models:
# - cerebras/llama3.1-8b (fastest)
```

**API Key:** Get from https://cloud.cerebras.ai/
```bash
export CEREBRAS_API_KEY="..."
```

### DeepSeek (Cost-Effective)
```bash
# Recommended: DeepSeek Chat
hive config models --provider deepseek --model "deepseek/deepseek-chat"

# Other models:
# - deepseek/deepseek-coder (specialized for coding)
```

**API Key:** Get from https://platform.deepseek.com/api_keys
```bash
export DEEPSEEK_API_KEY="..."
```

## Common Workflows

### Testing Different Models for Performance

```bash
# Test with Groq (fastest)
hive config models --provider groq --model "groq/llama3-8b-8192"
hive run my-agent --input '{"task": "test"}'

# Compare with Anthropic (best quality)
hive config models --provider anthropic --model "claude-sonnet-4-20250514"
hive run my-agent --input '{"task": "test"}'

# Compare with Gemini (largest context)
hive config models --provider google --model "gemini/gemini-2.0-flash-exp"
hive run my-agent --input '{"task": "test"}'
```

### Switching Due to Rate Limits

```bash
# Primary provider hit rate limit, switch to backup
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"

# Or keep multiple configurations in version control
cp ~/.hive/configuration.json ~/.hive/config-groq.json
cp ~/.hive/config-anthropic.json ~/.hive/configuration.json
```

### Adjusting for Different Tasks

```bash
# Simple tasks: use fast, cheap model
hive config models --provider groq --model "groq/llama3-8b-8192"

# Complex reasoning: use most capable model
hive config models --provider anthropic --model "claude-opus-4-20250514"

# Long documents: use large context window
hive config models --provider google --model "gemini/gemini-1.5-pro"
```

### Recovering from Configuration Errors

```bash
# If you accidentally misconfigured (e.g., wrong model with wrong provider)
# Just run the configurator again:
hive config models

# Or fix via CLI:
hive config show  # See current config
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"

# If configuration.json is corrupted, it's automatically backed up:
# ~/.hive/configuration.json.backup
```

## Advanced Usage

### Environment Variable Override (Temporary Testing)

```bash
# Test a model without changing configuration
MODEL="gpt-4o-mini" hive run my-agent --input '{"task": "test"}'

# Note: This only works if you use the --model flag or env var
# For persistent changes, use hive config models
```

### Scripting Configuration Changes

```bash
#!/bin/bash
# setup-dev.sh - Set up development environment

# Configure fast model for development
hive config models --provider groq --model "groq/llama3-8b-8192"

# Verify
hive config show

# Run tests
hive test-run my-agent --goal dev-test
```

### Multi-Environment Configuration

```bash
# Development
hive config models --provider groq --model "groq/llama3-8b-8192"
cp ~/.hive/configuration.json ./config-dev.json

# Staging
hive config models --provider anthropic --model "claude-sonnet-4-20250514"
cp ~/.hive/configuration.json ./config-staging.json

# Production
hive config models --provider anthropic --model "claude-opus-4-20250514"
cp ~/.hive/configuration.json ./config-production.json

# Switch environments
cp ./config-production.json ~/.hive/configuration.json
```

### Programmatic Configuration

```python
import json
from pathlib import Path

config_path = Path.home() / ".hive" / "configuration.json"

# Read current config
with open(config_path) as f:
    config = json.load(f)

# Update model
config["llm"]["provider"] = "groq"
config["llm"]["model"] = "groq/llama-3.3-70b-versatile"
config["llm"]["api_key_env_var"] = "GROQ_API_KEY"

# Write back
with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
```

## Validation & Error Handling

### API Key Validation

The system checks if the required API key environment variable is set:

```bash
# If API key is not set, you'll see a warning:
# ⚠ Not configured (GROQ_API_KEY)

# Set the key:
export GROQ_API_KEY="your-key-here"

# Add to shell config for persistence:
echo 'export GROQ_API_KEY="your-key-here"' >> ~/.zshrc
source ~/.zshrc
```

### Model-Provider Compatibility

Validation prevents mismatched configurations:

```bash
# This will fail:
hive config models --provider groq --model "gpt-4o"
# Error: Model 'gpt-4o' is not compatible with provider 'groq'

# This will succeed:
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"
```

### Automatic Backup

If your configuration file becomes corrupted, it's automatically backed up:

```bash
# Original (corrupted): ~/.hive/configuration.json
# Backup: ~/.hive/configuration.json.backup

# You can restore from backup:
cp ~/.hive/configuration.json.backup ~/.hive/configuration.json
```

## Troubleshooting

### "No module named 'textual'" Error

```bash
# Install Textual for TUI support:
uv pip install textual

# Or use CLI mode instead:
hive config models --list
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"
```

### Model Not Working Despite Configuration

```bash
# 1. Verify configuration
hive config show

# 2. Check API key is set
echo $GROQ_API_KEY  # Should not be empty

# 3. Test with a different model
hive config models --provider anthropic --model "claude-sonnet-4-20250514"

# 4. Check for rate limits or API issues
# Try a different provider as backup
```

### Configuration File Permissions

```bash
# Ensure the config directory exists and is writable:
mkdir -p ~/.hive
chmod 700 ~/.hive
```

## Integration with Existing Hive Workflows

### Use with hive run

```bash
# Configure model first
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"

# Then run agent (uses configured model)
hive run my-agent --input '{"objective": "..."}'
```

### Use with hive shell

```bash
# Configure model
hive config models --provider anthropic --model "claude-sonnet-4-20250514"

# Start interactive shell (uses configured model)
hive shell my-agent
```

### Use with TUI Dashboard

```bash
# Configure model
hive config models

# Launch TUI (uses configured model)
hive tui
```

## Future Enhancements

- **Model Presets**: Save favorite model configurations
  ```bash
  hive config models --save-preset production
  hive config models --load-preset development
  ```

- **Hotkey in Agent Runtime**: Press 'm' during execution to switch models

- **Automatic Fallback**: If primary provider fails, automatically try backup

- **Cost Tracking**: See token usage and costs per provider

- **Benchmarking**: Compare model performance side-by-side

## See Also

- [Configuration Module README](../core/framework/config/README.md)
- [Getting Started Guide](./getting-started.md)
- [LiteLLM Documentation](https://docs.litellm.ai/)
