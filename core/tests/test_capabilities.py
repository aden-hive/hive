"""Tests for LLM model capability checks."""

from __future__ import annotations

import pytest

from framework.llm.capabilities import supports_image_tool_results


class TestSupportsImageToolResults:
    """Verify the deny-list correctly identifies models that can't handle images."""

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "openai/gpt-4o",
            "anthropic/claude-sonnet-4-20250514",
            "claude-haiku-4-5-20251001",
            "gemini/gemini-1.5-pro",
            "google/gemini-1.5-flash",
            "mistral/mistral-large",
            "groq/llama3-70b",
            "together/meta-llama/Llama-3-70b",
            "fireworks_ai/llama-v3-70b",
            "azure/gpt-4o",
            "kimi/claude-sonnet-4-20250514",
            "hive/claude-sonnet-4-20250514",
        ],
    )
    def test_supported_models(self, model: str):
        assert supports_image_tool_results(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "deepseek/deepseek-chat",
            "deepseek/deepseek-coder",
            "deepseek-chat",
            "deepseek-reasoner",
            "ollama/llama3",
            "ollama/mistral",
            "ollama_chat/llama3",
            "lm_studio/my-model",
            "vllm/meta-llama/Llama-3-70b",
            "llamacpp/model",
            "cerebras/llama3-70b",
        ],
    )
    def test_unsupported_models(self, model: str):
        assert supports_image_tool_results(model) is False

    def test_case_insensitive(self):
        assert supports_image_tool_results("DeepSeek/deepseek-chat") is False
        assert supports_image_tool_results("OLLAMA/llama3") is False
        assert supports_image_tool_results("GPT-4o") is True
