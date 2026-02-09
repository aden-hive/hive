# Hive Configuration Module

This module provides interactive configuration management for Hive, particularly for LLM model and provider settings.

## Features

### Interactive TUI Model Selector
- Visual provider and model selection
- API key status indicators
- Model specifications (context window, capabilities)
- Configuration validation
- Atomic file writes with backup

### CLI Commands

#### Launch Model Selector TUI
```bash
hive config models
```

Interactive terminal interface for selecting:
- LLM provider (Anthropic, Groq, OpenAI, Google, Cerebras, DeepSeek)
- Specific model with specs
- Validates API key configuration
- Shows current configuration

#### Show Current Configuration
```bash
hive config show
hive config show --json  # JSON output for scripting
```

#### Set Configuration Values (Scripting)
```bash
hive config set llm.provider groq
hive config set llm.model "groq/llama-3.3-70b-versatile"
```

## Supported Providers

### Anthropic (Claude)
- **Models**: Opus 4, Sonnet 4, Haiku 4.5, 3.5 Sonnet
- **Context**: Up to 200K tokens
- **API Key**: `ANTHROPIC_API_KEY`
- **Get Key**: https://console.anthropic.com/settings/keys

### Groq
- **Models**: Llama 3.3 70B, Llama 3 70B/8B, Mixtral 8x7B, Gemma 2 9B
- **Context**: 8K - 32K tokens
- **API Key**: `GROQ_API_KEY`
- **Get Key**: https://console.groq.com/keys
- **Feature**: Ultra-fast inference

### OpenAI (GPT)
- **Models**: GPT-4o, GPT-4o Mini, GPT-4 Turbo, GPT-3.5 Turbo
- **Context**: Up to 128K tokens
- **API Key**: `OPENAI_API_KEY`
- **Get Key**: https://platform.openai.com/api-keys

### Google (Gemini)
- **Models**: Gemini 2.0 Flash, Gemini 1.5 Pro, Gemini 1.5 Flash
- **Context**: Up to 2M tokens
- **API Key**: `GEMINI_API_KEY`
- **Get Key**: https://makersuite.google.com/app/apikey

### Cerebras
- **Models**: Llama 3.3 70B, Llama 3.1 8B
- **Context**: 8K tokens
- **API Key**: `CEREBRAS_API_KEY`
- **Get Key**: https://cloud.cerebras.ai/
- **Feature**: Extremely fast inference on custom hardware

### DeepSeek
- **Models**: DeepSeek Chat, DeepSeek Coder
- **Context**: 64K tokens
- **API Key**: `DEEPSEEK_API_KEY`
- **Get Key**: https://platform.deepseek.com/api_keys

## Configuration File

Configuration is stored at: `~/.hive/configuration.json`

### Structure
```json
{
  "llm": {
    "provider": "groq",
    "model": "groq/llama-3.3-70b-versatile",
    "api_key_env_var": "GROQ_API_KEY"
  },
  "created_at": "2026-02-09T09:50:55+00:00",
  "updated_at": "2026-02-09T10:00:00+00:00"
}
```

## Usage Examples

### Quick Start - Interactive Setup
```bash
# Launch interactive model selector
hive config models

# Navigate with arrow keys or tab
# Press Enter to select
# API key status shown with ✓ or ○
```

### Scripting - Automated Setup
```bash
# Set provider and model programmatically
hive config set llm.provider anthropic
hive config set llm.model claude-sonnet-4-20250514

# Verify configuration
hive config show
```

### Troubleshooting

#### Invalid Model Configuration
The TUI prevents incompatible configurations (e.g., Moonshot AI model with Groq credentials) by showing only models compatible with the selected provider.

#### Missing API Key
The TUI shows a warning if the API key environment variable is not set, but still allows saving the configuration. Set your API key:

```bash
export GROQ_API_KEY="your-key-here"
# Add to ~/.zshrc or ~/.bashrc for persistence
```

## Implementation Details

### Modules
- `model_providers.py`: Provider and model registry
- `cli.py`: CLI command implementations
- `../tui/widgets/model_selector.py`: Interactive TUI widget

### Validation
- API key presence checked via environment variables
- Model-provider compatibility enforced
- Atomic file writes prevent corruption
- Automatic backup of corrupted configurations

### Adding New Providers

Edit `model_providers.py`:

```python
PROVIDERS = {
    "new_provider": ProviderInfo(
        id="new_provider",
        name="New Provider",
        env_var="NEW_PROVIDER_API_KEY",
        description="Provider description",
        api_key_url="https://provider.com/keys",
        requires_prefix=True,
        models=[
            ModelInfo(
                id="new_provider/model-name",
                name="Model Name",
                context_window=8192,
                description="Model description",
                recommended=True,
            ),
        ],
    ),
}
```
