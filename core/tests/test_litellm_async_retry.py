"""Tests for the async retry path in LiteLLM provider.

I noticed the sync version was using time.sleep() for rate-limit backoff
which blocked the entire event loop.  These tests make sure the async
version actually uses asyncio.sleep and that other coroutines can still
make progress while we wait.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# litellm may not be installed in the test environment, so we mock it
# at import time if necessary.
try:
    import litellm as _litellm  # noqa: F401
except ImportError:
    import sys

    litellm_mock = MagicMock()
    litellm_mock.exceptions = MagicMock()
    litellm_mock.exceptions.RateLimitError = type("RateLimitError", (Exception,), {})
    sys.modules["litellm"] = litellm_mock
    sys.modules["litellm.exceptions"] = litellm_mock.exceptions

from framework.llm.litellm import LiteLLMProvider


def _ok_response(content: str = "ok") -> SimpleNamespace:
    """Build a minimal litellm-style response."""
    msg = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    return SimpleNamespace(choices=[choice], usage=usage, model="mock-model")


def _empty_response() -> SimpleNamespace:
    """Empty content response — some providers do this instead of 429."""
    msg = SimpleNamespace(content="", tool_calls=None)
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=0)
    return SimpleNamespace(choices=[choice], usage=usage, model="mock-model")


class TestAsyncRetryUsesAsyncSleep:
    """The whole point of the async path is to not block the loop."""

    @pytest.mark.asyncio
    async def test_acompletion_success_no_sleep(self):
        """happy path - should just return without sleeping"""
        provider = LiteLLMProvider.__new__(LiteLLMProvider)
        provider.model = "test-model"
        provider.api_key = None
        provider.api_base = None
        provider.extra_kwargs = {}

        with patch("framework.llm.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=_ok_response())
            resp = await provider._acompletion_with_rate_limit_retry(
                messages=[{"role": "user", "content": "hi"}],
            )
            assert resp.choices[0].message.content == "ok"
            mock_litellm.acompletion.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acompletion_retries_with_asyncio_sleep(self):
        """empty response should retry with asyncio.sleep NOT time.sleep"""
        provider = LiteLLMProvider.__new__(LiteLLMProvider)
        provider.model = "test-model"
        provider.api_key = None
        provider.api_base = None
        provider.extra_kwargs = {}

        good = _ok_response("recovered")
        empty = _empty_response()

        with (
            patch("framework.llm.litellm.litellm") as mock_litellm,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_async_sleep,
            patch("time.sleep") as mock_time_sleep,
            patch("framework.llm.litellm._dump_failed_request", return_value="/tmp/dump"),
        ):
            mock_litellm.acompletion = AsyncMock(side_effect=[empty, good])
            resp = await provider._acompletion_with_rate_limit_retry(
                max_retries=2,
                messages=[{"role": "user", "content": "hi"}],
            )
            assert resp.choices[0].message.content == "recovered"
            mock_async_sleep.assert_awaited()
            # this is the important bit:
            mock_time_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_acompletion_rate_limit_retries_with_asyncio_sleep(self):
        """actual RateLimitError should also use asyncio.sleep"""
        provider = LiteLLMProvider.__new__(LiteLLMProvider)
        provider.model = "test-model"
        provider.api_key = None
        provider.api_base = None
        provider.extra_kwargs = {}

        good = _ok_response("after retry")

        with (
            patch("framework.llm.litellm.litellm") as mock_litellm,
            patch("framework.llm.litellm.RateLimitError", Exception),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_async_sleep,
            patch("time.sleep") as mock_time_sleep,
            patch("framework.llm.litellm._dump_failed_request", return_value="/tmp/dump"),
        ):
            mock_litellm.acompletion = AsyncMock(side_effect=[Exception("429"), good])
            resp = await provider._acompletion_with_rate_limit_retry(
                max_retries=2,
                messages=[{"role": "user", "content": "hi"}],
            )
            assert resp.choices[0].message.content == "after retry"
            mock_async_sleep.assert_awaited()
            mock_time_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_loop_not_blocked_during_backoff(self):
        """other tasks should still run while we're waiting on rate limit"""
        provider = LiteLLMProvider.__new__(LiteLLMProvider)
        provider.model = "test-model"
        provider.api_key = None
        provider.api_base = None
        provider.extra_kwargs = {}

        ran_bg = []

        async def bg_task():
            ran_bg.append("ran")

        good = _ok_response("done")
        empty = _empty_response()

        real_sleep = asyncio.sleep

        async def fake_sleep(seconds: float):
            # let bg task run during the wait
            await asyncio.ensure_future(bg_task())
            await real_sleep(0)

        with (
            patch("framework.llm.litellm.litellm") as mock_litellm,
            patch("asyncio.sleep", side_effect=fake_sleep),
            patch("framework.llm.litellm._dump_failed_request", return_value="/tmp/dump"),
        ):
            mock_litellm.acompletion = AsyncMock(side_effect=[empty, good])
            await provider._acompletion_with_rate_limit_retry(
                max_retries=2,
                messages=[{"role": "user", "content": "hi"}],
            )

        assert len(ran_bg) > 0, "event loop was blocked -- bg task never ran"
