# 🐝 Hive Agent v0.10.5: Cache-Aware Cost + New Frontier Models

> A patch release with two big practical wins: real prompt-cache hits across OpenRouter routes (and the cost numbers to prove it), plus first-class entries for GPT-5.5, DeepSeek V4 Pro/Flash, and GLM-5.1.

---

## ✨ Highlights

### 💸 Huge cost cut from prompt caching

v0.10.4 made the system prompt static so providers could cache it. v0.10.5 actually collects on that work.

- **`cache_control` now propagates through OpenRouter** for the sub-providers whose upstream APIs honor it: `openrouter/anthropic/*`, `openrouter/google/gemini-*`, `openrouter/z-ai/glm*`, and `openrouter/minimax/*`. Direct Anthropic / Bedrock / Vertex routes already worked; OpenRouter routes were silently no-op'ing the cache marker before.
- **Cache-token accounting is unified across providers.** A single `_extract_cache_tokens` helper now reads OpenAI-shape `prompt_tokens_details.cached_tokens`, Anthropic-raw `cache_read_input_tokens`, and OpenRouter's normalized `cache_write_tokens` / `cache_creation_input_tokens` — and surfaces both **cache-read** and **cache-creation** counts (subsets of the input total, never double-counted).
- **Streaming cache tokens no longer get dropped.** LiteLLM's `calculate_total_usage` aggregates token totals but discards `prompt_tokens_details`; the stream path now reaches back into the most recent chunk to recover cached/cache-creation counts so the FinishEvent is accurate.
- **Cost is reported in USD, not just tokens.** Every `LLMResponse` and `FinishEvent` now carries `cost_usd`. The extractor consults four sources in priority order: native `usage.cost` → LiteLLM `_hidden_params.response_cost` → `litellm.completion_cost` → curated catalog pricing — so models LiteLLM doesn't price (GLM, Kimi, MiniMax, DeepSeek V4) still get accurate numbers via the catalog fallback.
- **Persistent cost tracking** — the cost number now flows through the event bus to the chat panel and queen DM, and is persisted across sessions instead of resetting on reload.

The combined effect: on a long Claude Sonnet / Opus session routed through OpenRouter, the static system prefix is now a cache hit on every turn after the first, and the panel shows you the dollar savings turn-by-turn.

### 🧠 New frontier models

- **GPT-5.5** is now the OpenAI default — frontier coding + reasoning, 128k output / 1.05M context, vision-capable.
- **DeepSeek V4 Pro** and **DeepSeek V4 Flash** replace `deepseek-chat`. Both ship with **1M context**, **384k max output**, and full cache-read pricing (Pro: $1.74 / $3.48 / $0.145 per Mtok; Flash: $0.14 / $0.28 / $0.028). `deepseek-reasoner` is marked legacy.
- **GLM-5.1** replaces `GLM-5` with cache-read pricing wired in.
- **Catalog pricing schema** — every model can now declare `pricing_usd_per_mtok` with optional `cache_read` and `cache_creation` rates; validated on load.
- **`supports_vision` flag** added to every model in the catalog and consulted by the new vision-fallback path so non-vision models can still receive image inputs via captioning.

---

## 🆕 What's New

### Cost & Cache

- **`cache_control` for OpenRouter sub-providers** — Anthropic, Gemini, GLM, MiniMax routes now mark the static system prefix as ephemeral cache. (@RichardTang-Aden)
- **`_extract_cache_tokens` helper** — single reader for OpenAI / Anthropic / OpenRouter cache-token shapes; returns `(cache_read, cache_creation)`. (@RichardTang-Aden)
- **Catalog pricing fallback** — `_cost_from_catalog_pricing` and `_cost_from_tokens` compute USD from `pricing_usd_per_mtok` when LiteLLM's catalog has no entry. (@RichardTang-Aden)
- **Streaming usage recovery** — pull cache-token details from the last usage-bearing chunk after `calculate_total_usage` strips them. (@RichardTang-Aden)
- **`cost_usd`, `cached_tokens`, `cache_creation_tokens`** added to `LLMResponse`, `FinishEvent`, and the stream-event bus. (@RichardTang-Aden)
- **Persistent cost tracking** — costs survive session reload and surface in `ChatPanel` and `queen-dm`. (@RichardTang-Aden)

### Models & Catalog

- **GPT-5.5** as the new OpenAI default with 1.05M context + native pricing. (@RichardTang-Aden)
- **DeepSeek V4 Pro / Flash** with 1M context, 384k output, and cache-read pricing. (@RichardTang-Aden)
- **GLM-5.1** replaces GLM-5; cache-read pricing wired. (@RichardTang-Aden)
- **`pricing_usd_per_mtok` schema** — validated `input` / `output` / `cache_read` / `cache_creation` per model. (@RichardTang-Aden)
- **`supports_vision` flag** populated for every catalog entry; queried by the new vision-fallback path. (@RichardTang-Aden)
- **`get_model_pricing` / `model_supports_vision`** helpers exposed from `framework.llm.model_catalog`. (@RichardTang-Aden)

### Vision & Agent Loop

- **Image vision fallback** — `framework.agent_loop.internals.vision_fallback` captions images for non-vision models so the same conversation works regardless of provider capability. (@TimothyZhang7)
- **Hybrid compaction buffer** — context compaction now combines a fixed token reserve with a ratio-of-context buffer instead of one or the other. (@RichardTang-Aden)

### Frontend

- **Configuration UI redesign** — refreshed sidebar, prompt library, skills library, and tools editor. (@vincentjiang777)
- **Cost + token usage in chat** — `ChatPanel` and `queen-dm` show running token consumption and USD cost per session. (@RichardTang-Aden)

### Tests

- `test_litellm_provider.py` (+448 lines) covering cache-token extraction, cost-extraction priority order, OpenRouter compat-mode cache wiring, and streaming usage recovery.
- `test_model_catalog.py` extended for the new pricing schema and `supports_vision` flag.
- `test_event_bus.py` / `test_stream_events.py` extended for the new cost + cache fields.

---

## 🐛 Bug Fixes

- **Vision caption** — fix incorrect caption attachment in the vision-fallback path. (@TimothyZhang7)
- **Colony-fork test flake** — drain background fork tasks before asserting on colony-spawn artifacts. (@RichardTang-Aden)

---

## 🚀 Upgrading from v0.10.4

No migration. Pull `main` at `v0.10.5` and restart Hive — existing `~/.hive/` profiles, queens, colonies, and sessions keep working.

Two things to know:

1. **Default DeepSeek model changed** from `deepseek-chat` to `deepseek-v4-pro`. If a queen is pinned to `deepseek-chat`, that id is gone from the catalog — pick `deepseek-v4-pro` or `deepseek-v4-flash`.
2. **Default OpenAI model changed** from `gpt-5.4` to `gpt-5.5`. `gpt-5.4` stays in the catalog as the previous-flagship option.

Cache the prompts. 🐝
