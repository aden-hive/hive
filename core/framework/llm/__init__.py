"""LLM provider abstraction."""

from framework.llm.provider import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse"]

try:
    from framework.llm.anthropic import AnthropicProvider
    __all__.append("AnthropicProvider")
except ImportError:
    pass

try:
    from framework.llm.litellm import LiteLLMProvider
    __all__.append("LiteLLMProvider")
except ImportError:
    pass
