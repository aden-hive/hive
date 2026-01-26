"""
Tests for NodeResult.to_summary() async method.

Tests cover:
- Async behavior (non-blocking)
- Fallback when no API key
- Fallback on API error
- Timeout handling
- Success/failure message formatting
"""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from framework.graph.node import NodeResult


class TestNodeResultToSummary:
    """Tests for NodeResult.to_summary() async method."""

    @pytest.mark.asyncio
    async def test_failed_result_returns_error_message(self):
        """Failed results should return error message without API call."""
        result = NodeResult(
            success=False,
            error="Something went wrong",
            output={},
            tokens_used=0,
            latency_ms=0,
        )

        summary = await result.to_summary()

        assert "❌ Failed:" in summary
        assert "Something went wrong" in summary

    @pytest.mark.asyncio
    async def test_empty_output_returns_completed_message(self):
        """Empty output should return simple completed message."""
        result = NodeResult(
            success=True,
            error=None,
            output={},
            tokens_used=10,
            latency_ms=100,
        )

        summary = await result.to_summary()

        assert "✓ Completed (no output)" in summary

    @pytest.mark.asyncio
    async def test_fallback_when_no_api_key(self):
        """Should use fallback summary when ANTHROPIC_API_KEY not set."""
        result = NodeResult(
            success=True,
            error=None,
            output={"key1": "value1", "key2": "value2"},
            tokens_used=10,
            latency_ms=100,
        )

        with patch.dict("os.environ", {}, clear=True):
            summary = await result.to_summary()

        assert "✓ Completed with 2 outputs:" in summary
        assert "key1" in summary

    @pytest.mark.asyncio
    async def test_fallback_on_api_error(self):
        """Should use fallback summary when API call fails."""
        result = NodeResult(
            success=True,
            error=None,
            output={"data": "test"},
            tokens_used=10,
            latency_ms=100,
        )

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("anthropic.AsyncAnthropic") as mock_client:
                mock_instance = MagicMock()
                mock_instance.messages.create = AsyncMock(
                    side_effect=Exception("API Error")
                )
                mock_client.return_value = mock_instance

                summary = await result.to_summary()

        # Should fall back to simple summary
        assert "✓ Completed with 1 outputs:" in summary

    @pytest.mark.asyncio
    async def test_timeout_triggers_fallback(self):
        """Should use fallback when API call times out."""
        result = NodeResult(
            success=True,
            error=None,
            output={"data": "test"},
            tokens_used=10,
            latency_ms=100,
        )

        async def slow_api_call(*args, **kwargs):
            await asyncio.sleep(20)  # Longer than timeout

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("anthropic.AsyncAnthropic") as mock_client:
                mock_instance = MagicMock()
                mock_instance.messages.create = slow_api_call
                mock_client.return_value = mock_instance

                # Should timeout and use fallback (not hang)
                summary = await asyncio.wait_for(
                    result.to_summary(),
                    timeout=15.0  # Test timeout > method timeout
                )

        assert "✓ Completed with 1 outputs:" in summary

    @pytest.mark.asyncio
    async def test_successful_api_call_returns_summary(self):
        """Should return LLM-generated summary on successful API call."""
        result = NodeResult(
            success=True,
            error=None,
            output={"user_count": 42},
            tokens_used=10,
            latency_ms=100,
        )

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Found 42 users in the database.")]

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("anthropic.AsyncAnthropic") as mock_client:
                mock_instance = MagicMock()
                mock_instance.messages.create = AsyncMock(
                    return_value=mock_message
                )
                mock_client.return_value = mock_instance

                summary = await result.to_summary()

        assert "✓ Found 42 users in the database." in summary

    @pytest.mark.asyncio
    async def test_is_truly_async_non_blocking(self):
        """Verify to_summary() doesn't block other coroutines."""
        result = NodeResult(
            success=True,
            error=None,
            output={"data": "test"},
            tokens_used=10,
            latency_ms=100,
        )

        concurrent_task_ran = False

        async def concurrent_task():
            nonlocal concurrent_task_ran
            await asyncio.sleep(0.1)
            concurrent_task_ran = True

        # No API key = fast fallback path
        with patch.dict("os.environ", {}, clear=True):
            await asyncio.gather(
                result.to_summary(),
                concurrent_task()
            )

        assert concurrent_task_ran, "Concurrent task should have run"

