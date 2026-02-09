# Model Configuration Demo

This demo shows how the new model configuration system solves real-world problems with LLM provider and model selection.

## Problem: Misconfigured Model (Real Issue from GitHub)

### Before: Manual JSON Editing
```bash
# User accidentally configured Moonshot AI model with Groq credentials
cat ~/.hive/configuration.json
```

```json
{
  "llm": {
    "provider": "groq",
    "model": "moonshotai/kimi-k2-instruct-0905",
    "api_key_env_var": "GROQ_API_KEY"
  }
}
```

**Problems:**
1. ❌ Model `moonshotai/kimi-k2-instruct-0905` doesn't work with Groq
2. ❌ No validation until runtime (agent fails to start)
3. ❌ Hard to debug - unclear error messages
4. ❌ Had to manually edit JSON file (syntax error risk)

### After: Interactive Configuration

```bash
# Launch model selector TUI
hive config models

# Or use CLI with validation:
hive config models --provider groq --model "moonshotai/kimi-k2-instruct-0905"
# ✗ Error: Model 'moonshotai/kimi-k2-instruct-0905' is not compatible with provider 'groq'

# See available Groq models:
hive config models --list | grep -A 20 "Groq"

# Set correct model:
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"
# ✓ Configuration updated successfully
```

**Benefits:**
1. ✅ Validation prevents incompatible configurations
2. ✅ Clear error messages with suggestions
3. ✅ Interactive TUI shows only compatible models
4. ✅ No manual JSON editing required

## Use Case 1: Testing Different Models

### Scenario: Comparing performance/cost of different providers

```bash
# Test 1: Fastest (Groq Llama 3 8B)
hive config models --provider groq --model "groq/llama3-8b-8192"
time hive run my-agent --input '{"task": "Summarize this: ..."}'
# Result: 1.2s, cheap, good quality

# Test 2: Best Quality (Anthropic Claude Sonnet 4)
hive config models --provider anthropic --model "claude-sonnet-4-20250514"
time hive run my-agent --input '{"task": "Summarize this: ..."}'
# Result: 3.5s, expensive, excellent quality

# Test 3: Largest Context (Gemini 1.5 Pro - 2M tokens)
hive config models --provider google --model "gemini/gemini-1.5-pro"
time hive run my-agent --input '{"task": "Summarize this 100-page document: ..."}'
# Result: 4.2s, moderate cost, handles massive context
```

## Use Case 2: Rate Limit Failover

### Scenario: Primary provider hits rate limit

```bash
# Running agent with Groq (primary)
hive run my-agent --input '{"task": "..."}'
# Error: Rate limit exceeded (429)

# Quick failover to Anthropic (backup)
hive config models --provider anthropic --model "claude-sonnet-4-20250514"

# Retry immediately
hive run my-agent --input '{"task": "..."}'
# ✓ Success with backup provider
```

## Use Case 3: Task-Specific Model Selection

### Scenario: Different tasks need different models

```bash
# Simple classification task - use fast, cheap model
hive config models --provider groq --model "groq/llama3-8b-8192"
hive run classifier-agent --input '{"text": "..."}'

# Complex reasoning task - use most capable model
hive config models --provider anthropic --model "claude-opus-4-20250514"
hive run reasoning-agent --input '{"problem": "..."}'

# Long document analysis - use large context model
hive config models --provider google --model "gemini/gemini-1.5-pro"
hive run document-agent --input '{"document": "..."}'
```

## Use Case 4: Development vs Production

### Scenario: Different models for different environments

```bash
# Development: Fast, cheap testing
hive config models --provider groq --model "groq/llama3-8b-8192"
cp ~/.hive/configuration.json ./config-dev.json

# Staging: Balance speed and quality
hive config models --provider anthropic --model "claude-sonnet-4-20250514"
cp ~/.hive/configuration.json ./config-staging.json

# Production: Best quality, reliability
hive config models --provider anthropic --model "claude-opus-4-20250514"
cp ~/.hive/configuration.json ./config-prod.json

# Deploy to production
scp ./config-prod.json server:~/.hive/configuration.json
```

## Interactive TUI Demo

### Launching the TUI

```bash
hive config models
```

**What you see:**

```
┌─ Select LLM Provider ────────────────────────┐
│ ○ Anthropic (Claude)                         │
│ ✓ Groq (Llama, Mixtral) [current]           │
│ ○ OpenAI (GPT)                               │
│ ○ Google (Gemini)                            │
│ ○ Cerebras                                   │
│ ○ DeepSeek                                   │
└──────────────────────────────────────────────┘

┌─ Select Model ───────────────────────────────┐
│ ⭐ Llama 3.3 70B [8K context]                │
│ ○ Llama 3 70B [8K context]                   │
│ ○ Llama 3 8B [8K context] [current]          │
│ ○ Mixtral 8x7B [32K context]                 │
│ ○ Gemma 2 9B [8K context]                    │
└──────────────────────────────────────────────┘

┌─ Configuration ──────────────────────────────┐
│ Provider: Groq                               │
│ API Key Status: ✓ Configured                │
│ Model: Llama 3 8B                            │
│ Context: 8,192 tokens                        │
│ Fastest, good for simple tasks               │
└──────────────────────────────────────────────┘

[Save & Test]  [Cancel]
```

**Navigation:**
- Arrow keys / Tab: Navigate between sections
- Enter: Select provider or model
- Escape / Cancel: Exit without saving
- Save & Test: Validate and save configuration

## CLI Mode Demo

### List all available options

