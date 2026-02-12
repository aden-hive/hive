"""
Tests for LLM provider factory.

Tests multi-provider support for OpenAI, Anthropic, and Google.
"""

from unittest.mock import MagicMock, patch

import pytest

from framework.debugging.llm_provider import (
    _create_anthropic,
    _detect_provider,
    create_llm,
)


class TestProviderDetection:
    """Test automatic provider detection."""

    def test_detect_from_env_var(self, monkeypatch):
        """Should use HIVE_LLM_PROVIDER if set."""
        monkeypatch.setenv("HIVE_LLM_PROVIDER", "openai")
        assert _detect_provider() == "openai"

        monkeypatch.setenv("HIVE_LLM_PROVIDER", "anthropic")
        assert _detect_provider() == "anthropic"

        monkeypatch.setenv("HIVE_LLM_PROVIDER", "google")
        assert _detect_provider() == "google"

    def test_detect_from_openai_key(self, monkeypatch):
        """Should detect OpenAI when OPENAI_API_KEY is set."""
        monkeypatch.delenv("HIVE_LLM_PROVIDER", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert _detect_provider() == "openai"

    def test_detect_from_anthropic_key(self, monkeypatch):
        """Should detect Anthropic when ANTHROPIC_API_KEY is set."""
        monkeypatch.delenv("HIVE_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert _detect_provider() == "anthropic"

    def test_detect_from_google_key(self, monkeypatch):
        """Should detect Google when GOOGLE_API_KEY is set."""
        monkeypatch.delenv("HIVE_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        assert _detect_provider() == "google"

    def test_detect_no_provider(self, monkeypatch):
        """Should raise ValueError when no provider can be detected."""
        monkeypatch.delenv("HIVE_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        with pytest.raises(ValueError, match="No LLM provider configured"):
            _detect_provider()


class TestAnthropicProvider:
    """Test Anthropic provider creation (available in environment)."""

    @patch("langchain_anthropic.ChatAnthropic")
    def test_create_with_defaults(self, mock_chat, monkeypatch):
        """Should create Anthropic with default model and env API key."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_instance = MagicMock()
        mock_chat.return_value = mock_instance

        result = _create_anthropic(None, None, 0.0)

        mock_chat.assert_called_once_with(
            model="claude-3-5-sonnet-20241022", anthropic_api_key="sk-ant-test", temperature=0.0
        )
        assert result == mock_instance

    @patch("langchain_anthropic.ChatAnthropic")
    def test_create_with_custom_model(self, mock_chat, monkeypatch):
        """Should use custom model when provided."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_instance = MagicMock()
        mock_chat.return_value = mock_instance

        result = _create_anthropic("claude-3-opus-20240229", None, 0.7)

        mock_chat.assert_called_once_with(
            model="claude-3-opus-20240229", anthropic_api_key="sk-ant-test", temperature=0.7
        )
        assert result == mock_instance

    @patch("langchain_anthropic.ChatAnthropic")
    def test_create_with_explicit_key(self, mock_chat):
        """Should use explicit API key over env var."""
        mock_instance = MagicMock()
        mock_chat.return_value = mock_instance

        result = _create_anthropic(None, "sk-ant-explicit", 0.0)

        mock_chat.assert_called_once_with(
            model="claude-3-5-sonnet-20241022", anthropic_api_key="sk-ant-explicit", temperature=0.0
        )
        assert result == mock_instance

    def test_create_missing_key(self, monkeypatch):
        """Should raise ValueError when API key is missing."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with pytest.raises(ValueError, match="Anthropic API key required"):
            _create_anthropic(None, None, 0.0)


class TestCreateLLM:
    """Test main create_llm factory function."""

    @patch("framework.debugging.llm_provider._create_openai")
    def test_create_with_explicit_provider(self, mock_create, monkeypatch):
        """Should use explicit provider parameter."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_llm = MagicMock()
        mock_create.return_value = mock_llm

        result = create_llm(provider="openai", model="gpt-4-turbo")

        mock_create.assert_called_once_with("gpt-4-turbo", None, 0.0)
        assert result == mock_llm

    @patch("framework.debugging.llm_provider._create_anthropic")
    @patch("framework.debugging.llm_provider._detect_provider")
    def test_create_with_auto_detect(self, mock_detect, mock_create, monkeypatch):
        """Should auto-detect provider when not specified."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_detect.return_value = "anthropic"
        mock_llm = MagicMock()
        mock_create.return_value = mock_llm

        result = create_llm()

        mock_detect.assert_called_once()
        mock_create.assert_called_once_with(None, None, 0.0)
        assert result == mock_llm

    @patch("framework.debugging.llm_provider._create_google")
    def test_create_with_custom_temperature(self, mock_create, monkeypatch):
        """Should pass custom temperature to provider."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        mock_llm = MagicMock()
        mock_create.return_value = mock_llm

        result = create_llm(provider="google", temperature=0.8)

        mock_create.assert_called_once_with(None, None, 0.8)
        assert result == mock_llm

    def test_create_invalid_provider(self):
        """Should raise ValueError for invalid provider."""
        with pytest.raises(ValueError, match="Invalid provider"):
            create_llm(provider="invalid")  # type: ignore

    @patch("framework.debugging.llm_provider._create_openai")
    def test_create_with_api_key(self, mock_create):
        """Should pass explicit API key to provider."""
        mock_llm = MagicMock()
        mock_create.return_value = mock_llm

        result = create_llm(provider="openai", api_key="sk-explicit")

        mock_create.assert_called_once_with(None, "sk-explicit", 0.0)
        assert result == mock_llm
