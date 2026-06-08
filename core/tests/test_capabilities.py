"""Tests for LLM model capability checks."""

from __future__ import annotations

import pytest

from framework.llm.capabilities import filter_tools_for_model, supports_image_tool_results
from framework.llm.provider import Tool


class TestSupportsImageToolResults:
    """Verify catalog-driven vision capability checks."""

    @pytest.mark.parametrize(
        "model",
        [
            # Catalog entries with supports_vision=true
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-5-20250929",
            "claude-opus-4-6",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gemini-3-flash-preview",
            "kimi-k2.5",
            # Provider-prefixed catalog entries
            "openrouter/openai/gpt-5.4",
            "openrouter/anthropic/claude-sonnet-4.6",
            # Unknown models default to True (hosted frontier assumption)
            "some-future-model",
            "azure/gpt-5",
        ],
    )
    def test_supported_models(self, model: str):
        assert supports_image_tool_results(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            # Catalog entries with supports_vision=false
            "deepseek-reasoner",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "glm-5.1",
            "queen",
            "MiniMax-M2.7",
            "codestral-2508",
            "llama-3.3-70b-versatile",
            # Provider-prefixed forms resolve to the same catalog entry
            "deepseek/deepseek-reasoner",
            "hive/glm-5.1",
            "groq/llama-3.3-70b-versatile",
        ],
    )
    def test_unsupported_models(self, model: str):
        assert supports_image_tool_results(model) is False


class TestFilterToolsForModel:
    """Verify ``filter_tools_for_model`` — the real helper used by AgentLoop."""

    def test_hides_image_tool_from_text_only_model(self):
        tools = [
            Tool(name="read_file", description="read a file"),
            Tool(name="browser_screenshot", description="take a screenshot", produces_image=True),
            Tool(name="browser_snapshot", description="get page content"),
        ]
        filtered, hidden = filter_tools_for_model(tools, "glm-5.1")
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
        filtered, hidden = filter_tools_for_model(tools, "claude-sonnet-4-5-20250929")
        assert {t.name for t in filtered} == {"read_file", "browser_screenshot"}
        assert hidden == []

    def test_default_tools_are_not_filtered(self):
        """Tools without produces_image (default False) are kept for all models."""
        tools = [
            Tool(name="read_file", description="read a file"),
            Tool(name="web_search", description="search the web"),
        ]
        text_only, text_hidden = filter_tools_for_model(tools, "glm-5.1")
        vision, vision_hidden = filter_tools_for_model(tools, "claude-sonnet-4-5-20250929")
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
