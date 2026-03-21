"""Model capability checks for LLM providers.

Vision support rules are derived from official vendor documentation:
- ZAI (z.ai): docs.z.ai/guides/vlm — GLM-4.6V variants are vision; GLM-5/4.6/4.7 are text-only
- MiniMax: platform.minimax.io/docs — minimax-vl-01 is vision; M2.x are text-only
- DeepSeek: api-docs.deepseek.com — deepseek-vl2 is vision; chat/reasoner are text-only
- Cerebras: inference-docs.cerebras.ai — no vision models at all
- Groq: console.groq.com/docs/vision — vision capable; treat as supported by default
- Ollama/LM Studio/vLLM/llama.cpp: local runners denied by default; model names
  don't reliably indicate vision support, so users must configure explicitly
"""

from __future__ import annotations


def _model_name(model: str) -> str:
    """Return the bare model name after stripping any 'provider/' prefix."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


# Step 1: explicit vision allow-list — these always support images regardless
# of what the provider-level rules say.  Checked first so that e.g. glm-4.6v
# is allowed even though glm-4.6 is denied.
_VISION_ALLOW_BARE_PREFIXES: tuple[str, ...] = (
    # ZAI/GLM vision models (docs.z.ai/guides/vlm)
    "glm-4v",  # GLM-4V series (legacy)
    "glm-4.6v",  # GLM-4.6V, GLM-4.6V-flash, GLM-4.6V-flashx
    # DeepSeek vision models
    "deepseek-vl",  # deepseek-vl2, deepseek-vl2-small, deepseek-vl2-tiny
    # MiniMax vision model
    "minimax-vl",  # minimax-vl-01
)

# Step 2: provider-level deny — every model from this provider is text-only.
_TEXT_ONLY_PROVIDER_PREFIXES: tuple[str, ...] = (
    # Cerebras: inference-docs.cerebras.ai lists only text models
    "cerebras/",
    # Local runners: model names don't reliably indicate vision support
    "ollama/",
    "ollama_chat/",
    "lm_studio/",
    "vllm/",
    "llamacpp/",
)

# Step 3: per-model deny — text-only models within otherwise mixed providers.
# Matched against the bare model name (provider prefix stripped, lower-cased).
# The vision allow-list above is checked first, so vision variants of the same
# family are already handled before these deny patterns are reached.
_TEXT_ONLY_MODEL_BARE_PREFIXES: tuple[str, ...] = (
    # --- ZAI / GLM family ---
    # text-only: glm-5, glm-4.6, glm-4.7, glm-4.5, zai-glm-*
    # vision:    glm-4v, glm-4.6v (caught by allow-list above)
    "glm-5",
    "glm-4.6",  # bare glm-4.6 is text-only; glm-4.6v is caught by allow-list
    "glm-4.7",
    "glm-4.5",
    "zai-glm",
    # --- DeepSeek ---
    # text-only: deepseek-chat, deepseek-coder, deepseek-reasoner
    # vision:    deepseek-vl2 (caught by allow-list above)
    # Note: LiteLLM's deepseek handler may flatten content lists for some models;
    # VL models are allowed through and rely on LiteLLM's native VL support.
    "deepseek-chat",
    "deepseek-coder",
    "deepseek-reasoner",
    # --- MiniMax ---
    # text-only: minimax-m2.*, minimax-text-*, abab* (legacy)
    # vision:    minimax-vl-01 (caught by allow-list above)
    "minimax-m2",
    "minimax-text",
    "abab",
)


def supports_image_tool_results(model: str) -> bool:
    """Return whether *model* can receive image content in messages.

    Used to gate both user-message images and tool-result image blocks.

    Logic (checked in order):
    1. Vision allow-list  → True  (known vision model, skip all denies)
    2. Provider deny      → False (entire provider is text-only)
    3. Model deny         → False (specific text-only model within a mixed provider)
    4. Default            → True  (assume capable; unknown providers and models)
    """
    model_lower = model.lower()
    bare = _model_name(model_lower)

    # 1. Explicit vision allow — takes priority over all denies
    if any(bare.startswith(p) for p in _VISION_ALLOW_BARE_PREFIXES):
        return True

    # 2. Provider-level deny (all models from this provider are text-only)
    if any(model_lower.startswith(p) for p in _TEXT_ONLY_PROVIDER_PREFIXES):
        return False

    # 3. Per-model deny (text-only variants within mixed-capability families)
    if any(bare.startswith(p) for p in _TEXT_ONLY_MODEL_BARE_PREFIXES):
        return False

    # 5. Default: assume vision capable
    #    Covers: OpenAI, Anthropic, Google, Mistral, Kimi, and other hosted providers
    return True
