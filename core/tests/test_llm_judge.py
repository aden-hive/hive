"""
Unit tests for the LLMJudge with configurable LLM provider.

Tests cover:
- Fallback behavior (no provider, uses LiteLLM-backed provider)
- Custom LLM provider injection
- Response parsing (JSON, markdown code blocks)
- Error handling
"""

from unittest.mock import MagicMock

import pytest

from framework.llm.provider import LLMProvider, LLMResponse
from framework.testing.llm_judge import LLMJudge

# ============================================================================
# Mock LLM Provider
# ============================================================================


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, response_content: str = '{"passes": true, "explanation": "Test passed"}'):
        self.response_content = response_content
        self.complete_calls = []

    def complete(
        self,
        messages,
        system="",
        tools=None,
        max_tokens=1024,
        response_format=None,
        json_mode=False,
        max_retries=None,
    ):
        self.complete_calls.append(
            {
                "messages": messages,
                "system": system,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            }
        )
        return LLMResponse(
            content=self.response_content,
            model="mock-model",
            input_tokens=100,
            output_tokens=50,
        )

    def complete_with_tools(self, messages, system, tools, tool_executor, max_iterations=10):
        raise NotImplementedError("Tool use not needed for judge tests")


# ============================================================================
# LLMJudge Tests - Custom Provider
# ============================================================================


class TestLLMJudgeWithProvider:
    """Tests for LLMJudge with custom LLM provider."""

    def test_init_with_provider(self):
        """Test initialization with a custom LLM provider."""
        provider = MockLLMProvider()
        judge = LLMJudge(llm_provider=provider)

        assert judge._provider is provider
        assert judge._client is None

    def test_evaluate_uses_provider(self):
        """Test that evaluate() uses the injected provider."""
        provider = MockLLMProvider(
            response_content='{"passes": true, "explanation": "Summary is accurate"}'
        )
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="no-hallucination",
            source_document="The sky is blue.",
            summary="The sky is blue.",
            criteria="Summary must only contain facts from source",
        )

        assert result["passes"] is True
        assert result["explanation"] == "Summary is accurate"
        assert len(provider.complete_calls) == 1

    def test_evaluate_passes_correct_arguments(self):
        """Test that evaluate() passes correct arguments to provider."""
        provider = MockLLMProvider()
        judge = LLMJudge(llm_provider=provider)

        judge.evaluate(
            constraint="test-constraint",
            source_document="Source text",
            summary="Summary text",
            criteria="Test criteria",
        )

        call = provider.complete_calls[0]
        assert call["max_tokens"] == 500
        assert call["json_mode"] is True
        assert call["system"] == ""
        assert len(call["messages"]) == 1
        assert call["messages"][0]["role"] == "user"

        # Check prompt content
        prompt = call["messages"][0]["content"]
        assert "test-constraint" in prompt
        assert "Source text" in prompt
        assert "Summary text" in prompt
        assert "Test criteria" in prompt

    def test_evaluate_failing_result(self):
        """Test evaluation that returns a failing result."""
        provider = MockLLMProvider(
            response_content='{"passes": false, "explanation": "Summary has hallucinated facts"}'
        )
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="no-hallucination",
            source_document="The sky is blue.",
            summary="The sky is green and has rainbows.",
            criteria="Summary must only contain facts from source",
        )

        assert result["passes"] is False
        assert "hallucinated" in result["explanation"]


class TestLLMJudgeResponseParsing:
    """Tests for LLMJudge response parsing."""

    def test_parse_plain_json(self):
        """Test parsing plain JSON response."""
        provider = MockLLMProvider(response_content='{"passes": true, "explanation": "OK"}')
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="test", source_document="doc", summary="sum", criteria="crit"
        )

        assert result["passes"] is True
        assert result["explanation"] == "OK"

    def test_parse_json_in_markdown_code_block(self):
        """Test parsing JSON wrapped in markdown code block."""
        provider = MockLLMProvider(
            response_content='```json\n{"passes": false, "explanation": "Failed"}\n```'
        )
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="test", source_document="doc", summary="sum", criteria="crit"
        )

        assert result["passes"] is False
        assert result["explanation"] == "Failed"

    def test_parse_json_in_plain_code_block(self):
        """Test parsing JSON wrapped in plain code block (no json label)."""
        provider = MockLLMProvider(
            response_content='```\n{"passes": true, "explanation": "Passed"}\n```'
        )
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="test", source_document="doc", summary="sum", criteria="crit"
        )

        assert result["passes"] is True
        assert result["explanation"] == "Passed"

    def test_parse_response_with_whitespace(self):
        """Test parsing response with extra whitespace."""
        provider = MockLLMProvider(
            response_content='\n  {"passes": true, "explanation": "Clean"}  \n'
        )
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="test", source_document="doc", summary="sum", criteria="crit"
        )

        assert result["passes"] is True

    def test_default_explanation_when_missing(self):
        """Test that default explanation is used when not provided."""
        provider = MockLLMProvider(response_content='{"passes": true}')
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="test", source_document="doc", summary="sum", criteria="crit"
        )

        assert result["passes"] is True
        assert result["explanation"] == "No explanation provided"

    def test_passes_coerced_to_bool(self):
        """Test that passes value is coerced to boolean."""
        # Test truthy string
        provider = MockLLMProvider(response_content='{"passes": "yes", "explanation": "OK"}')
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="test", source_document="doc", summary="sum", criteria="crit"
        )

        assert result["passes"] is True

    def test_passes_false_when_missing(self):
        """Test that passes defaults to False when not in response."""
        provider = MockLLMProvider(response_content='{"explanation": "No pass key"}')
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="test", source_document="doc", summary="sum", criteria="crit"
        )

        assert result["passes"] is False


