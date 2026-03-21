"""Model capability checks for LLM providers."""

from __future__ import annotations

# Provider prefixes that are known to NOT support image content.
# These are checked against the full model string (e.g. "deepseek/deepseek-chat").
_IMAGE_DENY_PROVIDER_PREFIXES: tuple[str, ...] = (
    # DeepSeek: LiteLLM explicitly flattens all content lists to strings,
    # silently dropping image blocks.
    "deepseek/",
    "deepseek-",
    # Cerebras: no known vision/multimodal support.
    "cerebras/",
)

# Model name fragments (checked after stripping any "provider/" prefix) that
# indicate a text-only model regardless of which provider routes the request.
_IMAGE_DENY_MODEL_FRAGMENTS: tuple[str, ...] = (
    # ZAI / GLM family: GLM-5 and ZAI-GLM-4.x are text-only.
    # Accessed as "openai/glm-5", "cerebras/zai-glm-4.7", "glm-5", etc.
    "glm-",
    "zai-glm",
    # MiniMax M2.5: text-only, no vision.
    "minimax-text",
    "abab",
)


def _model_name(model: str) -> str:
    """Return the bare model name, stripping any 'provider/' prefix."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def supports_image_tool_results(model: str) -> bool:
    """Return whether *model* can receive image content in messages.

    Used to gate both tool-result image blocks and user-message images.
    Deny-list approach: everything is assumed capable unless explicitly listed.
    """
    model_lower = model.lower()
    if any(model_lower.startswith(p) for p in _IMAGE_DENY_PROVIDER_PREFIXES):
        return False
    model_name_lower = _model_name(model_lower)
    return not any(model_name_lower.startswith(f) for f in _IMAGE_DENY_MODEL_FRAGMENTS)
