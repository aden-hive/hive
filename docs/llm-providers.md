# LLM Providers: Selection, Error Handling, and Runtime Switching

This page describes how Hive picks an LLM provider, what happens when a call fails, and how the model is
switched while Hive is running. It describes current behavior, verified against `core/framework/llm/`,
`core/framework/config.py` and `core/framework/server/`. For the configuration file itself, see
[Configuration](configuration.md).

## Provider classes

All providers implement the abstract `LLMProvider` (`framework/llm/provider.py`): `complete()` (sync),
`acomplete()` (async; the default offloads `complete()` to a thread) and `stream()` (async iterator of
`StreamEvent`s; the default wraps `acomplete()` in synthetic events).

| Class | File | Role |
|---|---|---|
| `LiteLLMProvider` | `llm/litellm.py` | The main provider. Delegates to [LiteLLM](https://docs.litellm.ai/docs/providers), so it serves any provider LiteLLM supports. Owns retries, key rotation and `reconfigure()`. |
| `AnthropicProvider` | `llm/anthropic.py` | Backward-compatible wrapper. Holds a `LiteLLMProvider` internally and forwards `complete()`/`acomplete()` to it. Requires an Anthropic key (argument, credential store, or `ANTHROPIC_API_KEY`) and raises `ValueError` without one. |
| `AntigravityProvider` | `llm/antigravity.py` | Used instead of LiteLLM when the Antigravity subscription is enabled (`use_antigravity_subscription`). |
| `MockLLMProvider` | `llm/mock.py` | No network calls; for tests and structure-only runs. |

`framework.llm` exports `LLMProvider`, `LLMResponse`, the stream event types, and (when their dependencies import)
`AnthropicProvider`, `LiteLLMProvider` and `MockLLMProvider`.

## How the provider and model are selected

The server builds providers in `SessionManager.build_llm()` and `build_worker_llm()`
(`framework/server/session_manager.py`).

1. **Which model.** `get_preferred_model()` reads `llm.provider` and `llm.model` from `~/.hive/configuration.json`
   and joins them as `"<provider>/<model>"`. If either is missing it falls back to `anthropic/claude-sonnet-5-5`.
   An explicit model passed to `build_llm()` (or the one set by a model switch) wins over the file.
2. **Which class.** If `llm.use_antigravity_subscription` is true, `AntigravityProvider` is used. Otherwise
   `LiteLLMProvider` is used, and LiteLLM picks the vendor from the model string (`anthropic/...`,
   `openai/...`, `ollama/...`, and so on). Hive rewrites `hive/` and `kimi/` model names to LiteLLM's
   Anthropic-compatible route with the right base URL, and adds the `ollama_chat/` prefix to Ollama models.
3. **Which key** (`get_api_key()` in `config.py`), first match wins:
   1. the key of a named endpoint, when the main model is served from one (`model_endpoints`);
   2. the `llm.api_keys` list (a key pool; the first key is the default);
   3. a literal `llm.api_key`;
   4. a Claude Code, Codex, Kimi Code or Antigravity subscription token, when enabled;
   5. the encrypted credential store (needs `HIVE_CREDENTIAL_KEY`);
   6. the environment variable named in `llm.api_key_env_var`.

   The key is also re-resolved before every call through `api_key_resolver`, so a refreshed credential is
   picked up without rebuilding the provider.
4. **Workers.** `worker_llm` (with its own `get_worker_*` accessors) gives workers a separate model. When it is not
   set, `build_worker_llm()` returns `None` and workers share the main provider. A queen with a `queen_llm` entry
   uses that instead of the main model.

Several keys can be rotated by setting `llm.api_keys`; see [Errors](#errors-and-retries) for how rotation
interacts with rate limits.

## Errors and retries

Retry limits are constants in `llm/litellm.py`.

| Situation | Behavior |
|---|---|
| HTTP 429 (`RateLimitError`) | Retried up to `RATE_LIMIT_MAX_RETRIES` (10) times. The delay comes from the server's `retry-after`/`retry-after-ms` header when present, otherwise `2 * 2^attempt` seconds with jitter, capped at `RATE_LIMIT_MAX_DELAY` (120 s). After the last attempt the exception is raised (`complete`/`acomplete`) or a non-recoverable `StreamErrorEvent` with `error_type="rate_limit"` is yielded (`stream`). |
| 429 with a key pool | The rate-limited key is put on a 60 s cooldown and the next healthy key is used immediately, with no sleep. If every key is cooling down, the one that recovers soonest is used. |
| Empty response (HTTP 200, no text and no tool calls) | Retried up to `EMPTY_RESPONSE_MAX_RETRIES` (3) times, then the empty response is returned to the caller. Not retried when the last message was from the assistant, or when `finish_reason` is `length` (raise `max_tokens` instead). The request is dumped to a file for debugging. |
| Empty stream | Retried up to `EMPTY_STREAM_MAX_RETRIES` (3) times with a 1 s delay, then returned empty for the agent loop to handle. |
| Transient stream errors (connection errors, timeouts, 5xx) | Retried up to `STREAM_TRANSIENT_MAX_RETRIES` (3) times. If they persist, a `StreamErrorEvent` with `recoverable=True` is yielded. |
| Permanent errors (auth 401/403, bad request, context window, 402 payment required) | Not retried. In `stream()` a `StreamErrorEvent` with `recoverable=False` is yielded. `error_type` is `"payment_required"` for 402, `"rate_limit"` for 429, otherwise `None`; `upstream_status` carries the HTTP status when known. |

Failed requests are dumped to `failed_requests/` under the Hive home directory (the newest 50 are kept) so a failure can be replayed.

Hive does **not** fall back to a different model or provider on its own. A failure after the retries above surfaces
to the caller (the agent loop, which decides whether to retry or stop) and you change the model yourself, as below.

## Switching the model at runtime

Hive can change the model of running sessions without a restart:

- **From the dashboard**: Configuration → Models. Picking a model applies at once to running chats, and a failure
  shows its reason.
- **From the API**: `PUT /api/config/llm` (`framework/server/routes_config.py`) updates the stored configuration and
  calls `_hot_swap_sessions()`, which walks every running session and colony and calls
  `LiteLLMProvider.reconfigure(model, api_key, api_base, extra_body=...)` on each. The provider object is shared
  by reference, so the next LLM call uses the new model, key and base URL. Queens with their own model
  (`queen_llm`) are skipped.

Switching by configuration file instead of code:

```json
{
  "llm": {
    "provider": "openai",
    "model": "gpt-4o",
    "api_key_env_var": "OPENAI_API_KEY"
  }
}
```

Edit `~/.hive/configuration.json` and restart (or switch from the dashboard to avoid the restart).

Switching in code:

```python
from framework.llm.litellm import LiteLLMProvider

llm = LiteLLMProvider(model="anthropic/claude-sonnet-5-5", api_key="sk-ant-...")
# ... later, the same object, now pointed at another model:
llm.reconfigure("openai/gpt-4o", api_key="sk-...")
```