class TestLLMJudgeErrorHandling:
    """Tests for LLMJudge error handling."""

    def test_invalid_json_response(self):
        """Test handling of invalid JSON response."""
        provider = MockLLMProvider(response_content="This is not JSON")
        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="test", source_document="doc", summary="sum", criteria="crit"
        )

        assert result["passes"] is False
        assert "LLM judge error" in result["explanation"]

    def test_provider_raises_exception(self):
        """Test handling when provider raises an exception."""
        provider = MockLLMProvider()
        # Make complete() raise an exception
        provider.complete = MagicMock(side_effect=RuntimeError("API error"))

        judge = LLMJudge(llm_provider=provider)

        result = judge.evaluate(
            constraint="test", source_document="doc", summary="sum", criteria="crit"
        )

        assert result["passes"] is False
        assert "LLM judge error" in result["explanation"]
        assert "API error" in result["explanation"]


# ============================================================================
# LLMJudge Tests - Fallback and Legacy Client Behavior
# ============================================================================


class TestLLMJudgeFallbackBehavior:
    """Tests for LLMJudge fallback behavior when no provider is injected."""

    def test_init_without_provider(self):
        """Test initialization without a provider (backward compatible)."""
        judge = LLMJudge()

        assert judge._provider is None
        assert judge._client is None

    def test_evaluate_without_provider_uses_fallback_provider(self):
        """Test that evaluate() uses fallback provider when no provider is set."""
        judge = LLMJudge()
        fallback_provider = MockLLMProvider(
            response_content='{"passes": true, "explanation": "Fallback response"}'
        )
        judge._get_fallback_provider = MagicMock(return_value=fallback_provider)

        result = judge.evaluate(
            constraint="test",
            source_document="doc",
            summary="sum",
            criteria="crit",
        )

        assert result["passes"] is True
        assert result["explanation"] == "Fallback response"
        assert len(fallback_provider.complete_calls) == 1

    def test_legacy_client_used_only_when_mocked(self):
        """Test that legacy client path is used only when _get_client is mocked."""
        judge = LLMJudge()
        judge._get_fallback_provider = MagicMock(return_value=None)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"passes": true, "explanation": "Legacy"}')]
        mock_client.messages.create.return_value = mock_response
        judge._get_client = MagicMock(return_value=mock_client)

        result = judge.evaluate(
            constraint="test",
            source_document="doc",
            summary="sum",
            criteria="crit",
        )

        assert result["passes"] is True
        assert result["explanation"] == "Legacy"
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert call_kwargs["max_tokens"] == 500


# ============================================================================
# LLMJudge Integration Pattern Tests
# ============================================================================


class TestLLMJudgeIntegrationPatterns:
    """Tests demonstrating common usage patterns."""

    def test_with_anthropic_provider(self):
        """Test pattern: using LLMJudge with AnthropicProvider."""
        # This demonstrates the intended usage pattern without actually calling the API
        # Create a mock that behaves like AnthropicProvider
        mock_anthropic = MockLLMProvider(
            response_content='{"passes": true, "explanation": "Matches source"}'
        )

        judge = LLMJudge(llm_provider=mock_anthropic)

        result = judge.evaluate(
            constraint="factual-accuracy",
            source_document="Python was created by Guido van Rossum.",
            summary="Python's creator is Guido van Rossum.",
            criteria="Summary must be factually accurate",
        )

        assert result["passes"] is True

    def test_with_multiple_evaluations(self):
        """Test pattern: running multiple evaluations with same provider."""
        provider = MockLLMProvider()
        judge = LLMJudge(llm_provider=provider)

        # Run multiple evaluations
        for i in range(3):
            judge.evaluate(
                constraint=f"constraint_{i}",
                source_document="Source",
                summary="Summary",
                criteria="Criteria",
            )

        # Provider should have been called 3 times
        assert len(provider.complete_calls) == 3

    def test_provider_reuse_across_judges(self):
        """Test pattern: sharing a provider across multiple judges."""
        shared_provider = MockLLMProvider()

        judge1 = LLMJudge(llm_provider=shared_provider)
        judge2 = LLMJudge(llm_provider=shared_provider)

        judge1.evaluate(constraint="c1", source_document="d1", summary="s1", criteria="cr1")
        judge2.evaluate(constraint="c2", source_document="d2", summary="s2", criteria="cr2")

        # Both judges should use the same provider
        assert len(shared_provider.complete_calls) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