```bash
$ hive config models --list

Available LLM Providers and Models:
================================================================================

○ Anthropic (Claude) (anthropic)
  Claude models - advanced reasoning and code generation
  API Key: ANTHROPIC_API_KEY
  Get Key: https://console.anthropic.com/settings/keys

  Models:
       Claude Opus 4 [200K]
       Most capable model - complex reasoning
       ID: claude-opus-4-20250514
    ⭐ Claude Sonnet 4 [200K]
       Balanced performance and speed
       ID: claude-sonnet-4-20250514
    ...

✓ Groq (groq)
  Ultra-fast inference with open models
  API Key: GROQ_API_KEY
  Get Key: https://console.groq.com/keys

  Models:
    ⭐ Llama 3.3 70B [8K]
       Most capable Llama model
       ID: groq/llama-3.3-70b-versatile
    ...
```

### Set configuration directly

```bash
$ hive config models --provider groq --model "groq/llama-3.3-70b-versatile"
✓ Set llm.provider = groq
✓ Set llm.model = groq/llama-3.3-70b-versatile
✓ Set llm.api_key_env_var = GROQ_API_KEY

✓ Configuration updated successfully

Current configuration:
Current Hive Configuration:
============================================================

[LLM Configuration]
  Provider: groq
  Model: groq/llama-3.3-70b-versatile
  API Key Env Var: GROQ_API_KEY
```

### Validation in action

```bash
$ hive config models --provider groq --model "gpt-4o"
Error: Model 'gpt-4o' is not compatible with provider 'groq'

Use 'hive config models --list' to see available models for groq

$ hive config models --provider invalid_provider
Error: Unknown provider 'invalid_provider'

Available providers: anthropic, groq, openai, google, cerebras, deepseek
```

## Integration with Existing Workflows

### With `hive run`

```bash
# Set model
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"

# Run agent (automatically uses configured model)
hive run my-agent --input '{"task": "..."}'
```

### With `hive shell`

```bash
# Set model
hive config models --provider anthropic --model "claude-sonnet-4-20250514"

# Interactive shell (uses configured model)
hive shell my-agent
>>> Write a Python script to parse CSV files
[Agent uses Claude Sonnet 4]
```

### With `hive tui`

```bash
# Set model
hive config models

# Launch TUI dashboard (uses configured model)
hive tui
```

## Scripting Examples

### Automated Testing Script

```bash
#!/bin/bash
# test-all-providers.sh

declare -A providers=(
    ["groq"]="groq/llama-3.3-70b-versatile"
    ["anthropic"]="claude-sonnet-4-20250514"
    ["openai"]="gpt-4o-mini"
    ["google"]="gemini/gemini-2.0-flash-exp"
)

for provider in "${!providers[@]}"; do
    echo "Testing $provider with ${providers[$provider]}..."
    
    # Configure
    hive config models --provider "$provider" --model "${providers[$provider]}"
    
    # Test
    result=$(hive run test-agent --input '{"task": "test"}' --quiet)
    
    echo "Result: $result"
    echo "---"
done
```

### Cost Optimization Script

```bash
#!/bin/bash
# use-cheapest-model.sh

# For simple tasks, use fastest/cheapest
if [ "$TASK_COMPLEXITY" = "simple" ]; then
    hive config models --provider groq --model "groq/llama3-8b-8192"
else
    # For complex tasks, use best quality
    hive config models --provider anthropic --model "claude-sonnet-4-20250514"
fi

hive run my-agent --input "$INPUT"
```

## Migration Guide

### From Manual Configuration

**Old way:**
```bash
# Edit JSON manually
nano ~/.hive/configuration.json
# Risk of syntax errors, no validation
```

**New way:**
```bash
# Interactive TUI
hive config models

# Or CLI with validation
hive config models --provider groq --model "groq/llama-3.3-70b-versatile"
```

### From Environment Variables

**Old way:**
```bash
MODEL="gpt-4o-mini" hive run my-agent
# Temporary, not persisted
```

**New way:**
```bash
# Set persistent configuration
hive config set llm.model "gpt-4o-mini"
hive config set llm.provider "openai"

# Or use interactive config
hive config models
```

## Tips & Tricks

1. **Quick Model Swap During Development**
   ```bash
   # Save current config
   cp ~/.hive/configuration.json ~/.hive/config-backup.json
   
   # Try different model
   hive config models --provider groq --model "groq/llama3-8b-8192"
   
   # Restore if needed
   mv ~/.hive/config-backup.json ~/.hive/configuration.json
   ```

2. **API Key Management**
   ```bash
   # Check if API key is set
   echo $GROQ_API_KEY
   
   # Set temporarily
   export GROQ_API_KEY="your-key"
   
   # Set permanently
   echo 'export GROQ_API_KEY="your-key"' >> ~/.zshrc
   source ~/.zshrc
   ```

3. **Batch Configuration**
   ```bash
   # Set multiple values at once
   hive config set llm.provider groq
   hive config set llm.model "groq/llama-3.3-70b-versatile"
   hive config set llm.api_key_env_var GROQ_API_KEY
   ```

## Troubleshooting Common Issues

### Issue: TUI won't launch
```bash
# Install Textual
uv pip install textual

# Or use CLI mode instead
hive config models --list
```

### Issue: Model not working after configuration
```bash
# 1. Verify config
hive config show

# 2. Check API key
echo $GROQ_API_KEY

# 3. Test with different provider
hive config models --provider anthropic --model "claude-sonnet-4-20250514"
```

### Issue: Configuration file corrupted
```bash
# Restore from automatic backup
cp ~/.hive/configuration.json.backup ~/.hive/configuration.json

# Or recreate
hive config models
```

## Next Steps

- Try the TUI: `hive config models`
- List models: `hive config models --list`
- Read the full guide: [Model Configuration Guide](../docs/model-configuration.md)
- Check provider docs: [LiteLLM Providers](https://docs.litellm.ai/docs/providers)
