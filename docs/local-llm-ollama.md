# Running Hive Agents with Local LLMs (Ollama)

This guide shows how to run Hive template agents using a **local LLM via [Ollama](https://ollama.ai/)** instead of requiring cloud API keys (Anthropic, OpenAI, etc.). This is useful for:

- **Getting started quickly** without signing up for cloud API providers
- **Offline development** with no internet dependency for LLM calls
- **Privacy-sensitive workloads** where data must stay on your machine
- **Cost-free experimentation** during prototyping and learning

> **Note:** Local models are an *alternative* to cloud providers. Cloud APIs
> (Anthropic, OpenAI, etc.) generally offer stronger reasoning for complex
> agent tasks, but Ollama is a great way to explore Hive without needing
> API keys.

---

## Prerequisites

### 1. Install Ollama

Download and install Ollama for your operating system:

| OS | Install |
|----|---------|
| **macOS** | `brew install ollama` or download from [ollama.ai](https://ollama.ai/download) |
| **Linux** | `curl -fsSL https://ollama.ai/install.sh \| sh` |
| **Windows** | Download the installer from [ollama.ai/download](https://ollama.ai/download) |
| **Windows (WSL)** | Inside WSL: `curl -fsSL https://ollama.ai/install.sh \| sh` |

### 2. Start the Ollama Server

```bash
ollama serve
```

The server runs on `http://localhost:11434` by default. Keep this terminal
open, or run `ollama serve` as a background service.

### 3. Pull a Model

```bash
# Recommended for agent tasks (good balance of speed and capability)
ollama pull llama3.1

# Smaller/faster alternative
ollama pull llama3.2

# For code-heavy agents
ollama pull codellama

# For lightweight experimentation
ollama pull mistral
```

Verify the model is available:

```bash
ollama list
```

### 4. Hive Setup

Make sure you have completed the standard Hive setup:

```bash
./quickstart.sh
```

---

## Configuration

### Option A: Global Configuration (Recommended)

Edit `~/.hive/configuration.json` to set Ollama as the default provider
for all agents:

```json
{
  "llm": {
    "provider": "ollama",
    "model": "llama3.1",
    "max_tokens": 4096
  }
}
```

**Windows path:** `C:\Users\<YourUser>\.hive\configuration.json`

> **How it works:** The `provider` and `model` fields are combined into the
> LiteLLM model string `ollama/llama3.1`. The framework's `config.py`
> reads this at startup via `get_preferred_model()` and passes it to the
> `LiteLLMProvider`.

#### Other Local Models

| Model | Config `"model"` value | Best for |
|-------|----------------------|----------|
| Llama 3.1 8B | `llama3.1` | General-purpose agent tasks |
| Llama 3.2 3B | `llama3.2` | Fast, lightweight tasks |
| CodeLlama 7B | `codellama` | Code generation and analysis |
| Mistral 7B | `mistral` | General reasoning |
| Gemma 2 9B | `gemma2` | Google's open model |
| Qwen 2.5 7B | `qwen2.5` | Multilingual tasks |
| DeepSeek Coder | `deepseek-coder-v2` | Code-focused agents |
| Phi-3 | `phi3` | Microsoft's small model |

### Option B: CLI Override (Per-Run)

Override the model for a single run without changing the config file:

```bash
hive run exports/my_agent --model ollama/llama3.1 --input '{"task": "Hello"}'
```

### Option C: Agent-Level Configuration

Set the model inside a specific agent's `config.py`:

```python
# exports/my_agent/config.py
from framework.config import RuntimeConfig

default_config = RuntimeConfig(
    model="ollama/llama3.1",
    temperature=0.7,
    max_tokens=4096,
)
```

### Option D: Custom Ollama Server URL

If Ollama runs on a different host or port (e.g., a remote GPU machine):

```json
{
  "llm": {
    "provider": "ollama",
    "model": "llama3.1",
    "max_tokens": 4096,
    "api_base": "http://192.168.1.100:11434"
  }
}
```

---

## Running a Template Agent

With Ollama configured, template agents work exactly the same as with
cloud providers:

```bash
# Interactive TUI dashboard
hive tui

# Run a specific template agent
hive run examples/templates/hello_world --input '{"task": "Greet the user"}'

# Run with TUI dashboard
hive run examples/templates/hello_world --tui
```

No API key environment variables are needed — Ollama runs locally and
the framework detects `ollama/` prefixed models as local (no key required).

---

## How It Works Under the Hood

Hive uses [LiteLLM](https://docs.litellm.ai/docs/providers/ollama) as its
LLM abstraction layer. When you set `provider: "ollama"` and
`model: "llama3.1"`, the framework:

1. **Reads the config** from `~/.hive/configuration.json` via
   `framework.config.get_preferred_model()`, producing the model string
   `"ollama/llama3.1"`.

2. **Creates a `LiteLLMProvider`** with that model string:
   ```python
   from framework.llm.litellm import LiteLLMProvider
   provider = LiteLLMProvider(model="ollama/llama3.1")
   ```

3. **Skips API key validation** — the framework's `AgentRunner._get_api_key_env_var()`
   returns `None` for `ollama/` models, so no environment variable is
   required.

4. **Routes requests** through LiteLLM to Ollama's local HTTP API at
   `http://localhost:11434`.

---

## Troubleshooting

### "Connection refused" or "Could not connect to Ollama"

Ensure the Ollama server is running:

```bash
# Start the server
ollama serve

# Verify it's accessible
curl http://localhost:11434/api/tags
```

### Model not found

Make sure you've pulled the model:

```bash
ollama pull llama3.1
ollama list  # Verify it appears
```

### Slow responses

Local LLMs depend on your hardware. Tips:

- **Use a smaller model** (e.g., `llama3.2` or `phi3`) for faster inference
- **GPU acceleration**: Ollama automatically uses GPU if available. Check
  with `ollama ps`
- **Reduce `max_tokens`** in the config (e.g., `2048` instead of `4096`)

### Tool calling issues

Some local models have limited support for function/tool calling compared
to cloud models. If an agent relies heavily on tool use:

- Try `llama3.1` — it has good tool calling support
- Consider using a cloud provider for tool-heavy agents
- See [Issue #4222](https://github.com/adenhq/hive/issues/4222) for known
  Ollama tool calling limitations

### Windows-specific issues

- **WSL recommended**: Run both Ollama and Hive inside WSL for best
  compatibility
- If running Ollama natively on Windows and Hive in WSL, use `api_base`
  to point to the Windows host:
  ```json
  {
    "llm": {
      "provider": "ollama",
      "model": "llama3.1",
      "api_base": "http://host.docker.internal:11434"
    }
  }
  ```

---

## Switching Between Local and Cloud

You can easily switch back to a cloud provider by updating the config:

```json
{
  "llm": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 8192,
    "api_key_env_var": "ANTHROPIC_API_KEY"
  }
}
```

Or use the CLI override to test with cloud while keeping Ollama as default:

```bash
hive run exports/my_agent --model anthropic/claude-sonnet-4-5-20250929
```

---

## Recommended Models by Task

| Agent Task | Recommended Model | `ollama pull` command |
|-----------|-------------------|----------------------|
| General assistant | `llama3.1` | `ollama pull llama3.1` |
| Code generation | `codellama` | `ollama pull codellama` |
| Quick prototyping | `llama3.2` | `ollama pull llama3.2` |
| Reasoning tasks | `llama3.1` | `ollama pull llama3.1` |
| Multilingual | `qwen2.5` | `ollama pull qwen2.5` |

---

## See Also

- [Configuration Guide](./configuration.md) — Full configuration reference
- [Environment Setup](./environment-setup.md) — Detailed installation guide
- [Getting Started](./getting-started.md) — First-time setup walkthrough
- [LiteLLM Ollama Docs](https://docs.litellm.ai/docs/providers/ollama) — LiteLLM's Ollama provider reference
