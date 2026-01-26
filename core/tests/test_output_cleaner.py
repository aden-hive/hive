"""
Tests for OutputCleaner provider auto-detection and configuration.

Tests cover:
- Provider auto-detection from environment variables
- Explicit configuration override
- Backward compatibility with Cerebras
- Graceful fallback when no provider available
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from framework.graph.output_cleaner import (
    CleansingConfig,
    OutputCleaner,
    ValidationResult,
    PROVIDER_CONFIG,
    _detect_provider,
)


class TestProviderDetection:
    """Tests for provider auto-detection logic."""

    def test_detect_provider_with_cerebras(self):
        """Test that Cerebras is detected first when available."""
        with patch.dict(os.environ, {"CEREBRAS_API_KEY": "test-cerebras-key"}, clear=False):
            api_key, model, name = _detect_provider()
            assert api_key == "test-cerebras-key"
            assert model == "cerebras/llama-3.3-70b"
            assert name == "Cerebras"

    def test_detect_provider_with_openai(self):
        """Test OpenAI detection when Cerebras/Groq not available."""
        env = {
            "OPENAI_API_KEY": "test-openai-key",
        }
        with patch.dict(os.environ, env, clear=True):
            api_key, model, name = _detect_provider()
            assert api_key == "test-openai-key"
            assert model == "gpt-4o-mini"
            assert name == "OpenAI"

    def test_detect_provider_with_anthropic(self):
        """Test Anthropic detection."""
        env = {
            "ANTHROPIC_API_KEY": "test-anthropic-key",
        }
        with patch.dict(os.environ, env, clear=True):
            api_key, model, name = _detect_provider()
            assert api_key == "test-anthropic-key"
            assert model == "claude-3-haiku-20240307"
            assert name == "Anthropic"

    def test_detect_provider_with_groq(self):
        """Test Groq detection (should be second priority)."""
        env = {
            "GROQ_API_KEY": "test-groq-key",
        }
        with patch.dict(os.environ, env, clear=True):
            api_key, model, name = _detect_provider()
            assert api_key == "test-groq-key"
            assert model == "groq/llama-3.3-70b-versatile"
            assert name == "Groq"

    def test_detect_provider_priority_order(self):
        """Test that providers are checked in priority order."""
        # When multiple keys are present, Cerebras should be selected first
        env = {
            "CEREBRAS_API_KEY": "cerebras-key",
            "OPENAI_API_KEY": "openai-key",
            "ANTHROPIC_API_KEY": "anthropic-key",
        }
        with patch.dict(os.environ, env, clear=True):
            api_key, model, name = _detect_provider()
            assert name == "Cerebras"
            assert api_key == "cerebras-key"

    def test_detect_provider_no_keys(self):
        """Test graceful handling when no API keys are set."""
        with patch.dict(os.environ, {}, clear=True):
            api_key, model, name = _detect_provider()
            assert api_key is None
            assert model is None
            assert name is None

    def test_provider_config_structure(self):
        """Test that PROVIDER_CONFIG has expected structure."""
        assert len(PROVIDER_CONFIG) >= 6  # At least 6 providers
        for env_var, model, name in PROVIDER_CONFIG:
            assert isinstance(env_var, str)
            assert isinstance(model, str)
            assert isinstance(name, str)
            assert env_var.endswith("_API_KEY") or env_var.endswith("_KEY")


class TestCleansingConfig:
    """Tests for CleansingConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CleansingConfig()
        assert config.enabled is True
        assert config.fast_model is None  # Auto-detect
        assert config.api_key is None  # Auto-detect
        assert config.max_retries == 2
        assert config.fallback_to_raw is True
        assert config.log_cleanings is True

    def test_explicit_config(self):
        """Test explicit configuration."""
        config = CleansingConfig(
            enabled=True,
            fast_model="gpt-4o-mini",
            api_key="my-api-key",
            max_retries=5,
        )
        assert config.fast_model == "gpt-4o-mini"
        assert config.api_key == "my-api-key"
        assert config.max_retries == 5

    def test_disabled_config(self):
        """Test disabled configuration."""
        config = CleansingConfig(enabled=False)
        assert config.enabled is False


