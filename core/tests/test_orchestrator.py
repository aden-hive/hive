"""Tests for AgentOrchestrator LiteLLM integration.

Run with:
    cd core
    pytest tests/test_orchestrator.py -v
"""

from unittest.mock import Mock, patch

from framework.llm.provider import LLMProvider
from framework.llm.litellm import LiteLLMProvider
from framework.runner.orchestrator import AgentOrchestrator


class TestOrchestratorLLMInitialization:
    """Test AgentOrchestrator LLM provider initialization."""

    def test_auto_creates_litellm_provider_when_no_llm_passed(self):
        """Test that LiteLLMProvider is auto-created when no llm is passed."""
        with patch.object(LiteLLMProvider, '__init__', return_value=None) as mock_init:
            orchestrator = AgentOrchestrator()

            mock_init.assert_called_once_with(model="claude-sonnet-4-20250514")
            assert orchestrator._llm is not None

    def test_uses_custom_model_parameter(self):
        """Test that custom model parameter is passed to LiteLLMProvider."""
        with patch.object(LiteLLMProvider, '__init__', return_value=None) as mock_init:
            orchestrator = AgentOrchestrator(model="gpt-4o")

            mock_init.assert_called_once_with(model="gpt-4o")

    def test_supports_openai_model_names(self):
        """Test that OpenAI model names are supported."""
        with patch.object(LiteLLMProvider, '__init__', return_value=None) as mock_init:
            orchestrator = AgentOrchestrator(model="gpt-4o-mini")

            mock_init.assert_called_once_with(model="gpt-4o-mini")
            assert orchestrator._model == "gpt-4o-mini"

    def test_supports_anthropic_model_names(self):
        """Test that Anthropic model names are supported."""
        with patch.object(LiteLLMProvider, '__init__', return_value=None) as mock_init:
            orchestrator = AgentOrchestrator(model="claude-3-haiku-20240307")

            mock_init.assert_called_once_with(model="claude-3-haiku-20240307")
            assert orchestrator._model == "claude-3-haiku-20240307"

    def test_skips_auto_creation_when_llm_passed(self):
        """Test that auto-creation is skipped when llm is explicitly passed."""
        mock_llm = Mock(spec=LLMProvider)

        with patch.object(LiteLLMProvider, '__init__', return_value=None) as mock_init:
            orchestrator = AgentOrchestrator(llm=mock_llm)

            mock_init.assert_not_called()
            assert orchestrator._llm is mock_llm

    def test_model_attribute_stored_correctly(self):
        """Test that _model attribute is stored correctly."""
        with patch.object(LiteLLMProvider, '__init__', return_value=None):
            orchestrator = AgentOrchestrator(model="gemini/gemini-1.5-flash")

            assert orchestrator._model == "gemini/gemini-1.5-flash"


class TestOrchestratorLLMProviderType:
    """Test that orchestrator uses correct LLM provider type."""

    def test_llm_is_litellm_provider_instance(self):
        """Test that auto-created _llm is a LiteLLMProvider instance."""
        orchestrator = AgentOrchestrator()

        assert isinstance(orchestrator._llm, LiteLLMProvider)

    def test_llm_implements_llm_provider_interface(self):
        """Test that _llm implements LLMProvider interface."""
        orchestrator = AgentOrchestrator()

        assert isinstance(orchestrator._llm, LLMProvider)
        assert hasattr(orchestrator._llm, 'complete')
        assert hasattr(orchestrator._llm, 'complete_with_tools')
