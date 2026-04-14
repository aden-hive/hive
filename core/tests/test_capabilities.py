"""Tests for LLM model capability checks."""

from __future__ import annotations

import pytest

from framework.llm.capabilities import filter_tools_for_model, supports_image_tool_results
from framework.llm.provider import Tool


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


class TestFilterToolsForModel:
    """Verify ``filter_tools_for_model`` — the real helper used by AgentLoop."""

    def test_hides_image_tool_from_text_only_model(self):
        tools = [
            Tool(name="read_file", description="read a file"),
            Tool(name="browser_screenshot", description="take a screenshot", produces_image=True),
            Tool(name="browser_snapshot", description="get page content"),
        ]
        filtered, hidden = filter_tools_for_model(tools, "glm-5")
        names = [t.name for t in filtered]
        assert "browser_screenshot" not in names
        assert "read_file" in names
        assert "browser_snapshot" in names
        assert hidden == ["browser_screenshot"]

    def test_keeps_image_tool_for_vision_model(self):
        tools = [
            Tool(name="read_file", description="read a file"),
            Tool(name="browser_screenshot", description="take a screenshot", produces_image=True),
        ]
        filtered, hidden = filter_tools_for_model(tools, "claude-sonnet-4-20250514")
        assert {t.name for t in filtered} == {"read_file", "browser_screenshot"}
        assert hidden == []

    def test_default_tools_are_not_filtered(self):
        """Tools without produces_image (default False) are kept for all models."""
        tools = [
            Tool(name="read_file", description="read a file"),
            Tool(name="web_search", description="search the web"),
        ]
        text_only, text_hidden = filter_tools_for_model(tools, "glm-5")
        vision, vision_hidden = filter_tools_for_model(tools, "gpt-4o")
        assert len(text_only) == 2 and text_hidden == []
        assert len(vision) == 2 and vision_hidden == []

    def test_empty_model_string_returns_tools_unchanged(self):
        """Guards the ctx.llm-missing path where model is empty."""
        tools = [
            Tool(name="browser_screenshot", description="", produces_image=True),
        ]
        filtered, hidden = filter_tools_for_model(tools, "")
        assert len(filtered) == 1
        assert hidden == []

    def test_returned_list_is_a_copy(self):
        """Caller should be free to mutate the filtered list without affecting input."""
        tools = [Tool(name="read_file", description="")]
        filtered, _ = filter_tools_for_model(tools, "gpt-4o")
        filtered.append(Tool(name="extra", description=""))
        assert len(tools) == 1
