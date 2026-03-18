"""Model capability checks for LLM providers."""

from __future__ import annotations

# Prefixes of models/providers known to NOT support image content blocks
# inside tool result messages.  We use a deny-list (rather than an allow-list)
# because most OpenAI-compatible providers pass content lists through to the
# API unchanged — only a few are known to silently strip or break on images.
_IMAGE_TOOL_RESULT_DENY_PREFIXES: tuple[str, ...] = (
    # DeepSeek: LiteLLM explicitly flattens all content lists to strings,
    # silently dropping image blocks.
    "deepseek/",
    "deepseek-",
    # Local model providers: most models lack vision support, and those that
    # do typically handle images in user messages only, not tool results.
    "ollama/",
    "ollama_chat/",
    "lm_studio/",
    "vllm/",
    "llamacpp/",
    # Cerebras: no known vision/multimodal support.
    "cerebras/",
)


def supports_image_tool_results(model: str) -> bool:
    """Return whether *model* can receive image content in tool result messages.

    Models on the deny-list are known to either silently strip images or lack
    vision support entirely.  Everything else is assumed to work (OpenAI,
    Anthropic, Gemini, Mistral, Groq, etc. all handle it correctly via LiteLLM).
    """
    model_lower = model.lower()
    return not any(model_lower.startswith(prefix) for prefix in _IMAGE_TOOL_RESULT_DENY_PREFIXES)