class TestOutputCleanerInitialization:
    """Tests for OutputCleaner initialization logic."""

    def test_output_cleaner_with_provided_llm(self):
        """Test OutputCleaner uses provided LLM provider."""
        mock_llm = MagicMock()
        config = CleansingConfig()
        cleaner = OutputCleaner(config=config, llm_provider=mock_llm)
        assert cleaner.llm == mock_llm

    def test_output_cleaner_disabled(self):
        """Test OutputCleaner with disabled config."""
        config = CleansingConfig(enabled=False)
        cleaner = OutputCleaner(config=config)
        assert cleaner.llm is None

    def test_output_cleaner_no_provider_available(self):
        """Test graceful handling when no provider available."""
        config = CleansingConfig(enabled=True)
        with patch.dict(os.environ, {}, clear=True):
            # No API keys in environment, so _detect_provider returns None
            # This means LiteLLMProvider is never called
            cleaner = OutputCleaner(config=config)
            # Should not raise, just log warning and set llm to None
            assert cleaner.llm is None

    @patch("framework.llm.litellm.LiteLLMProvider")
    def test_output_cleaner_auto_detect_openai(self, mock_litellm_class):
        """Test auto-detection with OpenAI."""
        mock_llm_instance = MagicMock()
        mock_litellm_class.return_value = mock_llm_instance

        config = CleansingConfig(enabled=True)
        env = {"OPENAI_API_KEY": "test-openai-key"}

        with patch.dict(os.environ, env, clear=True):
            cleaner = OutputCleaner(config=config)

            # Verify LiteLLMProvider was created with correct args
            mock_litellm_class.assert_called_once_with(
                api_key="test-openai-key",
                model="gpt-4o-mini",
                temperature=0.0,
            )
            assert cleaner.llm == mock_llm_instance

    @patch("framework.llm.litellm.LiteLLMProvider")
    def test_output_cleaner_explicit_config(self, mock_litellm_class):
        """Test explicit configuration takes precedence."""
        mock_llm_instance = MagicMock()
        mock_litellm_class.return_value = mock_llm_instance

        config = CleansingConfig(
            enabled=True,
            fast_model="custom-model",
            api_key="custom-key",
        )

        # Even with OpenAI key in env, explicit config should be used
        env = {"OPENAI_API_KEY": "openai-key"}

        with patch.dict(os.environ, env, clear=True):
            cleaner = OutputCleaner(config=config)

            mock_litellm_class.assert_called_once_with(
                api_key="custom-key",
                model="custom-model",
                temperature=0.0,
            )

    @patch("framework.llm.litellm.LiteLLMProvider")
    def test_output_cleaner_model_override_with_auto_detect(self, mock_litellm_class):
        """Test model override with auto-detected provider."""
        mock_llm_instance = MagicMock()
        mock_litellm_class.return_value = mock_llm_instance

        # Specify model but not API key
        config = CleansingConfig(
            enabled=True,
            fast_model="gpt-4o",  # Override default model
        )

        env = {"OPENAI_API_KEY": "openai-key"}

        with patch.dict(os.environ, env, clear=True):
            cleaner = OutputCleaner(config=config)

            # Should use auto-detected key with overridden model
            mock_litellm_class.assert_called_once_with(
                api_key="openai-key",
                model="gpt-4o",  # Overridden
                temperature=0.0,
            )


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid_result(self):
        """Test valid validation result."""
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_invalid_result_with_errors(self):
        """Test invalid result with errors."""
        result = ValidationResult(
            valid=False,
            errors=["Missing key: 'name'", "Type mismatch"],
            warnings=["Large string value"],
        )
        assert result.valid is False
        assert len(result.errors) == 2
        assert len(result.warnings) == 1


class TestBackwardCompatibility:
    """Tests to ensure backward compatibility."""

    @patch("framework.llm.litellm.LiteLLMProvider")
    def test_cerebras_still_works(self, mock_litellm_class):
        """Test that existing Cerebras users are not affected."""
        mock_llm_instance = MagicMock()
        mock_litellm_class.return_value = mock_llm_instance

        config = CleansingConfig(enabled=True)
        env = {"CEREBRAS_API_KEY": "cerebras-key"}

        with patch.dict(os.environ, env, clear=True):
            cleaner = OutputCleaner(config=config)

            # Should use Cerebras (first priority)
            mock_litellm_class.assert_called_once_with(
                api_key="cerebras-key",
                model="cerebras/llama-3.3-70b",
                temperature=0.0,
            )

    def test_default_config_no_breaking_changes(self):
        """Test that default config hasn't changed behavior."""
        config = CleansingConfig()
        # enabled should still default to True
        assert config.enabled is True
        # These behavior-affecting defaults should remain
        assert config.fallback_to_raw is True
        assert config.max_retries == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
