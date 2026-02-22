# Roadmap: First-Class Local LLM Support

Local LLMs (Ollama, vLLM, LM Studio, Llama.cpp) let developers run agents
entirely on their own hardware — no API keys, no cloud costs, full data privacy.
This roadmap tracks the work to make local models first-class citizens in the
Aden Agent Framework.

> [!IMPORTANT]
> Related: [Bug #3994](https://github.com/aden-hive/hive/issues/3994) —
> AgentRunner crashes with local LLMs,
> [Feature #5154](https://github.com/aden-hive/hive/issues/5154) —
> First-Class Local LLM Support.

---

## Supported Local Providers

| Prefix | Provider | Status |
|---|---|---|
| `ollama/` | [Ollama](https://ollama.com) | ✅ Supported |
| `ollama_chat/` | Ollama (chat mode) | ✅ Supported |
| `vllm/` | [vLLM](https://vllm.ai) | ✅ Supported |
| `lm_studio/` | [LM Studio](https://lmstudio.ai) | ✅ Supported |
| `llamacpp/` | [Llama.cpp](https://github.com/ggerganov/llama.cpp) | ✅ Supported |

All of the above are recognized by `AgentRunner._is_local_model()` and
initialize `LiteLLMProvider` **without requiring an API key**.

---

## Phase 1: Core Support ✅

- [x] **Zero-config initialization** — `AgentRunner._setup()` detects local
  model prefixes and creates `LiteLLMProvider` without an API key
- [x] **`_is_local_model()` helper** — centralized check for all local
  provider prefixes, used by both `_setup()` and `_get_api_key_env_var()`
- [x] **No API key warnings** — `_get_api_key_env_var()` returns `None` for
  local models so no spurious "missing API key" warnings are shown

### Quick Start

```python
from pathlib import Path
from framework.runner import AgentRunner

# Just set the model — no API key, no env vars, no config needed
runner = AgentRunner.load(
    agent_path=Path("./my_agent"),
    model="ollama/llama3",     # or vllm/mistral, lm_studio/phi3, etc.
)
result = await runner.run({"query": "Hello!"})
```

---

## Phase 2: Enhanced Local Experience

- [ ] **Auto-detect local server** — ping `localhost:11434` (Ollama) or
  common ports to confirm the service is running before execution
- [ ] **Custom `api_base` from config** — read `api_base` per-provider from
  `~/.hive/configuration.json` for non-default ports/hosts
- [ ] **Connection health check** — pre-flight connectivity test with clear
  error message ("Ollama is not running — start it with `ollama serve`")
- [ ] **Model availability check** — verify the requested model is pulled
  locally (`ollama list`) before attempting completion

---

## Phase 3: Performance & DX

- [ ] **Local model benchmarking** — built-in timing for local inference to
  help users compare model speed
- [ ] **GPU/CPU detection** — log available hardware (CUDA, Metal, CPU) to
  help users optimize model selection
- [ ] **Model recommendation engine** — suggest the best local model based
  on agent complexity and available hardware
- [ ] **Offline mode** — graceful fallback when no internet is available,
  using only local models and cached tools

---

## Phase 4: Advanced Local Features

- [ ] **Model management CLI** — `hive model pull ollama/llama3`,
  `hive model list` for managing local models from the Hive CLI
- [ ] **Hybrid routing** — route simple tasks to local models and complex
  tasks to cloud models automatically based on configurable rules
- [ ] **Local model fine-tuning integration** — support for LoRA adapters
  and custom fine-tuned local models
- [ ] **Multi-GPU support** — distribute inference across multiple GPUs
  for larger local models (vLLM, Llama.cpp)

---

## Adding a New Local Provider

To add support for a new local LLM provider:

1. Add the provider prefix to `LOCAL_PREFIXES` in
   [`AgentRunner._is_local_model()`](file:///c:/Users/RAHUL/hive_aden/memo/hive/core/framework/runner/runner.py)
2. That's it — `_setup()` and `_get_api_key_env_var()` both delegate to
   `_is_local_model()`, so the new provider will be auto-detected

```python
# framework/runner/runner.py — AgentRunner._is_local_model()
LOCAL_PREFIXES = (
    "ollama/",
    "ollama_chat/",
    "vllm/",
    "lm_studio/",
    "llamacpp/",
    "your_provider/",  # ← add here
)
```

> [!TIP]
> The provider must be supported by [LiteLLM](https://docs.litellm.ai/docs/providers)
> for completion calls to work. Check LiteLLM's provider list before adding.
