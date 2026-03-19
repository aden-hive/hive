# LLM Provider Setup

This guide covers OpenRouter and Hive LLM, two providers available during quickstart setup.

## OpenRouter

[OpenRouter](https://openrouter.ai) provides access to 100+ models (Anthropic, OpenAI, Google, xAI, etc.) through a single API.

### Setup

1. Get an API key at [openrouter.ai/keys](https://openrouter.ai/keys).
2. Set the environment variable:
   ```bash
   export OPENROUTER_API_KEY="sk-or-..."
   ```
3. During `quickstart.sh` or `quickstart.ps1`, select **OpenRouter** when prompted for provider.
4. Paste your model ID when prompted (e.g. `x-ai/grok-4.20-beta`, `anthropic/claude-sonnet-4`).

### Configuration

- **API base:** `https://openrouter.ai/api/v1` (set automatically)
- **Model format:** Use OpenRouter model IDs (e.g. `x-ai/grok-4.20-beta`). If you paste `openrouter/<id>`, the framework normalizes it.
- **Privacy:** If calls fail with guardrail/privacy errors, check [openrouter.ai/settings/privacy](https://openrouter.ai/settings/privacy).

### Example `~/.hive/configuration.json`

```json
{
  "llm": {
    "provider": "openrouter",
    "model": "x-ai/grok-4.20-beta",
    "api_key_env_var": "OPENROUTER_API_KEY"
  }
}
```

## Hive LLM

Hive LLM provides access to Aden-hosted models (queen, kimi-2.5, GLM-5, etc.) via the Hive platform.

### Setup

1. Get an API key at [hive.adenhq.com](https://hive.adenhq.com).
2. Set the environment variable:
   ```bash
   export HIVE_API_KEY="your-hive-api-key"
   ```
3. During `quickstart.sh` or `quickstart.ps1`, select **Hive LLM** when prompted.
4. Choose a model (e.g. queen, kimi-2.5, GLM-5).

### Configuration

- **API base:** Set automatically to the Hive endpoint.
- **Model format:** Use model names such as `queen`, `kimi-2.5`, `GLM-5`.
- **Key storage:** The quickstart script stores `HIVE_API_KEY` in your environment (User scope on Windows).

### Example `~/.hive/configuration.json`

```json
{
  "llm": {
    "provider": "hive",
    "model": "queen",
    "api_key_env_var": "HIVE_API_KEY"
  }
}
```

## Switching Providers

Re-run `./quickstart.sh` (or `.\quickstart.ps1` on Windows) to change the default provider. The script will update `~/.hive/configuration.json` with your new selection.
